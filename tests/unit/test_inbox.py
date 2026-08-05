"""人工 Inbox 测试（Phase 1 任务 9 节）。"""
from __future__ import annotations

import pytest

from research_os.collectors.manual import ManualInboxService
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance


@pytest.fixture()
def service(tmp_path):
    db = Database(tmp_path / "inbox.db")
    db.initialize()
    yield ManualInboxService(db)
    db.close()


def test_inbox_add_valid(service):
    entry = service.add(source_name="雪球", source_url="https://xueqiu.com/x",
                        title="某公司观点", content_excerpt="用户摘录，非事实",
                        intended_entities=["company:600519.SH"])
    assert entry.status == "submitted"
    assert validate_instance(entry.model_dump(), "manual_inbox") == []
    assert service.list() and service.list()[0]["title"] == "某公司观点"


def test_inbox_add_invalid_url_fails(service):
    with pytest.raises(Exception):
        service.add(source_name="x", source_url="not-a-url", title="t")


def test_inbox_status_flow(service):
    entry = service.add(source_name="x", source_url="https://example.com", title="t")
    service.update_status(entry.inbox_id, "needs_review")
    service.update_status(entry.inbox_id, "accepted")
    rows = service.list(status="accepted")
    assert len(rows) == 1
    assert rows[0]["inbox_id"] == entry.inbox_id


def test_inbox_invalid_status_rejected(service):
    entry = service.add(source_name="x", source_url="https://example.com", title="t")
    with pytest.raises(Exception):
        service.update_status(entry.inbox_id, "bogus")


def test_inbox_unknown_id_raises(service):
    with pytest.raises(KeyError):
        service.update_status("11111111-1111-1111-1111-111111111111", "accepted")


def test_inbox_excerpt_not_fact_marker(service):
    """用户摘录保留 submitted_by=user 与状态，不自动进入图谱。"""
    entry = service.add(source_name="x", source_url="https://example.com", title="t",
                        content_excerpt="用户说 X 会涨")
    assert entry.submitted_by == "user"
    assert entry.status == "submitted"  # 图谱入库需后续明确审核
