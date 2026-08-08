"""Phase 5 M3 Candidate Repository 测试。

覆盖：
- append_candidate insert
- idempotent replay
- immutable candidate conflict
- generic upsert 阻断
- get_candidate / count / list
- canonical JSON payload equality
- reject approved/deferred/rejected candidates (via model_construct for invalid states)
- edge triple lookup via GraphRepository.find_edge_by_triple
"""
from __future__ import annotations

import json
import uuid

import pytest

from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
from research_os.knowledge.repository import GraphRepository
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


@pytest.fixture()
def graph_repo(db):
    return GraphRepository(db)


def _make_valid_uuid_id(prefix=""):
    """生成合法 UUID 格式的 graph_change_id。"""
    return str(uuid.uuid4())


def _make_node(**kw):
    defaults = {
        "node_id": "company:test-node",
        "node_type": "Company",
        "name": "测试节点",
        "aliases": [],
        "description": "",
        "status": "active",
        "valid_from": None,
        "valid_to": None,
        "evidence_ids": ["ev:001"],
        "version": 1,
        "last_reviewed_at": None,
        "review_status": "candidate",
        "origin_kind": "graph_change",
        "originating_graph_change_id": "11111111-1111-1111-1111-111111111111",
        "created_at": T0,
    }
    defaults.update(kw)
    return GraphNode(**defaults)


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
    gc = _make_graph_change(_make_valid_uuid_id())
    result = repo.append_candidate(gc)
    assert result == "inserted"


def test_append_candidate_idempotent(repo):
    """同 ID 同 payload 返回 idempotent_noop。"""
    cid = _make_valid_uuid_id()
    gc = _make_graph_change(cid)
    repo.append_candidate(gc)
    result = repo.append_candidate(gc)
    assert result == "idempotent_noop"


def test_append_candidate_immutable_conflict(repo):
    """同 ID 异 payload 抛出 IMMUTABLE_CANDIDATE_CONFLICT。"""
    cid = _make_valid_uuid_id()
    gc1 = _make_graph_change(cid)
    gc2 = _make_graph_change(cid, suggested_change="不同的变更描述")
    repo.append_candidate(gc1)
    with pytest.raises(ValueError, match="IMMUTABLE_CANDIDATE_CONFLICT"):
        repo.append_candidate(gc2)


# ---- reject approved/deferred/rejected (use model_construct to bypass validators) ----

def test_append_candidate_rejects_approved(repo):
    """拒绝 review_status=approved 的 candidate。"""
    cid = _make_valid_uuid_id()
    gc = GraphChange.model_construct(
        graph_change_id=cid, change_type="add_node",
        node=_make_node(), edge=None, current_knowledge="",
        new_evidence_ids=["ev:001"], suggested_change="test",
        impact_scope=[], conflicts=[], verification_points=[],
        review_status="approved", created_at=T0, reviewed_at=T0,
    )
    with pytest.raises(ValueError, match="仅允许 candidate"):
        repo.append_candidate(gc)


def test_append_candidate_rejects_deferred(repo):
    """拒绝 review_status=deferred 的 candidate。"""
    cid = _make_valid_uuid_id()
    gc = GraphChange.model_construct(
        graph_change_id=cid, change_type="add_node",
        node=_make_node(), edge=None, current_knowledge="",
        new_evidence_ids=["ev:001"], suggested_change="test",
        impact_scope=[], conflicts=[], verification_points=[],
        review_status="deferred", created_at=T0, reviewed_at=T0,
    )
    with pytest.raises(ValueError, match="仅允许 candidate"):
        repo.append_candidate(gc)


def test_append_candidate_rejects_rejected(repo):
    """拒绝 review_status=rejected 的 candidate。"""
    cid = _make_valid_uuid_id()
    gc = GraphChange.model_construct(
        graph_change_id=cid, change_type="add_node",
        node=_make_node(), edge=None, current_knowledge="",
        new_evidence_ids=["ev:001"], suggested_change="test",
        impact_scope=[], conflicts=[], verification_points=[],
        review_status="rejected", created_at=T0, reviewed_at=T0,
    )
    with pytest.raises(ValueError, match="仅允许 candidate"):
        repo.append_candidate(gc)


