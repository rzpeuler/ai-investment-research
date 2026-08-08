"""Phase 5 M4 Knowledge Validator 综合测试 — 36+ test cases covering all 19 KGV rules.

零 LLM、零网络、零随机数。使用真实 SQLite fixtures。
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from research_os.models import (
    GraphChange, GraphNode, GraphEdge, GraphReview, GraphReviewer,
)
from research_os.storage.db import Database
from research_os.knowledge.repository import GraphRepository
from research_os.knowledge.knowledge_validator import (
    KnowledgeValidator, KnowledgeValidationIssue, KnowledgeValidationResult,
    _CORE_STRUCTURAL_RELATIONS,
)
from research_os.validators.schema_validator import validate_instance

T0 = "2026-08-08T08:00:00"
T1 = "2026-08-08T09:00:00"
T2 = "2026-08-08T09:01:00"
_UUID = "11111111-1111-1111-1111-111111111111"
_UUID2 = "22222222-2222-2222-2222-222222222222"
_UUID3 = "33333333-3333-3333-3333-333333333333"
_UUID4 = "44444444-4444-4444-4444-444444444444"
_UUID5 = "55555555-5555-5555-5555-555555555555"
_HASH = "a" * 64

# UUIDs for evidence/raw_item IDs (must match regex ^[0-9a-fA-F-]{36}$)
_EV_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_RI_ID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_EV_ID2 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
_RI_ID2 = "dddddddd-dddd-dddd-dddd-dddddddddddd"


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def db_path():
    """Create a temporary database file."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield Path(path)
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass


@pytest.fixture
def db(db_path):
    """Initialize a Database with migrations applied."""
    database = Database(str(db_path))
    database._conn.execute("PRAGMA user_version = 0")
    database.initialize()
    return database


@pytest.fixture
def graph_repo(db):
    """Create a GraphRepository connected to the test database."""
    return GraphRepository(db)


@pytest.fixture
def validator(db, graph_repo):
    """Create a KnowledgeValidator."""
    return KnowledgeValidator(db, graph_repo)


# ============================================================================
# Helpers
# ============================================================================

def _valid_add_node_gc(**overrides):
    """Create a valid add_node GraphChange candidate (returns dict)."""
    d = {
        "graph_change_id": _UUID,
        "change_type": "add_node",
        "node": {
            "node_id": "company:600519.SH",
            "node_type": "Company",
            "name": "贵州茅台",
            "aliases": [],
            "description": "",
            "status": "active",
            "valid_from": None,
            "valid_to": None,
            "evidence_ids": [_EV_ID],
            "version": 1,
            "last_reviewed_at": None,
            "review_status": "candidate",
            "origin_kind": "graph_change",
            "originating_graph_change_id": _UUID2,
            "created_at": T0,
        },
        "edge": None,
        "current_knowledge": "",
        "new_evidence_ids": [_EV_ID],
        "suggested_change": "新增公司节点",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    d.update(overrides)
    return d


def _valid_add_edge_gc(**overrides):
    """Create a valid add_edge GraphChange candidate (returns dict)."""
    d = {
        "graph_change_id": _UUID,
        "change_type": "add_edge",
        "node": None,
        "edge": {
            "edge_id": "edge:competitive:002",
            "source_node_id": "company:A",
            "relation": "COMPETES_WITH",
            "target_node_id": "company:B",
            "attributes": {},
            "assertion_type": "FACT",
            "valid_from": None,
            "valid_to": None,
            "confidence": 0.8,
            "evidence_ids": [_EV_ID],
            "review_status": "candidate",
            "version": 1,
            "originating_graph_change_id": _UUID2,
            "created_at": T0,
            "last_reviewed_at": None,
        },
        "current_knowledge": "",
        "new_evidence_ids": [_EV_ID],
        "suggested_change": "新增竞争关系",
        "impact_scope": [],
        "conflicts": [],
        "verification_points": [],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    d.update(overrides)
    return d


def _insert_entity(db, entity_id="company:600519.SH", entity_type="company",
                   canonical_name="贵州茅台"):
    from research_os.models import Entity
    entity = Entity(
        entity_id=entity_id, entity_type=entity_type, canonical_name=canonical_name,
        market="A-share", industry_ids=[], concept_ids=[], source_ids=[],
        aliases=[], valid_from=None, valid_to=None,
    )
    db.upsert(entity)


def _insert_evidence(db, evidence_id=_EV_ID, raw_item_id=_RI_ID,
                     source_tier="S", published_at=T0, retrieved_at=T1):
    from research_os.models import Evidence
    ev = Evidence(
        evidence_id=evidence_id, source_id="cninfo", raw_item_id=raw_item_id,
        title="Test Evidence", publisher="Test Publisher",
        published_at=published_at, retrieved_at=retrieved_at,
        url="https://example.com/ev/1", excerpt="Test excerpt",
        evidence_type="official_disclosure", independence_group="test-group",
        source_tier=source_tier, access_status="ok",
    )
    db.upsert(ev)


def _insert_raw_item(db, raw_item_id=_RI_ID, entities=None):
    from research_os.models import RawItem
    from research_os.utils.id import content_sha256
    if entities is None:
        entities = ["company:600519.SH"]
    ri = RawItem(
        raw_item_id=raw_item_id, source_id="sse",
        external_id="ri-ext-001", url="https://example.com/ri/1",
        title="Test RawItem", publisher="Test Publisher",
        author=None, published_at=T0, retrieved_at=T1,
        content_hash=content_sha256("test content"),
        content_excerpt="Test excerpt", content_storage="metadata_and_excerpt",
        language="zh-CN", access_status="ok",
        entities=entities, raw_category="announcement",
    )
    db.upsert(ri)


def _insert_node(db, graph_repo, node_id="company:A", node_type="Company",
                 name="A公司", status="active", version=1, review_status="approved",
                 origin_kind="graph_change", evidence_ids=None, ogc_id=_UUID3):
    if evidence_ids is None:
        evidence_ids = [_EV_ID]
    node = GraphNode(
        node_id=node_id, node_type=node_type, name=name, status=status,
        version=version, review_status=review_status, origin_kind=origin_kind,
        evidence_ids=evidence_ids,
        originating_graph_change_id=ogc_id if origin_kind == "graph_change" else None,
        created_at=T0,
    )
    graph_repo.append_node(node)


def _insert_edge(graph_repo, edge_id="edge:comp:001", source="company:A",
                 relation="COMPETES_WITH", target="company:B",
                 assertion_type="FACT", version=1, review_status="approved",
                 evidence_ids=None, ogc_id=_UUID3):
    if evidence_ids is None:
        evidence_ids = [_EV_ID]
    edge = GraphEdge(
        edge_id=edge_id, source_node_id=source, relation=relation,
        target_node_id=target, assertion_type=assertion_type,
        version=version, review_status=review_status,
        evidence_ids=evidence_ids,
        originating_graph_change_id=ogc_id if assertion_type != "GOVERNANCE" else None,
        created_at=T0,
    )
    graph_repo.append_edge(edge)


# ============================================================================
# KGV-001: Schema validation
# ============================================================================

class TestKGV001Schema:
    def test_golden_add_node_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        assert result.structural_ok is True

    def test_golden_add_edge_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A", "company", "A公司")
        _insert_entity(db, "company:B", "company", "B公司")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        assert result.structural_ok is True

    def test_invalid_schema_blocks_review(self, validator, db, graph_repo):
        """KGV-001: invalid GraphChange blocks — test via validate_instance directly."""
        bad = _valid_add_node_gc()
        bad["change_type"] = "invalid_type"
        errors = validate_instance(bad, "graph_change")
        assert len(errors) > 0

    def test_invalid_node_schema_blocks(self, validator, db, graph_repo):
        """KGV-001: invalid GraphNode — test via validate_instance directly."""
        bad = _valid_add_node_gc()
        bad["node"]["node_type"] = "InvalidType"
        errors = validate_instance(bad["node"], "graph_node")
        assert len(errors) > 0

    def test_invalid_edge_schema_blocks(self, validator, db, graph_repo):
        """KGV-001: invalid GraphEdge — test via validate_instance directly."""
        bad = _valid_add_edge_gc()
        bad["edge"]["relation"] = "NOT_A_REAL_RELATION"
        errors = validate_instance(bad["edge"], "graph_edge")
        assert len(errors) > 0


# ============================================================================
# KGV-002: Node Identity
# ============================================================================

class TestKGV002NodeIdentity:
    def test_valid_company_entity_match(self, validator, db, graph_repo):
        _insert_entity(db, "company:600519.SH", "company")
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-002"]
        assert len(issues) == 0

    def test_entity_type_mismatch(self, validator, db, graph_repo):
        _insert_entity(db, "company:600519.SH", "security")
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-002"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_TYPE_MISMATCH" for i in issues)

    def test_entity_not_found(self, validator, db, graph_repo):
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-002"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_NOT_FOUND" for i in issues)


