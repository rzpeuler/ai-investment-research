"""Research OS authority handlers for the two B1 MCP read Tools."""
from __future__ import annotations

from ..research_capabilities import check_data_readiness, get_company_profile
from .server import ResearchOSMCPServer


def build_research_os_mcp_server() -> ResearchOSMCPServer:
    return ResearchOSMCPServer({
        "get_company_profile": get_company_profile,
        "check_data_readiness": check_data_readiness,
    })
