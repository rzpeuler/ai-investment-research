"""分层事件检索与时间因果测试（Phase 3 任务书 9、10 节）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.abnormal_move.causal_timing_checker import (
    AFTER_MOVE,
    BEFORE_MOVE,
    DURING_MOVE,
    UNKNOWN_ORDER,
    check_direct_trigger,
    classify_timing,
    official_confirmation_boost,
)
from research_os.abnormal_move.event_window_retriever import EventWindowRetriever
from research_os.models import RawItem
from research_os.storage import Database
from research_os.utils.id import content_sha256, new_uuid


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "ev.db")
    database.initialize()
    yield database
    database.close()


def _raw_item(source_id: str, title: str, published_at: str,
              entities=None) -> RawItem:
    return RawItem(
        raw_item_id=new_uuid(), source_id=source_id, external_id="",
        url="https://example.com/x", title=title, publisher=source_id,
        author=None, published_at=published_at, retrieved_at=published_at,
        content_hash=content_sha256(title),
        content_excerpt=f"{title}（摘录）", content_storage="metadata_and_excerpt",
        language="zh-CN", access_status="ok",
        entities=entities or ["company:600519.SH"], raw_category="news",
    )


class TestEventWindowRetriever:
    def test_layer1_high_authority(self, db):
        item = _raw_item("cninfo", "600519 发布业绩预告", "2026-08-04T09:00:00")
        db.upsert(item)
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert any(i.source_id == "cninfo" and i.layer == 1 for i in r.items)

    def test_layer2_manual_inbox(self, db):
        from research_os.collectors.manual import ManualInboxService
        service = ManualInboxService(db)
        entry = service.add(source_name="财联社", source_url="https://x",
                            title="某公司公告", content_excerpt="",
                            notes="", intended_entities=["company:600519.SH"])
        service.update_status(entry.inbox_id, "accepted")
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert any(i.kind == "manual" for i in r.items)

    def test_layer2_morning_artifacts(self, db, tmp_path):
        runs = tmp_path / "reports" / "runs" / "run-1"
        runs.mkdir(parents=True)
        (runs / "candidate_items.json").write_text(json.dumps([{
            "candidate_item_id": "c1", "title": "行业政策出台",
            "source_id": "cls", "published_at": "2026-08-04T10:00:00",
            "entities": ["company:600519.SH"], "summary": "行业政策",
        }], ensure_ascii=False), encoding="utf-8")
        r = EventWindowRetriever(db, reports_root=tmp_path / "reports").retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert any(i.kind == "candidate" for i in r.items)

    def test_window_filter_applies(self, db):
        db.upsert(_raw_item("cninfo", "窗口外公告", "2026-07-01T09:00:00"))
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert not any("窗口外" in i.title for i in r.items)

    def test_empty_result_warns_not_no_event(self, db):
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert r.items == []
        assert any("不等于没有事件" in w for w in r.warnings)

    def test_depth_budget_invalid(self, db):
        with pytest.raises(ValueError, match="depth"):
            EventWindowRetriever(db).retrieve(
                "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59",
                depth="ultra")

    def test_channels_covered_honest(self, db):
        db.upsert(_raw_item("cls", "快讯", "2026-08-04T10:00:00"))
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        assert r.channels_covered["fast_news"] == "covered"
        assert r.channels_covered["deep_financial_media"] == "manual_only"
        assert r.channels_covered["institutional_activity"] == "manual_only"

    def test_deduplication(self, db):
        db.upsert(_raw_item("cninfo", "同一公告", "2026-08-04T09:00:00"))
        db.upsert(_raw_item("cninfo", "同一公告", "2026-08-04T09:00:00"))
        r = EventWindowRetriever(db).retrieve(
            "company:600519.SH", "2026-08-01T00:00:00", "2026-08-05T23:59:59")
        titles = [i.title for i in r.items if i.title == "同一公告"]
        assert len(titles) == 1


class TestCausalTiming:
    def test_before_move_eligible(self):
        c = classify_timing("2026-08-04T09:00:00", "2026-08-05T09:30:00",
                            "2026-08-05T15:00:00")
        assert c.timing_relation == BEFORE_MOVE
        assert c.direct_eligible is True

    def test_after_move_not_eligible(self):
        c = classify_timing("2026-08-05T20:00:00", "2026-08-05T09:30:00",
                            "2026-08-05T15:00:00")
        assert c.timing_relation == AFTER_MOVE
        assert c.direct_eligible is False
        assert any("异动后" in w for w in c.warnings)

    def test_during_move(self):
        c = classify_timing("2026-08-05T11:00:00", "2026-08-05T09:30:00",
                            "2026-08-05T15:00:00")
        assert c.timing_relation == DURING_MOVE
        assert c.direct_eligible is False

    def test_same_day_no_minute_unknown_order(self):
        # 只有日期无分钟 -> UNKNOWN_ORDER + medium 上限
        c = classify_timing("2026-08-05", "2026-08-05T09:30:00",
                            "2026-08-05T15:00:00")
        assert c.timing_relation == UNKNOWN_ORDER
        assert c.confidence_cap == "medium"

    def test_old_news_no_development_rejected(self):
        c = check_direct_trigger(
            published_at="2026-08-04T09:00:00",
            first_disclosed_at="2026-01-01T00:00:00",
            move_start_at="2026-08-05T09:30:00",
            move_end_at="2026-08-05T15:00:00",
            is_old_news=True, has_new_development=False)
        assert c.direct_eligible is False
        assert any("旧闻" in w for w in c.warnings)

    def test_old_news_with_development_eligible(self):
        c = check_direct_trigger(
            published_at="2026-08-04T09:00:00",
            first_disclosed_at="2026-01-01T00:00:00",
            move_start_at="2026-08-05T09:30:00",
            move_end_at="2026-08-05T15:00:00",
            is_old_news=True, has_new_development=True)
        assert c.direct_eligible is True
        assert c.confidence_cap == "medium"

    def test_published_after_move_rejected(self):
        c = check_direct_trigger(
            published_at="2026-08-05T20:00:00",
            first_disclosed_at=None,
            move_start_at="2026-08-05T09:30:00",
            move_end_at="2026-08-05T15:00:00")
        assert c.direct_eligible is False
        assert c.timing_relation == AFTER_MOVE

    def test_event_after_move_not_original_cause(self):
        # 首次披露晚于异动开始（但报道时间在异动前）-> 规则 7
        c = check_direct_trigger(
            published_at="2026-08-05T09:00:00",
            first_disclosed_at="2026-08-05T10:00:00",
            move_start_at="2026-08-05T09:30:00",
            move_end_at="2026-08-05T15:00:00")
        assert c.direct_eligible is False
        assert "原始异动原因" in c.reason

    def test_missing_time_rejected(self):
        c = check_direct_trigger(None, None, "2026-08-05T09:30:00",
                                 "2026-08-05T15:00:00")
        assert c.direct_eligible is False
        assert any("缺失" in w for w in c.warnings)

    def test_official_confirmation_boost(self):
        r = official_confirmation_boost(
            community_first_at="2026-08-04T10:00:00",
            official_at="2026-08-05T08:00:00",
            move_start_at="2026-08-05T09:30:00")
        assert r["community_time_preserved"] is True
        assert r["confirmation_boost"] is True
        assert r["secondary_catalyst"] is True

    def test_official_confirmation_no_rewrite(self):
        r = official_confirmation_boost(
            community_first_at="2026-08-05T12:00:00",
            official_at="2026-08-05T08:00:00",
            move_start_at="2026-08-05T09:30:00")
        assert r["confirmation_boost"] is False
