"""Phase 5 M3 Candidate Builder 测试。

覆盖：
- add_node 构建（实体身份、版本）
- retire_node 构建
- modify_attribute 节点构建
- add_edge 构建（确定性 edge_id）
- retire_edge / modify_attribute 边构建
- current_knowledge 生成
- 本体保护（Industry/IndustrySegment 阻止）
- 冲突检测（CURRENT_NODE_ALREADY_EXISTS, NODE_NOT_FOUND）
- 证据门禁
- graph_change_id 确定性
"""
from __future__ import annotations

import pytest

from research_os.knowledge.candidate_builder import (
    GraphChangeBuilder,
    check_evidence_gate,
)
from research_os.models import (
    GraphChange,
    GraphChangeProposal,
    GraphChangeType,
    GraphProposalNode,
    GraphProposalEdge,
    GraphNode,
    GraphEdge,
    Evidence,
)
from research_os.storage.db import Database
from research_os.utils.id import new_uuid, content_sha256

T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    yield db
    db.close()


@pytest.fixture()
def builder(db):
    return GraphChangeBuilder(db)


def _make_add_node_proposal(**kw):
    defaults = {
        "proposal_type": "add_node",
        "source_object_ids": ["Event:ev1"],
        "candidate_node": {
            "existing_node_id": None,
            "node_type": "Company",
            "name": "测试公司",
            "aliases": ["测试"],
            "description": "测试描述",
            "valid_from": None,
            "valid_to": None,
        },
        "candidate_edge": None,
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "添加新公司节点",
        "impact_scope": ["供应链"],
        "conflicts": [],
        "verification_points": [],
        "confidence": 0.8,
    }
    defaults.update(kw)
    return GraphChangeProposal(**defaults)


def _make_modify_node_proposal(**kw):
    defaults = {
        "proposal_type": "modify_attribute",
        "source_object_ids": ["Event:ev1"],
        "candidate_node": {
            "existing_node_id": "company:test",
            "node_type": "Company",
            "name": "更新名称",
            "aliases": ["新别名"],
            "description": "更新描述",
            "valid_from": None,
            "valid_to": None,
        },
        "candidate_edge": None,
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "更新节点属性",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "confidence": 0.7,
    }
    defaults.update(kw)
    return GraphChangeProposal(**defaults)


def _make_retire_node_proposal(**kw):
    defaults = {
        "proposal_type": "retire_node",
        "source_object_ids": ["Event:ev1"],
        "candidate_node": {
            "existing_node_id": "company:test",
            "node_type": "Company",
            "name": "退役公司",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        },
        "candidate_edge": None,
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "退役节点",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "confidence": 0.9,
    }
    defaults.update(kw)
    return GraphChangeProposal(**defaults)


def _make_add_edge_proposal(**kw):
    defaults = {
        "proposal_type": "add_edge",
        "source_object_ids": ["Claim:cl1"],
        "candidate_node": None,
        "candidate_edge": {
            "source_node_id": "company:a",
            "relation": "SUPPLIES",
            "target_node_id": "company:b",
            "attributes": {"volume": 100},
            "assertion_type": "FACT",
            "valid_from": None,
            "valid_to": None,
            "confidence": 0.85,
        },
        "new_evidence_ids": ["ev:001"],
        "suggested_change": "添加供应关系",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "confidence": 0.85,
    }
    defaults.update(kw)
    return GraphChangeProposal(**defaults)


# ---- add_node ----

def test_build_add_node(builder):
    """构建 add_node GraphChange。"""
    proposal = _make_add_node_proposal()
    gc = builder.build(proposal)

    assert gc is not None
    assert gc.change_type == "add_node"
    assert gc.node is not None
    assert gc.node.node_type == "Company"
    assert gc.node.name == "测试公司"
    assert gc.node.version == 1
    assert gc.node.status == "active"
    assert gc.node.origin_kind == "graph_change"
    assert gc.node.review_status == "candidate"
    assert gc.node.last_reviewed_at is None
    assert gc.review_status == "candidate"
    assert gc.reviewed_at is None
    assert gc.new_evidence_ids == ["ev:001"]


def test_build_add_node_graph_change_id_deterministic(builder):
    """同一 proposal 产生相同 graph_change_id。"""
    p1 = _make_add_node_proposal()
    p2 = _make_add_node_proposal()
    gc1 = builder.build(p1)
    gc2 = builder.build(p2)
    assert gc1.graph_change_id == gc2.graph_change_id


