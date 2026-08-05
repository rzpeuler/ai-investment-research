"""ID 工具测试。"""
from __future__ import annotations

from research_os.utils.id import content_sha256, new_uuid


def test_uuid_format():
    value = new_uuid()
    parts = value.split("-")
    assert len(parts) == 5
    assert all(len(p) == 8 or len(p) == 4 or len(p) == 12 for p in parts)
    assert len(value) == 36


def test_sha256_deterministic():
    assert content_sha256("abc") == content_sha256("abc")
    assert content_sha256("abc") != content_sha256("abd")
    assert len(content_sha256("x")) == 64
