"""Real rc.7 runtime binding: package probe, profile evidence, HTTP client and factory."""
from __future__ import annotations

import json
import http.client
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from .config import EXPECTED_HARNESS_VERSION, MCP_NAMESPACE
from .errors import RuntimeNotReady, SessionFailure
from .mcp.server import ResearchOSMCPServer
from .models import GatewaySession
from .runtime_supervisor import OwnedProcess


ROOT = Path(__file__).resolve().parents[3]
PACKAGE_ROOT = ROOT / "agent_runtime"
PROFILE_ROOT = PACKAGE_ROOT / "profiles" / "research-headless"

PUBLIC_RESULT_KEYS = frozenset({"status", "response", "operational_metadata"})
PRIVATE_RESULT_KEYS = frozenset({
    "session_id", "harness_session_id", "internal_session_id", "session",
    "raw_session", "session_storage_path", "storage_path",
})


def sanitize_public_result(value: Any, *, forbidden_values: tuple[str, ...] = ()) -> dict[str, Any]:
    """Return the small public contract; raw Harness payloads never cross it."""
    if not isinstance(value, dict):
        raise SessionFailure("SESSION_CORRUPTED", "Harness response must be an object")

    def clean(item: Any) -> Any:
        if isinstance(item, dict):
            return {
                key: clean(child) for key, child in item.items()
                if key not in PRIVATE_RESULT_KEYS
            }
        if isinstance(item, list):
            return [clean(child) for child in item]
        if isinstance(item, str):
            if any(secret and secret in item for secret in forbidden_values):
                return "[REDACTED]"
        return item

    result = {key: clean(value[key]) for key in PUBLIC_RESULT_KEYS if key in value}
    if "status" not in result:
        result["status"] = "completed"
    return result


def _extract_usage(value: Any) -> dict[str, int | float]:
    """Extract only provider-reported usage fields; never estimate them."""
    allowed = {"input_tokens", "output_tokens", "cached_tokens", "total_tokens", "cost_usd"}
    found: dict[str, int | float] = {}

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in allowed and isinstance(child, (int, float)) and not isinstance(child, bool):
                    found[key] = child
                else:
                    walk(child)
        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)
    return found


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _read_json_lines(stdout: bytes) -> list[dict[str, Any]]:
    result = []
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            result.append(value)
    return result


