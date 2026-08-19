"""Explicit provider-backed acceptance; research data network stays off."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.gateway import AgentRuntimeGateway
from research_os.agent_runtime.production_runtime import build_production_harness_adapter


def _event_counts(path: Path) -> dict[str, int]:
    counts = {"get_company_profile": 0, "check_data_readiness": 0}
    if not path.exists():
        return counts
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        name = event.get("tool_name")
        if event.get("event_type") == "tool_call" and name in counts:
            counts[name] += 1
    return counts


def _secret_scan(values: list[str]) -> str:
    secret = os.environ.get("DEEPSEEK_API_KEY", "")
    needles = [needle for needle in (secret, "Authorization", "Bearer ", "Cookie", "password") if needle]
    return "FAIL" if any(needle in value for value in values for needle in needles) else "PASS"


def main() -> int:
    if os.environ.get("P8_B1_LIVE_ACCEPTANCE") != "1":
        print(json.dumps({"status": "LIVE_ACCEPTANCE_NOT_ENABLED"}))
        return 2
    adapter = None
    previous_event_log = os.environ.get("P8_B1_EVENT_LOG")
    descriptor, event_name = tempfile.mkstemp(prefix="p8-b1-r2-events-", suffix=".jsonl")
    os.close(descriptor)
    event_log = Path(event_name)
    os.environ["P8_B1_EVENT_LOG"] = str(event_log)
    try:
        config = AgentRuntimeConfig(mode="harness")
        adapter, evidence = build_production_harness_adapter(config, require_credential=True)
        gateway = AgentRuntimeGateway(config, harness=adapter, fallback_before_workflow=False)
        session = gateway.create_session({"acceptance": "p8-b1-r2"})
        before_internal = adapter.sessions[session.gateway_session_id].harness_session_id
        turn1 = gateway.send_message(
            session.gateway_session_id,
            "For Guizhou Moutai (Kweichow Moutai), call get_company_profile once and "
            "check_data_readiness once. Return a short structured summary from the tool results.",
        )
        after_turn1_internal = adapter.sessions[session.gateway_session_id].harness_session_id
        turn1_counts = _event_counts(event_log)
        turn2 = gateway.send_message(
            session.gateway_session_id,
            "In this same session, call check_data_readiness exactly once now and report the fresh result. "
            "Do not use cached results.",
        )
        after_turn2_internal = adapter.sessions[session.gateway_session_id].harness_session_id
        turn2_counts = _event_counts(event_log)
        process = adapter.supervisor.process
        operational = []
        if process is not None:
            operational = [bytes(process.stdout_tail).decode("utf-8", errors="replace"),
                           bytes(process.stderr_tail).decode("utf-8", errors="replace")]
        event_text = event_log.read_text(encoding="utf-8", errors="replace") if event_log.exists() else ""
        same_internal_session = bool(before_internal and before_internal == after_turn1_internal == after_turn2_internal)
        authority_reread = turn2_counts["check_data_readiness"] > turn1_counts["check_data_readiness"]
        tool_evidence = (
            turn1_counts["get_company_profile"] >= 1
            and turn1_counts["check_data_readiness"] >= 1
            and authority_reread
        )
        secret_scan = _secret_scan(operational + [event_text])
        result = {
            "status": "PASS" if same_internal_session and tool_evidence and secret_scan == "PASS" else "FAIL",
            "runtime_version_observed": evidence["version"],
            "profile_observed": evidence["profile"],
            "mcp_namespace": evidence["mcp_namespace"],
            "mcp_tools": list(evidence["tools"]),
            "gateway_session_opaque": session.gateway_session_id != session.harness_session_id,
            "same_internal_session": same_internal_session,
            "turn1_status": turn1.get("status"),
            "turn1_response_exists": bool(turn1.get("response")),
            "turn1_get_company_profile_calls": turn1_counts["get_company_profile"],
            "turn1_check_data_readiness_calls": turn1_counts["check_data_readiness"],
            "turn2_status": turn2.get("status"),
            "turn2_response_exists": bool(turn2.get("response")),
            "turn2_new_check_data_readiness_calls": turn2_counts["check_data_readiness"] - turn1_counts["check_data_readiness"],
            "authority_reread": "PASS" if authority_reread else "FAIL",
            "provider_network": "ON",
            "research_data_network": "OFF",
            "secret_scan": secret_scan,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "PASS" else 1
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_code": getattr(exc, "code", type(exc).__name__),
                          "provider_network": "ON", "research_data_network": "OFF"}, ensure_ascii=False, indent=2))
        return 1
    finally:
        if adapter is not None:
            adapter.supervisor.stop()
        if previous_event_log is None:
            os.environ.pop("P8_B1_EVENT_LOG", None)
        else:
            os.environ["P8_B1_EVENT_LOG"] = previous_event_log
        for _ in range(20):
            try:
                event_log.unlink()
                break
            except FileNotFoundError:
                break
            except PermissionError:
                time.sleep(0.25)


if __name__ == "__main__":
    raise SystemExit(main())
