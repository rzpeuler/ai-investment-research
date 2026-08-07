"""Phase 5 M1-R2 Graph Contracts — $ref reuse + registry + full parity."""
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

# === helpers ===

def _node(**kw):
    d = {"node_id":"company:X","node_type":"Company","name":"x","aliases":[],"description":"","status":"active",
         "valid_from":None,"valid_to":None,"evidence_ids":["ev-001"],"version":1,"last_reviewed_at":None,
         "review_status":"candidate","origin_kind":"graph_change","originating_graph_change_id":_UUID,"created_at":T0}
    d.update(kw); return d

def _gov_node(**kw):
    d = {"node_id":"industry:X","node_type":"Industry","name":"x","aliases":[],"description":"","status":"active",
         "valid_from":None,"valid_to":None,"evidence_ids":[],"version":1,"last_reviewed_at":None,
         "review_status":"approved","origin_kind":"governance_seed","originating_graph_change_id":None,"created_at":T0}
    d.update(kw); return d

def _edge(**kw):
    d = {"edge_id":"e1","source_node_id":"A","relation":"SUPPLIES","target_node_id":"B","attributes":{},
         "assertion_type":"FACT","valid_from":None,"valid_to":None,"confidence":0.8,
         "evidence_ids":["ev-001"],"review_status":"candidate","version":1,
         "originating_graph_change_id":_UUID,"created_at":T0,"last_reviewed_at":None}
    d.update(kw); return d

def _gov_edge(**kw):
    d = {"edge_id":"ge1","source_node_id":"A","relation":"BELONGS_TO","target_node_id":"B","attributes":{},
         "assertion_type":"GOVERNANCE","valid_from":None,"valid_to":None,"confidence":1.0,
         "evidence_ids":[],"review_status":"approved","version":1,
         "originating_graph_change_id":None,"created_at":T0,"last_reviewed_at":None}
    d.update(kw); return d

def _gc(**kw):
    d = {"graph_change_id":_UUID,"change_type":"add_node","node":_node(),"edge":None,
         "current_knowledge":"","new_evidence_ids":["ev-001"],"suggested_change":"x",
         "impact_scope":[],"conflicts":[],"verification_points":[],"review_status":"candidate",
         "created_at":T0,"reviewed_at":None}
    d.update(kw); return d

def _review(**kw):
    d = {"review_id":_UUID,"graph_change_id":_UUID2,"decision":"approved",
         "reviewer":{"reviewer_type":"human","reviewer_id":"u1","display_name":"T"},
         "reviewed_at":T1,"candidate_hash":_HASH,"review_patch":[],"notes":"",
         "resulting_graph_change_id":None}
    d.update(kw); return d


# ============================================================
# A: $ref reuse + drift tests
# ============================================================

class TestRefReuse:
    def test_graphchange_ref_resolves_valid(self):
        assert validate_instance(_gc(), "graph_change") == []

    def test_standalone_bad_company_fails(self):
        assert validate_instance(_node(node_id="bad"), "graph_node")

    def test_embedded_bad_company_fails(self):
        """$ref drift: bad company prefix must also fail inside GraphChange."""
        gc = _gc(node=_node(node_id="bad"))
        assert validate_instance(gc, "graph_change")

    def test_standalone_empty_evidence_fails(self):
        assert validate_instance(_node(evidence_ids=[]), "graph_node")

    def test_embedded_empty_evidence_fails(self):
        """$ref drift: empty evidence inside GraphChange.node must fail."""
        gc = _gc(node=_node(evidence_ids=[]))
        assert validate_instance(gc, "graph_change")

    def test_standalone_none_origin_id_fails(self):
        assert validate_instance(_node(originating_graph_change_id=None), "graph_node")

    def test_embedded_none_origin_id_fails(self):
        gc = _gc(node=_node(originating_graph_change_id=None))
        assert validate_instance(gc, "graph_change")


# ============================================================
# GraphNode + GraphEdge parity
# ============================================================