class ProductionEvidenceProbe:
    """Observes the installed binary, composed profile and actual stdio MCP."""

    def __init__(self, package_root: Path = PACKAGE_ROOT, repo_root: Path = ROOT):
        self.package_root = Path(package_root)
        self.repo_root = Path(repo_root)
        self.dsh = self.package_root / "node_modules" / ".bin" / ("dsh.cmd" if os.name == "nt" else "dsh")

    def _env(self, home: Path) -> dict[str, str]:
        env = os.environ.copy()
        env.update({
            "DSH_HOME": str(home),
            "P8_B1_REPO_ROOT": str(self.repo_root),
            "P8_B1_SKILL_DIR": str(self.repo_root / "agent_runtime_skills"),
            "DSH_PERMISSION_MODE": "read-only",
            "DSH_TELEMETRY_MODE": "DISABLED",
        })
        return env

    def prepare_profile(self, home: Path) -> Path:
        profile = home / "profiles" / "research-headless"
        profile.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROFILE_ROOT / "package.json", profile / "package.json")
        shutil.copy2(PROFILE_ROOT / "cordis.patch.yml", profile / "cordis.patch.yml")
        return profile

    def _run_dsh(self, args: list[str], home: Path, timeout: int = 30) -> str:
        if not self.dsh.exists():
            raise RuntimeNotReady("HARNESS_BOOT_FAILED", "production dsh binary is not installed")
        result = subprocess.run([str(self.dsh), *args], cwd=self.repo_root, env=self._env(home),
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=timeout, check=False)
        if result.returncode != 0:
            raise RuntimeNotReady("HARNESS_BOOT_FAILED", "dsh probe failed")
        return result.stdout.strip()

    def probe_mcp(self, timeout: int = 20) -> dict[str, Any]:
        process = subprocess.Popen([sys.executable, "scripts/p8_b1_mcp_server.py"], cwd=self.repo_root,
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                   text=False, env={**os.environ, "P8_B1_EVENT_LOG": ""})
        requests = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        ]
        payload = ("\n".join(json.dumps(item) for item in requests) + "\n").encode()
        try:
            stdout, _ = process.communicate(payload, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            process.kill()
            process.communicate()
            raise RuntimeNotReady("MCP_UNAVAILABLE", "stdio MCP probe timed out") from exc
        replies = _read_json_lines(stdout)
        initialize = next((item.get("result", {}) for item in replies if item.get("id") == 1), {})
        listing = next((item.get("result", {}) for item in replies if item.get("id") == 2), {})
        tools = tuple(sorted(item.get("name") for item in listing.get("tools", []) if item.get("name")))
        if initialize.get("serverInfo", {}).get("name") != MCP_NAMESPACE:
            raise RuntimeNotReady("MCP_UNAVAILABLE", "stdio MCP namespace evidence mismatch")
        return {"connected": True, "namespace": MCP_NAMESPACE, "tools": tools,
                "protocol_version": initialize.get("protocolVersion")}

    def observe(self) -> dict[str, Any]:
        home = self.package_root / ".dsh-home"
        self.prepare_profile(home)
        version = self._run_dsh(["--version"], home)
        composed = self._run_dsh(["--profile", "research-headless", "--dump-config"], home)
        component_blocks = {
            match.group(1): match.group(0)
            for match in re.finditer(r"(?ms)^- id: ([^\n]+).*?(?=^- id: |\Z)", composed)
        }
        observed_component_ids = set(component_blocks)
        observed_keys = {
            component for component in (
                "bash", "pwsh", "fs", "fs-search", "jobs", "subagent-control", "subagent",
                "workflow", "todo", "goal", "str-replace-editor", "web", "web-search-deepseek", "subprocess",
            ) if f"tool-{component}" in observed_component_ids or component in observed_component_ids
        }
        # The composed config is the observed source; disabled markers are required for every denied id.
        required_ids = {
            "bash": "tool-bash", "pwsh": "tool-pwsh", "fs": "tool-fs", "fs-search": "tool-fs-search",
            "jobs": "tool-jobs", "subagent-control": "tool-subagent-control", "subagent": "tool-subagent",
            "workflow": "tool-workflow", "todo": "tool-todo", "goal": "tool-goal",
            "str-replace-editor": "tool-str-replace-editor", "web": "tool-web", "web-search-deepseek": "web-search-deepseek",
        }
        disabled = {key for key, item_id in required_ids.items()
                    if item_id in component_blocks and re.search(r"disabled:\s*true\s*$", component_blocks[item_id], re.MULTILINE)}
        names = {
            "bash": "bash", "pwsh": "pwsh", "fs": "filesystem_write", "fs-search": "filesystem_search",
            "jobs": "jobs", "subagent-control": "subagent", "subagent": "subagent",
            "workflow": "workflow_coding_tools", "todo": "todo", "goal": "coding_goal_tools",
            "str-replace-editor": "filesystem_editor", "web": "direct_web", "web-search-deepseek": "web_search",
            "subprocess": "arbitrary_subprocess",
        }
        observed = {names[key] for key in observed_keys if key in names}
        disabled_observed = {names[key] for key in disabled if key in names}
        forbidden_component_ids = {
            "tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-jobs", "tool-web",
            "web-search-deepseek", "tool-subagent", "tool-subagent-control", "tool-workflow",
            "tool-todo", "tool-goal", "tool-str-replace-editor",
        }
        disabled_component_ids = sorted(
            component_id for component_id in forbidden_component_ids
            if component_id in component_blocks and re.search(r"disabled:\s*true\s*$", component_blocks[component_id], re.MULTILINE)
        )
        absent_forbidden_component_ids = sorted(
            component_id for component_id in forbidden_component_ids if component_id not in component_blocks
        )
        enabled_component_ids = sorted(
            component_id for component_id in forbidden_component_ids
            if component_id in component_blocks and component_id not in disabled_component_ids
        )
        if any(component_id in enabled_component_ids for component_id in ("tool-bash", "tool-pwsh")):
            observed.add("arbitrary_subprocess")
        if any(component_id in disabled_component_ids for component_id in ("tool-bash", "tool-pwsh")):
            disabled_observed.add("arbitrary_subprocess")
        mcp = self.probe_mcp()
        return {
            "evidence_source": "observed_runtime",
            "version": version.lstrip("v").strip(),
            "profile": "research-headless",
            "composed_config": composed,
            "observed_component_ids": sorted(observed_component_ids),
            "disabled_component_ids": disabled_component_ids,
            "enabled_component_ids": enabled_component_ids,
            "absent_forbidden_component_ids": absent_forbidden_component_ids,
            "denied_components": sorted(observed),
            "disabled_components": sorted(disabled_observed),
            "mcp_namespace": mcp["namespace"],
            "tools": mcp["tools"],
            "mcp_handshake": mcp,
        }


class BoundedOwnedProcess:
    def __init__(self, process: subprocess.Popen[bytes], base_url: str):
        self.process = process
        self.base_url = base_url
        self.stdout_tail = bytearray()
        self.stderr_tail = bytearray()
        self._threads = [
            threading.Thread(target=self._drain, args=(process.stdout, self.stdout_tail), daemon=True),
            threading.Thread(target=self._drain, args=(process.stderr, self.stderr_tail), daemon=True),
        ]
        for thread in self._threads:
            thread.start()

    @staticmethod
    def _drain(stream, target: bytearray) -> None:
        if stream is None:
            return
        while True:
            chunk = stream.read(4096)
            if not chunk:
                return
            target.extend(chunk)
            del target[:-65536]

    def poll(self):
        return self.process.poll()

    def terminate(self):
        if self.process.poll() is None:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(self.process.pid), "/T", "/F"],
                               capture_output=True, check=False)
            else:
                self.process.terminate()

    def wait(self, timeout: float | None = None):
        return self.process.wait(timeout=timeout)


