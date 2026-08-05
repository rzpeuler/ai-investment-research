"""结构化错误记录（工程指南 50 节：每次任务保存 errors.log）。

errors.log 采用 JSONL 结构化格式，每条记录含：
timestamp / task_id / component / module / exception_type / message /
retryable / attempt / stacktrace / context。

安全约束：不得记录 API Key、Cookie、Authorization Header、密码、
完整敏感响应体。写入前对 context/message 执行敏感字段过滤。

所有失败必须显式记录并返回明确状态，禁止静默失败（工程指南约束）。
"""
from __future__ import annotations

import json
import re
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

_lock = threading.Lock()

# 敏感键名（递归过滤 context 时匹配键）
_SENSITIVE_KEYS = (
    "api_key", "apikey", "api-key",
    "cookie", "cookies",
    "authorization", "auth_header", "auth",
    "password", "passwd", "pwd",
    "token", "access_token", "refresh_token", "secret",
    "private_key",
)

# 敏感值模式（message 打码用）：常见凭据格式
_SENSITIVE_VALUE_RE = re.compile(
    r"(?i)(api[_-]?key|token|password|secret|cookie|authorization)\s*[=:]\s*\S+"
)

_REDACTED = "[REDACTED]"


def redact_text(text: str) -> str:
    """对 message 中的敏感键值对打码。"""
    return _SENSITIVE_VALUE_RE.sub(lambda m: f"{m.group(1)}={_REDACTED}", text)


def redact_value(value: Any) -> Any:
    """递归过滤：键名匹配敏感键则替换值；字符串值含敏感模式则打码。"""
    if isinstance(value, dict):
        return {k: _REDACTED if k.lower() in _SENSITIVE_KEYS else redact_value(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_value(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


class ErrorLog:
    """线程安全的 JSONL 结构化错误记录器。"""

    def __init__(self, path: str | Path, task_id: Optional[str] = None):
        self.path = Path(path)
        self.task_id = task_id

    def record(
        self,
        level: str,
        component: str,
        message: str,
        details: Optional[dict] = None,
        *,
        module: Optional[str] = None,
        exception: Optional[BaseException] = None,
        retryable: bool = False,
        attempt: int = 1,
        task_id: Optional[str] = None,
    ) -> None:
        """写入一条结构化记录。

        details 中的 task_id/module/exception_type/retryable/attempt 等键会
        提升为顶层字段；其余进入 context（经过敏感过滤）。
        """
        context = dict(details or {})
        entry: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "task_id": task_id or self.task_id,
            "component": component,
            "module": context.pop("module", module),
            "exception_type": context.pop("exception_type", None)
                              or (type(exception).__name__ if exception is not None else None),
            "message": redact_text(message),
            "retryable": bool(context.pop("retryable", retryable)),
            "attempt": int(context.pop("attempt", attempt)),
            "stacktrace": context.pop("stacktrace", None),
            "context": redact_value(context),
            "level": level,  # 人类可读附加字段（兼容旧格式）
        }
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def error(
        self,
        component: str,
        message: str,
        details: Optional[dict] = None,
        *,
        exception: Optional[BaseException] = None,
        **kwargs: Any,
    ) -> None:
        self.record("ERROR", component, message, details, exception=exception, **kwargs)

    def warning(
        self,
        component: str,
        message: str,
        details: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        self.record("WARNING", component, message, details, **kwargs)

    def info(
        self,
        component: str,
        message: str,
        details: Optional[dict] = None,
        **kwargs: Any,
    ) -> None:
        self.record("INFO", component, message, details, **kwargs)

    def record_exception(
        self,
        component: str,
        message: str,
        exception: BaseException,
        *,
        task_id: Optional[str] = None,
        module: Optional[str] = None,
        retryable: bool = False,
        attempt: int = 1,
        context: Optional[dict] = None,
        include_stacktrace: bool = True,
    ) -> None:
        """记录异常：自动提取 exception_type 与堆栈。"""
        stack = None
        if include_stacktrace and exception.__traceback__ is not None:
            stack = "".join(traceback.format_exception(
                type(exception), exception, exception.__traceback__))[-4000:]
        self.record(
            "ERROR", component, message,
            {"task_id": task_id, "module": module,
             "retryable": retryable, "attempt": attempt,
             "stacktrace": stack, **(context or {})},
            exception=exception,
        )

    def read(self) -> list[dict]:
        """读取全部记录（用于审计与测试）。"""
        if not self.path.exists():
            return []
        entries: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
