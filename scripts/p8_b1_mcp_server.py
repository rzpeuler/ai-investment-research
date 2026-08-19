"""Production stdio MCP transport for the P8-B1 Research OS boundary."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from research_os.agent_runtime.mcp.tools import build_research_os_mcp_server


def _log(event: dict[str, object]) -> None:
    path = os.environ.get("P8_B1_EVENT_LOG")
    if not path:
        return
    safe = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(safe, ensure_ascii=False, separators=(",", ":")) + "\n")


def _reply(request_id: object, result: object = None, error: dict[str, object] | None = None) -> None:
    response: dict[str, object] = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        response["result"] = result
    else:
        response["error"] = error
    sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> int:
    server = build_research_os_mcp_server()
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        try:
            if method == "initialize":
                _reply(request_id, {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "research-os-mcp/v1", "version": "1"},
                })
            elif method == "tools/list":
                _reply(request_id, {"tools": [
                    {"name": definition.name, "description": definition.description,
                     "inputSchema": definition.input_schema}
                    for definition in server._catalog.values()
                ]})
            elif method == "tools/call":
                params = request.get("params") or {}
                name = params.get("name")
                result = server.call(name, params.get("arguments") or {}, str(request_id))
                _log({"event_type": "tool_call", "tool_name": name, "status": result.get("status", "unknown")})
                _reply(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
                                    "structuredContent": result})
            else:
                _reply(request_id, error={"code": -32601, "message": "method_not_found"})
        except Exception as exc:  # bounded failure: never emit traceback or secret values
            code = getattr(exc, "code", "TOOL_EXECUTION_FAILED")
            _log({"event_type": "tool_call", "tool_name": (request.get("params") or {}).get("name"), "status": code})
            _reply(request_id, error={"code": -32002, "message": str(code)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
