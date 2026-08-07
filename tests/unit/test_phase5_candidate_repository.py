"""Phase 5 M3 Candidate Repository 测试。

覆盖：
- append_candidate insert
- idempotent replay
- immutable candidate conflict
- generic upsert 阻断
- get_candidate / count / list
- canonical JSON payload equality
"""
from __future__ import annotations

import json

import pytest

from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
from research_os.models import (
    GraphChange,
    GraphNode,
    GraphEdge,
)
from research_os.storage.db import Database, TABLES
from research_os.utils.time import now_iso

T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    yield db
    db.close()


@pytest.fixture()
def repo(db):
    return GraphChangeCandidateRepository(db)


def _make_node():
    return GraphNode(
        node_id="company:test-node",
        node_type="Company",
        name="测试节点",
        aliases=[],
        description="",
        status="active",
        valid_from=None,
        valid_to=None,
        evidence_ids=["ev:001"],
        version=1,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )


def _make_graph_change(change_id, **kw):
    defaults = {
        "graph_change_id": change_id,
        "change_type": "add_node",
        "node": _make_node(),
        "edge": None,
        "current_knowledge": "",
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "测试变更",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


# ---- insert ----

def test_append_candidate_insert(repo):
    """首次插入返回 inserted。"""
    gc = _make_graph_change("11111111-1111-1111-1111-111111111111")
    result = repo.append_candidate(gc)
    assert result == "inserted"


def test_append_candidate_idempotent(repo):
    """同 ID 同 payload 返回 idempotent_noop。"""
    gc = _make_graph_change("22222222-2222-2222-2222-222222222222")
    repo.append_candidate(gc)
    result = repo.append_candidate(gc)
    assert result == "idempotent_noop"


def test_append_candidate_immutable_conflict(repo):
    """同 ID 异 payload 抛出 IMMUTABLE_CANDIDATE_CONFLICT。"""
    gc1 = _make_graph_change("33333333-3333-3333-3333-333333333333")
    gc2 = _make_graph_change(
        "33333333-3333-3333-3333-333333333333",
        suggested_change="不同的变更描述",
    )
    repo.append_candidate(gc1)
    with pytest.raises(ValueError, match="IMMUTABLE_CANDIDATE_CONFLICT"):
        repo.append_candidate(gc2)


# ---- query ----

def test_get_candidate(repo):
    """能正确读取已写入的 candidate。"""
    gc_id = "44444444-4444-4444-4444-444444444444"
    gc = _make_graph_change(gc_id)
    repo.append_candidate(gc)

    loaded = repo.get_candidate(gc_id)
    assert loaded is not None
    assert loaded["graph_change_id"] == gc_id
    assert loaded["suggested_change"] == "测试变更"


def test_get_candidate_missing(repo):
    """不存在的 candidate 返回 None。"""
    assert repo.get_candidate("nonexistent-id") is None


def test_count_candidates(repo):
    """count 正确反映写入数量。"""
    assert repo.count_candidates() == 0

    for i in range(3):
        gc = _make_graph_change(f"aa{i:034d}")
        repo.append_candidate(gc)

    assert repo.count_candidates() == 3


def test_list_candidates(repo):
    """list_candidates 返回全部。"""
    gc = _make_graph_change("55555555-5555-5555-5555-555555555555")
    repo.append_candidate(gc)

    candidates = repo.list_candidates()
    assert len(candidates) == 1
    assert candidates[0]["graph_change_id"] == gc.graph_change_id


# ---- generic upsert 阻断 ----

def test_graph_change_not_in_generic_tables():
    """GraphChange 不在 generic TABLES 中。"""
    assert "GraphChange" not in TABLES


def test_graph_change_upsert_blocked(db):
    """generic upsert(GraphChange) 应抛出 ValueError。"""
    from research_os.models import GraphChange as GC

    gc = GC(
        graph_change_id="66666666-6666-6666-6666-666666666666",
        change_type="add_node",
        node=_make_node(),
        edge=None,
        current_knowledge="",
        new_evidence_ids=["ev:001"],
        suggested_change="test",
        impact_scope=[],
        conflicts=[],
        verification_points=[],
        review_status="candidate",
        created_at=T0,
        reviewed_at=None,
    )

    with pytest.raises((ValueError, KeyError), match="(GraphChange|未知)"):
        db.upsert(gc)
