"""ID 与哈希工具（确定性逻辑，指南 6.3）。"""
from __future__ import annotations

import hashlib
import uuid


def new_uuid() -> str:
    """生成 UUID v4 字符串。"""
    return str(uuid.uuid4())


def content_sha256(text: str) -> str:
    """内容去重哈希（指南 29.1 精确去重使用）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
