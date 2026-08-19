"""Live P8-A0-R3 continuation verification through rc.7's public Web/API surface."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime-spike"
PINNED = "0.1.0-rc.7"


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def rpc(base: str, method: str, payload: dict, timeout: int = 30) -> dict:
    body = {
        "type": "client-request",
        "rpcId": str(uuid.uuid4()),
        "method": method,
        "payload": payload,
    }
    req = urllib.request.Request(
        f"{base}/api/{method}",
        data=json.dumps(body).encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.load(response)
    if result.get("rpcId") != body["rpcId"]:
        raise RuntimeError(f"rpc_id_mismatch:{method}")
    if not result.get("result", {}).get("ok"):
        raise RuntimeError(json.dumps(result.get("result"), ensure_ascii=False))
    return result["result"]["value"]


def text_from(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(text_from(item) for item in value)
    if isinstance(value, dict):
        for key in ("text", "content", "value", "message"):
            if key in value:
                found = text_from(value[key])
                if found:
                    return found
    return ""


def history_snapshot(base: str, session_id: str) -> dict:
    value = rpc(base, "session.history", {"sessionId": session_id, "maxMessages": 50})
    events = value.get("events", [])
    return {
        "events": events,
        "types": [event.get("event", {}).get("type") for event in events],
        "assistant_text": "\n".join(
            text_from(event.get("event", {}).get("data"))
            for event in events
            if event.get("event", {}).get("type") in {"assistant/message", "message/final", "message/created", "message"}
        ),
    }


def wait_turn(base: str, session_id: str, timeout: int) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    saw_running = False
    while time.monotonic() < deadline:
        listing = rpc(base, "session.list", {})
        row = next((item for item in listing.get("items", []) if item.get("sessionId") == session_id), None)
        last = history_snapshot(base, session_id)
        if row and row.get("running"):
            saw_running = True
        if row and not row.get("running") and (saw_running or len(last["events"]) >= 2):
            last["running"] = False
            return last
        time.sleep(1)
    raise TimeoutError(json.dumps({"running": last.get("running"), "types": last.get("types", [])}))


def prompt_and_wait(base: str, session_id: str, prompt: str, timeout: int) -> dict:
    accepted = rpc(base, "session.prompt", {
        "sessionId": session_id,
        "mode": "queue",
        "content": [{"type": "text", "text": prompt}],
    })
    if accepted.get("accepted") is not True:
        raise RuntimeError("prompt_not_accepted")
    return wait_turn(base, session_id, timeout)


def is_context_safe(text: str) -> bool:
    lowered = text.lower()
    markers = ("不清楚", "无法确定", "请提供", "上下文", "insufficient", "which company", "具体公司")
    return any(marker in lowered for marker in markers)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    """Terminate only the process tree created by this launcher."""
    if proc.poll() is None:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def wait_http(base: str, proc: subprocess.Popen[str], timeout: int = 30) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"web_process_exit:{proc.returncode}")
        try:
            with urllib.request.urlopen(base, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, TimeoutError):
            time.sleep(0.5)
    raise TimeoutError("web_startup_timeout")


def sanitized_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    result = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-50:]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        result.append({
            "tool": item.get("tool_name"),
            "status": item.get("status"),
            "event_type": item.get("event_type"),
        })
    return result


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "PROVIDER_AUTH_MISSING", "runtime_version": PINNED}, ensure_ascii=False))
        return 2
    dsh = RUNTIME / "node_modules" / ".bin" / ("dsh.cmd" if os.name == "nt" else "dsh")
    if not dsh.exists():
        print(json.dumps({"status": "HARNESS_BOOT_FAILED", "reason": "dsh_not_installed", "runtime_version": PINNED}, ensure_ascii=False))
        return 3

    home = RUNTIME / ".r3-live-home"
    profile = home / "profiles" / "research-web"
    profile.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RUNTIME / "research-profile-web" / "package.json", profile / "package.json")
    shutil.copy2(RUNTIME / "research-profile" / "cordis.patch.yml", profile / "cordis.patch.yml")
    event_log = RUNTIME / "r3-tool-events.jsonl"
    if event_log.exists():
        event_log.unlink()
    env = os.environ.copy()
    env["DSH_HOME"] = str(home)
    env["P8_R2_REPO_ROOT"] = str(ROOT)
    env["P8_R2_SKILL_DIR"] = str(RUNTIME / ".agents" / "skills")
    env["P8_R2_EVENT_LOG"] = str(event_log)
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = subprocess.Popen(
        [str(dsh), "--profile", "research-web", "--host", "127.0.0.1", "--port", str(port)],
        cwd=RUNTIME,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    started = iso()
    session_id = f"r3-{uuid.uuid4()}"
    try:
        wait_http(base, proc)
        created = rpc(base, "session.create", {"cwd": str(ROOT), "sessionId": session_id})
        session_id = created["sessionId"]
        turn1 = prompt_and_wait(
            base,
            session_id,
            "请研究贵州茅台。先识别公司，并调用 get_company_profile 与 check_data_readiness，然后只根据工具结果给出结构化摘要。",
            args.timeout,
        )
        turn2 = prompt_and_wait(
            base,
            session_id,
            "刚才这家公司的数据缺口主要是什么？请重新调用 check_data_readiness，不要使用旧缓存，并根据最新结果回答。",
            args.timeout,
        )
        negative_id = f"r3-negative-{uuid.uuid4()}"
        rpc(base, "session.create", {"cwd": str(ROOT), "sessionId": negative_id})
        negative = prompt_and_wait(base, negative_id, "刚才这家公司的数据缺口主要是什么？", args.timeout)
        result = {
            "status": "success",
            "runtime_version": PINNED,
            "surface": "official_loopback_web_api",
            "web_process_alive": proc.poll() is None,
            "session_id": session_id,
            "same_session": True,
            "turn1": {"event_types": turn1["types"], "assistant_response_exists": bool(turn1["assistant_text"].strip()), "assistant_excerpt": turn1["assistant_text"][-1000:]},
            "turn2": {"event_types": turn2["types"], "assistant_response_exists": bool(turn2["assistant_text"].strip()), "assistant_excerpt": turn2["assistant_text"][-1000:]},
            "negative_new_session": {"session_id_distinct": negative_id != session_id, "event_types": negative["types"], "assistant_response_exists": bool(negative["assistant_text"].strip()), "clarification_or_insufficient_context": is_context_safe(negative["assistant_text"])},
            "tool_events": sanitized_events(event_log),
            "started_at": started,
            "ended_at": iso(),
        }
        # Evidence for continuation: the second prompt must have produced a new user event
        # and another readiness tool result in the same server-owned session history.
        combined_types = turn2["types"]
        result["continuation_evidence"] = {
            "second_turn_has_user_event": sum(1 for item in combined_types if item == "user/message") >= 1,
            "readiness_invocation_count": sum(1 for item in result["tool_events"] if item.get("tool") == "check_data_readiness"),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # bounded failure report; never include environment values
        print(json.dumps({"status": "R3_FAILED", "runtime_version": PINNED, "error": type(exc).__name__, "message": str(exc)[:1000], "tool_events": sanitized_events(event_log)}, ensure_ascii=False, indent=2))
        return 1
    finally:
        terminate_process_tree(proc)


if __name__ == "__main__":
    raise SystemExit(main())
