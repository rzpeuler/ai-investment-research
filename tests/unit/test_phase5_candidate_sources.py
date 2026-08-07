"""Phase 5 M3 Candidate Sources 测试。

覆盖：
- SourceAdapter.load 各源类型
- SourceAdapter.load_batch
- 不支持的源类型拒绝
- 不存在的对象拒绝
- EvidenceContext 上下文加载
- Evidence 存在性验证
"""
from __future__ import annotations

import pytest

from research_os.knowledge.candidate_sources import (
    SourceAdapter,
    EvidenceContext,
    is_allowed_source_type,
    load_evidence_context,
    _SOURCE_MAP,
)
from research_os.models import (
    Event,
    Claim,
    Evidence,
    GraphChangeProposal,
)
from research_os.models.equity_research import Catalyst, CompetitiveFactor, RiskFactor, ResearchFinding
from research_os.models.companies import CompanyProfile
from research_os.models.valuation import BusinessSegment
from research_os.storage.db import Database
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso


T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def db(tmp_path):
    """创建已迁移的测试数据库。"""
    db = Database(tmp_path / "test.db")
    db.migrate()
    yield db
    db.close()


@pytest.fixture()
def adapter(db):
    return SourceAdapter(db)


# ---- 源类型名单 ----

def test_is_allowed_source_type():
    """is_allowed_source_type 正确识别 M3 允许的源类型。"""
    assert is_allowed_source_type("Event") is True
    assert is_allowed_source_type("Claim") is True
    assert is_allowed_source_type("ResearchFinding") is True
    assert is_allowed_source_type("CompetitiveFactor") is True
    assert is_allowed_source_type("Catalyst") is True
    assert is_allowed_source_type("RiskFactor") is True
    assert is_allowed_source_type("BusinessSegment") is True
    assert is_allowed_source_type("CompanyProfile") is True
    assert is_allowed_source_type("Evidence") is True
    assert is_allowed_source_type("Opinion") is False
    assert is_allowed_source_type("RawItem") is False
    assert is_allowed_source_type("Unknown") is False


# ---- Evidence 加载 ----

def test_load_evidence(db):
    """插入 Evidence 后能正确加载。"""
    ev_id = new_uuid()
    ev = Evidence(
        evidence_id=ev_id,
        source_id="source:test",
        raw_item_id=new_uuid(),
        title="测试证据标题",
        publisher="测试发布者",
        published_at=T0,
        retrieved_at=T0,
        url="https://example.com/ev",
        excerpt="测试摘录内容",
        evidence_type="official_disclosure",
        independence_group="group-1",
        source_tier="B",
        access_status="ok",
    )
    db.upsert(ev)

    adapter = SourceAdapter(db)
    loaded = adapter.load("Evidence", ev_id)
    assert isinstance(loaded, Evidence)
    assert loaded.evidence_id == ev_id
    assert loaded.title == "测试证据标题"


def test_load_event(db, adapter):
    """加载 Event 对象。"""
    ev_id = new_uuid()
    event = Event(
        event_id=ev_id,
        event_type="capacity_expansion",
        subject_entities=["company:test"],
        object_entities=[],
        event_time=T0,
        announced_at=T0,
        effective_at=None,
        status="announced",
        summary="测试事件摘要",
        quantitative_fields={"capacity": 100},
        industry_coordinates=[],
        novelty=0.5,
        impact_direction="positive",
        impact_horizon="short",
        evidence_ids=[],
        confidence=0.8,
        conflicts=[],
    )
    db.upsert(event)

    loaded = adapter.load("Event", ev_id)
    assert isinstance(loaded, Event)
    assert loaded.event_id == ev_id
    assert loaded.summary == "测试事件摘要"


def test_load_claim(db, adapter):
    """加载 Claim 对象。"""
    cl_id = new_uuid()
    claim = Claim(
        claim_id=cl_id,
        claim_type="FACT",
        statement="测试声明",
        subject_entities=["company:test"],
        predicate="test_predicate",
        object={"value": 100},
        as_of=T0,
        evidence_ids=[],
        support_level="direct",
        confidence=0.9,
        valid_until=None,
        review_status="unreviewed",
    )
    db.upsert(claim)

    loaded = adapter.load("Claim", cl_id)
    assert isinstance(loaded, Claim)
    assert loaded.claim_id == cl_id


def test_load_not_found(adapter):
    """不存在的对象抛出 ValueError。"""
    with pytest.raises(ValueError, match="不存在"):
        adapter.load("Event", "nonexistent-id")


