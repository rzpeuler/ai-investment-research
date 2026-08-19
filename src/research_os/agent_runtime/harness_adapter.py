"""Harness adapter seam; the gateway never imports runtime-spike."""
from __future__ import annotations

import uuid
from typing import Any, Protocol

from .errors import RuntimeNotReady, SessionFailure
from .mcp.server import ResearchOSMCPServer
from .models import GatewaySession, RuntimeStatus
from .runtime_supervisor import HarnessRuntimeSupervisor


class HarnessClient(Protocol):
    def create_session(self) -> str: ...
    def send_message(self, session_id: str, message: str) -> dict[str, Any]: ...
    def resume_session(self, session_id: str) -> None: ...
    def cancel_turn(self, session_id: str) -> None: ...


class HarnessAgentRuntimeAdapter:
    mode = "harness"

    def __init__(self, supervisor: HarnessRuntimeSupervisor, mcp: ResearchOSMCPServer, client: HarnessClient):
        self.supervisor = supervisor
        self.mcp = mcp
        self.client = client
        self.sessions: dict[str, GatewaySession] = {}
        self.formal_work_started: set[str] = set()
        self.agent_turn_started: set[str] = set()

    def admit(self) -> RuntimeStatus:
        if not self.supervisor.ready:
            raise RuntimeNotReady("HARNESS_BOOT_FAILED", "Harness runtime is not READY")
        return self.supervisor.status()

    def create_session(self, metadata: dict[str, str] | None = None) -> GatewaySession:
        self.admit()
        internal = self.client.create_session()
        session = GatewaySession("gw_" + uuid.uuid4().hex, self.mode, internal, metadata or {})
        self.sessions[session.gateway_session_id] = session
        return session

    def resume_session(self, session_id: str) -> dict[str, Any]:
        try:
            session = self.sessions[session_id]
            self.client.resume_session(session.harness_session_id or "")
            return {"status": "resumed", "gateway_session_id": session.gateway_session_id}
        except KeyError as exc:
            raise SessionFailure("SESSION_NOT_FOUND", "gateway session does not exist") from exc

    def send_message(self, session: GatewaySession, message: str) -> dict[str, Any]:
        if session.gateway_session_id not in self.sessions:
            raise SessionFailure("SESSION_NOT_FOUND", "gateway session does not exist")
        self.admit()
        self.agent_turn_started.add(session.gateway_session_id)
        try:
            result = self.client.send_message(session.harness_session_id or "", message)
            if not isinstance(result, dict):
                raise SessionFailure("MCP_TOOL_FAILED", "Harness response must be structured")
            return result
        except Exception:
            raise

    def cancel_turn(self, session: GatewaySession) -> dict[str, Any]:
        self.client.cancel_turn(session.harness_session_id or "")
        return {"status": "cancelled", "gateway_session_id": session.gateway_session_id}

    def mark_research_workflow_started(self, session_id: str) -> None:
        if session_id not in self.sessions:
            raise SessionFailure("SESSION_NOT_FOUND", "gateway session does not exist")
        self.formal_work_started.add(session_id)

    def close_session(self, session: GatewaySession) -> dict[str, Any]:
        # Harness owns its internal persistence; only the gateway mapping is removed.
        self.sessions.pop(session.gateway_session_id, None)
        self.formal_work_started.discard(session.gateway_session_id)
        self.agent_turn_started.discard(session.gateway_session_id)
        return {"status": "closed", "gateway_session_id": session.gateway_session_id}

    def get_runtime_status(self) -> RuntimeStatus:
        return self.supervisor.status()
