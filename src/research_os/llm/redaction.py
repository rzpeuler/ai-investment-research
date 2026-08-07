"""LLM 配置、日志和错误消息的机械脱敏。"""
from __future__ import annotations

import re
from typing import Any, Iterable

SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|authorization|bearer|cookie|secret|token|password)",
    re.IGNORECASE,
)
AUTH_VALUE_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|secret|token|password)"
    r"\s*[:=]\s*([^\s,;]+)"
)
REDACTED = "[REDACTED]"


def redact_text(value: Any, *, secrets: Iterable[str] = ()) -> str:
    """过滤常见凭证表达和调用方已知密钥值。"""
    text = str(value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, REDACTED)
    text = AUTH_VALUE_PATTERN.sub(f"Bearer {REDACTED}", text)
    text = ASSIGNMENT_PATTERN.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    return text


def redact_value(value: Any, *, secrets: Iterable[str] = ()) -> Any:
    """递归脱敏映射、序列和文本；敏感字段值整体替换。"""
    if isinstance(value, dict):
        return {
            key: REDACTED if SENSITIVE_KEY_PATTERN.search(str(key)) else
            redact_value(item, secrets=secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, secrets=secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, secrets=secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, secrets=secrets)
    return value


def contains_sensitive_label(value: str) -> bool:
    """Prompt 不得包含凭证字段或认证头指令。"""
    return bool(SENSITIVE_KEY_PATTERN.search(value))
