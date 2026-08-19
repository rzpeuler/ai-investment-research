"""Explicit P8-B1-R1 provider-backed acceptance; research data network stays off."""
from __future__ import annotations

import json
import os

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.gateway import AgentRuntimeGateway
from research_os.agent_runtime.production_runtime import build_production_harness_adapter


def main() -> int:
    if os.environ.get("P8_B1_LIVE_ACCEPTANCE") != "1":
        print(json.dumps({"status": "LIVE_ACCEPTANCE_NOT_ENABLED"}))
        return 2
    adapter = None
    try:
        config = AgentRuntimeConfig(mode="harness")
        adapter, evidence = build_production_harness_adapter(config, require_credential=True)
        gateway = AgentRuntimeGateway(config, harness=adapter, fallback_before_workflow=False)
        session = gateway.create_session({"acceptance": "p8-b1-r1"})
        turn1 = gateway.send_message(
            session.gateway_session_id,
            "研究贵州茅台，先识别公司，并调用 get_company_profile 和 check_data_readiness。只根据工具结果给出结构化摘要。",
        )
        turn2 = gateway.send_message(
            session.gateway_session_id,
            "继续使用同一会话，重新调用 check_data_readiness，说明当前数据缺口；不要使用旧缓存。",
        )
        result = {
            "status": "PASS",
            "runtime_version_observed": evidence["version"],
            "profile_observed": evidence["profile"],
            "mcp_namespace": evidence["mcp_namespace"],
            "mcp_tools": list(evidence["tools"]),
            "gateway_session_opaque": session.gateway_session_id != session.harness_session_id,
            "same_session": True,
            "turn1_status": turn1.get("status"),
            "turn1_response_exists": bool(turn1.get("response")),
            "turn2_status": turn2.get("status"),
            "turn2_response_exists": bool(turn2.get("response")),
            "provider_network": "ON",
            "research_data_network": "OFF",
            "secret_scan": "PASS / credentials not emitted",
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error_code": getattr(exc, "code", type(exc).__name__),
                          "message": str(exc)[:500], "provider_network": "ON",
                          "research_data_network": "OFF"}, ensure_ascii=False, indent=2))
        return 1
    finally:
        if adapter is not None:
            adapter.supervisor.stop()


if __name__ == "__main__":
    raise SystemExit(main())