class HarnessProcessFactory:
    """Starts only the locally installed, pinned package under an owned root."""

    def __init__(self, package_root: Path = PACKAGE_ROOT, repo_root: Path = ROOT):
        self.package_root = Path(package_root)
        self.repo_root = Path(repo_root)
        self.port: int | None = None
        self.home = self.package_root / ".dsh-home"
        self.probe = ProductionEvidenceProbe(self.package_root, self.repo_root)

    def observed_evidence(self) -> dict[str, Any]:
        return self.probe.observe()

    def __call__(self) -> BoundedOwnedProcess:
        self.probe.prepare_profile(self.home)
        dsh = self.probe.dsh
        if not dsh.exists():
            raise RuntimeNotReady("HARNESS_BOOT_FAILED", "production dsh binary is not installed")
        self.port = free_port()
        env = self.probe._env(self.home)
        process = subprocess.Popen([str(dsh), "--profile", "research-headless", "--host", "127.0.0.1",
                                    "--port", str(self.port)], cwd=self.repo_root, env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        base_url = f"http://127.0.0.1:{self.port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeNotReady("HARNESS_BOOT_FAILED", "Harness process exited during startup")
            try:
                with urllib.request.urlopen(base_url, timeout=1) as response:
                    if response.status == 200:
                        return BoundedOwnedProcess(process, base_url)
            except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError, TimeoutError):
                time.sleep(0.25)
        if process.poll() is None:
            BoundedOwnedProcess(process, base_url).terminate()
        raise RuntimeNotReady("HARNESS_BOOT_FAILED", "Harness HTTP surface did not become live")


