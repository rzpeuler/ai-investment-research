"""Phase 5 M7-R1 — Lifecycle Closure 测试。

覆盖（任务书 1-9 节）：
- 1/2. proposal lifecycle time gate（pipeline + builder 单一 helper）：
  modify valid_from 必填、retire valid_from==valid_to 必填，persist 前拒绝
- 3. 真实 CandidatePipeline 攻击（FakeLlmProvider + real schema + real SQLite）
  + direct-builder bypass（不能绕 pipeline）
- 4/5. retrograde retire：retire_at < predecessor.valid_from →
  RETIRE_TARGET_NOT_ACTIVE（node + edge，0 delta，history 仍可读）
- 6. history cross-version retrograde（v3.valid_from < v2.valid_from）→
  HISTORY_INTERVAL_INVALID
- 7/8. node retire origin 双向证明（status=retired ⟺ change_type=retire_node，
  不匹配 → HISTORY_ORIGIN_INTEGRITY_CONFLICT）
- 9. edge retire origin regression（modify_edge 不误判 retired）
"""
from __future__ import annotations

import json
import uuid

import pytest

from research_os.knowledge.candidate_builder import (
    GraphChangeBuilder,
    validate_proposal_lifecycle_times,
)
from research_os.knowledge.history import HistoryError
from research_os.models import (
    GraphChange, GraphChangeProposal, GraphNode, GraphEdge,
)
from research_os.utils.id import new_uuid

from tests.unit.test_phase5_m7_lifecycle import (
    _setup_db, _make_components,
    _make_add_node_candidate, _make_modify_node_candidate,
    _make_retire_node_candidate, _make_add_edge_candidate,
    _make_modify_edge_candidate, _make_retire_edge_candidate,
    _import_review, _apply_and_assert,
    _current_knowledge_of, _count_table, _canonical,
    T0, T1, T2, T3, APPLIED_AT, EVIDENCE_UUID,
)


# ═══════════════════════════════════════════════════════════════
# 1/2. proposal lifecycle time gate（helper 单元级）
# ═══════════════════════════════════════════════════════════════

def _proposal(pt, node=None, edge=None):
    return GraphChangeProposal(
        proposal_type=pt,
        source_object_ids=[new_uuid()],
        candidate_node=node,
        candidate_edge=edge,
        new_evidence_ids=[EVIDENCE_UUID],
        suggested_change="x",
        impact_scope=[],
        conflicts=[],
        verification_points=[],
        confidence=0.7,
    )


def _prop_node(valid_from=None, valid_to=None):
    from research_os.models import GraphProposalNode
    return GraphProposalNode(
        existing_node_id="company:test-corp",
        node_type="Company",
        name="测试公司",
        aliases=[],
        description="",
        valid_from=valid_from,
        valid_to=valid_to,
    )


def _prop_edge(valid_from=None, valid_to=None):
    from research_os.models import GraphProposalEdge
    return GraphProposalEdge(
        source_node_id="company:src",
        relation="COMPETES_WITH",
        target_node_id="company:tgt",
        attributes={},
        assertion_type="FACT",
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=0.8,
    )


