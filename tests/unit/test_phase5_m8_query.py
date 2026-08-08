"""Phase 5 M8 — Graph Query Service 测试（Golden + 攻击 + read snapshot）。

覆盖（Decision #38 + 任务书 §47/48/49）：
- Golden A-H：direct historical node / retired object / depth1 / depth2 /
  future isolation / governance / model inference / deterministic
- 攻击：as_of、depth、filter、payload 损坏、column mismatch、version gap、
  origin 缺失、endpoint 缺失/inactive、ambiguous edge、cycle、multipath、
  future leak、expired/retired 排除、inactive root、hard limits、错误映射
- snapshot concurrency：真实 SQLite WAL reader/writer（任务书 §49）
- M7 HistoryService conn 参数回归（默认 None 行为不变）
"""
from __future__ import annotations

import json
import sqlite3
import uuid

import pytest

from research_os.models import (
    Entity,
    Evidence,
    GraphChange,
    GraphEdge,
    GraphNode,
)
from research_os.storage.db import Database
from research_os.knowledge.candidate_repository import (
    GraphChangeCandidateRepository,
)
from research_os.knowledge.history import HistoryService
from research_os.knowledge.repository import GraphRepository
from research_os.knowledge.query import (
    MAX_EDGES,
    MAX_NODES,
    GraphQueryService,
    QueryError,
)

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"
T3 = "2026-08-10T09:00:00+08:00"
TFUTURE = "2026-09-01T09:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _setup_db(tmp_path):
    db_path = tmp_path / "m8.db"
    db = Database(db_path)
    db.initialize()
    conn = db._conn

    ev = Evidence(
        evidence_id=EVIDENCE_UUID,
        source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID,
        title="测试证据",
        publisher="测试发布者",
        published_at="2026-08-01T10:00:00+08:00",
        retrieved_at="2026-08-02T10:00:00+08:00",
        url="https://example.com",
        excerpt="测试摘录",
        evidence_type="news_report",
        independence_group="group-1",
        source_tier="B",
        access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID, _canonical(ev.model_dump()), SOURCE_UUID,
         RAW_ITEM_UUID, "group-1", "B"),
    )
    ri_payload = json.dumps({
        "raw_item_id": RAW_ITEM_UUID,
        "source_id": SOURCE_UUID,
        "external_id": "ext-001",
        "url": "https://example.com",
        "title": "测试",
        "publisher": "测试",
        "author": "测试作者",
        "published_at": "2026-08-01T10:00:00+08:00",
        "retrieved_at": "2026-08-02T10:00:00+08:00",
        "content_hash": SHA256_ZEROS,
        "content_excerpt": "测试摘录",
        "content_storage": "metadata_and_excerpt",
        "language": "zh-CN",
        "access_status": "ok",
        "entities": ["company:a"],
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    for eid, etype, name in (
        ("company:a", "company", "公司A"),
        ("company:b", "company", "公司B"),
        ("company:c", "company", "公司C"),
        ("industry:semi", "industry", "半导体"),
    ):
        entity = Entity(entity_id=eid, entity_type=etype, canonical_name=name)
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, _canonical(entity.model_dump()), etype, name),
        )
    conn.commit()
    return db, db_path


def _gc_exists(db, gc_id):
    row = db._conn.execute(
        "SELECT 1 FROM graph_changes WHERE graph_change_id = ?", (gc_id,)
    ).fetchone()
    return row is not None


def _ensure_gc(db, payload, version, kind, change_type=None):
    """确保 origin GraphChange 存在（candidate 形态；与 payload identity/version 匹配）。"""
    gc_id = payload.get("originating_graph_change_id")
    if gc_id is None:
        return None
    if _gc_exists(db, gc_id):
        return gc_id
    if kind == "node":
        if change_type is None:
            change_type = ("retire_node" if payload["status"] == "retired"
                           else ("add_node" if version == 1
                                 else "modify_attribute"))
        node_dict = dict(payload)
        node_dict["review_status"] = "candidate"
        node_dict["last_reviewed_at"] = None
        gc = GraphChange(
            graph_change_id=gc_id, change_type=change_type,
            node=GraphNode(**node_dict), edge=None,
            current_knowledge="{}", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="构造", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate",
            created_at=T0, reviewed_at=None,
        )
    else:
        if change_type is None:
            change_type = ("add_edge" if version == 1 else "modify_attribute")
        edge_dict = dict(payload)
        edge_dict["review_status"] = "candidate"
        edge_dict["last_reviewed_at"] = None
        gc = GraphChange(
            graph_change_id=gc_id, change_type=change_type,
            node=None, edge=GraphEdge(**edge_dict),
            current_knowledge="{}", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="构造", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate",
            created_at=T0, reviewed_at=None,
        )
    GraphChangeCandidateRepository(db).append_candidate(gc)
    return gc_id


