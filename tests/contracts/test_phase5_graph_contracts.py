"""Phase 5 M1-R1 Graph Contracts — 攻击性契约测试（Authority-fixed）。

全部测试现在反映 M1 Schema/Pydantic 的 object-internal 机械约束。
M4 只承担需要数据库/Evidence实体/图状态/历史版本的验证。
"""
from __future__ import annotations

import pytest

from research_os.validators.schema_validator import validate_instance
from research_os.models import (
    GraphNode, GraphEdge, GraphChange, GraphChangeProposal, GraphReview,
    GraphPatchValueOperation, GraphPatchRemoveOperation, GraphReviewer,
)


T0 = "2026-08-07T08:00:00"
T1 = "2026-08-07T09:00:00"
_UUID = "11111111-1111-1111-1111-111111111111"
_UUID2 = "22222222-2222-2222-2222-222222222222"
_HASH = "a" * 64


# ============================================================
# GraphNode helpers
# ============================================================
def _gc_node(**kw):
    d = {
        "node_id": "company:600519.SH", "node_type": "Company", "name": "贵州茅台",
        "aliases": [], "description": "", "status": "active",
        "valid_from": None, "valid_to": None, "evidence_ids": ["ev-001"],
        "version": 1, "last_reviewed_at": None, "review_status": "candidate",
        "origin_kind": "graph_change", "originating_graph_change_id": _UUID,
        "created_at": T0,
    }
    d.update(kw)
    return d


def _gov_node(**kw):
    d = {
        "node_id": "industry:AI_hardware", "node_type": "Industry", "name": "AI硬件",
        "aliases": [], "description": "", "status": "active",
        "valid_from": None, "valid_to": None, "evidence_ids": [],
        "version": 1, "last_reviewed_at": None, "review_status": "approved",
        "origin_kind": "governance_seed", "originating_graph_change_id": None,
        "created_at": T0,
    }
    d.update(kw)
    return d


# ============================================================
# GraphNode tests — object-internal constraints
# ============================================================

class TestGraphNode:
    def test_valid_graph_change_node(self):
        assert validate_instance(_gc_node(), "graph_node") == []

    def test_valid_governance_seed(self):
        assert validate_instance(_gov_node(), "graph_node") == []

    def test_unknown_node_type_fails(self):
        n = _gc_node()
        n["node_type"] = "UnknownType"
        assert validate_instance(n, "graph_node")

    def test_company_non_prefix_fails(self):
        n = _gc_node()
        n["node_id"] = "600519.SH"
        assert validate_instance(n, "graph_node")

    def test_version_zero_fails(self):
        n = _gc_node()
        n["version"] = 0
        assert validate_instance(n, "graph_node")

    def test_extra_field_fails(self):
        n = _gc_node()
        n["__extra__"] = "intruder"
        assert validate_instance(n, "graph_node")

    def test_graph_change_empty_evidence_fails(self):
        n = _gc_node()
        n["evidence_ids"] = []
        assert validate_instance(n, "graph_node")

    def test_graph_change_null_origin_id_fails(self):
        n = _gc_node()
        n["originating_graph_change_id"] = None
        errs = validate_instance(n, "graph_node")
        # Schema allOf requires non-null for graph_change
        assert errs, f"graph_change with null origin id should fail: {errs}"

    def test_governance_seed_nonnull_origin_id_fails(self):
        n = _gov_node()
        n["originating_graph_change_id"] = _UUID
        assert validate_instance(n, "graph_node")

    def test_governance_seed_candidate_review_fails(self):
        n = _gov_node()
        n["review_status"] = "candidate"
        assert validate_instance(n, "graph_node")

    def test_governance_seed_nonempty_evidence_fails(self):
        n = _gov_node()
        n["evidence_ids"] = ["ev-001"]
        assert validate_instance(n, "graph_node")

    def test_invalid_datetime_fails(self):
        n = _gc_node()
        n["created_at"] = "not-a-date"
        assert validate_instance(n, "graph_node")

    def test_omitted_created_at_fails(self):
        n = _gc_node()
        del n["created_at"]
        assert validate_instance(n, "graph_node")

    def test_pydantic_company_prefix_validator(self):
        """Pydantic rejects Company without company: prefix."""
        with pytest.raises(Exception):
            GraphNode(node_id="600519.SH", node_type="Company", name="x", created_at=T0)

    def test_pydantic_graph_change_empty_evidence_allowed_at_construct(self):
        """Pydantic allows construction; Schema rejects at dump."""
        m = GraphNode(node_id="company:X", node_type="Company", name="x",
                       origin_kind="graph_change", originating_graph_change_id=_UUID,
                       evidence_ids=[], created_at=T0)
        errs = validate_instance(m.model_dump(), "graph_node")
        assert errs

    def test_pydantic_governance_seed_candidate_fails_schema(self):
        m = GraphNode(node_id="industry:X", node_type="Industry", name="x",
                       origin_kind="governance_seed", originating_graph_change_id=None,
                       evidence_ids=[], review_status="candidate", created_at=T0)
        errs = validate_instance(m.model_dump(), "graph_node")
        assert errs