def test_load_unsupported_type(adapter):
    """不支持的源类型抛出 ValueError。"""
    with pytest.raises(ValueError, match="不支持的源类型"):
        adapter.load("Opinion", "any-id")


def test_load_batch(db, adapter):
    """批量加载多个源对象。"""
    ev_id = new_uuid()
    cl_id = new_uuid()

    event = Event(
        event_id=ev_id, event_type="test", subject_entities=["company:test"],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="事件", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    claim = Claim(
        claim_id=cl_id, claim_type="FACT", statement="声明",
        subject_entities=["company:test"], predicate="pred",
        object={"v": 1}, as_of=T0, evidence_ids=[],
        support_level="inferred", confidence=0.5, valid_until=None,
        review_status="unreviewed",
    )
    db.upsert(event)
    db.upsert(claim)

    result = adapter.load_batch([("Event", ev_id), ("Claim", cl_id)])
    assert len(result) == 2
    assert isinstance(result[("Event", ev_id)], Event)
    assert isinstance(result[("Claim", cl_id)], Claim)


def test_load_batch_failure(db, adapter):
    """批量加载中任一个失败则整体抛异常。"""
    ev_id = new_uuid()
    event = Event(
        event_id=ev_id, event_type="test", subject_entities=["company:test"],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="事件", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    db.upsert(event)

    with pytest.raises(ValueError, match="批量加载源对象失败"):
        adapter.load_batch([("Event", ev_id), ("Event", "nonexistent-id")])


# ---- Evidence context loader ----

def test_load_evidence_context(db):
    """加载证据上下文并验证字段。"""
    ev_id = new_uuid()
    ev = Evidence(
        evidence_id=ev_id, source_id="source:test", raw_item_id=new_uuid(),
        title="证据标题", publisher="发布者", published_at=T0, retrieved_at=T0,
        url="https://example.com", excerpt="摘录内容",
        evidence_type="official", independence_group="g1",
        source_tier="A", access_status="ok",
    )
    db.upsert(ev)

    contexts, errors = load_evidence_context(db, [ev_id])
    assert len(contexts) == 1
    assert len(errors) == 0
    ctx = contexts[0]
    assert ctx.evidence_id == ev_id
    assert ctx.title == "证据标题"
    assert ctx.role == "supporting"
    assert ctx.source_tier == "A"


def test_load_evidence_context_with_counter(db):
    """含反证证据的上下文加载。"""
    ev1_id = new_uuid()
    ev2_id = new_uuid()
    ev1 = Evidence(
        evidence_id=ev1_id, source_id="s1", raw_item_id=new_uuid(),
        title="支持证据", publisher="p1", published_at=T0, retrieved_at=T0,
        url="https://x.com/1", excerpt="支持", evidence_type="official",
        independence_group="g1", source_tier="B", access_status="ok",
    )
    ev2 = Evidence(
        evidence_id=ev2_id, source_id="s2", raw_item_id=new_uuid(),
        title="反证证据", publisher="p2", published_at=T0, retrieved_at=T0,
        url="https://x.com/2", excerpt="反证", evidence_type="official",
        independence_group="g2", source_tier="B", access_status="ok",
    )
    db.upsert(ev1)
    db.upsert(ev2)

    contexts, errors = load_evidence_context(
        db, [ev1_id], counter_evidence_ids=[ev2_id]
    )
    assert len(contexts) == 2
    assert len(errors) == 0
    roles = {ctx.evidence_id: ctx.role for ctx in contexts}
    assert roles[ev1_id] == "supporting"
    assert roles[ev2_id] == "counter"


def test_load_evidence_context_missing(db):
    """缺失的 Evidence 报告错误。"""
    contexts, errors = load_evidence_context(db, ["nonexistent-ev"])
    assert len(contexts) == 0
    assert len(errors) >= 1
    assert any("不存在" in e for e in errors)


def test_load_evidence_context_dedup(db):
    """重复的 evidence_id 只加载一次。"""
    ev_id = new_uuid()
    ev = Evidence(
        evidence_id=ev_id, source_id="s1", raw_item_id=new_uuid(),
        title="证据", publisher="p1", published_at=T0, retrieved_at=T0,
        url="https://x.com", excerpt="ex", evidence_type="official",
        independence_group="g1", source_tier="B", access_status="ok",
    )
    db.upsert(ev)

    contexts, errors = load_evidence_context(db, [ev_id, ev_id])
    assert len(contexts) == 1
    assert len(errors) == 0