def _insert_node(db, payload, version, change_type=None):
    _ensure_gc(db, payload, version, "node", change_type)
    db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload["node_id"], version, _canonical(payload),
         payload["node_type"], payload["name"], payload["status"],
         payload["review_status"], payload["origin_kind"],
         payload["created_at"], payload["valid_from"], payload["valid_to"],
         payload["last_reviewed_at"], payload["originating_graph_change_id"]),
    )
    db._conn.commit()


def _insert_edge(db, payload, version, change_type=None):
    _ensure_gc(db, payload, version, "edge", change_type)
    db._conn.execute(
        "INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, valid_from, valid_to, confidence, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (payload["edge_id"], version, _canonical(payload),
         payload["source_node_id"], payload["relation"],
         payload["target_node_id"], payload["assertion_type"],
         payload["review_status"], payload["created_at"],
         payload["valid_from"], payload["valid_to"], payload["confidence"],
         payload["last_reviewed_at"],
         payload["originating_graph_change_id"]),
    )
    db._conn.commit()


def _node(node_id, version, *, name=None, status="active", valid_from=None,
          valid_to=None, gc_id=None, origin_kind="graph_change",
          evidence_ids=(EVIDENCE_UUID,), node_type=None):
    if node_type is None:
        node_type = ("Industry" if node_id.startswith("industry:")
                     else "Company")
    return {
        "node_id": node_id,
        "node_type": node_type,
        "name": name or node_id,
        "aliases": [],
        "description": "测试节点",
        "status": status,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "evidence_ids": list(evidence_ids),
        "version": version,
        "last_reviewed_at": T1,
        "review_status": "approved",
        "origin_kind": origin_kind,
        "originating_graph_change_id": gc_id,
        "created_at": T0,
    }


def _gov_node(node_id, version=1, *, name=None, status="active"):
    return _node(node_id, version, name=name, status=status, gc_id=None,
                 origin_kind="governance_seed", evidence_ids=[])


def _edge(edge_id, src, rel, tgt, version, *, assertion_type="FACT",
          valid_from=None, valid_to=None, confidence=0.9, gc_id=None,
          evidence_ids=(EVIDENCE_UUID,)):
    return {
        "edge_id": edge_id,
        "source_node_id": src,
        "relation": rel,
        "target_node_id": tgt,
        "attributes": {},
        "assertion_type": assertion_type,
        "valid_from": valid_from,
        "valid_to": valid_to,
        "confidence": confidence,
        "evidence_ids": list(evidence_ids),
        "review_status": "approved",
        "version": version,
        "originating_graph_change_id": gc_id,
        "created_at": T0,
        "last_reviewed_at": T1,
    }


def _gov_edge(edge_id, src, rel, tgt, version=1, *, valid_from=None,
              valid_to=None):
    return _edge(edge_id, src, rel, tgt, version, assertion_type="GOVERNANCE",
                 valid_from=valid_from, valid_to=valid_to, gc_id=None,
                 evidence_ids=[])


def _service(db):
    return GraphQueryService(db)


def _mk_chain(db, *, with_future_v2=False, future_from=TFUTURE):
    """A →(SUPPLIES) B →(SUPPLIES) C，全部 FACT v1 active。"""
    _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
    _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
    _insert_node(db, _node("company:c", 1, gc_id=str(uuid.uuid4())), 1)
    _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                           gc_id=str(uuid.uuid4())), 1)
    _insert_edge(db, _edge("edge:bc", "company:b", "SUPPLIES", "company:c", 1,
                           gc_id=str(uuid.uuid4())), 1)
    if with_future_v2:
        gc = str(uuid.uuid4())
        _insert_node(db, _node("company:b", 2, name="公司B-v2",
                               valid_from=future_from, gc_id=gc), 2)
        gc2 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 2,
                               valid_from=future_from, gc_id=gc2), 2)


# ── Golden A-H（任务书 §47）────────────────────────────────