class TestProposalLifecycleHelper:
    """validate_proposal_lifecycle_times 单一 helper 单元测试。"""

    def test_modify_node_valid_from_missing(self):
        assert validate_proposal_lifecycle_times(
            _proposal("modify_attribute", node=_prop_node(valid_from=None))
        ) == "TRANSITION_TIME_MISSING"

    def test_modify_edge_valid_from_missing(self):
        assert validate_proposal_lifecycle_times(
            _proposal("modify_attribute", edge=_prop_edge(valid_from=None))
        ) == "TRANSITION_TIME_MISSING"

    def test_modify_node_valid_from_present(self):
        assert validate_proposal_lifecycle_times(
            _proposal("modify_attribute", node=_prop_node(valid_from=T2))
        ) is None

    def test_retire_node_valid_from_missing(self):
        assert validate_proposal_lifecycle_times(
            _proposal("retire_node", node=_prop_node(valid_from=None))
        ) == "RETIRE_TIME_INVALID"

    def test_retire_node_valid_from_ne_valid_to(self):
        assert validate_proposal_lifecycle_times(
            _proposal("retire_node",
                      node=_prop_node(valid_from=T2, valid_to=T3))
        ) == "RETIRE_TIME_INVALID"

    def test_retire_edge_valid_from_missing(self):
        assert validate_proposal_lifecycle_times(
            _proposal("retire_edge", edge=_prop_edge(valid_from=None))
        ) == "RETIRE_TIME_INVALID"

    def test_retire_edge_valid_from_ne_valid_to(self):
        assert validate_proposal_lifecycle_times(
            _proposal("retire_edge",
                      edge=_prop_edge(valid_from=T2, valid_to=T3))
        ) == "RETIRE_TIME_INVALID"

    def test_retire_valid_time_ok(self):
        assert validate_proposal_lifecycle_times(
            _proposal("retire_node",
                      node=_prop_node(valid_from=T2, valid_to=T2))
        ) is None

    def test_add_types_no_gate(self):
        from research_os.models import GraphProposalNode
        node = _prop_node(valid_from=None)
        node.existing_node_id = None
        add_node_prop = _proposal("add_node", node=node)
        assert validate_proposal_lifecycle_times(add_node_prop) is None
        assert validate_proposal_lifecycle_times(
            _proposal("add_edge", edge=_prop_edge(valid_from=None))
        ) is None

    def test_modify_invalid_iso_rejected(self):
        # Pydantic 先拦非法 ISO（构造失败），helper 层面防御
        with pytest.raises(Exception):
            _proposal("modify_attribute",
                      node=_prop_node(valid_from="not-a-time"))


class TestBuilderLifecycleDefense:
    """2. direct-builder bypass：绕过 pipeline 直接 build 也必须拒绝。"""

    @pytest.fixture()
    def db(self, tmp_path):
        from research_os.storage import Database
        db = Database(tmp_path / "m7r1.db")
        db.initialize()
        yield db
        db.close()

    def test_builder_rejects_modify_missing_time(self, db):
        builder = GraphChangeBuilder(db)
        with pytest.raises(ValueError, match="PROPOSAL_REJECTED"):
            builder.build(_proposal("modify_attribute",
                                    node=_prop_node(valid_from=None)))

    def test_builder_rejects_retire_missing_time(self, db):
        builder = GraphChangeBuilder(db)
        with pytest.raises(ValueError, match="PROPOSAL_REJECTED"):
            builder.build(_proposal("retire_node", node=_prop_node()))

    def test_builder_rejects_retire_unequal(self, db):
        builder = GraphChangeBuilder(db)
        with pytest.raises(ValueError, match="PROPOSAL_REJECTED"):
            builder.build(_proposal(
                "retire_node",
                node=_prop_node(valid_from=T2, valid_to=T3)))


