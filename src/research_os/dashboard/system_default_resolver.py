"""Code-only owner for required chat-to-runner system controls."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict

from research_os.dashboard.models import TemporalResult


@dataclass(frozen=True)
class SystemDefaultResolver:
    reference_now: datetime

    def required_as_of(self, temporal: TemporalResult) -> str:
        if temporal.status == "resolved" and temporal.as_of:
            return temporal.as_of
        return self.reference_now.isoformat(timespec="seconds")

    @staticmethod
    def add_research_live(request: Dict[str, Any], enabled: bool) -> None:
        if enabled:
            request["live"] = True