# ============================================================
# GraphEdge helpers
# ============================================================
def _gc_edge(**kw):
    d = {
        "edge_id": "edge-001", "source_node_id": "company:A",
        "relation": "SUPPLIES", "target_node_id": "company:B",
        "attributes": {}, "assertion_type": "FACT",
        "valid_from": None, "valid_to": None, "confidence": 0.8,
        "evidence_ids": ["ev-001"], "review_status": "candidate",
        "version": 1, "originating_graph_change_id": _UUID,
        "created_at": T0, "last_reviewed_at": None,
    }
    d.update(kw)
    return d


def _gov_edge(**kw):
    d = {
        "edge_id": "edge-gov", "source_node_id": "industry:A",
        "relation": "BELONGS_TO", "target_node_id": "industry:B",
        "attributes": {}, "assertion_type": "GOVERNANCE",
        "valid_from": None, "valid_to": None, "confidence": 1.0,
        "evidence_ids": [], "review_status": "approved",
        "version": 1, "originating_graph_change_id": None,
        "created_at": T0, "last_reviewed_at": None,
    }
    d.update(kw)
    return d


# ============================================================
# GraphEdge tests
# ============================================================

class TestGraphEdge:
    def test_valid_fact_candidate(self):
        assert validate_instance(_gc_edge(), "graph_edge") == []

    def test_valid_governance_approved(self):
        assert validate_instance(_gov_edge(), "graph_edge") == []

    def test_unknown_relation_fails(self):
        e = _gc_edge()
        e["relation"] = "UNKNOWN_REL"
        assert validate_instance(e, "graph_edge")

    def test_unknown_assertion_type_fails(self):
        e = _gc_edge()
        e["assertion_type"] = "OPINION"
        assert validate_instance(e, "graph_edge")

    def test_confidence_below_zero_fails(self):
        e = _gc_edge()
        e["confidence"] = -0.1
        assert validate_instance(e, "graph_edge")

    def test_confidence_above_one_fails(self):
        e = _gc_edge()
        e["confidence"] = 1.1
        assert validate_instance(e, "graph_edge")

    def test_fact_empty_evidence_fails(self):
        e = _gc_edge()
        e["evidence_ids"] = []
        assert validate_instance(e, "graph_edge")

    def test_model_inference_empty_evidence_fails(self):
        e = _gc_edge()
        e["assertion_type"] = "MODEL_INFERENCE"
        e["evidence_ids"] = []
        assert validate_instance(e, "graph_edge")

    def test_fact_null_origin_id_fails(self):
        e = _gc_edge()
        e["originating_graph_change_id"] = None
        assert validate_instance(e, "graph_edge")

    def test_governance_nonnull_origin_id_fails(self):
        e = _gov_edge()
        e["originating_graph_change_id"] = _UUID
        assert validate_instance(e, "graph_edge")

    def test_governance_candidate_review_fails(self):
        e = _gov_edge()
        e["review_status"] = "candidate"
        assert validate_instance(e, "graph_edge")

    def test_governance_nonempty_evidence_fails(self):
        e = _gov_edge()
        e["evidence_ids"] = ["ev-001"]
        assert validate_instance(e, "graph_edge")

    def test_extra_field_fails(self):
        e = _gc_edge()
        e["__extra__"] = "intruder"
        assert validate_instance(e, "graph_edge")

    def test_omitted_created_at_fails(self):
        e = _gc_edge()
        del e["created_at"]
        assert validate_instance(e, "graph_edge")

    def test_pydantic_omitted_created_at_rejected(self):
        with pytest.raises(Exception):
            GraphEdge(edge_id="e", source_node_id="A", relation="SUPPLIES",
                      target_node_id="B")


