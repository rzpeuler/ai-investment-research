"""时间工具：统一 Asia/Shanghai 口径（工程指南：时间口径 Asia/Shanghai）。

确定性逻辑（日期计算、数据日期校验等）必须使用代码，不得交给 LLM（指南 6.3）。
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta

PROJECT_TIMEZONE = "Asia/Shanghai"
_SHANGHAI_TZ = timezone(timedelta(hours=8), name="Asia/Shanghai")

_ISO_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?$"
)


def shanghai_now() -> datetime:
    """返回当前 Asia/Shanghai 时间的 naive datetime。"""
    return datetime.now(_SHANGHAI_TZ).replace(tzinfo=None)


def now_iso() -> str:
    """当前 Asia/Shanghai 时间，ISO-8601 格式（无时区后缀，语义为 Asia/Shanghai）。"""
    return shanghai_now().isoformat(timespec="seconds")


def validate_iso(value: str) -> bool:
    """校验字符串是否为合法 ISO-8601 时间（宽松：允许 Z 或 ±HH:MM 后缀或 naive）。"""
    if not isinstance(value, str) or not _ISO_RE.match(value):
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def to_iso(dt: datetime) -> str:
    """datetime -> ISO-8601 字符串（Asia/Shanghai 口径）。"""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_SHANGHAI_TZ)
    return dt.astimezone(_SHANGHAI_TZ).isoformat(timespec="seconds")


def parse_iso(value: str) -> datetime:
    """ISO-8601 字符串 -> datetime（naive，统一为 Asia/Shanghai 语义）。"""
    if not validate_iso(value):
        raise ValueError(f"非法 ISO-8601 时间: {value!r}")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is not None:
        dt = dt.astimezone(_SHANGHAI_TZ).replace(tzinfo=None)
    return dt