class TestNodeParity:
    def test_graph_change_empty_evidence_rejects(self):
        with pytest.raises(Exception):
            GraphNode(node_id="company:X",node_type="Company",name="x",created_at=T0,
                       origin_kind="graph_change",originating_graph_change_id=_UUID,evidence_ids=[])

    def test_governance_seed_candidate_rejects(self):
        with pytest.raises(Exception):
            GraphNode(node_id="industry:X",node_type="Industry",name="x",created_at=T0,
                       origin_kind="governance_seed",originating_graph_change_id=None,
                       evidence_ids=[],review_status="candidate")

    def test_governance_seed_with_evidence_rejects(self):
        with pytest.raises(Exception):
            GraphNode(node_id="industry:X",node_type="Industry",name="x",created_at=T0,
                       origin_kind="governance_seed",originating_graph_change_id=None,
                       evidence_ids=["ev"],review_status="approved")

    def test_governance_seed_with_origin_id_rejects(self):
        with pytest.raises(Exception):
            GraphNode(node_id="industry:X",node_type="Industry",name="x",created_at=T0,
                       origin_kind="governance_seed",originating_graph_change_id=_UUID,
                       evidence_ids=[],review_status="approved")

    def test_valid_governance_seed(self):
        n = GraphNode(node_id="industry:X",node_type="Industry",name="x",created_at=T0,
                       origin_kind="governance_seed",originating_graph_change_id=None,
                       evidence_ids=[],review_status="approved")
        assert validate_instance(n.model_dump(), "graph_node") == []

    def test_valid_graph_change_node(self):
        n = GraphNode(node_id="company:X",node_type="Company",name="x",created_at=T0,
                       origin_kind="graph_change",originating_graph_change_id=_UUID,evidence_ids=["ev"])
        assert validate_instance(n.model_dump(), "graph_node") == []


class TestEdgeParity:
    def test_fact_empty_evidence_rejects(self):
        with pytest.raises(Exception):
            GraphEdge(edge_id="e",source_node_id="A",relation="SUPPLIES",target_node_id="B",
                       created_at=T0,originating_graph_change_id=_UUID,evidence_ids=[])

    def test_fact_none_origin_id_rejects(self):
        with pytest.raises(Exception):
            GraphEdge(edge_id="e",source_node_id="A",relation="SUPPLIES",target_node_id="B",
                       created_at=T0,originating_graph_change_id=None,evidence_ids=["ev"])

    def test_governance_with_evidence_rejects(self):
        with pytest.raises(Exception):
            GraphEdge(edge_id="e",source_node_id="A",relation="BELONGS_TO",target_node_id="B",
                       created_at=T0,assertion_type="GOVERNANCE",
                       originating_graph_change_id=None,evidence_ids=["ev"],review_status="approved")

    def test_governance_candidate_rejects(self):
        with pytest.raises(Exception):
            GraphEdge(edge_id="e",source_node_id="A",relation="BELONGS_TO",target_node_id="B",
                       created_at=T0,assertion_type="GOVERNANCE",
                       originating_graph_change_id=None,evidence_ids=[],review_status="candidate")

    def test_valid_governance_edge(self):
        e = GraphEdge(edge_id="e",source_node_id="A",relation="BELONGS_TO",target_node_id="B",
                       created_at=T0,assertion_type="GOVERNANCE",
                       originating_graph_change_id=None,evidence_ids=[],review_status="approved")
        assert validate_instance(e.model_dump(), "graph_edge") == []


# ============================================================
# GraphChange
# ============================================================

class TestGraphChange:
    def test_valid(self):
        assert validate_instance(_gc(), "graph_change") == []

    def test_empty_evidence_ids_rejects(self):
        assert validate_instance(_gc(new_evidence_ids=[]), "graph_change")

    def test_add_node_edge_populated_fails(self):
        gc = _gc(edge=_edge())
        assert validate_instance(gc, "graph_change")

    def test_add_node_node_null_fails(self):
        assert validate_instance(_gc(node=None), "graph_change")

    def test_add_edge_valid(self):
        gc = {"graph_change_id":_UUID,"change_type":"add_edge","node":None,"edge":_edge(),
              "current_knowledge":"","new_evidence_ids":["ev-001"],"suggested_change":"x",
              "impact_scope":[],"conflicts":[],"verification_points":[],
              "review_status":"candidate","created_at":T0,"reviewed_at":None}
        assert validate_instance(gc, "graph_change") == []

    def test_modify_attribute_both_populated_fails(self):
        gc = _gc(change_type="modify_attribute",edge=_edge())
        assert validate_instance(gc, "graph_change")

    def test_modify_attribute_both_null_fails(self):
        gc = _gc(change_type="modify_attribute",node=None)
        assert validate_instance(gc, "graph_change")

    def test_governance_edge_in_graphchange_fails(self):
        gc = {"graph_change_id":_UUID,"change_type":"add_edge","node":None,"edge":_edge(assertion_type="GOVERNANCE"),
              "current_knowledge":"","new_evidence_ids":["ev-001"],"suggested_change":"x",
              "impact_scope":[],"conflicts":[],"verification_points":[],
              "review_status":"candidate","created_at":T0,"reviewed_at":None}
        assert validate_instance(gc, "graph_change")

    def test_pydantic_empty_evidence_rejects(self):
        gn = GraphNode(node_id="company:X",node_type="Company",name="x",created_at=T0,
                        origin_kind="graph_change",originating_graph_change_id=_UUID,evidence_ids=["ev"])
        with pytest.raises(Exception):
            GraphChange(graph_change_id=_UUID,change_type="add_node",node=gn,
                         suggested_change="x",created_at=T0,new_evidence_ids=[])

    def test_pydantic_typed_fields(self):
        gn = GraphNode(node_id="company:X",node_type="Company",name="x",created_at=T0,
                        origin_kind="graph_change",originating_graph_change_id=_UUID,evidence_ids=["ev"])
        gc = GraphChange(graph_change_id=_UUID,change_type="add_node",node=gn,
                          suggested_change="x",created_at=T0,new_evidence_ids=["ev"])
        assert gc.node is not None


