"""Phase 5 M8 — Knowledge Context Builder 测试。

覆盖（Decision #38.6 + 任务书 §47/48/50）：
- Golden H：context 结构（graph + Evidence summaries + epistemic + limitations + conflicts=[]）
- Evidence lineage：summary 字段（不含 excerpt）、source_id/raw_item_id 保留
- Governance evidence_ids=[] 合法（不误报 QUERY_EVIDENCE_MISSING）
- Evidence 缺失/损坏/wrong-type/schema/identity/column 冲突 → fail-closed
- Evidence retrieved after as_of 仍作为 provenance 可见（不按 retrieved_at 过滤）
- graph 与 Evidence 同一 read snapshot（writer 修改不可见，任务书 §50）
- MAX_EVIDENCE hard limit
- context 禁止投资结论字段
"""
from __future__ import annotations

import json
import uuid

import pytest

from research_os.models import Entity, Evidence, GraphChange, GraphEdge, GraphNode
from research_os.storage.db import Database
from research_os.knowledge.candidate_repository import (
    GraphChangeCandidateRepository,
)
from research_os.knowledge.context_builder import (
    EVIDENCE_SUMMARY_FIELDS,
    KnowledgeContextBuilder,
)
from research_os.knowledge.query import GraphQueryService, QueryError

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"
T3 = "2026-08-10T09:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
EVIDENCE_UUID2 = "44444444-4444-4444-4444-444444444444"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _insert_evidence(db, eid, *, tier="B", published_at=None, retrieved_at=None):
    ev = Evidence(
        evidence_id=eid,
        source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID,
        title=f"证据-{eid[-8:]}",
        publisher="测试发布者",
        published_at=published_at or "2026-08-01T10:00:00+08:00",
        retrieved_at=retrieved_at or "2026-08-02T10:00:00+08:00",
        url="https://example.com",
        excerpt="测试摘录",
        evidence_type="news_report",
        independence_group="group-1",
        source_tier=tier,
        access_status="ok",
    )
    db._conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (eid, _canonical(ev.model_dump()), SOURCE_UUID,
         RAW_ITEM_UUID, "group-1", tier),
    )
    db._conn.commit()
    return ev


def _setup_db(tmp_path):
    db_path = tmp_path / "m8ctx.db"
    db = Database(db_path)
    db.initialize()
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
    db._conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    for eid, etype, name in (
        ("company:a", "company", "公司A"),
        ("company:b", "company", "公司B"),
        ("industry:semi", "industry", "半导体"),
    ):
        entity = Entity(entity_id=eid, entity_type=etype, canonical_name=name)
        db._conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, _canonical(entity.model_dump()), etype, name),
        )
    db._conn.commit()
    _insert_evidence(db, EVIDENCE_UUID)
    return db, db_path


def _gc_exists(db, gc_id):
    row = db._conn.execute(
        "SELECT 1 FROM graph_changes WHERE graph_change_id = ?", (gc_id,)
    ).fetchone()
    return row is not None


def _ensure_gc(db, payload, version, kind):
    gc_id = payload.get("originating_graph_change_id")
    if gc_id is None or _gc_exists(db, gc_id):
        return gc_id
    if kind == "node":
        node_dict = dict(payload)
        node_dict["review_status"] = "candidate"
        node_dict["last_reviewed_at"] = None
        gc = GraphChange(
            graph_change_id=gc_id, change_type="add_node",
            node=GraphNode(**node_dict), edge=None,
            current_knowledge="{}", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="构造", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate",
            created_at=T0, reviewed_at=None,
        )
    else:
        edge_dict = dict(payload)
        edge_dict["review_status"] = "candidate"
        edge_dict["last_reviewed_at"] = None
        gc = GraphChange(
            graph_change_id=gc_id, change_type="add_edge",
            node=None, edge=GraphEdge(**edge_dict),
            current_knowledge="{}", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="构造", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate",
            created_at=T0, reviewed_at=None,
        )
    GraphChangeCandidateRepository(db).append_candidate(gc)
    return gc_id


def _insert_node(db, node_id, version=1, *, gc_id=None,
                 origin_kind="graph_change", evidence_ids=(EVIDENCE_UUID,),
                 node_type=None):
    gc_id = gc_id or (None if origin_kind == "governance_seed"
                      else str(uuid.uuid4()))
    node_type = node_type or (
        "Industry" if node_id.startswith("industry:") else "Company")
    payload = {
        "node_id": node_id,
        "node_type": node_type,
        "name": node_id,
        "aliases": [],
        "description": "测试节点",
        "status": "active",
        "valid_from": None,
        "valid_to": None,
        "evidence_ids": list(evidence_ids),
        "version": version,
        "last_reviewed_at": T1,
        "review_status": "approved",
        "origin_kind": origin_kind,
        "originating_graph_change_id": gc_id,
        "created_at": T0,
    }
    _ensure_gc(db, payload, version, "node")
    db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (node_id, version, _canonical(payload), node_type, node_id, "active",
         "approved", origin_kind, T0, None, None, T1, gc_id),
    )
    db._conn.commit()


