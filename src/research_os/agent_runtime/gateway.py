"""Single backend Agent Runtime boundary with legacy-safe routing."""
from __future__ import annotations

import uuid
from typing import Any

from .config import AgentRuntimeConfig
from .errors import ConfigurationError, RuntimeFailure, RuntimeNotReady, SessionFailure
from .harness_adapter import HarnessAgentRuntimeAdapter
from .legacy_adapter import LegacyAgentRuntimeAdapter
from .models import GatewaySession, RuntimeStatus


class AgentRuntimeGateway:
    def __init__(
        self,
        config: AgentRuntimeConfig | None = None,
        legacy: LegacyAgentRuntimeAdapter | None = None,
        harness: HarnessAgentRuntimeAdapter | None = None,
        fallback_before_workflow: bool = True,
    ):
        self.config = (config or AgentRuntimeConfig.from_env()).validate()
        self.legacy = legacy or LegacyAgentRuntimeAdapter()
        self.harness = harness
        self.fallback_before_workflow = fallback_before_workflow
        self._sessions: dict[str, tuple[GatewaySession, Any]] = {}
        self._turn_counts: dict[str, int] = {}
        self._fallback_reasons: dict[str, str] = {}

    @property
    def mode(self) -> str:
        return self.config.mode

    def _adapter(self) -> Any:
        if self.config.mode == "legacy":
            return self.legacy
        if self.harness is None:
            raise ConfigurationError("Harness adapter is not configured")
        return self.harness

    def create_session(self, metadata: dict[str, str] | None = None, request: dict[str, object] | None = None) -> GatewaySession:
        AgentRuntimeConfig.from_request(request)
        if len(self._sessions) >= self.config.max_active_sessions:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "active session limit exceeded")
        adapter = self._adapter()
        try:
            session = adapter.create_session(metadata)
        except RuntimeFailure as exc:
            if self.config.mode == "harness" and self.fallback_before_workflow:
                session = self.legacy.create_session(metadata)
                self._fallback_reasons[session.gateway_session_id] = exc.code
                adapter = self.legacy
            else:
                raise
        self._sessions[session.gateway_session_id] = (session, adapter)
        self._turn_counts[session.gateway_session_id] = 0
        return session

    def _lookup(self, session_id: str) -> tuple[GatewaySession, Any]:
        try:
            return self._sessions[session_id]
        except KeyError as exc:
            raise SessionFailure("SESSION_NOT_FOUND", "gateway session does not exist") from exc

    def send_message(self, session_id: str, message: str) -> dict[str, Any]:
        session, adapter = self._lookup(session_id)
        if not isinstance(message, str) or not message.strip():
            raise SessionFailure("TURN_INVALID", "message must not be empty")
        if self._turn_counts[session.gateway_session_id] >= self.config.max_turns:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "session turn limit exceeded")
        result = adapter.send_message(session, message)
        self._turn_counts[session.gateway_session_id] += 1
        if session.gateway_session_id in self._fallback_reasons and isinstance(result, dict):
            result = {**result, "fallback_reason": self._fallback_reasons[session.gateway_session_id]}
        return result

    def resume_session(self, session_id: str) -> GatewaySession:
        session, adapter = self._lookup(session_id)
        return adapter.resume_session(session.gateway_session_id)

    def cancel_turn(self, session_id: str) -> dict[str, Any]:
        session, adapter = self._lookup(session_id)
        return adapter.cancel_turn(session)

    def get_runtime_status(self) -> RuntimeStatus:
        return self._adapter().get_runtime_status()