# ============================================================
# GraphChange tests
# ============================================================

class TestGraphChange:
    def _valid_add_node(self):
        return {
            "graph_change_id": _UUID, "change_type": "add_node",
            "node": _gc_node(), "edge": None,
            "current_knowledge": "", "new_evidence_ids": ["ev-001"],
            "suggested_change": "add", "impact_scope": [], "conflicts": [],
            "verification_points": [], "review_status": "candidate",
            "created_at": T0, "reviewed_at": None,
        }

    def _valid_add_edge(self):
        return {
            "graph_change_id": _UUID, "change_type": "add_edge",
            "node": None, "edge": _gc_edge(),
            "current_knowledge": "", "new_evidence_ids": ["ev-001"],
            "suggested_change": "add", "impact_scope": [], "conflicts": [],
            "verification_points": [], "review_status": "candidate",
            "created_at": T0, "reviewed_at": None,
        }

    def test_add_node_valid(self):
        assert validate_instance(self._valid_add_node(), "graph_change") == []

    def test_add_node_edge_populated_fails(self):
        gc = self._valid_add_node()
        gc["edge"] = _gc_edge()
        assert validate_instance(gc, "graph_change")

    def test_add_node_node_null_fails(self):
        gc = self._valid_add_node()
        gc["node"] = None
        assert validate_instance(gc, "graph_change")

    def test_add_edge_valid(self):
        assert validate_instance(self._valid_add_edge(), "graph_change") == []

    def test_add_edge_node_populated_fails(self):
        gc = self._valid_add_edge()
        gc["node"] = _gc_node()
        assert validate_instance(gc, "graph_change")

    def test_modify_attribute_both_populated_fails(self):
        gc = self._valid_add_node()
        gc["change_type"] = "modify_attribute"
        gc["edge"] = _gc_edge()
        assert validate_instance(gc, "graph_change")

    def test_modify_attribute_both_null_fails(self):
        gc = self._valid_add_node()
        gc["change_type"] = "modify_attribute"
        gc["node"] = None
        assert validate_instance(gc, "graph_change")

    def test_governance_edge_in_graphchange_fails(self):
        gc = self._valid_add_edge()
        gc["edge"]["assertion_type"] = "GOVERNANCE"
        assert validate_instance(gc, "graph_change")

    def test_candidate_reviewed_at_non_null_fails(self):
        gc = self._valid_add_node()
        gc["reviewed_at"] = T0
        assert validate_instance(gc, "graph_change")

    def test_non_candidate_reviewed_at_null_fails(self):
        gc = self._valid_add_node()
        gc["review_status"] = "approved"
        assert validate_instance(gc, "graph_change")

    def test_empty_new_evidence_ids_fails(self):
        gc = self._valid_add_node()
        gc["new_evidence_ids"] = []
        assert validate_instance(gc, "graph_change")

    def test_pydantic_typed_fields(self):
        """Pydantic requires typed GraphNode/GraphEdge, not dict."""
        from research_os.models import GraphChange as GC
        with pytest.raises(Exception):
            GC(graph_change_id=_UUID, change_type="add_node",
               node={"node_id": "x"}, created_at=T0, suggested_change="s")
        # GraphNode construction passes
        gn = GraphNode(node_id="company:X", node_type="Company", name="x",
                        created_at=T0, origin_kind="graph_change",
                        originating_graph_change_id=_UUID, evidence_ids=["ev-001"])
        gc = GC(graph_change_id=_UUID, change_type="add_node",
                node=gn, suggested_change="s", created_at=T0)
        assert gc.node is not None

    def test_pydantic_change_type_consistency(self):
        """add_node with edge populated rejected by Pydantic."""
        from research_os.models import GraphChange as GC
        gn = GraphNode(node_id="company:X", node_type="Company", name="x",
                        created_at=T0, origin_kind="graph_change",
                        originating_graph_change_id=_UUID, evidence_ids=["ev-001"])
        ge = GraphEdge(edge_id="e", source_node_id="A", relation="SUPPLIES",
                       target_node_id="B", created_at=T0)
        with pytest.raises(Exception):
            GC(graph_change_id=_UUID, change_type="add_node",
               node=gn, edge=ge, suggested_change="s", created_at=T0)


