"""Thread-safe, bounded, process-local dashboard conversation state."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

IN_MEMORY_ONLY = "IN_MEMORY_ONLY"


@dataclass
class _Session:
    session_id: str
    selected_scenario: str | None = "AUTO"
    resolved_scenario: str | None = None
    last_target: Any = None
    public_draft: dict[str, Any] | None = None
    minimal_request: dict[str, Any] | None = None
    semantic_user_messages: list[str] = field(default_factory=list)
    turns: list[dict[str, Any]] = field(default_factory=list)
    inflight: bool = False


class SessionStore:
    """LRU session store; one complete request/response pair is one turn."""

    storage_policy = IN_MEMORY_ONLY

    def __init__(self, max_turns: int = 20, max_sessions: int = 128,
                 max_semantic_messages: int = 5):
        for name, value in (("max_turns", max_turns), ("max_sessions", max_sessions),
                            ("max_semantic_messages", max_semantic_messages)):
            if not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        self.max_semantic_messages = max_semantic_messages
        self._sessions: OrderedDict[str, _Session] = OrderedDict()
        self._lock = RLock()

    @property
    def session_count(self) -> int:
        with self._lock:
            return len(self._sessions)

    @property
    def session_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._sessions)

    def try_begin(self, session_id: str) -> bool:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                self._touch(session_id)
                if session.inflight:
                    return False
            else:
                session = self._create(session_id)
                if session is None:
                    return False
            session.inflight = True
            return True

    def end(self, session_id: str) -> None:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is not None:
                session.inflight = False
                self._touch(session_id)

    def context(self, session_id: str, selected_scenario: str | None = None) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            if (selected_scenario not in {None, "AUTO"}
                    and session.resolved_scenario not in {None, selected_scenario}):
                self._clear_semantic(session)
            self._touch(session_id)
            return deepcopy({
                "scenario": session.resolved_scenario,
                "user_messages": session.semantic_user_messages,
            })

    def record_turn(self, session_id: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.get(session_id) or self._create(session_id)
            if session is None:
                return
            session.selected_scenario = request.get("selected_scenario")
            current_draft = response.get("draft")
            current_minimal = response.get("minimal_request")
            recognized = response.get("recognized") or {}
            resolved = recognized.get("scenario")
            if isinstance(resolved, str):
                if resolved != session.resolved_scenario:
                    self._clear_semantic(session)
                    session.resolved_scenario = resolved
                session.public_draft = current_draft
                session.minimal_request = current_minimal
                minimal = current_minimal or {}
                session.last_target = minimal.get("entity") or minimal.get("entity_id")
                if isinstance(current_draft, dict):
                    message = request.get("message")
                    if isinstance(message, str) and message.strip():
                        session.semantic_user_messages.append(message)
                        del session.semantic_user_messages[:-self.max_semantic_messages]
            session.turns.append({
                "session_id": session_id,
                "request": deepcopy(request),
                "response": deepcopy(response),
            })
            del session.turns[:-self.max_turns]
            self._touch(session_id)

    def recent(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return []
            self._touch(session_id)
            return deepcopy(session.turns)

    def _create(self, session_id: str) -> _Session | None:
        while len(self._sessions) >= self.max_sessions:
            evict_id = next((key for key, value in self._sessions.items()
                             if not value.inflight), None)
            if evict_id is None:
                return None
            del self._sessions[evict_id]
        session = _Session(session_id)
        self._sessions[session_id] = session
        return session

    def _touch(self, session_id: str) -> None:
        self._sessions.move_to_end(session_id)

    @staticmethod
    def _clear_semantic(session: _Session) -> None:
        session.resolved_scenario = None
        session.semantic_user_messages.clear()
        session.public_draft = None
        session.minimal_request = None
        session.last_target = None