# ============================================================================
# KGV-003: Relation Allowlist
# ============================================================================

class TestKGV003RelationAllowlist:
    def test_valid_relation_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-003"]
        assert len(issues) == 0

    def test_invalid_relation_fails(self, validator, db, graph_repo):
        """KGV-003: invalid relation — test via validate_instance."""
        bad = _valid_add_edge_gc()
        bad["edge"]["relation"] = "FRIEND_OF"
        errors = validate_instance(bad["edge"], "graph_edge")
        assert len(errors) > 0


# ============================================================================
# KGV-004: Source/Target Existence
# ============================================================================

class TestKGV004SourceTargetExistence:
    def test_valid_endpoints_pass(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-004"]
        assert len(issues) == 0

    def test_source_not_found(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-004"]
        assert len(issues) > 0
        assert any(i.code == "SOURCE_NOT_FOUND" for i in issues)

    def test_target_not_found(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-004"]
        assert len(issues) > 0
        assert any(i.code == "TARGET_NOT_FOUND" for i in issues)


# ============================================================================
# KGV-005: Evidence Existence
# ============================================================================

class TestKGV005EvidenceExistence:
    def test_evidence_exists_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"]
        assert len(issues) == 0

    def test_evidence_not_found(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_NOT_FOUND" for i in issues)

    def test_evidence_schema_invalid(self, validator, db, graph_repo):
        _insert_entity(db)
        # Insert malformed evidence payload (missing required fields)
        bad_ev_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        # Insert with all required NOT NULL columns for evidence table
        db._conn.execute(
            """INSERT INTO evidence (evidence_id, payload, source_id, raw_item_id,
            independence_group, source_tier) VALUES (?, ?, ?, ?, ?, ?)""",
            (bad_ev_id, json.dumps({"evidence_id": bad_ev_id}),
             "src", _RI_ID, "grp", "B"),
        )
        _insert_raw_item(db)
        bad = _valid_add_node_gc()
        bad["new_evidence_ids"] = [bad_ev_id]
        bad["node"]["evidence_ids"] = [bad_ev_id]
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_SCHEMA_INVALID" for i in issues)


# ============================================================================
# KGV-006: Evidence Entity Relevance
# ============================================================================

class TestKGV006EvidenceEntityRelevance:
    def test_entity_coverage_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:600519.SH"])
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) == 0

    def test_entity_not_covered(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:OTHER"])
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_NOT_COVERED_BY_EVIDENCE" for i in issues)

    def test_raw_item_missing(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db, _EV_ID, "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_LINEAGE_INCOMPLETE" for i in issues)

    def test_edge_coverage_both_entities(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) == 0

    def test_edge_partial_coverage_fails(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_NOT_COVERED_BY_EVIDENCE" for i in issues)


# ============================================================================
# KGV-007: Evidence Time
# ============================================================================

class TestKGV007EvidenceTime:
    def test_valid_time_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db, published_at=T0, retrieved_at=T1)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-007"]
        assert len(issues) == 0

    def test_published_after_retrieved(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db, published_at=T2, retrieved_at=T1)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-007"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_TIME_INVALID" for i in issues)


# ============================================================================
# KGV-008: Source Tier
# ============================================================================

class TestKGV008SourceTier:
    def test_sa_source_for_fact_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="S")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        bad = _valid_add_edge_gc()
        bad["edge"]["relation"] = "PRODUCES"
        bad["edge"]["assertion_type"] = "FACT"
        bad["new_evidence_ids"] = [_EV_ID]
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) == 0

    def test_b_source_for_fact_structural_fails(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        bad = _valid_add_edge_gc()
        bad["edge"]["relation"] = "PRODUCES"
        bad["edge"]["assertion_type"] = "FACT"
        bad["new_evidence_ids"] = [_EV_ID]
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) > 0
        assert any(i.code == "INSUFFICIENT_SOURCE_TIER" for i in issues)

    def test_non_structural_relation_b_tier_passes(self, validator, db, graph_repo):
        """Non-structural FACT needs at least S/A/B — B passes."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) == 0

    def test_non_structural_relation_c_tier_fails(self, validator, db, graph_repo):
        """Non-structural FACT with C-only new evidence fails."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="C")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) > 0
        assert any(i.code == "INSUFFICIENT_SOURCE_TIER" for i in issues)

    def test_model_inference_skips_tier_check(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        bad = _valid_add_edge_gc()
        bad["edge"]["relation"] = "PRODUCES"
        bad["edge"]["assertion_type"] = "MODEL_INFERENCE"
        bad["new_evidence_ids"] = [_EV_ID]
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) == 0


# ============================================================================
# KGV-009: Governance Seed Scope
# ============================================================================

class TestKGV009GovernanceSeedScope:
    def test_industry_add_node_blocks(self, validator, db, graph_repo):
        _insert_entity(db, "industry:AI_hardware", "industry")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["industry:AI_hardware"])
        bad = _valid_add_node_gc()
        bad["node"]["node_id"] = "industry:AI_hardware"
        bad["node"]["node_type"] = "Industry"
        bad["node"]["origin_kind"] = "graph_change"
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-009"]
        assert len(issues) > 0
        assert any(i.code == "ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE" for i in issues)

    def test_industry_segment_add_node_blocks(self, validator, db, graph_repo):
        _insert_entity(db, "industry_segment:AI_chips", "industry_segment")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["industry_segment:AI_chips"])
        bad = _valid_add_node_gc()
        bad["node"]["node_id"] = "industry_segment:AI_chips"
        bad["node"]["node_type"] = "IndustrySegment"
        bad["node"]["origin_kind"] = "graph_change"
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-009"]
        assert len(issues) > 0


