"""Transport-neutral contracts for research-os-mcp/v1."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ..config import MCP_NAMESPACE, MAX_TOOL_RESULT_BYTES
from ..errors import ToolFailure, ToolNotAllowed
from ..tool_catalog import ALLOWED_TOOL_NAMES, ToolDefinition

# Protocol versions accepted by the MCP SDK used by the pinned Harness
# (@deepseek-ai/dsh-mcp-client → @modelcontextprotocol/sdk 1.30.0). The SDK
# rejects any other value with "Server's protocol version is not supported".
SUPPORTED_MCP_PROTOCOL_VERSIONS = (
    "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07",
)
DEFAULT_MCP_PROTOCOL_VERSION = "2024-11-05"


def negotiate_mcp_protocol_version(client_version: str | None) -> str:
    """Negotiate the MCP wire protocol version for the stdio server.

    Echoes the client's offered version when it is supported by the MCP SDK;
    otherwise falls back to a stable supported baseline. The internal
    ``MCPHandshake.version`` (namespace contract version) is unchanged.
    """
    if client_version in SUPPORTED_MCP_PROTOCOL_VERSIONS:
        return client_version
    return DEFAULT_MCP_PROTOCOL_VERSION


@dataclass(frozen=True)
class MCPHandshake:
    namespace: str
    version: str
    tools: tuple[str, ...]


def validate_input(definition: ToolDefinition, args: dict[str, Any]) -> None:
    required = definition.input_schema.get("required", [])
    properties = definition.input_schema.get("properties", {})
    if any(field not in args for field in required):
        raise ToolFailure(f"missing required Tool input for {definition.name}")
    if definition.input_schema.get("additionalProperties") is False:
        unknown = set(args) - set(properties)
        if unknown:
            raise ToolFailure(f"unknown Tool inputs: {sorted(unknown)}")


def bounded_result(value: dict[str, Any], limit: int = MAX_TOOL_RESULT_BYTES) -> dict[str, Any]:
    import json
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > limit:
        raise ToolFailure("TOOL_RESULT_TOO_LARGE")
    return value


def handshake(namespace: str, version: str, tools: set[str] | frozenset[str]) -> MCPHandshake:
    if namespace != MCP_NAMESPACE or tools != ALLOWED_TOOL_NAMES:
        raise ToolNotAllowed("catalog")
    return MCPHandshake(namespace=namespace, version=version, tools=tuple(sorted(tools)))

