"""Compatibility adapter for the existing P7-UX1 runtime."""
from __future__ import annotations

import uuid
from typing import Any, Callable

from .models import GatewaySession, RuntimeStatus, SupervisorState


class LegacyAgentRuntimeAdapter:
    mode = "legacy"

    def __init__(self, turn_handler: Callable[[str, str], dict[str, Any]] | None = None):
        self.turn_handler = turn_handler or (lambda _session_id, message: {"status": "accepted", "message": message})
        self.sessions: dict[str, GatewaySession] = {}

    def create_session(self, metadata: dict[str, str] | None = None) -> GatewaySession:
        session = GatewaySession("gw_" + uuid.uuid4().hex, self.mode, metadata=metadata or {})
        self.sessions[session.gateway_session_id] = session
        return session

    def send_message(self, session: GatewaySession, message: str) -> dict[str, Any]:
        return self.turn_handler(session.gateway_session_id, message)

    def resume_session(self, session_id: str) -> GatewaySession:
        return self.sessions[session_id]

    def cancel_turn(self, session: GatewaySession) -> dict[str, Any]:
        return {"status": "cancelled", "gateway_session_id": session.gateway_session_id}

    def get_runtime_status(self) -> RuntimeStatus:
        return RuntimeStatus(SupervisorState.READY, True, True, True, True)