class TestGolden:
    def test_golden_a_direct_historical_node(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc1 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 1, gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 2, name="公司A-v2",
                               valid_from=T2, gc_id=gc2), 2)
        svc = _service(db)
        assert svc.get_node("company:a", T1).payload["name"] == "company:a"
        assert svc.get_node("company:a", T1).version == 1
        assert svc.get_node("company:a", T2).payload["name"] == "公司A-v2"
        assert svc.get_node("company:a", T2).version == 2

    def test_golden_b_direct_retired_object(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc1 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 1, gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 2, status="retired",
                               valid_from=T2, valid_to=T2, gc_id=gc2), 2,
                     change_type="retire_node")
        svc = _service(db)
        r = svc.get_node("company:a", T3)
        assert r.version == 2
        assert r.derived_status == "retired"
        assert r.is_active is False

    def test_golden_c_depth1(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1)
        ids = sorted(w["node_id"] for w in r.nodes)
        assert ids == ["company:a", "company:b"]
        assert [w["edge_id"] for w in r.edges] == ["edge:ab"]
        by_id = {w["node_id"]: w for w in r.nodes}
        assert by_id["company:a"]["depth"] == 0
        assert by_id["company:b"]["depth"] == 1
        assert r.edges[0]["depth"] == 1

    def test_golden_d_depth2(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=2)
        ids = sorted(w["node_id"] for w in r.nodes)
        assert ids == ["company:a", "company:b", "company:c"]
        by_id = {w["node_id"]: w for w in r.nodes}
        assert by_id["company:c"]["depth"] == 2
        assert {w["edge_id"] for w in r.edges} == {"edge:ab", "edge:bc"}
        by_eid = {w["edge_id"]: w for w in r.edges}
        assert by_eid["edge:bc"]["depth"] == 2

    def test_golden_e_future_isolation(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db, with_future_v2=True)
        svc = _service(db)
        # as_of 早于 future valid_from：b 仍是 v1，edge:ab 仍是 v1
        r = svc.query_graph("company:a", T2, max_depth=1)
        by_id = {w["node_id"]: w for w in r.nodes}
        assert by_id["company:b"]["version"] == 1
        assert r.edges[0]["version"] == 1

    def test_golden_f_governance_partition(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _gov_node("industry:semi", name="半导体"), 1)
        _insert_node(db, _gov_node("industry:ai-hardware", name="AI硬件"), 1)
        _insert_edge(db, _gov_edge("edge:gov-1", "industry:semi",
                                   "BELONGS_TO", "industry:ai-hardware"), 1)
        svc = _service(db)
        r = svc.query_graph("industry:semi", T2, max_depth=1)
        assert r.epistemic["governance"] == ["edge:gov-1"]
        assert r.epistemic["facts"] == []
        assert r.epistemic["model_inferences"] == []

    def test_golden_g_model_inference_partition(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:mi", "company:a", "BENEFITS_FROM",
                               "company:b", 1,
                               assertion_type="MODEL_INFERENCE",
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1)
        assert r.epistemic["model_inferences"] == ["edge:mi"]
        assert r.epistemic["facts"] == []
        assert any(l["code"] == "MODEL_INFERENCE_PRESENT"
                   for l in r.limitations)

    def test_golden_h_deterministic(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db)
        svc = _service(db)
        r1 = svc.query_graph("company:a", T2, max_depth=2)
        r2 = svc.query_graph("company:a", T2, max_depth=2)
        assert json.dumps(r1.to_dict(), ensure_ascii=False, sort_keys=True) \
            == json.dumps(r2.to_dict(), ensure_ascii=False, sort_keys=True)
        # 无 path / 无因果结论
        assert "paths" not in r1.to_dict()
        assert any(l["code"] == "BUSINESS_VALIDITY_TIME_ONLY"
                   for l in r1.limitations)
        assert any(l["code"] == "PATHS_NOT_CAUSAL" for l in r1.limitations)


# ── 参数校验攻击 ────────────────────────────────────────────