# ============================================================================
# KGV-010: FACT/MODEL_INFERENCE boundary
# ============================================================================

class TestKGV010FactModelInference:
    def test_governance_edge_blocks(self, validator, db, graph_repo):
        """KGV-010: GOVERNANCE assertion blocked on GraphChange edge.
        Test via validate_instance since Pydantic rejects GOVERNANCE+
        evidence_ids, and Schema-level check is the real gate."""
        bad = _valid_add_edge_gc()
        bad["edge"]["assertion_type"] = "GOVERNANCE"
        # GOVERNANCE edges need evidence_ids=[] in graph_edge schema
        bad["edge"]["evidence_ids"] = []
        bad["edge"]["originating_graph_change_id"] = None
        bad["edge"]["review_status"] = "approved"
        # The graph_edge schema accepts GOVERNANCE, but GraphChange rejects it
        # We test via the schema validator on graph_change level
        errors = validate_instance(bad, "graph_change")
        assert len(errors) > 0

    def test_model_inference_no_evidence(self, validator, db, graph_repo):
        """KGV-010: MODEL_INFERENCE needs evidence.
        Test via validate_instance at graph_edge level."""
        bad = _valid_add_edge_gc()
        bad["edge"]["assertion_type"] = "MODEL_INFERENCE"
        bad["edge"]["evidence_ids"] = []
        errors = validate_instance(bad["edge"], "graph_edge")
        # Schemas enforce the evidence requirement
        assert len(errors) > 0


# ============================================================================
# KGV-011: Conflict Blocking
# ============================================================================

