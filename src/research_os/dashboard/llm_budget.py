"""One-call Flash-only budget used independently by each chat stage."""
from __future__ import annotations

from typing import Any, Dict


class ChatStageBudget:
    def __init__(self, stage: str):
        self.stage = stage
        self.flash_calls = 0
        self.pro_calls = 0

    def can_call(self, model_class: str) -> bool:
        return model_class == "flash" and self.flash_calls < 1

    def record(self, model_class: str) -> None:
        if not self.can_call(model_class):
            raise RuntimeError(f"chat {self.stage} budget denied {model_class}")
        self.flash_calls += 1

    def summary(self) -> Dict[str, Any]:
        return {"stage": self.stage, "flash_calls": self.flash_calls, "pro_calls": self.pro_calls,
                "max_flash": 1, "max_pro": 0}
