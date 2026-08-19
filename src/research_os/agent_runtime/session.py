import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


_SECRET = re.compile(r"(?i)(api[_ -]?key|authorization|cookie|password|credential)\s*[:=]\s*[^\s,]+")


@dataclass
class DurableSession:
    """Small JSON session store for conversation memory only.

    Research state remains owned by Research OS.  The store keeps bounded
    messages and references, and rejects obvious credential material.
    """

    session_id: str
    root: Path
    max_turns: int = 20
    messages: list[dict[str, Any]] = field(default_factory=list)
    references: list[str] = field(default_factory=list)

    @property
    def path(self) -> Path:
        return self.root / f"{self.session_id}.json"

    def add_turn(self, user: str, assistant: str, references: list[str] | None = None) -> None:
        if _SECRET.search(user) or _SECRET.search(assistant):
            raise ValueError("credential-like material is not allowed in agent session")
        self.messages.append({"user": user, "assistant": assistant})
        self.messages = self.messages[-self.max_turns :]
        self.references = list(dict.fromkeys(self.references + (references or [])))

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def to_dict(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "messages": self.messages, "references": self.references}

    @classmethod
    def load(cls, session_id: str, root: Path, max_turns: int = 20) -> "DurableSession":
        path = root / f"{session_id}.json"
        if not path.exists():
            return cls(session_id=session_id, root=root, max_turns=max_turns)
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(session_id=session_id, root=root, max_turns=max_turns,
                   messages=data.get("messages", [])[-max_turns:], references=data.get("references", []))
