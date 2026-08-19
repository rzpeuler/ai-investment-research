"""Small deterministic lifecycle helpers used by offline acceptance tests."""
from __future__ import annotations

from dataclasses import dataclass

from .errors import RuntimeNotReady


@dataclass
class SessionQuota:
    limit: int
    active: int = 0

    def acquire(self) -> None:
        if self.active >= self.limit:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "session quota exceeded")
        self.active += 1

    def release(self) -> None:
        if self.active:
            self.active -= 1


def can_fallback(formal_work_started: bool) -> bool:
    return not formal_work_started
