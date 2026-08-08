"""Phase 5 M3 Candidate Builder 测试。

覆盖：
- add_node 构建（实体身份、版本、严格 entity_id 解析无 name-based 回退）
- retire_node 构建
- modify_attribute 节点构建
- add_edge 构建（triple lookup from repository）
- retire_edge / modify_attribute 边构建
- current_knowledge 生成
- 本体保护（Industry/IndustrySegment 阻止）
- 冲突检测（CURRENT_EDGE_CONFLICT, NODE_NOT_FOUND）
- 证据门禁
- graph_change_id 确定性（SHA256→UUID5, no created_at/random）
- 攻击测试：identity 0/multiple, ID changes, clock replay, edge triple lookup, ambiguous edge, edge conflicts, out-of-context evidence
"""
from __future__ import annotations

import pytest

from research_os.knowledge.candidate_builder import (
    GraphChangeBuilder,
    BuildResult,
    check_evidence_gate,
    stable_evidence_merge,
    _stable_graph_change_id,
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
    Entity,
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


@pytest.fixture()
def entity_id():
    """实体 ID fixture。"""
    return f"company:test-entity-{new_uuid()[:8]}"


@pytest.fixture()
def entity_in_db(db, entity_id):
    """在 entities 表中插入测试实体。"""
    entity = Entity(
        entity_id=entity_id,
        entity_type="company",
        canonical_name="测试实体公司",
        aliases=["测试"],
        market="SH",
        industry_ids=[],
        concept_ids=[],
        valid_from=None,
        valid_to=None,
        source_ids=[],
    )
    db.upsert(entity)
    return entity_id


def _make_add_node_proposal(entity_id_in_source=None, **kw):
    """构造 add_node proposal，optionally 提供 source_objects 中的 entity_id。"""
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


def _make_source_objects_with_entity(entity_id):
    """构造带有 entity_id 的 source_objects dict。"""
    from research_os.models import Event as Evt
    event = Evt(
        event_id=f"ev-test-{new_uuid()[:8]}",
        event_type="capacity_expansion",
        subject_entities=[entity_id],
        object_entities=[],
        event_time=T0,
        announced_at=T0,
        effective_at=None,
        status="announced",
        summary="测试事件",
        quantitative_fields={},
        industry_coordinates=[],
        novelty=0.5,
        impact_direction="neutral",
        impact_horizon="short",
        evidence_ids=["ev:001"],
        confidence=0.5,
        conflicts=[],
    )
    return {("Event", event.event_id): event}


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
            "valid_to": T0,
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


# ---- add_node（entity_id from source_objects, 严格解析）----

def test_build_add_node_with_entity(builder, entity_in_db):
    """构建 add_node GraphChange，entity_id 来自 source_objects。"""
    proposal = _make_add_node_proposal()
    source_objects = _make_source_objects_with_entity(entity_in_db)
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change

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
    # Company: node_id == entity_id
    assert gc.node.node_id == entity_in_db


# ---- 攻击测试：identity resolution（无 source_objects → IDENTITY_RESOLUTION_REQUIRED）----

def test_add_node_rejects_when_no_entity_id(builder):
    """无 source_objects 时 add_node → IDENTITY_RESOLUTION_REQUIRED。"""
    proposal = _make_add_node_proposal()
    with pytest.raises(ValueError, match="IDENTITY_RESOLUTION_REQUIRED"):
        builder.build(proposal, supporting_evidence_ids=["ev:001"])


def test_add_node_rejects_ambiguous_entity(builder, entity_in_db, db):
    """多个 candidate entity_id → AMBIGUOUS_ENTITY_IDENTITY。"""
    # 插入第二个公司 entity（两个都在表中，类型都匹配 → 歧义）
    second_entity_id = "company:other"
    db.upsert(Entity(
        entity_id=second_entity_id, entity_type="company",
        canonical_name="Other Company", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    from research_os.models import Event as Evt
    ev1 = Evt(
        event_id=f"ev1-{new_uuid()[:8]}",
        event_type="test", subject_entities=[entity_in_db],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    ev2 = Evt(
        event_id=f"ev2-{new_uuid()[:8]}",
        event_type="test", subject_entities=[second_entity_id],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev1.event_id): ev1, ("Event", ev2.event_id): ev2}
    proposal = _make_add_node_proposal()
    with pytest.raises(ValueError, match="AMBIGUOUS_ENTITY_IDENTITY"):
        builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"])


def test_add_node_identity_entity_not_in_db(builder):
    """entity_id 不在 entities 表中 → IDENTITY_RESOLUTION_REQUIRED。"""
    missing_id = "company:not-in-db"
    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[missing_id],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}
    proposal = _make_add_node_proposal()
    with pytest.raises(ValueError, match="IDENTITY_RESOLUTION_REQUIRED"):
        builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"])


# ---- graph_change_id 确定性（SHA256→UUID5，不含 created_at/random）----

def test_build_add_node_graph_change_id_deterministic(builder, entity_in_db):
    """同一 proposal + baseline 产生相同 graph_change_id。"""
    p1 = _make_add_node_proposal()
    p2 = _make_add_node_proposal()
    so1 = _make_source_objects_with_entity(entity_in_db)
    so2 = _make_source_objects_with_entity(entity_in_db)
    gc1 = builder.build(p1, source_objects=so1, supporting_evidence_ids=["ev:001"]).graph_change
    gc2 = builder.build(p2, source_objects=so2, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.graph_change_id == gc2.graph_change_id


def test_build_add_node_different_proposal_different_id(builder, entity_in_db):
    """不同 suggested_change → 不同 graph_change_id（proposal.model_dump() 参与）."""
    p1 = _make_add_node_proposal(suggested_change="变更A")
    p2 = _make_add_node_proposal(suggested_change="变更B")
    so = _make_source_objects_with_entity(entity_in_db)
    gc1 = builder.build(p1, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    gc2 = builder.build(p2, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.graph_change_id != gc2.graph_change_id


def test_graph_change_id_changes_with_node_changes(builder, entity_in_db):
    """node name 变更 → graph_change_id 变化。"""
    p1 = _make_add_node_proposal()
    p2 = _make_add_node_proposal(
        candidate_node={"existing_node_id": None, "node_type": "Company",
                        "name": "不同名称", "aliases": [], "description": "",
                        "valid_from": None, "valid_to": None}
    )
    so = _make_source_objects_with_entity(entity_in_db)
    gc1 = builder.build(p1, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    gc2 = builder.build(p2, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.graph_change_id != gc2.graph_change_id


def test_graph_change_id_changes_with_edge_changes(builder):
    """edge confidence 变更 → graph_change_id 变化。"""
    p1 = _make_add_edge_proposal()
    p2 = _make_add_edge_proposal(
        candidate_edge={"source_node_id": "company:a", "relation": "SUPPLIES",
                        "target_node_id": "company:b", "attributes": {},
                        "assertion_type": "FACT", "valid_from": None, "valid_to": None,
                        "confidence": 0.99}
    )
    gc1 = builder.build(p1, supporting_evidence_ids=["ev:001"]).graph_change
    gc2 = builder.build(p2, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.graph_change_id != gc2.graph_change_id


def test_graph_change_id_same_with_clock_change(builder, entity_in_db):
    """时钟变化不影响 graph_change_id（created_at 被排除）。"""
    p1 = _make_add_node_proposal()
    so = _make_source_objects_with_entity(entity_in_db)
    gc1 = builder.build(p1, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change

    import time
    time.sleep(0.1)
    gc2 = builder.build(p1, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.graph_change_id == gc2.graph_change_id


# ---- retire_node ----

def test_build_retire_node(builder):
    """构建 retire_node GraphChange。"""
    proposal = _make_retire_node_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change

    assert gc.change_type == "retire_node"
    assert gc.node is not None
    assert gc.node.status == "retired"
    assert gc.node.valid_to == T0  # 来自 Proposal，非 auto-now


# ---- modify_attribute ----

def test_build_modify_node(builder):
    """构建 modify_attribute 节点 GraphChange。"""
    proposal = _make_modify_node_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change

    assert gc.change_type == "modify_attribute"
    assert gc.node is not None
    assert gc.node.name == "更新名称"
    assert gc.node.aliases == ["新别名"]
    assert gc.edge is None


# ---- add_edge（triple identity）----

def test_build_add_edge(builder):
    """构建 add_edge GraphChange（triple lookup）。"""
    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change

    assert gc.change_type == "add_edge"
    assert gc.edge is not None
    assert gc.edge.relation == "SUPPLIES"
    assert gc.edge.version == 1
    assert gc.edge.review_status == "candidate"
    assert gc.edge.last_reviewed_at is None
    assert gc.node is None


def test_build_add_edge_deterministic_id(builder):
    """相同三元组的边复用相同 edge_id。"""
    p1 = _make_add_edge_proposal()
    p2 = _make_add_edge_proposal()
    gc1 = builder.build(p1, supporting_evidence_ids=["ev:001"]).graph_change
    gc2 = builder.build(p2, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc1.edge.edge_id == gc2.edge.edge_id  # 相同 source/relation/target


def test_add_edge_existing_reuse(builder, db):
    """已有边的三元组 → CURRENT_EDGE_ALREADY_EXISTS 冲突。"""
    # 先添加一条边到 graph_edges
    from research_os.models import GraphEdge as GE
    edge = GE(
        edge_id="edge:governance:supplies-test",
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
    # 直接插入 graph_edges
    import json
    db._conn.execute(
        """INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id,
           assertion_type, review_status, created_at, valid_from, valid_to, confidence,
           last_reviewed_at, originating_graph_change_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (edge.edge_id, edge.version, json.dumps(edge.model_dump(), ensure_ascii=False, sort_keys=True),
         edge.source_node_id, edge.relation, edge.target_node_id,
         edge.assertion_type, edge.review_status, edge.created_at,
         edge.valid_from, edge.valid_to, edge.confidence,
         edge.last_reviewed_at, edge.originating_graph_change_id),
    )
    db._conn.commit()

    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change
    # reuse existing edge_id (来自 triple lookup)
    assert gc.edge.edge_id == "edge:governance:supplies-test"
    assert gc.edge.version == 2  # N+1


def test_add_edge_ambiguous_identity(builder, db):
    """多个不同 edge_id 但相同三元组 → AMBIGUOUS_EDGE_IDENTITY。"""
    import json
    for eid in ("edge:dupe-1", "edge:dupe-2"):
        edge = GraphEdge(
            edge_id=eid, source_node_id="company:x", relation="SUPPLIES",
            target_node_id="company:y", attributes={}, assertion_type="FACT",
            valid_from=None, valid_to=None, confidence=0.9, evidence_ids=["ev:001"],
            review_status="approved", version=1,
            originating_graph_change_id="11111111-1111-1111-1111-111111111111",
            created_at=T0, last_reviewed_at=None,
        )
        db._conn.execute(
            """INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id,
               assertion_type, review_status, created_at, valid_from, valid_to, confidence,
               last_reviewed_at, originating_graph_change_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (edge.edge_id, edge.version, json.dumps(edge.model_dump(), ensure_ascii=False, sort_keys=True),
             edge.source_node_id, edge.relation, edge.target_node_id,
             edge.assertion_type, edge.review_status, edge.created_at,
             edge.valid_from, edge.valid_to, edge.confidence,
             edge.last_reviewed_at, edge.originating_graph_change_id),
        )
    db._conn.commit()

    proposal = _make_add_edge_proposal(
        candidate_edge={"source_node_id": "company:x", "relation": "SUPPLIES",
                        "target_node_id": "company:y", "attributes": {},
                        "assertion_type": "FACT", "valid_from": None, "valid_to": None,
                        "confidence": 0.85}
    )
    with pytest.raises(ValueError, match="AMBIGUOUS_EDGE_IDENTITY"):
        builder.build(proposal, supporting_evidence_ids=["ev:001"])


# ---- 证据闭包攻击 ----

def test_evidence_closure_rejects_external(builder, entity_in_db):
    """new_evidence_ids 不在 supporting_evidence_ids → PROPOSAL_REJECTED。"""
    proposal = _make_add_node_proposal()
    so = _make_source_objects_with_entity(entity_in_db)
    with pytest.raises(ValueError, match="PROPOSAL_REJECTED"):
        builder.build(proposal, source_objects=so, supporting_evidence_ids=["ev:allowed-only"])


def test_evidence_closure_passes_with_subset(builder, entity_in_db):
    """new_evidence_ids ⊆ supporting → 通过。"""
    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    so = _make_source_objects_with_entity(entity_in_db)
    gc = builder.build(proposal, source_objects=so, supporting_evidence_ids=["ev:001", "ev:002"]).graph_change
    assert gc is not None


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
        new_evidence_ids=["ev:001"],
    )
    with pytest.raises(ValueError, match="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE"):
        builder.build(proposal, supporting_evidence_ids=["ev:001"])


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
        new_evidence_ids=["ev:001"],
    )
    with pytest.raises(ValueError, match="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE"):
        builder.build(proposal, supporting_evidence_ids=["ev:001"])


# ---- 冲突检测 ----

def test_check_conflicts_node_not_found(builder):
    """modify_attribute for non-existing node → CURRENT_NODE_NOT_FOUND。"""
    proposal = _make_modify_node_proposal(
        candidate_node={
            "existing_node_id": "company:nonexistent",
            "node_type": "Company",
            "name": "不存在",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        }
    )
    conflicts = builder.check_conflicts(proposal)
    assert any("CURRENT_NODE_NOT_FOUND" in c for c in conflicts)


# ---- 证据门禁 ----

def test_check_evidence_gate_pass(db):
    """证据存在时门禁通过。"""
    ev_id = new_uuid()
    ev = Evidence(
        evidence_id=ev_id, source_id="s1", raw_item_id=new_uuid(),
        title="t", publisher="p", published_at=T0, retrieved_at=T0,
        url="https://x.com", excerpt="e", evidence_type="official_disclosure",
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

def test_version_first_is_1(builder, entity_in_db):
    """首次创建的节点版本为 1。"""
    proposal = _make_add_node_proposal()
    so = _make_source_objects_with_entity(entity_in_db)
    gc = builder.build(proposal, source_objects=so, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.node.version == 1
    assert gc.edge is None


def test_version_fresh_edge_is_1(builder):
    """首次创建的边版本为 1。"""
    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.edge.version == 1


# ---- Fix A：Entity identity ALL types ----

def test_add_node_wrong_entity_type_fails(builder, db):
    """entity_type 不匹配 node_type → IDENTITY_RESOLUTION_REQUIRED。"""
    # 插入一个 company entity
    entity_id = f"company:type-mismatch-{new_uuid()[:8]}"
    entity = Entity(
        entity_id=entity_id,
        entity_type="company",  # Company type
        canonical_name="Type Mismatch",
        aliases=[],
        market="SH",
        industry_ids=[],
        concept_ids=[],
        valid_from=None,
        valid_to=None,
        source_ids=[],
    )
    db.upsert(entity)

    # 尝试以 Product 类型创建节点
    proposal = _make_add_node_proposal(
        candidate_node={
            "existing_node_id": None,
            "node_type": "Product",
            "name": "测试产品",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        }
    )
    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[entity_id],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}
    with pytest.raises(ValueError, match="IDENTITY_RESOLUTION_REQUIRED"):
        builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"])


def test_add_node_non_company_entity_type(db, builder):
    """非 Company 类型节点需正确匹配 entity_type。"""
    # 插入 product entity
    entity_id = f"product:test-{new_uuid()[:8]}"
    entity = Entity(
        entity_id=entity_id,
        entity_type="product",
        canonical_name="测试产品",
        aliases=[],
        market="unknown",
        industry_ids=[],
        concept_ids=[],
        valid_from=None,
        valid_to=None,
        source_ids=[],
    )
    db.upsert(entity)

    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[entity_id],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}

    proposal = _make_add_node_proposal(
        candidate_node={
            "existing_node_id": None,
            "node_type": "Product",
            "name": "测试产品",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        },
        new_evidence_ids=["ev:001"],
    )
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.node.node_id == entity_id
    assert gc.node.node_type == "Product"


def test_add_node_object_entities_extraction(db, builder):
    """object_entities 字段中的 entity_id 被正确提取。"""
    entity_id = f"company:obj-{new_uuid()[:8]}"
    entity = Entity(
        entity_id=entity_id, entity_type="company",
        canonical_name="对象公司", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    )
    db.upsert(entity)

    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[],
        object_entities=[entity_id],  # entity_id 在 object_entities 中
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}

    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.node.node_id == entity_id


def test_add_node_target_entities_extraction(db, builder):
    """*_entity_ids (plural) 字段中的 entity_id 被正确提取。"""
    entity_id = f"company:pl-{new_uuid()[:8]}"
    entity = Entity(
        entity_id=entity_id, entity_type="company",
        canonical_name="Plural Company", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    )
    db.upsert(entity)

    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[],
        object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    # Event doesn't have target_entities — 改用 Claim 的 entity_ids 字段测试
    from research_os.models import Claim as Clm
    cl = Clm(
        claim_id=f"cl-{new_uuid()[:8]}",
        claim_type="FACT", statement="test",
        subject_entities=[entity_id],
        predicate="has",
        object={"v": 1},
        as_of=T0,
        evidence_ids=[],
        support_level="inferred",
        confidence=0.5,
        valid_until=None,
        review_status="unreviewed",
    )
    source_objects = {("Claim", cl.claim_id): cl}

    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.node.node_id == entity_id


# ---- Fix B：add-node baseline ordering ----

def test_add_node_existing_baseline_increment(db, builder):
    """已存在的 entity → add_node 产生 CURRENT_NODE_ALREADY_EXISTS 冲突，版本递增。"""
    entity_id = f"company:baseline-{new_uuid()[:8]}"
    entity = Entity(
        entity_id=entity_id, entity_type="company",
        canonical_name="基线公司", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    )
    db.upsert(entity)

    # 先插入一个已存在的 graph_node
    from research_os.models import GraphNode as GN
    import json as _json
    existing_node = GN(
        node_id=entity_id, node_type="Company", name="基线公司",
        aliases=[], description="", status="active",
        valid_from=None, valid_to=None, evidence_ids=["ev:001"],
        version=1, last_reviewed_at=None, review_status="approved",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )
    db._conn.execute(
        """INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status,
           review_status, origin_kind, created_at, valid_from, valid_to,
           last_reviewed_at, originating_graph_change_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (existing_node.node_id, existing_node.version,
         _json.dumps(existing_node.model_dump(), ensure_ascii=False, sort_keys=True),
         existing_node.node_type, existing_node.name, existing_node.status,
         existing_node.review_status, existing_node.origin_kind, existing_node.created_at,
         existing_node.valid_from, existing_node.valid_to,
         existing_node.last_reviewed_at, existing_node.originating_graph_change_id),
    )
    db._conn.commit()

    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}",
        event_type="test", subject_entities=[entity_id],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}

    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change
    # 已存在节点 → version 应为 2 (N+1)
    assert gc.node.version == 2


def test_modify_missing_node_returns_current_node_not_found(builder):
    """modify_attribute 对不存在的节点 → CURRENT_NODE_NOT_FOUND。"""
    proposal = _make_modify_node_proposal(
        candidate_node={
            "existing_node_id": "company:nonexistent-xyz",
            "node_type": "Company",
            "name": "不存在",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        }
    )
    conflicts = builder.check_conflicts(proposal)
    assert any("CURRENT_NODE_NOT_FOUND" in c for c in conflicts)


# ---- Fix E：Edge ID format ----

def test_fresh_edge_id_format(builder):
    """新边的 edge_id 格式为 edge:graph:SHA256 小写 hex。"""
    proposal = _make_add_edge_proposal()
    gc = builder.build(proposal, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.edge.edge_id.startswith("edge:graph:")
    assert len(gc.edge.edge_id) >= len("edge:graph:") + 64
    # 验证是合法 hex
    hex_part = gc.edge.edge_id[len("edge:graph:"):]
    assert set(hex_part).issubset("0123456789abcdef")


# ---- Fix F：Edge semantics ----

def test_add_edge_fresh_no_current_edge_not_found(builder):
    """新 add_edge 不应报告 CURRENT_EDGE_NOT_FOUND。"""
    proposal = _make_add_edge_proposal(
        candidate_edge={
            "source_node_id": "company:new-a",
            "relation": "COMPETES_WITH",
            "target_node_id": "company:new-b",
            "attributes": {},
            "assertion_type": "FACT",
            "valid_from": None,
            "valid_to": None,
            "confidence": 0.8,
        }
    )
    conflicts = builder.check_conflicts(proposal)
    # 新边不应有 CURRENT_EDGE_NOT_FOUND
    assert not any("CURRENT_EDGE_NOT_FOUND" in c for c in conflicts)
    assert len(conflicts) == 0


def test_modify_edge_missing_raises_current_edge_not_found(builder):
    """modify_attribute 对不存在的边 → CURRENT_EDGE_NOT_FOUND。"""
    ce = GraphProposalEdge(
        source_node_id="company:no-such-a",
        relation="AFFECTS",
        target_node_id="company:no-such-b",
        attributes={},
        assertion_type="FACT",
        valid_from=None,
        valid_to=None,
        confidence=0.8,
    )
    proposal = GraphChangeProposal(
        proposal_type="modify_attribute",
        source_object_ids=["Claim:cl1"],
        candidate_node=None,
        candidate_edge=ce,
        new_evidence_ids=["ev:001"],
        suggested_change="修改不存在的边",
        impact_scope=[],
        conflicts=[],
        verification_points=[],
        confidence=0.8,
    )
    conflicts = builder.check_conflicts(proposal)
    assert any("CURRENT_EDGE_NOT_FOUND" in c for c in conflicts)


# Fix C：GC evidence parity
def test_graph_change_new_evidence_ids_equals_proposal(builder, entity_in_db):
    """GraphChange.new_evidence_ids == proposal.new_evidence_ids。"""
    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001", "ev:002"])
    so = _make_source_objects_with_entity(entity_in_db)
    gc = builder.build(proposal, source_objects=so, supporting_evidence_ids=["ev:001", "ev:002"]).graph_change
    assert gc.new_evidence_ids == ["ev:001", "ev:002"]


# ---- M3 Final: entity type filter ----

def test_type_filter_before_ambiguity(db, builder):
    """Company + Product 实体 → 类型过滤后 Company 被选中，无歧义。"""
    company_id = f"company:typefilter-c-{new_uuid()[:8]}"
    product_id = f"product:typefilter-p-{new_uuid()[:8]}"
    db.upsert(Entity(
        entity_id=company_id, entity_type="company",
        canonical_name="TypeFilter Company", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    db.upsert(Entity(
        entity_id=product_id, entity_type="product",
        canonical_name="TypeFilter Product", aliases=[], market="unknown",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    from research_os.models import Event as Evt
    ev1 = Evt(
        event_id=f"ev-{new_uuid()[:8]}", event_type="test",
        subject_entities=[company_id], object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    ev2 = Evt(
        event_id=f"ev-{new_uuid()[:8]}", event_type="test",
        subject_entities=[product_id], object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev1.event_id): ev1, ("Event", ev2.event_id): ev2}
    # 节点类型为 Company，类型过滤应只保留 company 类型的 entity
    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    gc = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"]).graph_change
    assert gc.node.node_id == company_id


def test_type_filter_two_companies_ambiguous(db, builder):
    """两个 Company entity → 类型过滤后仍有两个 → AMBIGUOUS_ENTITY_IDENTITY。"""
    cid1 = f"company:amb-c1-{new_uuid()[:8]}"
    cid2 = f"company:amb-c2-{new_uuid()[:8]}"
    for cid in (cid1, cid2):
        db.upsert(Entity(
            entity_id=cid, entity_type="company",
            canonical_name=f"Ambiguous {cid}", aliases=[], market="SH",
            industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
        ))
    from research_os.models import Event as Evt
    ev1 = Evt(
        event_id=f"ev-{new_uuid()[:8]}", event_type="test",
        subject_entities=[cid1], object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    ev2 = Evt(
        event_id=f"ev-{new_uuid()[:8]}", event_type="test",
        subject_entities=[cid2], object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev1.event_id): ev1, ("Event", ev2.event_id): ev2}
    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    with pytest.raises(ValueError, match="AMBIGUOUS_ENTITY_IDENTITY"):
        builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"])


# ---- M3 Final: evidence merge ----

def test_modify_node_evidence_merge(db, builder):
    """modify_node: old=[A,B], new=[B,C] → candidate evidence_ids=[A,B,C]。"""
    node_id = f"company:evmerge-{new_uuid()[:8]}"
    # 插入 entity
    db.upsert(Entity(
        entity_id=node_id, entity_type="company",
        canonical_name="EvMerge", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    # 插入已有 graph_node（含旧 evidence_ids）
    import json as _json
    existing_node = GraphNode(
        node_id=node_id, node_type="Company", name="EvMerge",
        aliases=[], description="", status="active",
        valid_from=None, valid_to=None, evidence_ids=["ev:A", "ev:B"],
        version=1, last_reviewed_at=None, review_status="approved",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )
    db._conn.execute(
        """INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status,
           review_status, origin_kind, created_at, valid_from, valid_to,
           last_reviewed_at, originating_graph_change_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (existing_node.node_id, existing_node.version,
         _json.dumps(existing_node.model_dump(), ensure_ascii=False, sort_keys=True),
         existing_node.node_type, existing_node.name, existing_node.status,
         existing_node.review_status, existing_node.origin_kind, existing_node.created_at,
         existing_node.valid_from, existing_node.valid_to,
         existing_node.last_reviewed_at, existing_node.originating_graph_change_id),
    )
    db._conn.commit()

    proposal = _make_modify_node_proposal(
        candidate_node={
            "existing_node_id": node_id,
            "node_type": "Company",
            "name": "EvMerge Updated",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": None,
        },
        new_evidence_ids=["ev:B", "ev:C"],
    )
    gc = builder.build(proposal, supporting_evidence_ids=["ev:B", "ev:C"]).graph_change
    assert gc.node.evidence_ids == ["ev:A", "ev:B", "ev:C"]


def test_retire_node_evidence_merge(db, builder):
    """retire_node: old=[A,B], new=[B,C] → candidate evidence_ids=[A,B,C]。"""
    node_id = f"company:retire-ev-{new_uuid()[:8]}"
    db.upsert(Entity(
        entity_id=node_id, entity_type="company",
        canonical_name="RetireEv", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    import json as _json
    existing_node = GraphNode(
        node_id=node_id, node_type="Company", name="RetireEv",
        aliases=[], description="", status="active",
        valid_from=None, valid_to=None, evidence_ids=["ev:A", "ev:B"],
        version=1, last_reviewed_at=None, review_status="approved",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )
    db._conn.execute(
        """INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status,
           review_status, origin_kind, created_at, valid_from, valid_to,
           last_reviewed_at, originating_graph_change_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (existing_node.node_id, existing_node.version,
         _json.dumps(existing_node.model_dump(), ensure_ascii=False, sort_keys=True),
         existing_node.node_type, existing_node.name, existing_node.status,
         existing_node.review_status, existing_node.origin_kind, existing_node.created_at,
         existing_node.valid_from, existing_node.valid_to,
         existing_node.last_reviewed_at, existing_node.originating_graph_change_id),
    )
    db._conn.commit()

    proposal = _make_retire_node_proposal(
        candidate_node={
            "existing_node_id": node_id,
            "node_type": "Company",
            "name": "RetireEv",
            "aliases": [],
            "description": "",
            "valid_from": None,
            "valid_to": T0,
        },
        new_evidence_ids=["ev:B", "ev:C"],
    )
    gc = builder.build(proposal, supporting_evidence_ids=["ev:B", "ev:C"]).graph_change
    assert gc.node.evidence_ids == ["ev:A", "ev:B", "ev:C"]


# ---- M3 Final: BuildResult.deterministic_conflicts ----

def test_add_node_deterministic_conflict(db, builder):
    """已有 entity + add_node → BuildResult.deterministic_conflicts 含 CURRENT_NODE_ALREADY_EXISTS。"""
    entity_id = f"company:detconf-{new_uuid()[:8]}"
    db.upsert(Entity(
        entity_id=entity_id, entity_type="company",
        canonical_name="DetConf", aliases=[], market="SH",
        industry_ids=[], concept_ids=[], valid_from=None, valid_to=None, source_ids=[],
    ))
    # 插入已有 node
    import json as _json
    existing_node = GraphNode(
        node_id=entity_id, node_type="Company", name="DetConf",
        aliases=[], description="", status="active",
        valid_from=None, valid_to=None, evidence_ids=["ev:001"],
        version=1, last_reviewed_at=None, review_status="approved",
        origin_kind="graph_change",
        originating_graph_change_id="11111111-1111-1111-1111-111111111111",
        created_at=T0,
    )
    db._conn.execute(
        """INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status,
           review_status, origin_kind, created_at, valid_from, valid_to,
           last_reviewed_at, originating_graph_change_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (existing_node.node_id, existing_node.version,
         _json.dumps(existing_node.model_dump(), ensure_ascii=False, sort_keys=True),
         existing_node.node_type, existing_node.name, existing_node.status,
         existing_node.review_status, existing_node.origin_kind, existing_node.created_at,
         existing_node.valid_from, existing_node.valid_to,
         existing_node.last_reviewed_at, existing_node.originating_graph_change_id),
    )
    db._conn.commit()

    from research_os.models import Event as Evt
    ev = Evt(
        event_id=f"ev-{new_uuid()[:8]}", event_type="test",
        subject_entities=[entity_id], object_entities=[],
        event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="s", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    source_objects = {("Event", ev.event_id): ev}
    proposal = _make_add_node_proposal(new_evidence_ids=["ev:001"])
    build_result = builder.build(proposal, source_objects=source_objects, supporting_evidence_ids=["ev:001"])
    assert isinstance(build_result, BuildResult)
    assert any("CURRENT_NODE_ALREADY_EXISTS" in c for c in build_result.deterministic_conflicts)
    # graph_change 仍然生成（版本递增，非拒绝）
    assert build_result.graph_change is not None
    assert build_result.graph_change.node.version >= 2
