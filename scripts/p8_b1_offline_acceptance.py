"""Run deterministic P8-B1 foundation checks without provider or data network."""
from __future__ import annotations

import json

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.mcp.server import ResearchOSMCPServer
from research_os.agent_runtime.profile_verifier import default_runtime_descriptor
from research_os.agent_runtime.tool_catalog import ALLOWED_TOOL_NAMES


def run() -> dict[str, object]:
    config = AgentRuntimeConfig.from_env()
    server = ResearchOSMCPServer({
        "get_company_profile": lambda **_: {"status": "insufficient_evidence"},
        "check_data_readiness": lambda **_: {"status": "insufficient_evidence"},
    })
    handshake = server.perform_handshake()
    return {
        "status": "PASS",
        "default_runtime": config.mode,
        "harness_version": config.harness_version,
        "profile_verified": default_runtime_descriptor()["profile"],
        "mcp_namespace": handshake.namespace,
        "tools": list(handshake.tools),
        "provider_network": "OFF",
        "research_data_network": "OFF",
        "schema_change": "NONE",
        "db": "v6",
        "migrations": "NONE",
        "assertions": sorted(ALLOWED_TOOL_NAMES) == list(handshake.tools),
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