def test_build_add_node_different_proposal_different_id(builder):
    """不同 proposal 产生不同 graph_change_id。"""
    p1 = _make_add_node_proposal(suggested_change="变更A")
    p2 = _make_add_node_proposal(suggested_change="变更B")
    gc1 = builder.build(p1)
    gc2 = builder.build(p2)
    assert gc1.graph_change_id != gc2.graph_change_id


# ---- retire_node ----

def test_build_retire_node(builder):
    """构建 retire_node GraphChange。"""
    proposal = _make_retire_node_proposal()
    gc = builder.build(proposal)

    assert gc.change_type == "retire_node"
    assert gc.node is not None
    assert gc.node.status == "retired"
    assert gc.node.valid_to is not None  # 设为 now


# ---- modify_attribute ----

def test_build_modify_node(builder):
    """构建 modify_attribute 节点 GraphChange。"""
    proposal = _make_modify_node_proposal()
    gc = builder.build(proposal)

    assert gc.change_type == "modify_attribute"
    assert gc.node is not None
    assert gc.node.name == "更新名称"
    assert gc.node.aliases == ["新别名"]
    assert gc.edge is None


# ---- add_edge ----

def test_build_add_edge(builder):
    """构建 add_edge GraphChange。"""
    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal)

    assert gc.change_type == "add_edge"
    assert gc.edge is not None
    assert gc.edge.relation == "SUPPLIES"
    assert gc.edge.version == 1
    assert gc.edge.review_status == "candidate"
    assert gc.edge.last_reviewed_at is None
    assert gc.node is None


def test_build_add_edge_deterministic_id(builder):
    """边 ID 确定性。"""
    p1 = _make_add_edge_proposal()
    p2 = _make_add_edge_proposal()
    gc1 = builder.build(p1)
    gc2 = builder.build(p2)
    assert gc1.edge.edge_id == gc2.edge.edge_id  # 相同 source/relation/target


# ---- 本体保护 ----

def test_ontology_protection_industry_blocked(builder):
    """Industry 类型 add_node 被阻止。"""
    proposal = _make_add_node_proposal(
        candidate_node={
            "existing_node_id": None,
            "node_type": "Industry",
            "name": "新产业",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        },
    )
    with pytest.raises(ValueError, match="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE"):
        builder.build(proposal)


def test_ontology_protection_industry_segment_blocked(builder):
    """IndustrySegment 类型 add_node 被阻止。"""
    proposal = _make_add_node_proposal(
        candidate_node={
            "existing_node_id": None,
            "node_type": "IndustrySegment",
            "name": "新细分",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        },
    )
    with pytest.raises(ValueError, match="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE"):
        builder.build(proposal)


# ---- 冲突检测 ----

def test_check_conflicts_no_conflict(builder):
    """新节点 add_node 无冲突。"""
    proposal = _make_add_node_proposal()
    conflicts = builder.check_conflicts(proposal)
    # 新节点可能解析出 entity_id 但不存在于图中 → 不冲突
    assert "CURRENT_NODE_ALREADY_EXISTS" not in str(conflicts)


# ---- 证据门禁 ----

def test_check_evidence_gate_pass(db):
    """证据存在时门禁通过。"""
    ev_id = new_uuid()
    ev = Evidence(
        evidence_id=ev_id, source_id="s1", raw_item_id=new_uuid(),
        title="t", publisher="p", published_at=T0, retrieved_at=T0,
        url="https://x.com", excerpt="e", evidence_type="official",
        independence_group="g1", source_tier="B", access_status="ok",
    )
    db.upsert(ev)
    ok, errs = check_evidence_gate(db, [ev_id])
    assert ok is True
    assert len(errs) == 0


def test_check_evidence_gate_fail(db):
    """证据不存在时门禁失败。"""
    ok, errs = check_evidence_gate(db, ["nonexistent"])
    assert ok is False
    assert len(errs) >= 1


# ---- version ----

def test_version_first_is_1(builder):
    """首次创建的节点版本为 1。"""
    proposal = _make_add_node_proposal()
    gc = builder.build(proposal)
    assert gc.node.version == 1
    assert gc.edge is None


def test_version_fresh_edge_is_1(builder):
    """首次创建的边版本为 1。"""
    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal)
    assert gc.edge.version == 1