class TestParamAttacks:
    def test_missing_as_of(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.get_node("company:a", None)
        assert ei.value.error_code == "QUERY_AS_OF_REQUIRED"

    def test_invalid_as_of(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.get_node("company:a", "not-a-time")
        assert ei.value.error_code == "QUERY_AS_OF_INVALID"

    def test_nonexistent_node(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.get_node("company:missing", T2)
        assert ei.value.error_code == "QUERY_NODE_NOT_FOUND"

    def test_nonexistent_edge(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.get_edge("edge:missing", T2)
        assert ei.value.error_code == "QUERY_EDGE_NOT_FOUND"

    def test_depth_negative(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.query_graph("company:a", T2, max_depth=-1)
        assert ei.value.error_code == "QUERY_DEPTH_INVALID"

    def test_depth_gt_2(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.query_graph("company:a", T2, max_depth=3)
        assert ei.value.error_code == "QUERY_DEPTH_EXCEEDED"

    def test_invalid_direction(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.query_graph("company:a", T2, direction="sideways")
        assert ei.value.error_code == "QUERY_FILTER_INVALID"

    def test_invalid_relation(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.query_graph("company:a", T2, relation_filters=["LOVES"])
        assert ei.value.error_code == "QUERY_FILTER_INVALID"

    def test_invalid_assertion_type(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        svc = _service(db)
        with pytest.raises(QueryError) as ei:
            svc.query_graph("company:a", T2, assertion_types=["OPINION"])
        assert ei.value.error_code == "QUERY_FILTER_INVALID"

    def test_depth0_root_only(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=0)
        assert [w["node_id"] for w in r.nodes] == ["company:a"]
        assert r.edges == []


# ── integrity 攻击（fail-closed）────────────────────────────

class TestIntegrityAttacks:
    def _bogus(self, db, payload, version, corrupt):
        _insert_node(db, payload, version)
        # 直接篡改 payload 字段
        if corrupt == "bad_json":
            db._conn.execute(
                "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = ?",
                ("{not-json", payload["node_id"], version))
        elif corrupt == "wrong_type":
            db._conn.execute(
                "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = ?",
                ("[]", payload["node_id"], version))
        elif corrupt == "schema_invalid":
            bad = dict(payload)
            bad["node_type"] = "NotAType"
            db._conn.execute(
                "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = ?",
                (_canonical(bad), payload["node_id"], version))
        elif corrupt == "col_mismatch":
            db._conn.execute(
                "UPDATE graph_nodes SET name = '篡改名' WHERE node_id = ? AND version = ?",
                (payload["node_id"], version))
        db._conn.commit()

    def test_node_invalid_json(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        self._bogus(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1,
                    "bad_json")
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_NODE_PAYLOAD_INVALID"

    def test_node_valid_json_wrong_type(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        self._bogus(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1,
                    "wrong_type")
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_NODE_PAYLOAD_INVALID"

    def test_node_schema_invalid(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        self._bogus(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1,
                    "schema_invalid")
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_NODE_PAYLOAD_INVALID"

    def test_node_column_payload_mismatch(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        self._bogus(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1,
                    "col_mismatch")
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_INTEGRITY_CONFLICT"

    def test_edge_payload_invalid(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        db._conn.execute(
            "UPDATE graph_edges SET payload = ? WHERE edge_id = 'edge:ab'",
            ("[1,2]",))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EDGE_PAYLOAD_INVALID"

    def test_version_gap(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:a", 3, gc_id=str(uuid.uuid4())), 3)
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_VERSION_GAP"

    def test_interval_corruption(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc1 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 1, valid_from=T2, gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 2, valid_from=T1, gc_id=gc2), 2)
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_INTERVAL_INVALID"

    def test_origin_missing(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc = str(uuid.uuid4())
        payload = _node("company:a", 1, gc_id=gc)
        _insert_node(db, payload, 1)
        db._conn.execute(
            "DELETE FROM graph_changes WHERE graph_change_id = ?", (gc,))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_ORIGIN_INTEGRITY_CONFLICT"

    def test_origin_malformed(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc = str(uuid.uuid4())
        payload = _node("company:a", 1, gc_id=gc)
        _insert_node(db, payload, 1)
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            ("{broken", gc))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_ORIGIN_INTEGRITY_CONFLICT"

    def test_endpoint_missing(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:ghost", 1,
                               gc_id=str(uuid.uuid4())), 1)
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_ENDPOINT_MISSING"

    def test_endpoint_inactive(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        gc_b1 = str(uuid.uuid4())
        _insert_node(db, _node("company:b", 1, gc_id=gc_b1), 1)
        gc_b2 = str(uuid.uuid4())
        _insert_node(db, _node("company:b", 2, status="retired",
                               valid_from=T2, valid_to=T2, gc_id=gc_b2), 2,
                     change_type="retire_node")
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T3, max_depth=1)
        assert ei.value.error_code == "QUERY_ENDPOINT_INACTIVE"

    def test_column_says_not_incident_but_payload_says_incident(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        # 篡改 denormalized column：source_node_id 不再是 a（payload 仍是 a）
        db._conn.execute(
            "UPDATE graph_edges SET source_node_id = 'company:zzz' "
            "WHERE edge_id = 'edge:ab'")
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        # dual-source discovery 仍发现 edge:ab → strict resolve 检出 mismatch
        assert ei.value.error_code == "QUERY_INTEGRITY_CONFLICT"

    def test_payload_says_not_incident_but_column_says_incident(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        payload = _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                        gc_id=str(uuid.uuid4()))
        _insert_edge(db, payload, 1)
        # 篡改 payload 的 source_node_id（column 仍是 a）
        bad = dict(payload)
        bad["source_node_id"] = "company:zzz"
        db._conn.execute(
            "UPDATE graph_edges SET payload = ? WHERE edge_id = 'edge:ab'",
            (_canonical(bad),))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_INTEGRITY_CONFLICT"

    def test_duplicate_active_triple(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab-1", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab-2", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_AMBIGUOUS_EDGE_IDENTITY"

    def test_same_edge_multiple_versions_single_logical(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        gc1 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 2,
                               valid_from=T2, gc_id=gc2), 2)
        svc = _service(db)
        r = svc.query_graph("company:a", T3, max_depth=1)
        assert len(r.edges) == 1  # 同一 edge_id 只算一个 active logical edge
        assert r.edges[0]["version"] == 2


# ── traversal 语义攻击 ──────────────────────────────────────

class TestTraversalSemantics:
    def test_multipath_dedup(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:c", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:d", 1, gc_id=str(uuid.uuid4())), 1)
        # A→B→D 与 A→C→D 两条路径到达 D
        _insert_edge(db, _edge("e1", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e2", "company:b", "SUPPLIES", "company:d", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e3", "company:a", "SUPPLIES", "company:c", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e4", "company:c", "SUPPLIES", "company:d", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=2)
        ids = [w["node_id"] for w in r.nodes]
        assert ids.count("company:d") == 1  # 只输出一次
        assert len(r.nodes) == 4

    def test_cycle_ab_a(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-ba", "company:b", "SUPPLIES", "company:a", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=2)
        assert {w["node_id"] for w in r.nodes} == {"company:a", "company:b"}
        assert {w["edge_id"] for w in r.edges} == {"e-ab", "e-ba"}

    def test_future_successor_leak_in_traversal(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_chain(db, with_future_v2=True)
        svc = _service(db)
        r = svc.query_graph("company:a", T1, max_depth=1)
        by_id = {w["node_id"]: w for w in r.nodes}
        assert by_id["company:b"]["version"] == 1  # future v2 未泄漏

    def test_expired_edge_excluded(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               valid_to=T2, gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T3, max_depth=1)
        assert r.edges == []  # expired（无 successor）不参与 traversal
        assert [w["node_id"] for w in r.nodes] == ["company:a"]

    def test_retired_edge_excluded(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        gc1 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 2,
                               valid_from=T2, valid_to=T2, gc_id=gc2), 2,
                     change_type="retire_edge")
        svc = _service(db)
        r = svc.query_graph("company:a", T3, max_depth=1)
        assert r.edges == []

    def test_root_retired_no_traversal(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        gc1 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 1, gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 2, status="retired",
                               valid_from=T2, valid_to=T2, gc_id=gc2), 2,
                     change_type="retire_node")
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T3, max_depth=1)
        assert [w["node_id"] for w in r.nodes] == ["company:a"]
        assert r.edges == []
        assert any(l["code"] == "ROOT_INACTIVE_NO_TRAVERSAL"
                   for l in r.limitations)

    def test_root_not_yet_valid_no_traversal(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, valid_from=TFUTURE,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T1, max_depth=1)
        assert [w["node_id"] for w in r.nodes] == ["company:a"]
        assert r.edges == []
        assert any(l["code"] == "ROOT_INACTIVE_NO_TRAVERSAL"
                   for l in r.limitations)

    def test_direction_outgoing(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-out", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-in", "company:b", "PURCHASES_FROM", "company:a", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1, direction="outgoing")
        assert [w["edge_id"] for w in r.edges] == ["e-out"]
        assert {w["node_id"] for w in r.nodes} == {"company:a", "company:b"}

    def test_direction_incoming(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-out", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-in", "company:b", "PURCHASES_FROM", "company:a", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1, direction="incoming")
        assert [w["edge_id"] for w in r.edges] == ["e-in"]

    def test_direction_both(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-out", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-in", "company:b", "PURCHASES_FROM", "company:a", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1, direction="both")
        assert {w["edge_id"] for w in r.edges} == {"e-out", "e-in"}

    def test_relation_filter(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e1", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e2", "company:a", "COMPETES_WITH", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1,
                            relation_filters=["SUPPLIES"])
        assert [w["edge_id"] for w in r.edges] == ["e1"]

    def test_assertion_filter(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-fact", "company:a", "SUPPLIES", "company:b", 1,
                               assertion_type="FACT",
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e-mi", "company:a", "BENEFITS_FROM", "company:b", 1,
                               assertion_type="MODEL_INFERENCE",
                               gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        r = svc.query_graph("company:a", T2, max_depth=1,
                            assertion_types=["FACT"])
        assert [w["edge_id"] for w in r.edges] == ["e-fact"]
        assert r.epistemic["model_inferences"] == []

    def test_governance_in_traversal_but_partitioned(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _gov_node("industry:semi", name="半导体"), 1)
        _insert_node(db, _gov_node("industry:ai-hardware", name="AI硬件"), 1)
        _insert_edge(db, _gov_edge("edge:gov-1", "industry:semi",
                                   "BELONGS_TO", "industry:ai-hardware"), 1)
        svc = _service(db)
        r = svc.query_graph("industry:semi", T2, max_depth=1)
        assert {w["node_id"] for w in r.nodes} == {
            "industry:semi", "industry:ai-hardware"}
        assert r.epistemic["governance"] == ["edge:gov-1"]
        assert r.epistemic["facts"] == []


# ── hard limits / 错误映射 ──────────────────────────────────

class TestLimitsAndMapping:
    def test_max_nodes_exceeded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research_os.knowledge.query.MAX_NODES", 2)
        db, _ = _setup_db(tmp_path)
        _mk_chain(db)
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=2)
        assert ei.value.error_code == "QUERY_RESULT_LIMIT_EXCEEDED"

    def test_max_edges_exceeded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research_os.knowledge.query.MAX_EDGES", 1)
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:c", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e1", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("e2", "company:a", "SUPPLIES", "company:c", 1,
                               gc_id=str(uuid.uuid4())), 1)
        with pytest.raises(QueryError) as ei:
            _service(db).query_graph("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_RESULT_LIMIT_EXCEEDED"

    def test_sql_error_mapped(self, tmp_path, monkeypatch):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)

        def boom(node_id, as_of, conn=None):
            raise sqlite3.OperationalError("db is locked")

        monkeypatch.setattr(svc._history, "resolve_node_as_of", boom)
        with pytest.raises(QueryError) as ei:
            svc.get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_READ_FAILED"

    def test_history_error_mapped_payload(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        self_bogus = TestIntegrityAttacks()
        self_bogus._bogus(db, _node("company:a", 1, gc_id=str(uuid.uuid4())),
                          1, "bad_json")
        with pytest.raises(QueryError) as ei:
            _service(db).get_node("company:a", T2)
        assert ei.value.error_code == "QUERY_NODE_PAYLOAD_INVALID"

    def test_active_caller_transaction_conflict(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        svc = _service(db)
        conn = db._conn
        conn.execute("BEGIN")
        try:
            with pytest.raises(QueryError) as ei:
                svc.get_node("company:a", T2)
            assert ei.value.error_code == "QUERY_ACTIVE_TRANSACTION_CONFLICT"
        finally:
            conn.execute("ROLLBACK")

    def test_read_only_db_zero_writes(self, tmp_path):
        db, db_path = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        db.close()
        before = db_path.read_bytes()
        ro = Database.open_read_only(db_path)
        svc = GraphQueryService(ro)
        r = svc.query_graph("company:a", T2, max_depth=1)
        assert r.as_of == T2
        ro.close()
        assert db_path.read_bytes() == before  # 零写


# ── snapshot concurrency（任务书 §49：真实 SQLite WAL）──────

class TestSnapshotConcurrency:
    def test_reader_snapshot_isolated_from_writer(self, tmp_path):
        db, db_path = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        db.close()

        # reader / writer 两个独立连接（WAL）
        db_r = Database(db_path)
        db_w = Database(db_path)
        svc = GraphQueryService(db_r)
        conn = db_r._conn
        conn.execute("BEGIN")  # 显式 read transaction
        try:
            r1 = svc._resolve_node("company:a", T2, conn)
            assert r1["version"] == 1
            # writer 提交新版本
            gc = str(uuid.uuid4())
            _insert_node(db_w, _node("company:a", 2, name="公司A-v2",
                                     valid_from=T2, gc_id=gc), 2)
            # 同一 read snapshot 内再读：仍 v1
            r2 = svc._resolve_node("company:a", T2, conn)
            assert r2["version"] == 1
            assert r2["payload"]["name"] == "company:a"
        finally:
            conn.execute("ROLLBACK")
            db_r.close()
            db_w.close()
        # 新 query（新 snapshot）看到 writer 提交的状态
        db_r2 = Database(db_path)
        r3 = GraphQueryService(db_r2).get_node("company:a", T2)
        assert r3.version == 2
        assert r3.payload["name"] == "公司A-v2"
        db_r2.close()

    def test_query_graph_whole_call_single_snapshot(self, tmp_path, monkeypatch):
        db, db_path = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=str(uuid.uuid4())), 1)
        db.close()

        db_r = Database(db_path)
        db_w = Database(db_path)
        svc = GraphQueryService(db_r)
        original = svc._discover_incident_edge_ids

        def discover_then_write(conn, node_id):
            result = original(conn, node_id)
            if node_id == "company:a":
                # 第一次 discovery 后 writer 提交新边
                _insert_node(db_w, _node("company:zzz", 1,
                                         gc_id=str(uuid.uuid4())), 1)
                _insert_edge(db_w, _edge("edge:az", "company:a", "SUPPLIES",
                                         "company:zzz", 1,
                                         gc_id=str(uuid.uuid4())), 1)
            return result

        monkeypatch.setattr(svc, "_discover_incident_edge_ids",
                            discover_then_write)
        r = svc.query_graph("company:a", T2, max_depth=1)
        # 同一次 query 内 writer 提交不可见：只有 edge:ab
        assert {w["edge_id"] for w in r.edges} == {"edge:ab"}
        db_r.close()
        db_w.close()
        # 新 query 看到新边
        db_r2 = Database(db_path)
        r2 = GraphQueryService(db_r2).query_graph("company:a", T2, max_depth=1)
        assert {w["edge_id"] for w in r2.edges} == {"edge:ab", "edge:az"}
        db_r2.close()


# ── M7 HistoryService conn 参数回归 ─────────────────────────

class TestHistoryConnRegression:
    def test_default_conn_behavior_unchanged(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        gc1 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 1, gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_node(db, _node("company:a", 2, name="公司A-v2",
                               valid_from=T2, gc_id=gc2), 2)
        history = HistoryService(db, GraphRepository(db))
        r_default = history.get_node_history("company:a", as_of=T2)
        r_conn = history.get_node_history("company:a", as_of=T2, conn=db._conn)
        assert r_default.to_dict() == r_conn.to_dict()
        rd = history.resolve_node_as_of("company:a", T2)
        rc = history.resolve_node_as_of("company:a", T2, conn=db._conn)
        assert rd == rc

    def test_edge_conn_behavior_unchanged(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, _node("company:a", 1, gc_id=str(uuid.uuid4())), 1)
        _insert_node(db, _node("company:b", 1, gc_id=str(uuid.uuid4())), 1)
        gc1 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 1,
                               gc_id=gc1), 1)
        gc2 = str(uuid.uuid4())
        _insert_edge(db, _edge("edge:ab", "company:a", "SUPPLIES", "company:b", 2,
                               valid_from=T2, gc_id=gc2), 2)
        history = HistoryService(db, GraphRepository(db))
        r_default = history.get_edge_history("edge:ab", as_of=T3)
        r_conn = history.get_edge_history("edge:ab", as_of=T3, conn=db._conn)
        assert r_default.to_dict() == r_conn.to_dict()
        rd = history.resolve_edge_as_of("edge:ab", T3)
        rc = history.resolve_edge_as_of("edge:ab", T3, conn=db._conn)
        assert rd == rc