def _insert_edge(db, edge_id, src, rel, tgt, *, assertion_type="FACT",
                 evidence_ids=(EVIDENCE_UUID,), gc_id=None):
    gc_id = gc_id or (None if assertion_type == "GOVERNANCE"
                      else str(uuid.uuid4()))
    payload = {
        "edge_id": edge_id,
        "source_node_id": src,
        "relation": rel,
        "target_node_id": tgt,
        "attributes": {},
        "assertion_type": assertion_type,
        "valid_from": None,
        "valid_to": None,
        "confidence": 0.9,
        "evidence_ids": list(evidence_ids),
        "review_status": "approved",
        "version": 1,
        "originating_graph_change_id": gc_id,
        "created_at": T0,
        "last_reviewed_at": T1,
    }
    _ensure_gc(db, payload, 1, "edge")
    db._conn.execute(
        "INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, valid_from, valid_to, confidence, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (edge_id, 1, _canonical(payload), src, rel, tgt, assertion_type,
         "approved", T0, None, None, 0.9, T1, gc_id),
    )
    db._conn.commit()


def _builder(db):
    return KnowledgeContextBuilder(GraphQueryService(db))


def _mk_graph(db):
    _insert_node(db, "company:a")
    _insert_node(db, "company:b")
    _insert_edge(db, "edge:ab", "company:a", "SUPPLIES", "company:b")


# ── Golden H / 结构 ─────────────────────────────────────────