class TestPipelineLifecycleGate:
    """3. 真实 CandidatePipeline 攻击（FakeLlmProvider + real schema +
    real SQLite）：invalid proposal → proposal_rejected + 0 graph_changes。"""

    @pytest.fixture()
    def db(self, tmp_path):
        from research_os.storage import Database
        db = Database(tmp_path / "pipeline.db")
        db.migrate()
        yield db
        db.close()

    def _seed_source(self, db):
        """创建真实 evidence + event，返回 (ev_id, event_id)。"""
        ev_id = new_uuid()
        from research_os.models import Evidence
        ev = Evidence(
            evidence_id=ev_id,
            source_id="source:test",
            raw_item_id=new_uuid(),
            title="测试证据",
            publisher="测试",
            published_at=T0,
            retrieved_at=T0,
            url="https://example.com",
            excerpt="摘录",
            evidence_type="official_disclosure",
            independence_group="g1",
            source_tier="B",
            access_status="ok",
        )
        db.upsert(ev)
        event_id = new_uuid()
        from research_os.models import Event
        event = Event(
            event_id=event_id,
            event_type="test",
            subject_entities=["company:test"],
            object_entities=[],
            event_time=T0,
            announced_at=T0,
            effective_at=None,
            status="announced",
            summary="事件摘要",
            quantitative_fields={},
            industry_coordinates=[],
            novelty=0.5,
            impact_direction="neutral",
            impact_horizon="short",
            evidence_ids=[ev_id],
            confidence=0.5,
            conflicts=[],
        )
        db.upsert(event)
        return ev_id, event_id

    def _run_pipeline(self, db, tmp_path, proposal_output, event_id):
        from research_os.llm.provider import FakeLlmProvider
        from research_os.knowledge.candidate_pipeline import CandidatePipeline

        fake_provider = FakeLlmProvider(behavior=lambda req, schema: {
            "ok": True, "output": proposal_output, "error": None,
            "model_id": "fake-model",
        })
        pipeline = CandidatePipeline(db=db, provider=fake_provider,
                                     live=True, dry_run=False)
        pipeline._llm_client.configured = True
        pipeline._llm_client.provider = fake_provider
        result = pipeline.run(
            sources=[("Event", event_id)],
            knowledge_dir=tmp_path / "knowledge",
        )
        return result

    def _base_node_proposal(self, pt, valid_from, valid_to, node=True,
                            ev_id=None, event_id=None):
        cand = {
            "existing_node_id": "company:test-corp",
            "node_type": "Company",
            "name": "测试公司",
            "aliases": [],
            "description": "",
            "valid_from": valid_from,
            "valid_to": valid_to,
        }
        if node:
            return {
                "proposal_type": pt,
                "source_object_ids": [f"Event:{event_id or new_uuid()}"],
                "candidate_node": cand,
                "candidate_edge": None,
                "new_evidence_ids": [ev_id or EVIDENCE_UUID],
                "suggested_change": "x",
                "impact_scope": [],
                "conflicts": [],
                "verification_points": [],
                "confidence": 0.7,
            }
        edge = {
            "source_node_id": "company:src",
            "relation": "COMPETES_WITH",
            "target_node_id": "company:tgt",
            "attributes": {},
            "assertion_type": "FACT",
            "valid_from": valid_from,
            "valid_to": valid_to,
            "confidence": 0.8,
        }
        return {
            "proposal_type": pt,
            "source_object_ids": [f"Event:{event_id or new_uuid()}"],
            "candidate_node": None,
            "candidate_edge": edge,
            "new_evidence_ids": [ev_id or EVIDENCE_UUID],
            "suggested_change": "x",
            "impact_scope": [],
            "conflicts": [],
            "verification_points": [],
            "confidence": 0.7,
        }

    @pytest.mark.parametrize("pt,valid_from,valid_to,node", [
        ("modify_attribute", None, None, True),
        ("modify_attribute", None, None, False),
        ("retire_node", None, None, True),
        ("retire_node", T2, T3, True),
        ("retire_edge", None, None, False),
        ("retire_edge", T2, T3, False),
    ])
    def test_invalid_lifecycle_proposal_rejected(self, db, tmp_path, pt,
                                                 valid_from, valid_to, node):
        """6 项 pipeline 真实攻击：proposal_rejected + 0 graph_changes。"""
        ev_id, event_id = self._seed_source(db)
        proposal_output = self._base_node_proposal(
            pt, valid_from, valid_to, node=node,
            ev_id=ev_id, event_id=event_id)
        result = self._run_pipeline(db, tmp_path, proposal_output, event_id)
        assert result["status"] == "proposal_rejected", result
        assert any("PROPOSAL_REJECTED" in e for e in result.get("errors", [])), \
            result.get("errors")
        assert db.count("graph_changes") == 0, \
            "invalid proposal 不得持久化 candidate"


# ═══════════════════════════════════════════════════════════════
# 4/5. retrograde retire（apply 侧）
# ═══════════════════════════════════════════════════════════════