# ============================================================
# GraphChangeProposal tests
# ============================================================

class TestGraphChangeProposal:
    def _add_node(self):
        return {
            "proposal_type": "add_node", "source_object_ids": ["obj-001"],
            "candidate_node": {"existing_node_id": None, "node_type": "Company",
                               "name": "新公司", "aliases": [], "description": "",
                               "valid_from": None, "valid_to": None},
            "candidate_edge": None, "new_evidence_ids": ["ev-001"],
            "suggested_change": "add", "impact_scope": [], "conflicts": [],
            "verification_points": [], "confidence": 0.5,
        }

    def _add_edge(self):
        return {
            "proposal_type": "add_edge", "source_object_ids": ["obj-001"],
            "candidate_node": None,
            "candidate_edge": {"source_node_id": "A", "relation": "SUPPLIES",
                               "target_node_id": "B", "attributes": {},
                               "assertion_type": "FACT", "valid_from": None,
                               "valid_to": None, "confidence": 0.7},
            "new_evidence_ids": ["ev-001"],
            "suggested_change": "add", "impact_scope": [], "conflicts": [],
            "verification_points": [], "confidence": 0.5,
        }

    def test_legal_add_node(self):
        assert validate_instance(self._add_node(), "graph_change_proposal") == []

    def test_legal_add_edge(self):
        assert validate_instance(self._add_edge(), "graph_change_proposal") == []

    def test_add_node_existing_node_id_not_null_fails(self):
        p = self._add_node()
        p["candidate_node"]["existing_node_id"] = "company:X"
        assert validate_instance(p, "graph_change_proposal")

    def test_add_node_edge_not_null_fails(self):
        p = self._add_node()
        p["candidate_edge"] = p["_add_edge"] if False else self._add_edge()["candidate_edge"]
        assert validate_instance(p, "graph_change_proposal")

    def test_retire_node_existing_node_id_null_fails(self):
        p = self._add_node()
        p["proposal_type"] = "retire_node"
        assert validate_instance(p, "graph_change_proposal")

    def test_add_edge_node_not_null_fails(self):
        p = self._add_edge()
        p["candidate_node"] = self._add_node()["candidate_node"]
        assert validate_instance(p, "graph_change_proposal")

    def test_proposal_contains_graph_change_id_fails(self):
        p = self._add_node()
        p["graph_change_id"] = _UUID
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_node_contains_node_id_fails(self):
        p = self._add_node()
        p["candidate_node"]["node_id"] = "company:X"
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_edge_contains_edge_id_fails(self):
        p = self._add_edge()
        p["candidate_edge"]["edge_id"] = "edge-X"
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_contains_version_fails(self):
        p = self._add_node()
        p["candidate_node"]["version"] = 1
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_contains_review_status_fails(self):
        p = self._add_node()
        p["candidate_node"]["review_status"] = "approved"
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_contains_created_at_fails(self):
        p = self._add_node()
        p["candidate_node"]["created_at"] = T0
        assert validate_instance(p, "graph_change_proposal")

    def test_candidate_edge_governance_fails(self):
        p = self._add_edge()
        p["candidate_edge"]["assertion_type"] = "GOVERNANCE"
        assert validate_instance(p, "graph_change_proposal")

    def test_empty_source_object_ids_fails(self):
        p = self._add_node()
        p["source_object_ids"] = []
        assert validate_instance(p, "graph_change_proposal")

    def test_empty_new_evidence_ids_fails(self):
        p = self._add_node()
        p["new_evidence_ids"] = []
        assert validate_instance(p, "graph_change_proposal")

    def test_modify_attribute_both_null_fails(self):
        p = {"proposal_type": "modify_attribute", "source_object_ids": ["obj"],
             "candidate_node": None, "candidate_edge": None,
             "new_evidence_ids": ["ev"], "suggested_change": "x",
             "impact_scope": [], "conflicts": [], "verification_points": [],
             "confidence": 0.5}
        assert validate_instance(p, "graph_change_proposal")

    def test_modify_attribute_node_missing_existing_id_fails(self):
        p = {"proposal_type": "modify_attribute", "source_object_ids": ["obj"],
             "candidate_node": {"existing_node_id": None, "node_type": "Company",
                                "name": "x", "aliases": [], "description": "",
                                "valid_from": None, "valid_to": None},
             "candidate_edge": None, "new_evidence_ids": ["ev"],
             "suggested_change": "x", "impact_scope": [], "conflicts": [],
             "verification_points": [], "confidence": 0.5}
        assert validate_instance(p, "graph_change_proposal")

    def test_extra_field_fails(self):
        p = self._add_node()
        p["__extra__"] = "intruder"
        assert validate_instance(p, "graph_change_proposal")

    def test_pydantic_add_node_payload(self):
        from research_os.models import GraphChangeProposal as GCP, GraphProposalNode
        cn = GraphProposalNode(existing_node_id=None, node_type="Company", name="x")
        p = GCP(proposal_type="add_node", source_object_ids=["o"],
                candidate_node=cn, new_evidence_ids=["ev"],
                suggested_change="x")
        assert p.candidate_node.existing_node_id is None

    def test_pydantic_add_node_edge_populated_rejected(self):
        from research_os.models import GraphChangeProposal as GCP, GraphProposalNode, GraphProposalEdge
        cn = GraphProposalNode(existing_node_id=None, node_type="Company", name="x")
        ce = GraphProposalEdge(source_node_id="A", relation="SUPPLIES", target_node_id="B")
        with pytest.raises(Exception):
            GCP(proposal_type="add_node", source_object_ids=["o"],
                candidate_node=cn, candidate_edge=ce,
                new_evidence_ids=["ev"], suggested_change="x")


