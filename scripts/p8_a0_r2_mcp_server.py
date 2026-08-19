"""Minimal stdio MCP server exposing the R2 read-only Research OS surface."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

from research_os.agent_runtime.research_capabilities import TOOLS, bounded


def event_log(event: dict) -> None:
    path = os.environ.get("P8_R2_EVENT_LOG")
    if not path:
        return
    event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event}
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n")


def reply(request_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is not None:
        message["error"] = error
    else:
        message["result"] = result
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    for line in sys.stdin:
        if not line.strip():
            continue
        request = json.loads(line)
        method = request.get("method")
        request_id = request.get("id")
        if request_id is None:
            continue
        try:
            if method == "initialize":
                reply(request_id, {"protocolVersion": "2025-06-18", "capabilities": {"tools": {"listChanged": False}}, "serverInfo": {"name": "research-os", "version": "p8-a0-r2"}})
            elif method == "tools/list":
                reply(request_id, {"tools": [{k: v for k, v in spec.items() if k != "handler"} | {"name": name} for name, spec in TOOLS.items()]})
            elif method == "tools/call":
                params = request.get("params") or {}
                name = params.get("name")
                if name not in TOOLS:
                    event_log({"event_type": "tool_call", "tool_name": name, "status": "TOOL_NOT_ALLOWED"})
                    raise PermissionError("TOOL_NOT_ALLOWED")
                result = bounded(TOOLS[name]["handler"](**(params.get("arguments") or {})))
                event_log({"event_type": "tool_call", "tool_name": name, "status": result.get("status", "unknown")})
                reply(request_id, {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)},], "structuredContent": result})
            else:
                reply(request_id, error={"code": -32601, "message": "method_not_found"})
        except PermissionError as exc:
            event_log({"event_type": "tool_call", "tool_name": request.get("params", {}).get("name"), "status": str(exc)})
            reply(request_id, error={"code": -32001, "message": str(exc)})
        except Exception as exc:  # fail closed; no traceback or secrets on stdout
            event_log({"event_type": "tool_call", "tool_name": request.get("params", {}).get("name"), "status": "TOOL_EXECUTION_FAILED"})
            reply(request_id, error={"code": -32002, "message": f"TOOL_EXECUTION_FAILED: {type(exc).__name__}"})


if __name__ == "__main__":
    main()