class TestRetrogradeRetire:
    """retire_at < predecessor.valid_from → RETIRE_TARGET_NOT_ACTIVE。"""

    def test_retrograde_retire_node(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        # v1 add（valid_from=null）
        gc1 = _make_add_node_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        # v2 modify valid_from=T2（future）
        gc2 = _make_modify_node_candidate(
            version=2, valid_from=T2, name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        # v3 retire_at=T1（< v2.valid_from=T2）→ retrograde；
        # retire candidate 必须与 latest（v2 name="v2", description="更新后的描述"）
        # 业务字段一致
        gc3 = _make_retire_node_candidate(
            version=3, retire_at=T1, name="v2",
            description="更新后的描述",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 2))
        candidate_repo.append_candidate(gc3)
        _import_review(workflow, gc3, decision="批准")
        result = _apply_and_assert(engine, gc3,
                                   expected="RETIRE_TARGET_NOT_ACTIVE")
        assert result.status == "APPLY_REJECTED"

        # 0 delta
        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before

        # 失败后 history 仍能正常读取原 v1/v2 chain
        hist = history.get_node_history("company:test-corp", as_of=T1)
        assert hist.resolved["version"] == 1
        assert hist.resolved["derived_status"] == "active"
        hist2 = history.get_node_history("company:test-corp", as_of=T2)
        assert hist2.resolved["version"] == 2
        assert hist2.resolved["derived_status"] == "active"
        db.close()

    def test_retrograde_retire_edge(self, tmp_path):
        db, _ = _setup_db(tmp_path,
                          raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        gc2 = _make_modify_edge_candidate(
            version=2, valid_from=T2, confidence=0.9,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        edges_before = _count_table(db, "graph_edges")
        apps_before = _count_table(db, "graph_applications")

        gc3 = _make_retire_edge_candidate(
            version=3, retire_at=T1, confidence=0.9,
            attributes={"detail": "v2"},
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 2))
        candidate_repo.append_candidate(gc3)
        _import_review(workflow, gc3, decision="批准")
        _apply_and_assert(engine, gc3, expected="RETIRE_TARGET_NOT_ACTIVE")

        assert _count_table(db, "graph_edges") == edges_before
        assert _count_table(db, "graph_applications") == apps_before

        hist = history.get_edge_history("edge:test-1", as_of=T1)
        assert hist.resolved["version"] == 1
        assert hist.resolved["derived_status"] == "active"
        db.close()

    def test_retire_at_equal_valid_from_kept(self, tmp_path):
        """retire_at == predecessor.valid_from 保持既有语义（不改为拒绝）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        gc1 = _make_add_node_candidate(valid_from=T2)
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        # retire_at == v1.valid_from == T2 → 允许（既有语义）
        gc2 = _make_retire_node_candidate(
            retire_at=T2,
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        result = _apply_and_assert(engine, gc2, expected="applied")
        assert result.target_version == 2
        db.close()


# ═══════════════════════════════════════════════════════════════
# 6. history cross-version retrograde
# ═══════════════════════════════════════════════════════════════

class TestHistoryCrossVersionRetrograde:
    """v2.valid_from=T2, v3.valid_from=T1（T1<T2）→ HISTORY_INTERVAL_INVALID。"""

    def test_cross_version_retrograde(self, tmp_path):
        from tests.unit.test_phase5_m7_history import (
            _setup_db as _hist_setup,
            _seed_node_v1, _insert_raw_node, _node_payload_v2,
            _make_graph_repo,
        )
        db, _ = _hist_setup(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        # v2.valid_from=T2
        gc2 = str(uuid.uuid4())
        _insert_raw_node(db, graph_repo, _node_payload_v2(gc2), version=2)
        # v3.valid_from=T1（< v2.valid_from=T2）→ cross-version retrograde
        v3 = _node_payload_v2(str(uuid.uuid4()), valid_from=T1, name="v3")
        v3["version"] = 3
        _insert_raw_node(db, graph_repo, v3, version=3)

        from research_os.knowledge.history import HistoryService
        history = HistoryService(db, graph_repo)
        with pytest.raises(HistoryError) as exc_info:
            history.get_node_history("company:test-corp")
        assert exc_info.value.error_code == "HISTORY_INTERVAL_INVALID"
        db.close()


# ═══════════════════════════════════════════════════════════════
# 7/8. node retire origin 双向证明
# ═══════════════════════════════════════════════════════════════

class TestNodeRetireOriginProof:
    """node retired lifecycle 双向证明（graph_change origin）。"""

    def _make_history_db(self, tmp_path):
        from tests.unit.test_phase5_m7_history import (
            _setup_db as _hist_setup, _seed_node_v1, _make_graph_repo,
        )
        db, _ = _hist_setup(tmp_path)
        graph_repo = _make_graph_repo(db)
        _seed_node_v1(db, graph_repo)
        from research_os.knowledge.history import HistoryService
        return db, graph_repo, HistoryService(db, graph_repo)

    def _insert_node_with_origin(self, db, graph_repo, payload, version,
                                 origin_change_type):
        """直接 SQL 构造 Schema-valid、column/payload 一致的 node v2，
        origin GraphChange 使用指定 change_type。"""
        from tests.unit.test_phase5_m7_history import (
            _insert_raw_node,
        )
        gc_id = payload["originating_graph_change_id"]
        _insert_raw_node(db, graph_repo, payload, version, gc_id=gc_id)
        # 改写 origin GraphChange.change_type
        row = db._conn.execute(
            "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
            (gc_id,),
        ).fetchone()
        gc_dict = json.loads(row["payload"])
        gc_dict["change_type"] = origin_change_type
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (_canonical(gc_dict), gc_id),
        )
        db._conn.commit()

    def test_attack_a_status_retired_origin_modify(self, tmp_path):
        """Attack A：node.status=retired 但 origin change_type=modify_attribute
        → HISTORY_ORIGIN_INTEGRITY_CONFLICT。"""
        from tests.unit.test_phase5_m7_history import _node_payload_v2
        db, graph_repo, history = self._make_history_db(tmp_path)
        v2 = _node_payload_v2(str(uuid.uuid4()), name="损坏")
        v2["status"] = "retired"
        v2["valid_to"] = v2["valid_from"] = T2
        self._insert_node_with_origin(db, graph_repo, v2, 2,
                                      "modify_attribute")
        with pytest.raises(HistoryError) as exc_info:
            history.get_node_history("company:test-corp")
        assert exc_info.value.error_code == "HISTORY_ORIGIN_INTEGRITY_CONFLICT"
        db.close()

    def test_attack_b_origin_retire_status_active(self, tmp_path):
        """Attack B：origin change_type=retire_node 但 node.status=active
        → HISTORY_ORIGIN_INTEGRITY_CONFLICT。"""
        from tests.unit.test_phase5_m7_history import _node_payload_v2
        db, graph_repo, history = self._make_history_db(tmp_path)
        v2 = _node_payload_v2(str(uuid.uuid4()), name="损坏")
        v2["valid_to"] = v2["valid_from"] = T2
        self._insert_node_with_origin(db, graph_repo, v2, 2,
                                      "retire_node")
        with pytest.raises(HistoryError) as exc_info:
            history.get_node_history("company:test-corp")
        assert exc_info.value.error_code == "HISTORY_ORIGIN_INTEGRITY_CONFLICT"
        db.close()

    def test_normal_retire_chain_ok(self, tmp_path):
        """合法 retire_node chain：v2 status=retired + origin retire_node
        → history 正常（retired tombstone）。"""
        from tests.unit.test_phase5_m7_history import _node_payload_v2
        db, graph_repo, history = self._make_history_db(tmp_path)
        v2 = _node_payload_v2(str(uuid.uuid4()), name="退休")
        v2["status"] = "retired"
        v2["valid_to"] = v2["valid_from"] = T2
        self._insert_node_with_origin(db, graph_repo, v2, 2,
                                      "retire_node")
        hist = history.get_node_history("company:test-corp", as_of=T3)
        assert hist.resolved["version"] == 2
        assert hist.resolved["derived_status"] == "retired"
        db.close()


# ═══════════════════════════════════════════════════════════════
# 9. edge retire origin regression
# ═══════════════════════════════════════════════════════════════

class TestEdgeRetireOriginRegression:
    """retire_edge → retired；modify_edge 即使 valid_from==valid_to 不误判。"""

    def test_retire_edge_origin_retired(self, tmp_path):
        db, _ = _setup_db(tmp_path,
                          raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        gc2 = _make_retire_edge_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        hist = history.get_edge_history("edge:test-1", as_of=T2)
        assert hist.resolved["version"] == 2
        assert hist.resolved["derived_status"] == "retired"
        assert hist.versions[1].is_tombstone is True
        db.close()

    def test_modify_edge_valid_from_eq_valid_to_not_retired(self, tmp_path):
        """modify_edge 即使 valid_from == valid_to 也不得误判 retired
        （origin change_type 是唯一判定依据）。"""
        db, _ = _setup_db(tmp_path,
                          raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        # modify edge：valid_from == valid_to == T2（业务自设，非 tombstone）
        gc2 = _make_modify_edge_candidate(
            version=2, valid_from=T2, valid_to=T2, confidence=0.9,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        hist = history.get_edge_history("edge:test-1", as_of=T2)
        # lifecycle 类型由 origin change_type 唯一判定：modify 不是 retire tombstone
        assert hist.versions[1].is_tombstone is False
        assert hist.resolved["version"] == 2
        # v2 有效区间 [T2, T2) 为空 → as_of=T2 时 expired（而非 retired，
        # 证明没有被误判为 retire tombstone）
        assert hist.resolved["derived_status"] == "expired"
        db.close()

    def test_governance_seed_edge_history_ok(self, tmp_path):
        """seed edge（assertion_type=GOVERNANCE, gc_id=null）的 history 必须
        正常读取（非 retire tombstone，不触发 fail-closed）。"""
        from research_os.models import GraphEdge as _GE
        from research_os.knowledge.repository import GraphRepository
        db, _ = _setup_db(tmp_path)
        graph_repo = GraphRepository(db)
        seed_edge = _GE(
            edge_id="edge:seed-1",
            source_node_id="industry:semiconductor",
            relation="BELONGS_TO",
            target_node_id="industry:tech",
            attributes={},
            assertion_type="GOVERNANCE",
            valid_from=None,
            valid_to=None,
            confidence=1.0,
            evidence_ids=[],
            review_status="approved",
            version=1,
            originating_graph_change_id=None,
            created_at=T0,
            last_reviewed_at=None,
        )
        graph_repo.append_edge(seed_edge)
        history = _make_components(db)[-1]
        hist = history.get_edge_history("edge:seed-1")
        assert [e.version for e in hist.versions] == [1]
        assert hist.versions[0].is_tombstone is False
        resolved = history.resolve_edge_as_of("edge:seed-1", T2)
        assert resolved["version"] == 1
        assert resolved["derived_status"] == "active"
        db.close()

    def test_seed_edge_incident_guard_no_crash(self, tmp_path):
        """retire node 带 GOVERNANCE seed incident edge：seed edge 解析必须
        正常（不得 INCIDENT_EDGE_CHECK_FAILED）；edge active → 正确
        ACTIVE_INCIDENT_EDGES 阻塞（不是 check 失败）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        # node v1
        gc1 = _make_add_node_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        # GOVERNANCE seed incident edge：src → test-corp
        from research_os.models import GraphEdge as _GE
        seed_edge = _GE(
            edge_id="edge:seed-incident",
            source_node_id="company:src",
            relation="COMPETES_WITH",
            target_node_id="company:test-corp",
            attributes={},
            assertion_type="GOVERNANCE",
            valid_from=None,
            valid_to=None,
            confidence=1.0,
            evidence_ids=[],
            review_status="approved",
            version=1,
            originating_graph_change_id=None,
            created_at=T0,
            last_reviewed_at=None,
        )
        graph_repo.append_edge(seed_edge)

        gc_r = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        result = _apply_and_assert(engine, gc_r,
                                   expected="ACTIVE_INCIDENT_EDGES")
        assert "INCIDENT_EDGE_CHECK_FAILED" not in result.errors[0]
        db.close()
