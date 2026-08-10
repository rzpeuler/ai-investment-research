"""Thread-safe, process-local dashboard conversation state."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

IN_MEMORY_ONLY = "IN_MEMORY_ONLY"


@dataclass
class _Session:
    session_id: str
    selected_scenario: str | None = "AUTO"
    last_target: Any = None
    public_draft: dict[str, Any] | None = None
    minimal_request: dict[str, Any] | None = None
    turns: list[dict[str, Any]] = field(default_factory=list)


class SessionStore:
    """Stores complete request/response pairs; one pair is one turn."""

    storage_policy = IN_MEMORY_ONLY

    def __init__(self, max_turns: int = 20):
        if not isinstance(max_turns, int) or max_turns < 1:
            raise ValueError("max_turns must be a positive integer")
        self.max_turns = max_turns
        self._sessions: dict[str, _Session] = {}
        self._lock = RLock()

    def context(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return {}
            return deepcopy({
                "selected_scenario": session.selected_scenario,
                "last_target": session.last_target,
                "public_draft": session.public_draft,
                "minimal_request": session.minimal_request,
            })

    def record_turn(self, session_id: str, request: dict[str, Any], response: dict[str, Any]) -> None:
        with self._lock:
            session = self._sessions.setdefault(session_id, _Session(session_id))
            session.selected_scenario = request.get("selected_scenario")
            session.public_draft = response.get("draft")
            session.minimal_request = response.get("minimal_request")
            minimal = session.minimal_request or {}
            session.last_target = minimal.get("entity") or minimal.get("entity_id")
            session.turns.append({
                "session_id": session_id,
                "request": deepcopy(request),
                "response": deepcopy(response),
            })
            del session.turns[:-self.max_turns]

    def recent(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            session = self._sessions.get(session_id)
            return deepcopy(session.turns if session else [])
