"""Explicit live acceptance launcher for the isolated R2 profile."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime-spike"
PINNED = "0.1.0-rc.7"


def iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", default="研究贵州茅台（如需精确核验，可使用用户提供的证券标识 600519.SH），先告诉我公司身份和当前研究数据是否准备好。")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "PROVIDER_AUTH_MISSING", "runtime_version": PINNED}, ensure_ascii=False))
        return 2
    dsh = RUNTIME / "node_modules" / ".bin" / ("dsh.cmd" if os.name == "nt" else "dsh")
    if not dsh.exists():
        print(json.dumps({"status": "HARNESS_BOOT_FAILED", "reason": "dsh_not_installed", "runtime_version": PINNED}, ensure_ascii=False))
        return 3
    home = RUNTIME / ".r2-live-home"
    profile = home / "profiles" / "research-headless"
    profile.mkdir(parents=True, exist_ok=True)
    shutil.copy2(RUNTIME / "research-profile" / "package.json", profile / "package.json")
    shutil.copy2(RUNTIME / "research-profile" / "cordis.patch.yml", profile / "cordis.patch.yml")
    env = os.environ.copy()
    env["DSH_HOME"] = str(home)
    env["P8_R2_REPO_ROOT"] = str(ROOT)
    env["P8_R2_SKILL_DIR"] = str(RUNTIME / ".agents" / "skills")
    event_log = RUNTIME / "r2-tool-events.jsonl"
    if event_log.exists():
        event_log.unlink()
    env["P8_R2_EVENT_LOG"] = str(event_log)
    started = iso()
    proc = subprocess.Popen([str(dsh), "--profile", "research-headless", args.prompt], cwd=RUNTIME,
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            encoding="utf-8", errors="replace")
    try:
        stdout, stderr = proc.communicate(timeout=args.timeout)
        stdout = stdout or ""
        stderr = stderr or ""
        status = "success" if proc.returncode == 0 and stdout.strip() else "PROVIDER_SESSION_FAILED"
    except subprocess.TimeoutExpired:
        terminate_process_tree(proc)
        stdout, stderr = proc.communicate()
        stdout = stdout or ""
        stderr = stderr or ""
        status = "PROVIDER_SESSION_TIMEOUT"
    terminate_process_tree(proc)
    result = {
        "status": status,
        "runtime_version": PINNED,
        "profile": "research-headless",
        "started_at": started,
        "ended_at": iso(),
        "exit_code": proc.returncode,
        "final_assistant_response_exists": bool(stdout.strip()),
        "stdout": stdout[-16000:],
        "stderr_summary": stderr[-2000:] if stderr else "",
        "tool_events": [json.loads(line) for line in event_log.read_text(encoding="utf-8").splitlines()[-20:]] if event_log.exists() else [],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
