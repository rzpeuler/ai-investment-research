"""Compatibility adapter for the existing P7-UX1 runtime."""
from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Protocol

from .models import GatewaySession, RuntimeStatus, SupervisorState


class P7UX1Runtime(Protocol):
    def send(self, session_id: str, message: str) -> dict[str, Any]: ...

    def resume(self, session_id: str) -> bool: ...

    def cancel(self, session_id: str) -> dict[str, Any]: ...


class DashboardP7UX1Runtime:
    """Thin binding to the existing dashboard ChatService and SessionStore."""

    def __init__(self, project_root: str | Path):
        from research_os.dashboard.models import ChatRequest
        from research_os.dashboard.runtime import build_dashboard_runtime

        self._chat_request = ChatRequest
        self.app, self.llm_configured, _ = build_dashboard_runtime(project_root)

    def send(self, session_id: str, message: str) -> dict[str, Any]:
        if not self.app.sessions.try_begin(session_id):
            return {"status": "failed", "code": "SESSION_BUSY", "message": "P7-UX1 session is busy"}
        try:
            context = self.app.sessions.context(session_id, "AUTO")
            request = self._chat_request(
                message=message, selected_scenario="AUTO",
                llm_enabled=bool(self.llm_configured), research_live=False,
                session_context=context,
            )
            result = self.app.chat_service.handle(request, conversation_context=context)
            raw = asdict(result)
            response = {
                "status": raw["state"],
                "message": raw["message"],
                "recognized": {"scenario": raw["scenario"], "reference_now": raw["reference_now"], "llm_calls": raw["llm_calls"]},
                "draft": raw["public_draft"],
                "minimal_request": raw["minimal_request"],
                "result": raw["research_result"],
            }
            self.app.sessions.record_turn(session_id, {"session_id": session_id, "message": message,
                                                        "selected_scenario": "AUTO", "llm_enabled": bool(self.llm_configured),
                                                        "research_live": False}, response)
            return response
        finally:
            self.app.sessions.end(session_id)

    def resume(self, session_id: str) -> bool:
        return session_id in self.app.sessions.session_ids

    def cancel(self, session_id: str) -> dict[str, Any]:
        # SessionStore has no turn-cancellation seam; never claim fake success.
        if session_id not in self.app.sessions.session_ids:
            return {"status": "not_supported", "code": "SESSION_NOT_FOUND"}
        return {"status": "not_supported", "code": "CANCEL_NOT_SUPPORTED"}

    def close(self, session_id: str) -> dict[str, Any]:
        return {"status": "closed", "gateway_session_id": session_id}


class LegacyAgentRuntimeAdapter:
    mode = "legacy"

    def __init__(self, turn_handler: Callable[[str, str], dict[str, Any]] | None = None,
                 runtime: P7UX1Runtime | None = None, project_root: str | Path | None = None):
        self.turn_handler = turn_handler
        self.runtime = runtime
        self.project_root = Path(project_root) if project_root is not None else None
        self.sessions: dict[str, GatewaySession] = {}

    def _send(self, session_id: str, message: str) -> dict[str, Any]:
        if self.turn_handler is not None:
            return self.turn_handler(session_id, message)
        if self.runtime is None:
            if self.project_root is None:
                self.project_root = Path.cwd()
            self.runtime = DashboardP7UX1Runtime(self.project_root)
        return self.runtime.send(session_id, message)

    def create_session(self, metadata: dict[str, str] | None = None) -> GatewaySession:
        session = GatewaySession("gw_" + uuid.uuid4().hex, self.mode, metadata=metadata or {})
        self.sessions[session.gateway_session_id] = session
        return session

    def send_message(self, session: GatewaySession, message: str) -> dict[str, Any]:
        return self._send(session.gateway_session_id, message)

    def resume_session(self, session_id: str) -> GatewaySession:
        try:
            session = self.sessions[session_id]
        except KeyError as exc:
            raise KeyError(session_id) from exc
        if self.runtime is not None and not self.runtime.resume(session_id):
            raise KeyError(session_id)
        return session

    def cancel_turn(self, session: GatewaySession) -> dict[str, Any]:
        if self.runtime is None:
            return {"status": "not_supported", "code": "CANCEL_NOT_SUPPORTED"}
        return {**self.runtime.cancel(session.gateway_session_id), "gateway_session_id": session.gateway_session_id}

    def close_session(self, session: GatewaySession) -> dict[str, Any]:
        result = {"status": "closed", "gateway_session_id": session.gateway_session_id}
        self.sessions.pop(session.gateway_session_id, None)
        if self.runtime is not None:
            result = {**self.runtime.close(session.gateway_session_id), "gateway_session_id": session.gateway_session_id}
        return result

    def get_runtime_status(self) -> RuntimeStatus:
        return RuntimeStatus(SupervisorState.READY, True, True, True, True)