def test_append_candidate_rejects_reviewed_at_not_null(repo):
    """拒绝 reviewed_at 非 null 的 candidate（Schema 先于 status gate 拒绝）。"""
    cid = _make_valid_uuid_id()
    gc = GraphChange.model_construct(
        graph_change_id=cid, change_type="add_node",
        node=_make_node(), edge=None, current_knowledge="",
        new_evidence_ids=["ev:001"], suggested_change="test",
        impact_scope=[], conflicts=[], verification_points=[],
        review_status="candidate", created_at=T0, reviewed_at=T0,
    )
    with pytest.raises(ValueError, match="is not of type .null"):
        repo.append_candidate(gc)


# ---- query ----

def test_get_candidate(repo):
    """能正确读取已写入的 candidate。"""
    cid = _make_valid_uuid_id()
    gc = _make_graph_change(cid)
    repo.append_candidate(gc)

    loaded = repo.get_candidate(cid)
    assert loaded is not None
    assert loaded["graph_change_id"] == cid
    assert loaded["suggested_change"] == "测试变更"


def test_get_candidate_missing(repo):
    """不存在的 candidate 返回 None。"""
    assert repo.get_candidate(_make_valid_uuid_id()) is None


def test_count_candidates(repo):
    """count 正确反映写入数量。"""
    assert repo.count_candidates() == 0

    for i in range(3):
        gc = _make_graph_change(_make_valid_uuid_id())
        repo.append_candidate(gc)

    assert repo.count_candidates() == 3


def test_list_candidates(repo):
    """list_candidates 返回全部。"""
    cid = _make_valid_uuid_id()
    gc = _make_graph_change(cid)
    repo.append_candidate(gc)

    candidates = repo.list_candidates()
    assert len(candidates) == 1
    assert candidates[0]["graph_change_id"] == cid


# ---- generic upsert 阻断 ----

def test_graph_change_not_in_generic_tables():
    """GraphChange 不在 generic TABLES 中。"""
    assert "GraphChange" not in TABLES


def test_graph_change_upsert_blocked(db):
    """generic upsert(GraphChange) 应抛出 ValueError。"""
    cid = _make_valid_uuid_id()
    gc = _make_graph_change(cid)
    with pytest.raises((ValueError, KeyError), match="(GraphChange|未知)"):
        db.upsert(gc)


# ---- edge triple lookup (GraphRepository helper) ----

def test_find_edge_by_triple_empty(graph_repo):
    """空图返回空列表。"""
    result = graph_repo.find_edge_by_triple("n1", "SUPPLIES", "n2")
    assert len(result) == 0


def test_find_edge_by_triple_single(graph_repo, db):
    """单一边匹配返回 1 条记录。"""
    edge = GraphEdge(
        edge_id="edge:triple-test-1",
        source_node_id="company:a",
        relation="SUPPLIES",
        target_node_id="company:b",
        attributes={},
        assertion_type="FACT",
        valid_from=None,
        valid_to=None,
        confidence=0.9,
        evidence_ids=["ev:001"],
        review_status="approved",
        version=1,
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
        last_reviewed_at=None,
    )
    graph_repo.append_edge(edge)

    result = graph_repo.find_edge_by_triple("company:a", "SUPPLIES", "company:b")
    assert len(result) == 1
    assert result[0]["edge_id"] == "edge:triple-test-1"


def test_find_edge_by_triple_multi_version(graph_repo, db):
    """多个版本（同 edge_id）返回多条记录但 unique edge_id 只有 1 个。"""
    edge1 = GraphEdge(
        edge_id="edge:multi-ver",
        source_node_id="company:x",
        relation="DOWNSTREAM_OF",
        target_node_id="company:y",
        attributes={},
        assertion_type="FACT",
        valid_from=None,
        valid_to=None,
        confidence=0.9,
        evidence_ids=["ev:001"],
        review_status="approved",
        version=1,
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
        last_reviewed_at=None,
    )
    edge2 = GraphEdge(
        edge_id="edge:multi-ver",
        source_node_id="company:x",
        relation="DOWNSTREAM_OF",
        target_node_id="company:y",
        attributes={"updated": True},
        assertion_type="FACT",
        valid_from=None,
        valid_to=None,
        confidence=0.95,
        evidence_ids=["ev:002"],
        review_status="approved",
        version=2,
        originating_graph_change_id="22222222-2222-2222-2222-222222222222",
        created_at=T0,
        last_reviewed_at=None,
    )
    graph_repo.append_edge(edge1)
    graph_repo.append_edge(edge2)

    result = graph_repo.find_edge_by_triple("company:x", "DOWNSTREAM_OF", "company:y")
    assert len(result) >= 1
    edge_ids = set(r["edge_id"] for r in result)
    assert len(edge_ids) == 1
    assert "edge:multi-ver" in edge_ids
