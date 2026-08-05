"""时间工具测试（Asia/Shanghai 口径）。"""
from __future__ import annotations

import pytest

from research_os.utils.time import now_iso, parse_iso, shanghai_now, validate_iso


def test_validate_iso_accepts_valid():
    assert validate_iso("2026-08-05T08:00:00")
    assert validate_iso("2026-08-05T08:00:00+08:00")
    assert validate_iso("2026-08-05T08:00:00Z")
    assert validate_iso("2026-08-05T08:00:00.123")


def test_validate_iso_rejects_invalid():
    assert not validate_iso("2026/08/05 08:00")
    assert not validate_iso("08-05-2026")
    assert not validate_iso("not-a-date")
    assert not validate_iso("2026-13-45T99:00:00")
    assert not validate_iso("")


def test_now_iso_format():
    value = now_iso()
    assert validate_iso(value)
    assert value.startswith("2026") or value.startswith("2027")


def test_shanghai_now_is_naive_and_positive():
    dt = shanghai_now()
    assert dt.tzinfo is None  # naive，语义为 Asia/Shanghai


def test_parse_iso_roundtrip():
    dt = parse_iso("2026-08-05T08:00:00+08:00")
    assert dt.hour == 8
    dt2 = parse_iso("2026-08-05T00:00:00Z")
    assert dt2.hour == 8  # UTC 0 点 = 上海 8 点


def test_parse_iso_invalid_raises():
    with pytest.raises(ValueError):
        parse_iso("yesterday")