class OfficialHarnessClient:
    """Public loopback Web/API session client for pinned rc.7."""

    def __init__(self, base_url: str, timeout: int = 120):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _rpc(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = uuid.uuid4().hex
        body = {"type": "client-request", "rpcId": request_id, "method": method, "payload": payload}
        request = urllib.request.Request(f"{self.base_url}/api/{method}", data=json.dumps(body).encode(),
                                          headers={"content-type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (urllib.error.URLError, http.client.RemoteDisconnected, ConnectionResetError, TimeoutError) as exc:
            raise RuntimeNotReady("PROVIDER_TIMEOUT", "Harness API request failed") from exc
        if result.get("rpcId") != request_id or not result.get("result", {}).get("ok"):
            raise SessionFailure("SESSION_CORRUPTED", "Harness API returned an invalid response")
        return result["result"].get("value") or {}

    def create_session(self) -> str:
        session_id = "b1-" + uuid.uuid4().hex
        value = self._rpc("session.create", {"cwd": str(ROOT), "sessionId": session_id})
        return str(value.get("sessionId") or session_id)

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            return "".join(OfficialHarnessClient._text(item) for item in value)
        if isinstance(value, dict):
            return next((OfficialHarnessClient._text(value[key]) for key in ("text", "content", "value", "message") if key in value), "")
        return ""

    def _history(self, session_id: str) -> dict[str, Any]:
        return self._rpc("session.history", {"sessionId": session_id, "maxMessages": 50})

    def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        accepted = self._rpc("session.prompt", {"sessionId": session_id, "mode": "queue",
                                                 "content": [{"type": "text", "text": message}]})
        if accepted.get("accepted") is not True:
            raise SessionFailure("TURN_REJECTED", "Harness did not accept the turn")
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            history = self._history(session_id)
            events = history.get("events", [])
            listing = self._rpc("session.list", {})
            row = next((item for item in listing.get("items", []) if item.get("sessionId") == session_id), None)
            if row and not row.get("running") and len(events) >= 2:
                text = "\n".join(self._text(item.get("event", {}).get("data")) for item in events[-5:])
                result = {"status": "completed", "response": text}
                usage = _extract_usage({"history": history, "listing": listing})
                if usage:
                    result["operational_metadata"] = {"usage": usage}
                return sanitize_public_result(result, forbidden_values=(session_id,))
            time.sleep(0.5)
        raise RuntimeNotReady("TURN_TIMEOUT", "Harness turn timed out")

    def resume_session(self, session_id: str) -> None:
        self._history(session_id)

    def cancel_turn(self, session_id: str) -> None:
        self._rpc("session.cancel", {"sessionId": session_id})


def build_production_harness_adapter(config=None, *, require_credential: bool = True):
    """Boot the real local package and return an admitted Harness adapter."""
    from .config import AgentRuntimeConfig
    from .harness_adapter import HarnessAgentRuntimeAdapter
    from .mcp.tools import build_research_os_mcp_server
    from .runtime_supervisor import HarnessRuntimeSupervisor

    config = (config or AgentRuntimeConfig(mode="harness")).validate()
    factory = HarnessProcessFactory()
    evidence = factory.observed_evidence()
    supervisor = HarnessRuntimeSupervisor(config=config, process_factory=factory)
    supervisor.start(evidence, require_credential=require_credential)
    process = supervisor.process
    if process is None or not hasattr(process, "base_url"):
        supervisor.stop()
        raise RuntimeNotReady("HARNESS_BOOT_FAILED", "owned process did not expose loopback API")
    client = OfficialHarnessClient(process.base_url, config.turn_timeout_seconds)
    mcp = build_research_os_mcp_server()
    mcp.perform_handshake()
    supervisor.complete_mcp_handshake(evidence["mcp_handshake"])
    return HarnessAgentRuntimeAdapter(supervisor, mcp, client), evidence