# ============================================================
# GraphReview tests
# ============================================================

class TestGraphReview:
    def _base(self):
        return {
            "review_id": _UUID, "graph_change_id": _UUID2,
            "decision": "approved",
            "reviewer": {"reviewer_type": "human", "reviewer_id": "u1",
                         "display_name": "Test User"},
            "reviewed_at": T1, "candidate_hash": _HASH,
            "review_patch": [], "notes": "",
            "resulting_graph_change_id": None,
        }

    def test_approved_valid(self):
        assert validate_instance(self._base(), "graph_review") == []

    def test_approved_with_changes_valid(self):
        r = self._base()
        r["decision"] = "approved_with_changes"
        r["review_patch"] = [{"op": "replace", "path": "/suggested_change", "value": "x"}]
        r["resulting_graph_change_id"] = _UUID2
        assert validate_instance(r, "graph_review") == []

    def test_approved_with_changes_empty_patch_fails(self):
        r = self._base()
        r["decision"] = "approved_with_changes"
        r["resulting_graph_change_id"] = _UUID2
        assert validate_instance(r, "graph_review")

    def test_approved_with_changes_null_resulting_id_fails(self):
        r = self._base()
        r["decision"] = "approved_with_changes"
        r["review_patch"] = [{"op": "replace", "path": "/suggested_change", "value": "x"}]
        assert validate_instance(r, "graph_review")

    def test_approved_nonempty_patch_fails(self):
        r = self._base()
        r["review_patch"] = [{"op": "replace", "path": "/suggested_change", "value": "x"}]
        assert validate_instance(r, "graph_review")

    def test_approved_resulting_id_fails(self):
        r = self._base()
        r["resulting_graph_change_id"] = _UUID2
        assert validate_instance(r, "graph_review")

    def test_deferred_patch_fails(self):
        r = self._base()
        r["decision"] = "deferred"
        r["review_patch"] = [{"op": "replace", "path": "/suggested_change", "value": "x"}]
        assert validate_instance(r, "graph_review")

    def test_rejected_resulting_id_fails(self):
        r = self._base()
        r["decision"] = "rejected"
        r["resulting_graph_change_id"] = _UUID2
        assert validate_instance(r, "graph_review")

    def test_reviewer_not_human_fails(self):
        r = self._base()
        r["reviewer"]["reviewer_type"] = "llm"
        assert validate_instance(r, "graph_review")

    def test_missing_reviewer_id_fails(self):
        r = self._base()
        del r["reviewer"]["reviewer_id"]
        assert validate_instance(r, "graph_review")

    def test_missing_display_name_fails(self):
        r = self._base()
        del r["reviewer"]["display_name"]
        assert validate_instance(r, "graph_review")

    def test_candidate_hash_malformed_fails(self):
        r = self._base()
        r["candidate_hash"] = "not-a-hash"
        assert validate_instance(r, "graph_review")

    def test_patch_attempts_graph_change_id_fails(self):
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace", path="/graph_change_id", value="x")

    def test_patch_attempts_node_node_id_fails(self):
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace", path="/node/node_id", value="x")

    def test_patch_attempts_edge_relation_fails(self):
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace", path="/edge/relation", value="x")

    def test_patch_allowed_path_suggested_change(self):
        r = _make_review_with_patch("approved_with_changes", "/suggested_change")
        assert validate_instance(r, "graph_review") == []

    def test_patch_allowed_path_node_name(self):
        r = _make_review_with_patch("approved_with_changes", "/node/name")
        assert validate_instance(r, "graph_review") == []

    def test_patch_allowed_subpath(self):
        r = _make_review_with_patch("approved_with_changes", "/node/evidence_ids/0")
        assert validate_instance(r, "graph_review") == []

    def test_patch_disallowed_subpath(self):
        # /edge/relation/sub is not allowed (relation is forbidden base)
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace", path="/edge/relation/sub", value="x")

    def test_patch_operation_unknown_fails(self):
        r = self._base()
        r["review_patch"] = [{"op": "move", "path": "/suggested_change", "from": "/x"}]
        assert validate_instance(r, "graph_review")

    def test_patch_operation_extra_field_fails(self):
        r = self._base()
        r["review_patch"] = [{"op": "replace", "path": "/suggested_change", "value": "x", "__extra__": 1}]
        assert validate_instance(r, "graph_review")

    def test_graph_review_extra_top_field_fails(self):
        r = self._base()
        r["__extra__"] = "intruder"
        assert validate_instance(r, "graph_review")

    def test_pydantic_remove_patch_parity(self):
        """remove operation model_dump 不含 value 键，Schema 验证通过。"""
        r = GraphReview(
            review_id=_UUID, graph_change_id=_UUID2,
            decision="approved_with_changes",
            reviewer=GraphReviewer(reviewer_id="u1", display_name="Test"),
            reviewed_at=T1, candidate_hash=_HASH,
            review_patch=[GraphPatchRemoveOperation(op="remove", path="/node/description")],
            resulting_graph_change_id=_UUID2,
        )
        dump = r.model_dump()
        errs = validate_instance(dump, "graph_review")
        assert errs == [], errs

    def test_pydantic_decision_consistency(self):
        """Pydantic rejects approved_with_changes without patch."""
        with pytest.raises(Exception):
            GraphReview(review_id=_UUID, graph_change_id=_UUID2,
                        decision="approved_with_changes",
                        reviewer=GraphReviewer(reviewer_id="u1", display_name="Test"),
                        reviewed_at=T1, candidate_hash=_HASH,
                        review_patch=[])


def _make_review_with_patch(decision, path):
    return {
        "review_id": _UUID, "graph_change_id": _UUID2,
        "decision": decision,
        "reviewer": {"reviewer_type": "human", "reviewer_id": "u1",
                     "display_name": "Test"},
        "reviewed_at": T1, "candidate_hash": _HASH,
        "review_patch": [{"op": "replace", "path": path, "value": "x"}],
        "notes": "", "resulting_graph_change_id": _UUID2,
    }
