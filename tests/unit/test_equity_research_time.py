"""Phase 4 日期与 as_of 语义回归测试。"""
from __future__ import annotations

from datetime import datetime

import pytest

from research_os.equity_research.pipeline import EquityResearchPipeline
from research_os.storage import Database


def _pipeline(tmp_path):
    db = Database(":memory:")
    db.initialize()
    return EquityResearchPipeline(tmp_path, db), db


def test_default_report_date_uses_frozen_shanghai_time(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        request = pipeline.parse_request({"entity": "600519.SH"})
    finally:
        db.close()
    assert request.report_date == "2031-02-03"
    assert request.report_date != "2026-08-06"
    assert request.timezone == "Asia/Shanghai"


def test_explicit_historical_date_is_not_overwritten(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        request = pipeline.parse_request({"entity": "600519.SH", "date": "2024-01-15"})
    finally:
        db.close()
    assert request.report_date == "2024-01-15"


def test_as_of_and_requested_at_have_separate_semantics(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        request = pipeline.parse_request({
            "entity": "600519.SH", "date": "2024-01-15",
            "as_of": "2024-01-14T18:30:00",
        })
    finally:
        db.close()
    assert request.as_of == "2024-01-14T18:30:00"
    assert request.requested_at == "2031-02-03T04:05:06"
    assert request.as_of_basis == "user_provided"


def test_missing_as_of_is_labeled_query_cutoff_not_data_date(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        request = pipeline.parse_request({"entity": "600519.SH"})
    finally:
        db.close()
    assert request.as_of_basis == "query_cutoff"
    assert any("实际数据日期" in warning for warning in request.warnings)


def test_as_of_within_five_second_clock_skew_is_allowed(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        request = pipeline.parse_request({
            "entity": "600519.SH", "as_of": "2031-02-03T04:05:11",
        })
    finally:
        db.close()
    assert request.as_of == "2031-02-03T04:05:11"


def test_as_of_more_than_five_seconds_after_requested_at_fails(tmp_path, monkeypatch):
    import research_os.utils.time as time_utils

    monkeypatch.setattr(time_utils, "shanghai_now", lambda: datetime(2031, 2, 3, 4, 5, 6))
    pipeline, db = _pipeline(tmp_path)
    try:
        with pytest.raises(ValueError, match="as_of 不得晚于 requested_at 超过 5 秒"):
            pipeline.parse_request({
                "entity": "600519.SH", "as_of": "2031-02-03T04:05:12",
            })
    finally:
        db.close()
