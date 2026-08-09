"""Phase 6B 时间窗口测试（DECISIONS #43 / shared-contract §12）。

evening_brief 窗口严格为 [08:00, 20:00) Asia/Shanghai：
08:00 inclusive、20:00 exclusive；延迟补跑不漂移。
"""
from __future__ import annotations

from datetime import date

from research_os.brief.window import evening_policy, morning_policy
from research_os.brief.pipeline import BriefPipeline, PipelineConfig
from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid

EVENING = evening_policy()
DAY = date(2026, 8, 6)


def _raw(published: str, title: str = "测试信息") -> RawItem:
    return RawItem(
        raw_item_id=new_uuid(), source_id="manual_inbox", external_id=new_uuid(),
        url="https://example.com/x", title=title, publisher="人工",
        author=None, published_at=published, retrieved_at="2026-08-06T20:00:00",
        content_hash=content_sha256(f"{title}|{published}"),
        content_excerpt=title, content_storage="metadata_and_excerpt",
        language="zh-CN", access_status="ok", entities=[], raw_category="news",
    )


def _run_window(items):
    pipeline = BriefPipeline(PipelineConfig(
        source_tiers={"manual_inbox": "C"}, source_status={},
        channel_map={"manual_inbox": "manual_submission"},
    ), window_policy=EVENING)
    return pipeline.run(items, DAY, as_of="2026-08-06T20:00:00+08:00")


def test_evening_window_bounds():
    """窗口常量：当日 08:00 至 20:00（+08:00）。"""
    start, end = EVENING.window(DAY)
    assert start == "2026-08-06T08:00:00+08:00"
    assert end == "2026-08-06T20:00:00+08:00"


def test_075959_excluded():
    a = _run_window([_raw("2026-08-06T07:59:59+08:00")])
    assert a.raw_items == []
    assert any("窗口外" in w for w in a.warnings)


def test_080000_included():
    a = _run_window([_raw("2026-08-06T08:00:00+08:00")])
    assert len(a.raw_items) == 1


def test_195959_included():
    a = _run_window([_raw("2026-08-06T19:59:59+08:00")])
    assert len(a.raw_items) == 1


def test_200000_excluded():
    """20:00:00 严格排除（end exclusive）。"""
    a = _run_window([_raw("2026-08-06T20:00:00+08:00")])
    assert a.raw_items == []
    assert any("窗口外" in w for w in a.warnings)


def test_200001_excluded():
    a = _run_window([_raw("2026-08-06T20:00:01+08:00")])
    assert a.raw_items == []


def test_previous_day_2000_excluded():
    """前一日信息不属于晚报窗口（晨报职责）。"""
    a = _run_window([_raw("2026-08-05T20:00:00+08:00")])
    assert a.raw_items == []


def test_late_run_does_not_drift():
    """21:15 补跑仍采集 08:00→20:00，不得变成 08:00→21:15。"""
    a = _run_window([
        _raw("2026-08-06T20:30:00+08:00", "补跑时点之后的信息"),
        _raw("2026-08-06T19:30:00+08:00", "窗口内信息"),
    ])
    titles = [c.title for c in a.candidates]
    assert "窗口内信息" in titles
    assert "补跑时点之后的信息" not in titles


def test_as_of_tighter_than_window_end():
    """用户显式 as_of 早于窗口结束时以其为数据截止。"""
    a = BriefPipeline(PipelineConfig(
        source_tiers={"manual_inbox": "C"}, source_status={},
        channel_map={"manual_inbox": "manual_submission"},
    ), window_policy=EVENING).run(
        [_raw("2026-08-06T15:00:00+08:00", "as_of 之前"),
         _raw("2026-08-06T17:00:00+08:00", "as_of 之后")],
        DAY, as_of="2026-08-06T16:00:00+08:00")
    titles = [c.title for c in a.candidates]
    assert "as_of 之前" in titles
    assert "as_of 之后" not in titles


def test_morning_and_evening_end_exclusive_consistent():
    """morning 与 evening 共享同一 end-exclusive 过滤语义。"""
    morning = morning_policy()
    m_start, m_end = morning.window(DAY)
    assert m_start == "2026-08-05T20:00:00+08:00"
    assert m_end == "2026-08-06T08:00:00+08:00"
    # morning 的 end 时刻（08:00:00）同样排除
    a = BriefPipeline(PipelineConfig(
        source_tiers={"manual_inbox": "C"}, source_status={},
        channel_map={"manual_inbox": "manual_submission"},
    ), window_policy=morning).run(
        [_raw("2026-08-06T08:00:00+08:00", "晨报窗口 end 时刻")], DAY,
        as_of="2026-08-06T08:00:00+08:00")
    assert a.raw_items == []
    assert any("窗口外" in w for w in a.warnings)


def test_morning_and_evening_idempotency_keys_differ_by_scenario():
    """幂等键：scenario + report_date + window（morning/evening 天然区分）。"""
    m_key = morning_policy().idempotency_key("2026-08-06", "2026-08-05T20:00:00+08:00", "2026-08-06T08:00:00+08:00")
    e_key = EVENING.idempotency_key("2026-08-06", "2026-08-06T08:00:00+08:00", "2026-08-06T20:00:00+08:00")
    assert m_key != e_key
    assert m_key.startswith("morning_brief|")
    assert e_key.startswith("evening_brief|")
