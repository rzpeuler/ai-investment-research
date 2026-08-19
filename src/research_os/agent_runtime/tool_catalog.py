"""The exact public Tool catalog for P8-B1."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .config import MCP_NAMESPACE, MAX_TOOL_RESULT_BYTES

ALLOWED_TOOL_NAMES = frozenset({"get_company_profile", "check_data_readiness"})
DENIED_TOOL_NAMES = frozenset({
    "cninfo_fetch", "nbs_fetch", "sina_fetch", "collector_execute", "sql_query",
    "execute_sql", "query_db", "read_table", "graph_write", "graph_apply", "graph_approve",
    "query_industry_graph", "run_research_scenario", "run_stock_research",
})


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    version: str
    description: str
    input_schema: dict[str, Any]
    authority_owner: str = "Research OS"
    network_policy: str = "research-data-network-off"
    write_policy: str = "read-only"
    result_limit_bytes: int = MAX_TOOL_RESULT_BYTES
    handler: Callable[..., dict[str, Any]] | None = None


def catalog(handlers: dict[str, Callable[..., dict[str, Any]]] | None = None) -> dict[str, ToolDefinition]:
    handlers = handlers or {}
    definitions = {
        "get_company_profile": ToolDefinition(
            name="get_company_profile", version="1.0.0",
            description="Read exact company and security identity from Research OS authority.",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}},
                          "required": ["target"], "additionalProperties": False},
            handler=handlers.get("get_company_profile"),
        ),
        "check_data_readiness": ToolDefinition(
            name="check_data_readiness", version="1.0.0",
            description="Read dry-run Research OS readiness without source acquisition.",
            input_schema={"type": "object", "properties": {"target": {"type": "string"}, "as_of": {"type": "string"}},
                          "required": ["target"], "additionalProperties": False},
            handler=handlers.get("check_data_readiness"),
        ),
    }
    if set(handlers) - ALLOWED_TOOL_NAMES:
        raise ValueError("MCP tool catalog must contain exactly the two allowed read Tools")
    return definitions


def advertised_tools(handlers: dict[str, Callable[..., dict[str, Any]]] | None = None) -> tuple[str, ...]:
    return tuple(sorted(catalog(handlers)))


__all__ = ["ALLOWED_TOOL_NAMES", "DENIED_TOOL_NAMES", "MCP_NAMESPACE", "ToolDefinition", "advertised_tools", "catalog"]