class TestKGV011ConflictBlocking:
    def test_no_conflicts(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-011"]
        assert len(issues) == 0

    def test_conflicts_block_apply_not_review(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        bad = _valid_add_node_gc()
        bad["conflicts"] = ["Existing node with same name"]
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-011"]
        assert len(issues) > 0
        conflict_issue = issues[0]
        assert conflict_issue.blocks_review is False
        assert conflict_issue.blocks_apply is True
        assert result.apply_eligible is False


# ============================================================================
# KGV-012: Review Status
# ============================================================================

class TestKGV012ReviewStatus:
    def test_candidate_status_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-012"]
        assert len(issues) == 0

    def test_non_candidate_status_fails(self, validator, db, graph_repo):
        """KGV-012: non-candidate review_status caught by validator.
        Pydantic allows GraphChange.review_status="approved" with reviewed_at
        set, but KGV-012's deterministic check catches it."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        bad = _valid_add_node_gc()
        bad["review_status"] = "approved"
        bad["reviewed_at"] = T1
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-012"]
        assert len(issues) > 0
        assert any(i.code == "INVALID_REVIEW_STATUS" for i in issues)

    def test_reviewed_at_not_null_on_candidate(self, validator, db, graph_repo):
        """KGV-012: candidate with reviewed_at non-null.
        Pydantic model_validator catches this in _check_review_timing,
        so we test that the Schema-level check also blocks it."""
        bad = _valid_add_node_gc()
        bad["reviewed_at"] = T1
        # Pydantic will reject this, but KGV-012 also validates at Schema level
        errors = validate_instance(bad, "graph_change")
        assert len(errors) > 0


# ============================================================================
# KGV-013: Version Monotonicity
# ============================================================================

class TestKGV013VersionMonotonicity:
    def test_fresh_v1_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-013"]
        assert len(issues) == 0

    def test_fresh_v2_fails(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        bad = _valid_add_node_gc()
        bad["node"]["version"] = 2
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-013"]
        assert len(issues) > 0
        assert any(i.code == "VERSION_VIOLATION" for i in issues)

    def test_existing_n_plus_one_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:600519.SH", version=1,
                     origin_kind="graph_change", evidence_ids=[_EV_ID])
        bad = _valid_add_node_gc()
        bad["change_type"] = "modify_attribute"
        bad["node"]["version"] = 2
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-013"]
        assert len(issues) == 0

    def test_existing_version_gap_fails(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:600519.SH", version=1,
                     origin_kind="graph_change", evidence_ids=[_EV_ID])
        bad = _valid_add_node_gc()
        bad["change_type"] = "modify_attribute"
        bad["node"]["version"] = 3
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-013"]
        assert len(issues) > 0
        assert any(i.code == "VERSION_GAP" for i in issues)


# ============================================================================
# KGV-014: Explicit As-Of
# ============================================================================

class TestKGV014ExplicitAsOf:
    def test_explicit_as_of_accepted(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        assert result.structural_ok is True


# ============================================================================
# KGV-015: Duplicate Relation
# ============================================================================

class TestKGV015DuplicateRelation:
    def test_add_fresh_edge_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-015"]
        assert len(issues) == 0

    def test_add_duplicate_edge_fails(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        _insert_edge(graph_repo)
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-015"]
        assert len(issues) > 0
        assert any(i.code == "DUPLICATE_TRIPLE" for i in issues)


# ============================================================================
# KGV-016: Self-Loop
# ============================================================================

class TestKGV016SelfLoop:
    def test_no_self_loop_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-016"]
        assert len(issues) == 0

    def test_self_loop_blocked(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A"])
        _insert_node(db, graph_repo, "company:A")
        bad = _valid_add_edge_gc()
        bad["edge"]["target_node_id"] = "company:A"
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-016"]
        assert len(issues) > 0
        assert any(i.code == "SELF_LOOP_NOT_ALLOWED" for i in issues)

    def test_self_loop_all_relations_blocked(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A"])
        _insert_node(db, graph_repo, "company:A")
        bad = _valid_add_edge_gc()
        bad["edge"]["source_node_id"] = "company:A"
        bad["edge"]["target_node_id"] = "company:A"
        bad["edge"]["relation"] = "SUPPLIES"
        gc = GraphChange(**bad)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-016"]
        assert len(issues) > 0
        assert any(i.code == "SELF_LOOP_NOT_ALLOWED" for i in issues)


# ============================================================================
# KGV-017: Retired Node Reference
# ============================================================================

class TestKGV017RetiredNodeReference:
    def test_active_node_passes(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A", status="active")
        _insert_node(db, graph_repo, "company:B", status="active")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-017"]
        assert len(issues) == 0

    def test_retired_node_reference_fails(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B", status="retired")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-017"]
        assert len(issues) > 0
        assert any(i.code == "RETIRED_NODE_REFERENCE" for i in issues)


# ============================================================================
# KGV-018: Candidate Hash
# ============================================================================

class TestKGV018CandidateHash:
    def test_candidate_hash_computes(self, validator):
        gc = GraphChange(**_valid_add_node_gc())
        h = validator.compute_candidate_hash(gc)
        assert isinstance(h, str)
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_candidate_hash_deterministic(self, validator):
        gc1 = GraphChange(**_valid_add_node_gc())
        gc2 = GraphChange(**_valid_add_node_gc())
        assert validator.compute_candidate_hash(gc1) == validator.compute_candidate_hash(gc2)

    def test_candidate_hash_differs_on_change(self, validator):
        gc1 = GraphChange(**_valid_add_node_gc())
        gc2 = GraphChange(**_valid_add_node_gc(suggested_change="Different"))
        assert validator.compute_candidate_hash(gc1) != validator.compute_candidate_hash(gc2)

    def test_hash_placement_in_result(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        assert result.candidate_hash is not None
        assert len(result.candidate_hash) == 64


# ============================================================================
# KGV-019: Stale Review
# ============================================================================

class TestKGV019StaleReview:
    def test_fresh_add_node_no_staleness(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc)
        result = validator.validate_apply_preflight(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) == 0

    def test_add_node_stale_when_exists(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:600519.SH")
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc)
        result = validator.validate_apply_preflight(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0
        assert any(i.code == "STALE_REVIEW_NODE_EXISTS" for i in issues)

    def test_add_edge_stale_when_exists(self, validator, db, graph_repo):
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        _insert_edge(graph_repo)
        gc = GraphChange(**_valid_add_edge_gc())
        review = _make_review(gc)
        result = validator.validate_apply_preflight(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0
        assert any(i.code == "STALE_REVIEW_EDGE_EXISTS" for i in issues)


# ============================================================================
# validate_review tests
# ============================================================================

class TestValidateReview:
    def test_approved_review_passes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc, decision="approved")
        result = validator.validate_review(gc, review, T1)
        assert result.review_eligible is True

    def test_hash_mismatch_blocks(self, validator, db, graph_repo):
        gc = GraphChange(**_valid_add_node_gc())
        review = GraphReview(
            review_id=_UUID4,
            graph_change_id=_UUID,
            decision="approved",
            reviewer=GraphReviewer(reviewer_type="human", reviewer_id="reviewer-01"),
            reviewed_at=T1,
            candidate_hash="0" * 64,
        )
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.code == "CANDIDATE_HASH_MISMATCH"]
        assert len(issues) > 0

    def test_rejected_decision_blocks_apply(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc, decision="rejected")
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.code == "NON_APPROVABLE_DECISION"]
        assert len(issues) > 0
        assert result.apply_eligible is False

    def test_review_mismatch_graph_change_id(self, validator, db, graph_repo):
        gc = GraphChange(**_valid_add_node_gc())
        review = GraphReview(
            review_id=_UUID4,
            graph_change_id=_UUID4,
            decision="approved",
            reviewer=GraphReviewer(reviewer_type="human", reviewer_id="reviewer-01"),
            reviewed_at=T1,
            candidate_hash=KnowledgeValidator.compute_candidate_hash(gc),
        )
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.code == "REVIEW_MISMATCH"]
        assert len(issues) > 0


# ============================================================================
# validate_apply_preflight tests
# ============================================================================

class TestValidateApplyPreflight:
    def test_approved_full_pass(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc, decision="approved")
        result = validator.validate_apply_preflight(gc, review, T1)
        assert result.structural_ok is True
        assert result.apply_eligible is True

    def test_conflict_blocks_apply(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        bad = _valid_add_node_gc()
        bad["conflicts"] = ["blocking"]
        gc = GraphChange(**bad)
        review = _make_review(gc, decision="approved")
        result = validator.validate_apply_preflight(gc, review, T1)
        assert result.apply_eligible is False


# ============================================================================
# Zero-write test
# ============================================================================

class TestZeroWriteVerification:
    def test_validator_makes_zero_writes(self, validator, db, graph_repo):
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")

        initial_node_count = db.count("graph_nodes")
        initial_edge_count = db.count("graph_edges")
        initial_evidence_count = db.count("evidence")

        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        review = _make_review(gc, decision="approved")
        result2 = validator.validate_review(gc, review, T1)
        result3 = validator.validate_apply_preflight(gc, review, T1)

        assert db.count("graph_nodes") == initial_node_count
        assert db.count("graph_edges") == initial_edge_count
        assert db.count("evidence") == initial_evidence_count


# ============================================================================
# All 18 relations test
# ============================================================================

class TestAllRelations:
    def test_all_18_relations_in_allowlist(self):
        from research_os.models import GraphRelation
        from typing import get_args
        relations = set(get_args(GraphRelation))
        from research_os.knowledge.knowledge_validator import _ALLOWED_RELATIONS
        assert relations == _ALLOWED_RELATIONS
        assert len(relations) == 18


# ============================================================================
# M4-R1 Attack Tests — Public Validator API (18+ tests)
# ============================================================================

class TestM4R1PublicValidatorFailClosed:
    """Public validator API accepts raw dict, normalizes fail-closed."""

    def test_raw_dict_candidate_invalid_schema(self, validator, db, graph_repo):
        """Raw dict with invalid schema → public Validator returns SCHEMA_INVALID."""
        bad = _valid_add_node_gc()
        bad["change_type"] = "invalid_type"
        result = validator.validate_candidate(bad, T1)
        assert result.structural_ok is False
        assert len(result.issues) > 0
        assert any(i.code == "SCHEMA_INVALID" and i.rule_id == "KGV-001" for i in result.issues)

    def test_raw_dict_candidate_valid_passes(self, validator, db, graph_repo):
        """Raw dict that is valid → public Validator normalizes and returns model."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        raw = _valid_add_node_gc()
        result = validator.validate_candidate(raw, T1)
        assert result.structural_ok is True

    def test_raw_dict_review_invalid(self, validator, db, graph_repo):
        """Raw dict review with bad schema → REVIEW_SCHEMA_INVALID."""
        gc = GraphChange(**_valid_add_node_gc())
        raw_review = {
            "review_id": "not-a-uuid",
            "graph_change_id": gc.graph_change_id,
            "decision": "approved",
            "reviewed_at": T1,
            "candidate_hash": KnowledgeValidator.compute_candidate_hash(gc),
        }
        result = validator.validate_review(gc, raw_review, T1)
        assert result.structural_ok is False
        # Should have KGV-012 REVIEW_SCHEMA_INVALID
        review_issues = [i for i in result.issues if i.rule_id == "KGV-012"
                         and "REVIEW_SCHEMA_INVALID" in i.code]
        assert len(review_issues) > 0

    def test_model_direct_passes_normalized(self, validator, db, graph_repo):
        """Model object → public Validator normalizes (dump→schema check)."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        assert result.structural_ok is True


class TestM4R1EntitySchemaFirst:
    """KGV-002 Entity Schema-first validation."""

    def test_entity_payload_schema_invalid(self, validator, db, graph_repo):
        """Entity with bad payload → ENTITY_INVALID."""
        _insert_evidence(db)
        _insert_raw_item(db)
        bad_entity_id = "company:bad_entity"
        # Insert entity with malformed payload (missing required fields)
        db._conn.execute(
            "INSERT OR REPLACE INTO entities (entity_id, entity_type, canonical_name, payload) VALUES (?, ?, ?, ?)",
            (bad_entity_id, "company", "Bad Entity", json.dumps({"entity_id": bad_entity_id})),
        )
        raw = _valid_add_node_gc()
        raw["node"]["node_id"] = bad_entity_id
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-002"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_INVALID" for i in issues)

    def test_entity_valid_schema_first(self, validator, db, graph_repo):
        """Valid entity passes schema-first check."""
        _insert_entity(db, "company:600519.SH", "company")
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-002"]
        assert len(issues) == 0


class TestM4R1EvidenceSubset:
    """KGV-005 Evidence subset check: new_evidence_ids ⊆ candidate evidence_ids."""

    def test_new_evidence_not_in_candidate_ids(self, validator, db, graph_repo):
        """new_evidence_id not in node/edge evidence_ids → NEW_EVIDENCE_NOT_IN_CANDIDATE."""
        _insert_entity(db)
        _insert_evidence(db, _EV_ID)
        _insert_evidence(db, _EV_ID2)
        _insert_raw_item(db)
        raw = _valid_add_node_gc()
        raw["new_evidence_ids"] = [_EV_ID2]
        # node evidence_ids has _EV_ID, not _EV_ID2
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"
                  and i.code == "NEW_EVIDENCE_NOT_IN_CANDIDATE"]
        assert len(issues) > 0

    def test_all_new_evidence_in_candidate_ids(self, validator, db, graph_repo):
        """All new_evidence_ids ⊆ node evidence_ids → passes."""
        _insert_entity(db)
        _insert_evidence(db, _EV_ID)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"
                  and i.code == "NEW_EVIDENCE_NOT_IN_CANDIDATE"]
        assert len(issues) == 0

    def test_evidence_schema_invalid_detected(self, validator, db, graph_repo):
        """Evidence with bad payload → EVIDENCE_SCHEMA_INVALID via schema-first."""
        _insert_entity(db)
        bad_ev_id = "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee"
        db._conn.execute(
            "INSERT INTO evidence (evidence_id, payload, source_id, raw_item_id,"
            "independence_group, source_tier) VALUES (?, ?, ?, ?, ?, ?)",
            (bad_ev_id, json.dumps({"evidence_id": bad_ev_id}),
             "src", _RI_ID, "grp", "B"),
        )
        _insert_raw_item(db)
        raw = _valid_add_node_gc()
        raw["new_evidence_ids"] = [bad_ev_id]
        raw["node"]["evidence_ids"] = [bad_ev_id]
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-005"
                  and i.code == "EVIDENCE_SCHEMA_INVALID"]
        assert len(issues) > 0


class TestM4R1KGV006NewEvidenceOnly:
    """KGV-006 uses ONLY new_evidence_ids for relevance qualification."""

    def test_historical_evidence_irrelevant_new_irrelevant(self, validator, db, graph_repo):
        """Historical evidence relevant + new evidence irrelevant → KGV-006 FAIL."""
        _insert_entity(db)
        _insert_evidence(db, _EV_ID)
        _insert_raw_item(db, _RI_ID, ["company:OTHER"])  # RawItem NOT covering required entity
        raw = _valid_add_node_gc()
        raw["new_evidence_ids"] = [_EV_ID]
        raw["node"]["evidence_ids"] = [_EV_ID, _EV_ID2]  # _EV_ID2 in node but not new
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        # new_evidence_ids only has _EV_ID which doesn't cover "company:600519.SH"
        assert len(issues) > 0
        assert any(i.code == "ENTITY_NOT_COVERED_BY_EVIDENCE" for i in issues)

    def test_new_only_evidence_covers_entities(self, validator, db, graph_repo):
        """Both new evidence IDs cover the required entity → PASS."""
        _insert_entity(db)
        _insert_evidence(db, _EV_ID)
        _insert_evidence(db, _EV_ID2)
        _insert_raw_item(db, _RI_ID, ["company:600519.SH"])
        _insert_raw_item(db, _RI_ID2, ["company:600519.SH"])
        raw = _valid_add_node_gc()
        raw["new_evidence_ids"] = [_EV_ID, _EV_ID2]
        raw["node"]["evidence_ids"] = [_EV_ID, _EV_ID2]
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) == 0

    def test_raw_item_invalid_excludes_entities(self, validator, db, graph_repo):
        """Invalid RawItem → entities excluded, coverage fails."""
        _insert_entity(db)
        _insert_evidence(db, _EV_ID)
        bad_ri_id = "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz"
        db._conn.execute(
            "INSERT INTO raw_items (raw_item_id, source_id, content_hash, access_status, payload) VALUES (?, ?, ?, ?, ?)",
            (bad_ri_id, "test-src", "badhash123", "ok", json.dumps({"raw_item_id": bad_ri_id})),
        )
        # Evidence points to bad RawItem
        db._conn.execute(
            "UPDATE evidence SET raw_item_id = ? WHERE evidence_id = ?",
            (bad_ri_id, _EV_ID),
        )
        raw = _valid_add_node_gc()
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-006"]
        assert len(issues) > 0
        assert any(i.code == "ENTITY_NOT_COVERED_BY_EVIDENCE" for i in issues)


class TestM4R1KGV007Datetime:
    """KGV-007 parsed datetime comparison."""

    def test_time_inverted_strings(self, validator, db, graph_repo):
        """Published after retrieved → EVIDENCE_TIME_INVALID."""
        _insert_entity(db)
        _insert_evidence(db, published_at=T2, retrieved_at=T1)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-007"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_TIME_INVALID" for i in issues)

    def test_review_retrieved_after_reviewed(self, validator, db, graph_repo):
        """retrieved_at > reviewed_at → EVIDENCE_RETRIEVED_AFTER_REVIEW."""
        _insert_entity(db)
        _insert_evidence(db, published_at=T0, retrieved_at=T2)  # retrieved after review time
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc, decision="approved")  # reviewed_at = T1
        result = validator.validate_review(gc, review, T2)
        issues = [i for i in result.issues
                  if i.rule_id == "KGV-007" and i.code == "EVIDENCE_RETRIEVED_AFTER_REVIEW"]
        assert len(issues) > 0


class TestM4R1KGV008SourceTierNewOnly:
    """KGV-008 uses new_evidence_ids ONLY for source tier."""

    def test_produces_b_only_fails(self, validator, db, graph_repo):
        """PRODUCES with B-only new evidence → FAIL."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        raw = _valid_add_edge_gc()
        raw["edge"]["relation"] = "PRODUCES"
        raw["edge"]["assertion_type"] = "FACT"
        raw["new_evidence_ids"] = [_EV_ID]
        raw["edge"]["evidence_ids"] = [_EV_ID]
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) > 0
        assert any(i.code == "INSUFFICIENT_SOURCE_TIER" for i in issues)

    def test_produces_old_s_new_b_fails(self, validator, db, graph_repo):
        """PRODUCES with old S-tier evidence + new B-tier → FAIL (new_evidence_ids only)."""
        ev_id_s = "11111111-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        ev_id_b = "22222222-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, ev_id_s, source_tier="S")
        _insert_evidence(db, ev_id_b, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_raw_item(db, _RI_ID2, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        raw = _valid_add_edge_gc()
        raw["edge"]["relation"] = "PRODUCES"
        raw["edge"]["assertion_type"] = "FACT"
        raw["new_evidence_ids"] = [ev_id_b]  # only B-tier is new
        raw["edge"]["evidence_ids"] = [ev_id_s, ev_id_b]  # both in candidate
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) > 0
        assert any(i.code == "INSUFFICIENT_SOURCE_TIER" for i in issues)

    def test_competes_with_c_only_fails(self, validator, db, graph_repo):
        """COMPETES_WITH with C-only → FAIL (non-structural FACT needs S/A/B)."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="C")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) > 0
        assert any(i.code == "INSUFFICIENT_SOURCE_TIER" for i in issues)

    def test_competes_with_b_passes(self, validator, db, graph_repo):
        """COMPETES_WITH with B-tier → PASS (golden baseline)."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="B")
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        gc = GraphChange(**_valid_add_edge_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-008"]
        assert len(issues) == 0


class TestM4R1KGV014AsOf:
    """KGV-014 actual implementation: as_of checks, future evidence, validity interval."""

    def test_future_evidence_after_as_of(self, validator, db, graph_repo):
        """Evidence.published_at > as_of → EVIDENCE_AFTER_AS_OF."""
        T_future = "2027-01-01T00:00:00"
        _insert_entity(db)
        _insert_evidence(db, published_at=T_future, retrieved_at=T_future)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-014"]
        assert len(issues) > 0
        assert any(i.code == "EVIDENCE_AFTER_AS_OF" for i in issues)

    def test_invalid_as_of_fails(self, validator, db, graph_repo):
        """Invalid as_of → AS_OF_INVALID."""
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, "not-a-date")
        issues = [i for i in result.issues if i.rule_id == "KGV-014"]
        assert len(issues) > 0
        assert any(i.code == "AS_OF_INVALID" for i in issues)

    def test_valid_as_of_passes(self, validator, db, graph_repo):
        """Valid as_of with in-range evidence → passes."""
        _insert_entity(db)
        _insert_evidence(db, published_at=T0, retrieved_at=T1)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-014"]
        assert len(issues) == 0

    def test_validity_interval_invalid(self, validator, db, graph_repo):
        """valid_from > valid_to → INVALID_VALIDITY_INTERVAL."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        raw = _valid_add_node_gc()
        raw["node"]["valid_from"] = T2
        raw["node"]["valid_to"] = T1  # valid_from > valid_to
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T2)
        issues = [i for i in result.issues if i.rule_id == "KGV-014"]
        assert len(issues) > 0
        assert any(i.code == "INVALID_VALIDITY_INTERVAL" for i in issues)


class TestM4R1KGV012ReviewTime:
    """KGV-012 review time checks."""

    def test_reviewed_at_before_created_at(self, validator, db, graph_repo):
        """reviewed_at < created_at → REVIEWED_BEFORE_CREATED."""
        gc = GraphChange(**_valid_add_node_gc())  # created_at = T0
        review = GraphReview(
            review_id=_UUID4,
            graph_change_id=_UUID,
            decision="approved",
            reviewer=GraphReviewer(reviewer_type="human", reviewer_id="reviewer-01"),
            reviewed_at="2025-01-01T00:00:00",  # before T0
            candidate_hash=KnowledgeValidator.compute_candidate_hash(gc),
        )
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.code == "REVIEWED_BEFORE_CREATED"]
        assert len(issues) > 0

    def test_reviewer_not_human(self, validator, db, graph_repo):
        """reviewer_type != human → caught by REVIEW_SCHEMA_INVALID via raw dict normalization."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        # Use raw dict to bypass Pydantic model validation; schema const:"human" catches "system"
        raw_review = {
            "review_id": _UUID4,
            "graph_change_id": gc.graph_change_id,
            "decision": "approved",
            "reviewer": {"reviewer_type": "system", "reviewer_id": "auto", "display_name": None},
            "reviewed_at": T1,
            "candidate_hash": KnowledgeValidator.compute_candidate_hash(gc),
            "review_patch": [],
            "notes": "",
            "resulting_graph_change_id": None,
        }
        result = validator.validate_review(gc, raw_review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-012"
                  and "REVIEW_SCHEMA_INVALID" in i.code]
        assert len(issues) > 0

    def test_reviewer_id_empty(self, validator, db, graph_repo):
        """Empty reviewer_id → caught by REVIEW_SCHEMA_INVALID via raw dict normalization."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        raw_review = {
            "review_id": _UUID4,
            "graph_change_id": gc.graph_change_id,
            "decision": "approved",
            "reviewer": {"reviewer_type": "human", "reviewer_id": "", "display_name": None},
            "reviewed_at": T1,
            "candidate_hash": KnowledgeValidator.compute_candidate_hash(gc),
            "review_patch": [],
            "notes": "",
            "resulting_graph_change_id": None,
        }
        result = validator.validate_review(gc, raw_review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-012"
                  and "REVIEW_SCHEMA_INVALID" in i.code]
        assert len(issues) > 0


class TestM4R1KGV019CanonicalBaseline:
    """KGV-019 uses current_knowledge canonical baseline, runs in validate_review."""

    def test_add_node_not_stale_when_no_existing(self, validator, db, graph_repo):
        """Add node with no existing node → NOT stale."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) == 0

    def test_add_node_stale_when_exists(self, validator, db, graph_repo):
        """Add node where node already exists → STALE_REVIEW_NODE_EXISTS."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:600519.SH")
        gc = GraphChange(**_valid_add_node_gc())
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0
        assert any(i.code == "STALE_REVIEW_NODE_EXISTS" for i in issues)

    def test_add_node_with_matching_current_knowledge_not_stale(self, validator, db, graph_repo):
        """Add node where existing node canonical matches current_knowledge → NOT stale."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        # Create a node and capture its canonical payload
        node = _make_graph_node("company:600519.SH", "Company", "贵州茅台")
        graph_repo.append_node(node)
        # Use current_knowledge as the canonical JSON of the existing node
        ck_payload = node.model_dump()
        raw = _valid_add_node_gc()
        raw["current_knowledge"] = json.dumps(ck_payload, ensure_ascii=False,
                                               sort_keys=True, separators=(",", ":"))
        gc = GraphChange(**raw)
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) == 0

    def test_add_node_baseline_changed_stale(self, validator, db, graph_repo):
        """Add node where baseline changed → STALE_REVIEW."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:600519.SH", name="不同名称")
        raw = _valid_add_node_gc()
        raw["current_knowledge"] = '{"name": "贵州茅台", "different": true}'
        gc = GraphChange(**raw)
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0

    def test_modify_node_stale_baseline(self, validator, db, graph_repo):
        """Modify node where baseline changed → STALE_REVIEW_NODE_CHANGED."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        node = _make_graph_node("company:600519.SH", "Company", "旧名称")
        graph_repo.append_node(node)
        raw = _valid_add_node_gc()
        raw["change_type"] = "modify_attribute"
        raw["node"]["version"] = 2
        # current_knowledge different from persisted
        raw["current_knowledge"] = '{"name": "贵州茅台"}'
        gc = GraphChange(**raw)
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0

    def test_edge_stale_when_exists(self, validator, db, graph_repo):
        """Add edge where triple already exists → STALE_REVIEW_EDGE_EXISTS."""
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db)
        _insert_raw_item(db, _RI_ID, ["company:A", "company:B"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        _insert_edge(graph_repo)
        gc = GraphChange(**_valid_add_edge_gc())
        review = _make_review(gc)
        result = validator.validate_review(gc, review, T1)
        issues = [i for i in result.issues if i.rule_id == "KGV-019"]
        assert len(issues) > 0
        assert any(i.code == "STALE_REVIEW_EDGE_EXISTS" for i in issues)


class TestM4R1Determinism:
    """Determinism: same candidate+DB+as_of → identical result."""

    def test_deterministic_same_input_same_result(self, validator, db, graph_repo):
        """Same input twice → identical issues, same checked_rule_ids."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc1 = GraphChange(**_valid_add_node_gc())
        gc2 = GraphChange(**_valid_add_node_gc())
        result1 = validator.validate_candidate(gc1, T1)
        result2 = validator.validate_candidate(gc2, T1)
        assert result1.structural_ok == result2.structural_ok
        assert result1.review_eligible == result2.review_eligible
        assert result1.apply_eligible == result2.apply_eligible
        assert result1.issues == result2.issues
        assert result1.checked_rule_ids == result2.checked_rule_ids
        assert result1.candidate_hash == result2.candidate_hash

    def test_issues_sorted_by_rule_code_message(self, validator, db, graph_repo):
        """Issues are deterministically sorted by (rule_id, code, message)."""
        # Create a scenario with multiple issues
        _insert_entity(db, "company:A")
        _insert_entity(db, "company:B")
        _insert_evidence(db, source_tier="C")
        _insert_raw_item(db, _RI_ID, ["company:OTHER"])
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")
        raw = _valid_add_edge_gc()
        raw["edge"]["relation"] = "COMPETES_WITH"
        raw["edge"]["assertion_type"] = "FACT"
        gc = GraphChange(**raw)
        result = validator.validate_candidate(gc, T1)
        # Verify sorted
        for i in range(len(result.issues) - 1):
            a = result.issues[i]
            b = result.issues[i + 1]
            assert (a.rule_id, a.code, a.message) <= (b.rule_id, b.code, b.message)

    def test_checked_rule_ids_unique_stable(self, validator, db, graph_repo):
        """checked_rule_ids are unique, sorted, stable."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        gc = GraphChange(**_valid_add_node_gc())
        result = validator.validate_candidate(gc, T1)
        ids = result.checked_rule_ids
        assert len(ids) == len(set(ids))  # unique
        assert list(ids) == sorted(ids)   # sorted
        # Should include all KGV rules
        expected = tuple(
            f"KGV-{n:03d}" for n in [1, 2, 3, 4, 5, 6, 7, 8, 9, 10,
                                      11, 12, 13, 14, 15, 16, 17, 18, 19]
        )
        for e in expected:
            assert e in ids


class TestM4R1ZeroWriteAllTables:
    """Zero-write: no writes to graph_nodes, graph_edges, graph_changes,
    graph_reviews, graph_applications during any validate_* call."""

    def _table_counts(self, db):
        tables = ["graph_nodes", "graph_edges", "graph_changes",
                  "graph_reviews", "graph_applications"]
        counts = {}
        for tbl in tables:
            try:
                row = db._conn.execute(f"SELECT COUNT(*) FROM {tbl}").fetchone()
                counts[tbl] = row[0] if row else 0
            except Exception:
                counts[tbl] = -1
        return counts

    def test_all_validation_stages_zero_writes(self, validator, db, graph_repo):
        """Full cycle: validate_candidate + validate_review + validate_apply_preflight → zero writes."""
        _insert_entity(db)
        _insert_evidence(db)
        _insert_raw_item(db)
        _insert_node(db, graph_repo, "company:A")
        _insert_node(db, graph_repo, "company:B")

        initial = self._table_counts(db)

        gc = GraphChange(**_valid_add_node_gc())
        validator.validate_candidate(gc, T1)

        review = _make_review(gc, decision="approved")
        validator.validate_review(gc, review, T1)
        validator.validate_apply_preflight(gc, review, T1)

        final = self._table_counts(db)

        for tbl, expected in initial.items():
            if expected >= 0:
                assert final[tbl] == expected, (
                    f"Table {tbl}: initial={expected}, final={final[tbl]}"
                )


def _make_graph_node(node_id, node_type, name, status="active",
                     version=1, review_status="approved",
                     origin_kind="graph_change", evidence_ids=None,
                     ogc_id=_UUID3):
    """Helper to create a GraphNode for testing."""
    if evidence_ids is None:
        evidence_ids = [_EV_ID]
    return GraphNode(
        node_id=node_id, node_type=node_type, name=name, status=status,
        version=version, review_status=review_status, origin_kind=origin_kind,
        evidence_ids=evidence_ids,
        originating_graph_change_id=ogc_id if origin_kind == "graph_change" else None,
        created_at=T0,
    )


# ============================================================================
# Helpers
# ============================================================================

def _make_review(gc: GraphChange, decision: str = "approved") -> GraphReview:
    h = KnowledgeValidator.compute_candidate_hash(gc)
    return GraphReview(
        review_id=_UUID4,
        graph_change_id=gc.graph_change_id,
        decision=decision,
        reviewer=GraphReviewer(reviewer_type="human", reviewer_id="reviewer-01"),
        reviewed_at=T1,
        candidate_hash=h,
    )