class TestContextStructure:
    def test_golden_h_context(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        ctx = _builder(db).build("company:a", T2, max_depth=1)
        d = ctx.to_dict()
        assert d["as_of"] == T2
        assert d["root"]["node_id"] == "company:a"
        assert {w["node_id"] for w in d["nodes"]} == {"company:a", "company:b"}
        assert [w["edge_id"] for w in d["edges"]] == ["edge:ab"]
        assert d["epistemic"]["facts"] == ["edge:ab"]
        assert d["evidence_ids"] == [EVIDENCE_UUID]
        assert d["conflicts"] == []
        codes = {l["code"] for l in d["limitations"]}
        assert {"BUSINESS_VALIDITY_TIME_ONLY", "PATHS_NOT_CAUSAL",
                "DEPTH_BOUNDED"} <= codes

    def test_context_evidence_summary_fields(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        ctx = _builder(db).build("company:a", T2, max_depth=1)
        assert len(ctx.evidence) == 1
        summary = ctx.evidence[0]
        assert set(summary.keys()) == set(EVIDENCE_SUMMARY_FIELDS)
        assert "excerpt" not in summary
        assert summary["evidence_id"] == EVIDENCE_UUID
        assert summary["source_id"] == SOURCE_UUID
        assert summary["raw_item_id"] == RAW_ITEM_UUID
        assert summary["source_tier"] == "B"
        assert summary["independence_group"] == "group-1"

    def test_governance_evidence_empty_ok(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, "industry:semi", origin_kind="governance_seed",
                     evidence_ids=[])
        _insert_node(db, "industry:ai-hardware",
                     origin_kind="governance_seed", evidence_ids=[])
        _insert_edge(db, "edge:gov", "industry:semi", "BELONGS_TO",
                     "industry:ai-hardware", assertion_type="GOVERNANCE",
                     evidence_ids=[])
        ctx = _builder(db).build("industry:semi", T2, max_depth=1)
        assert ctx.evidence == []
        assert ctx.evidence_ids == []
        assert ctx.epistemic["governance"] == ["edge:gov"]

    def test_context_no_investment_conclusion(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        d = _builder(db).build("company:a", T2, max_depth=1).to_dict()
        banned = {"target_price", "rating", "buy", "sell", "position",
                  "recommendation", "investment_conclusion", "paths"}
        assert not (banned & set(d.keys()))
        for w in d["nodes"] + d["edges"]:
            assert not (banned & set(w.keys()))

    def test_evidence_retrieved_after_as_of_still_visible(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        # evidence retrieved_at 晚于 as_of：作为 immutable provenance 输出，不过滤
        _insert_evidence(db, EVIDENCE_UUID2, retrieved_at=T3)
        _insert_node(db, "company:a", evidence_ids=[EVIDENCE_UUID2])
        _insert_node(db, "company:b")
        _insert_edge(db, "edge:ab", "company:a", "SUPPLIES", "company:b",
                     evidence_ids=[EVIDENCE_UUID2])
        ctx = _builder(db).build("company:a", T1, max_depth=1)
        # evidence retrieved_at 晚于 as_of 仍作为 provenance 输出（不过滤）
        found = [e for e in ctx.evidence if e["evidence_id"] == EVIDENCE_UUID2]
        assert len(found) == 1
        assert found[0]["retrieved_at"] == T3  # 时间事实仍完整输出


# ── Evidence 攻击（fail-closed）─────────────────────────────

class TestEvidenceAttacks:
    def test_evidence_missing(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _insert_node(db, "company:a", evidence_ids=["99999999-9999-9999-9999-999999999999"])
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=0)
        assert ei.value.error_code == "QUERY_EVIDENCE_MISSING"

    def test_evidence_malformed_json(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            ("{broken", EVIDENCE_UUID))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EVIDENCE_INVALID"

    def test_evidence_wrong_top_level(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            ("[1,2,3]", EVIDENCE_UUID))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EVIDENCE_INVALID"

    def test_evidence_schema_invalid(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        row = db._conn.execute(
            "SELECT payload FROM evidence WHERE evidence_id = ?",
            (EVIDENCE_UUID,)).fetchone()
        bad = json.loads(row["payload"])
        del bad["title"]  # required 字段缺失
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            (_canonical(bad), EVIDENCE_UUID))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EVIDENCE_INVALID"

    def test_evidence_identity_mismatch(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        row = db._conn.execute(
            "SELECT payload FROM evidence WHERE evidence_id = ?",
            (EVIDENCE_UUID,)).fetchone()
        bad = json.loads(row["payload"])
        bad["evidence_id"] = EVIDENCE_UUID2  # payload identity 与 DB 主键不一致
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            (_canonical(bad), EVIDENCE_UUID))
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EVIDENCE_INTEGRITY_CONFLICT"

    def test_evidence_column_mismatch(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        _mk_graph(db)
        db._conn.execute(
            "UPDATE evidence SET source_tier = 'S' WHERE evidence_id = ?",
            (EVIDENCE_UUID,))  # column 与 payload(source_tier=B) 不一致
        db._conn.commit()
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=1)
        assert ei.value.error_code == "QUERY_EVIDENCE_INTEGRITY_CONFLICT"

    def test_max_evidence_exceeded(self, tmp_path, monkeypatch):
        monkeypatch.setattr("research_os.knowledge.query.MAX_EVIDENCE", 1)
        db, _ = _setup_db(tmp_path)
        _insert_evidence(db, EVIDENCE_UUID2)
        _insert_node(db, "company:a",
                     evidence_ids=[EVIDENCE_UUID, EVIDENCE_UUID2])
        with pytest.raises(QueryError) as ei:
            _builder(db).build("company:a", T2, max_depth=0)
        assert ei.value.error_code == "QUERY_RESULT_LIMIT_EXCEEDED"


# ── graph + Evidence 同一 snapshot（任务书 §50）──────────────

class TestContextSnapshot:
    def test_evidence_same_snapshot_as_graph(self, tmp_path):
        db, db_path = _setup_db(tmp_path)
        _mk_graph(db)
        db.close()

        db_r = Database(db_path)
        db_w = Database(db_path)
        builder = KnowledgeContextBuilder(GraphQueryService(db_r))
        conn = db_r._conn
        conn.execute("BEGIN")
        try:
            qr = builder._query._query_graph_locked(
                conn, "company:a", T2, max_depth=1,
                relation_filters=None, direction="both",
                assertion_types=None)
            # writer 在 graph 读取后、Evidence load 前修改 Evidence（同一时刻提交）
            db_w._conn.execute(
                "UPDATE evidence SET payload = json_set(payload, '$.title', '被篡改') "
                "WHERE evidence_id = ?", (EVIDENCE_UUID,))
            db_w._conn.commit()
            # 同一 snapshot 内 Evidence strict load：看到旧 title（混合状态被阻止）
            summaries = builder._query._strict_read_evidence(
                conn, qr.evidence_ids)
            assert summaries[0]["title"] == "证据-11111111"
        finally:
            conn.execute("ROLLBACK")
            db_r.close()
            db_w.close()
        # 新 context（新 snapshot）：看到 writer 已提交的 Evidence
        db_r2 = Database(db_path)
        ctx = builder.__class__(GraphQueryService(db_r2)).build(
            "company:a", T2, max_depth=1)
        assert ctx.evidence[0]["title"] == "被篡改"
        db_r2.close()
