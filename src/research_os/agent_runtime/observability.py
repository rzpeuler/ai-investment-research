"""Bounded operational telemetry and secret redaction."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SECRET_FIELD = re.compile(r"(?i)(api[_ -]?key|authorization|bearer|cookie|password|token|credential|secret)")
SECRET_VALUE = re.compile(r"(?i)(bearer\s+)?[A-Za-z0-9_\-./+=]{12,}")


def redact(value: Any, known_secrets: set[str] | frozenset[str] = frozenset(), field_name: str = "") -> Any:
    if SECRET_FIELD.search(field_name):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(key): redact(item, known_secrets, str(key)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, known_secrets, field_name) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item, known_secrets, field_name) for item in value)
    if isinstance(value, str):
        result = value
        for secret in known_secrets:
            if secret:
                result = result.replace(secret, "[REDACTED]")
        if "authorization" in result.lower() or "bearer " in result.lower():
            return "[REDACTED]"
        return result
    return value


@dataclass
class EventRecorder:
    known_secrets: set[str] = field(default_factory=set)
    events: list[dict[str, Any]] = field(default_factory=list)

    def record(self, event: str, **fields: Any) -> dict[str, Any]:
        item = {"event": event, **redact(fields, self.known_secrets)}
        self.events.append(item)
        return item