# ============================================================
# GraphChangeProposal
# ============================================================

class TestProposal:
    def _an(self): return {"proposal_type":"add_node","source_object_ids":["o"],"candidate_node":{"existing_node_id":None,"node_type":"Company","name":"x","aliases":[],"description":"","valid_from":None,"valid_to":None},"candidate_edge":None,"new_evidence_ids":["ev"],"suggested_change":"x","impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
    def _rn(self): return {"proposal_type":"retire_node","source_object_ids":["o"],"candidate_node":{"existing_node_id":"company:X","node_type":"Company","name":"x","aliases":[],"description":"","valid_from":None,"valid_to":None},"candidate_edge":None,"new_evidence_ids":["ev"],"suggested_change":"x","impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
    def _ae(self): return {"proposal_type":"add_edge","source_object_ids":["o"],"candidate_node":None,"candidate_edge":{"source_node_id":"A","relation":"SUPPLIES","target_node_id":"B","attributes":{},"assertion_type":"FACT","valid_from":None,"valid_to":None,"confidence":0.5},"new_evidence_ids":["ev"],"suggested_change":"x","impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}

    def test_add_node_valid(self): assert validate_instance(self._an(),"graph_change_proposal")==[]
    def test_retire_node_valid(self): assert validate_instance(self._rn(),"graph_change_proposal")==[]
    def test_add_edge_valid(self): assert validate_instance(self._ae(),"graph_change_proposal")==[]

    def test_retire_node_existing_null_fails(self):
        p = self._rn(); p["candidate_node"]["existing_node_id"]=None
        assert validate_instance(p,"graph_change_proposal")

    def test_retire_node_edge_populated_fails(self):
        p = self._rn(); p["candidate_edge"]=self._ae()["candidate_edge"]
        assert validate_instance(p,"graph_change_proposal")

    def test_modify_attribute_node_valid(self):
        p = {"proposal_type":"modify_attribute","source_object_ids":["o"],
             "candidate_node":{"existing_node_id":"company:X","node_type":"Company","name":"x","aliases":[],"description":"","valid_from":None,"valid_to":None},
             "candidate_edge":None,"new_evidence_ids":["ev"],"suggested_change":"x",
             "impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
        assert validate_instance(p,"graph_change_proposal")==[]

    def test_modify_attribute_edge_valid(self):
        p = {"proposal_type":"modify_attribute","source_object_ids":["o"],
             "candidate_node":None,
             "candidate_edge":{"source_node_id":"A","relation":"SUPPLIES","target_node_id":"B","attributes":{},"assertion_type":"FACT","valid_from":None,"valid_to":None,"confidence":0.5},
             "new_evidence_ids":["ev"],"suggested_change":"x",
             "impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
        assert validate_instance(p,"graph_change_proposal")==[]

    def test_modify_attribute_both_null_fails(self):
        p = {"proposal_type":"modify_attribute","source_object_ids":["o"],
             "candidate_node":None,"candidate_edge":None,
             "new_evidence_ids":["ev"],"suggested_change":"x",
             "impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
        assert validate_instance(p,"graph_change_proposal")

    def test_modify_attribute_both_populated_fails(self):
        p = {"proposal_type":"modify_attribute","source_object_ids":["o"],
             "candidate_node":{"existing_node_id":"company:X","node_type":"Company","name":"x","aliases":[],"description":"","valid_from":None,"valid_to":None},
             "candidate_edge":{"source_node_id":"A","relation":"SUPPLIES","target_node_id":"B","attributes":{},"assertion_type":"FACT","valid_from":None,"valid_to":None,"confidence":0.5},
             "new_evidence_ids":["ev"],"suggested_change":"x",
             "impact_scope":[],"conflicts":[],"verification_points":[],"confidence":0.5}
        assert validate_instance(p,"graph_change_proposal")

    def test_forbidden_fields(self):
        p = self._an(); p["graph_change_id"]=_UUID
        assert validate_instance(p,"graph_change_proposal")


# ============================================================
# GraphReview + patch path whitelist (raw dict + Pydantic)
# ============================================================

class TestReview:
    def test_approved_valid(self): assert validate_instance(_review(),"graph_review")==[]

    def test_approved_nonempty_patch_fails(self):
        r = _review(review_patch=[{"op":"replace","path":"/suggested_change","value":"x"}])
        assert validate_instance(r,"graph_review")

    def test_approved_with_changes_valid(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/suggested_change","value":"x"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")==[]

    def test_approved_with_changes_empty_patch_fails(self):
        r = _review(decision="approved_with_changes",resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")

    def test_approved_with_changes_null_result_fails(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/suggested_change","value":"x"}])
        assert validate_instance(r,"graph_review")

    def test_deferred_patch_fails(self):
        r = _review(decision="deferred",review_patch=[{"op":"replace","path":"/suggested_change","value":"x"}])
        assert validate_instance(r,"graph_review")

    def test_rejected_result_id_fails(self):
        r = _review(decision="rejected",resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")

    # Raw dict patch path whitelist tests
    def test_raw_dict_forbidden_path_graph_change_id(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/graph_change_id","value":"x"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")

    def test_raw_dict_forbidden_path_node_node_id(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/node/node_id","value":"x"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")

    def test_raw_dict_forbidden_path_edge_relation(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/edge/relation","value":"BELONGS_TO"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")

    def test_raw_dict_allowed_path(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/node/name","value":"new"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")==[]

    def test_raw_dict_allowed_subpath(self):
        r = _review(decision="approved_with_changes",
                     review_patch=[{"op":"replace","path":"/node/evidence_ids/0","value":"ev"}],
                     resulting_graph_change_id=_UUID2)
        assert validate_instance(r,"graph_review")==[]

    # Pydantic patch path
    def test_pydantic_forbidden_path_rejects(self):
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace",path="/graph_change_id",value="x")

    def test_pydantic_allowed_path(self):
        op = GraphPatchValueOperation(op="replace",path="/node/name",value="new")
        assert op.path == "/node/name"

    # Patch value required
    def test_value_omitted_rejects(self):
        with pytest.raises(Exception):
            GraphPatchValueOperation(op="replace",path="/suggested_change")

    def test_value_explicit_none_passes(self):
        op = GraphPatchValueOperation(op="replace",path="/suggested_change",value=None)
        dump = op.model_dump()
        assert "value" in dump

    def test_remove_no_value_key(self):
        op = GraphPatchRemoveOperation(op="remove",path="/node/description")
        dump = op.model_dump()
        assert "value" not in dump
        # Schema should also validate (via GraphReview)
        r = GraphReview(review_id=_UUID,graph_change_id=_UUID2,decision="approved_with_changes",
                         reviewer=GraphReviewer(reviewer_id="u1",display_name="T"),
                         reviewed_at=T1,candidate_hash=_HASH,
                         review_patch=[op],resulting_graph_change_id=_UUID2)
        assert validate_instance(r.model_dump(),"graph_review")==[]

    # Reviewer
    def test_missing_display_name_fails(self):
        r = _review(); del r["reviewer"]["display_name"]
        assert validate_instance(r,"graph_review")

    def test_non_human_reviewer_fails(self):
        r = _review(); r["reviewer"]["reviewer_type"]="llm"
        assert validate_instance(r,"graph_review")

    # Extra field
    def test_extra_field_fails(self):
        r = _review(); r["__extra__"]=1
        assert validate_instance(r,"graph_review")

    # Unknown patch op
    def test_unknown_op_fails(self):
        r = _review(review_patch=[{"op":"move","path":"/suggested_change","from":"/x"}])
        assert validate_instance(r,"graph_review")

    # Extra patch field
    def test_extra_patch_field_fails(self):
        r = _review(review_patch=[{"op":"replace","path":"/suggested_change","value":"x","__extra__":1}])
        assert validate_instance(r,"graph_review")
