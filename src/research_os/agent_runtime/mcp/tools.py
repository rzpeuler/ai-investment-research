"""Research OS authority handlers for the two B1 MCP read Tools."""
from __future__ import annotations

from ..research_capabilities import (
    check_data_readiness,
    get_company_profile,
    query_industry_graph,
    run_research_scenario,
)
from ..tool_catalog import SPIKE_ALLOWED_TOOL_NAMES
from .server import ResearchOSMCPServer


def build_research_os_mcp_server() -> ResearchOSMCPServer:
    return ResearchOSMCPServer({
        "get_company_profile": get_company_profile,
        "check_data_readiness": check_data_readiness,
    })


def build_spike_research_os_mcp_server() -> ResearchOSMCPServer:
    """P8-A0 Hybrid spike 4-tool MCP facade (opt-in; never the default).

    Exposes the frozen two read Tools plus the spike's read-only graph query
    and bounded scenario trigger. All four are Research OS authority tools;
    collectors, DB writes and graph writes remain denied.
    """
    return ResearchOSMCPServer({
        "get_company_profile": get_company_profile,
        "check_data_readiness": check_data_readiness,
        "query_industry_graph": query_industry_graph,
        "run_research_scenario": run_research_scenario,
    }, allowed_tools=SPIKE_ALLOWED_TOOL_NAMES)
