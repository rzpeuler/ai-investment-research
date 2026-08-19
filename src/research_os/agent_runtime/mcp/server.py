"""In-process MCP boundary used by the supervisor and deterministic tests."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from ..config import MCP_NAMESPACE, MAX_TOOL_RESULT_BYTES
from ..errors import RuntimeNotReady, ToolFailure, ToolNotAllowed
from ..observability import EventRecorder
from ..tool_catalog import ALLOWED_TOOL_NAMES, catalog
from .contracts import MCPHandshake, bounded_result, handshake, validate_input


class ResearchOSMCPServer:
    namespace = MCP_NAMESPACE
    protocol_version = "1"

    def __init__(self, handlers: dict[str, Callable[..., dict[str, Any]]], recorder: EventRecorder | None = None):
        if set(handlers) != ALLOWED_TOOL_NAMES:
            raise ValueError("Research OS MCP server requires exactly two handlers")
        self._catalog = catalog(handlers)
        self._recorder = recorder or EventRecorder()
        self._handshake: MCPHandshake | None = None

    @property
    def tools(self) -> tuple[str, ...]:
        return tuple(sorted(self._catalog))

    def perform_handshake(self) -> MCPHandshake:
        self._handshake = handshake(self.namespace, self.protocol_version, set(self._catalog))
        return self._handshake

    def call(self, name: str, args: dict[str, Any], request_id: str | None = None) -> dict[str, Any]:
        if self._handshake is None:
            raise RuntimeNotReady("MCP_UNAVAILABLE", "MCP handshake has not completed")
        if name not in ALLOWED_TOOL_NAMES:
            raise ToolNotAllowed(name)
        definition = self._catalog[name]
        validate_input(definition, args)
        if definition.handler is None:
            raise ToolFailure(f"handler unavailable: {name}")
        request_id = request_id or uuid.uuid4().hex
        self._recorder.record("tool_start", request_id=request_id, tool=name)
        try:
            result = definition.handler(**args)
            if not isinstance(result, dict):
                raise ToolFailure("Tool result must be structured")
            result = bounded_result(result, MAX_TOOL_RESULT_BYTES)
        except RuntimeNotReady:
            raise
        except ToolFailure:
            raise
        except Exception as exc:
            raise ToolFailure(str(exc)) from exc
        self._recorder.record("tool_complete", request_id=request_id, tool=name, status=result.get("status"))
        return result
