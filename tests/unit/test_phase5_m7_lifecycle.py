"""Phase 5 M7 — Supersede / Expire / History（apply 侧）测试。

覆盖：
- Golden A: modify node（v1 byte identical、v2 approved、history as_of 切换、v1 superseded）
- Golden B: modify edge（triple/assertion_type 不变、MODEL_INFERENCE 保持）
- Golden C: retire edge（before/at/after retire_at；v1 untouched）
- Golden D: retire node（先 retire incident edges；ACTIVE_INCIDENT_EDGES guard）
- modify/retire 攻击测试（identity mutation / transition / evidence / payload）
- M6 回归（add_node/add_edge 语义不变）
- dry-run 零写入 / 原子性 / concurrent modify conflict / commit failure

真实 SQLite + 真实 schemas + 真实 KnowledgeValidator + 真实 repositories。
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import uuid
from pathlib import Path

import pytest

from research_os.models import (
    GraphChange, GraphNode, GraphEdge, Evidence, Entity,
)
from research_os.knowledge.knowledge_validator import KnowledgeValidator
from research_os.knowledge.review_workflow import ReviewWorkflow
from research_os.knowledge.apply_engine import ApplyEngine, ApplyResult
from research_os.knowledge.history import HistoryService

# ── 常量 ─────────────────────────────────────────────────────
T0 = "2026-08-08T10:00:00+08:00"       # created_at
T1 = "2026-08-08T14:00:00+08:00"       # reviewed_at
T2 = "2026-08-09T09:00:00+08:00"       # transition_at / retire_at
T3 = "2026-08-10T09:00:00+08:00"       # after transition
APPLIED_AT = "2026-08-09T10:00:00+08:00"  # >= reviewed_at

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


# ── helpers（独立实现，不 import 其它测试模块） ─────────────

def _setup_db(tmp_path, raw_item_entities=None):
    """建立最小可 apply 的 SQLite DB（同 M6 测试语义）。"""
    from research_os.storage import Database

    db_path = tmp_path / "m7.db"
    db = Database(db_path)
    db.initialize()
    conn = db._conn

    if raw_item_entities is None:
        raw_item_entities = ["company:test-corp"]

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
    ev_payload = json.dumps(ev.model_dump(), ensure_ascii=False,
                            sort_keys=True, separators=(",", ":"))
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID, ev_payload, SOURCE_UUID, RAW_ITEM_UUID, "group-1", "B"),
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
        "entities": raw_item_entities,
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )

    for eid, ename in [
        ("company:test-corp", "测试公司"),
        ("company:src", "源公司"),
        ("company:tgt", "目标公司"),
    ]:
        entity = Entity(entity_id=eid, entity_type="company",
                        canonical_name=ename)
        ent_payload = json.dumps(entity.model_dump(), ensure_ascii=False,
                                 sort_keys=True, separators=(",", ":"))
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, ent_payload, "company", ename),
        )

    for nid, nname in [("company:src", "源公司"), ("company:tgt", "目标公司")]:
        node_payload = json.dumps({
            "node_id": nid,
            "node_type": "Company",
            "name": nname,
            "status": "active",
            "version": 1,
            "origin_kind": "governance_seed",
            "review_status": "approved",
            "created_at": T0,
            "evidence_ids": [],
        }, ensure_ascii=False)
        conn.execute(
            "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES (?, 1, ?, 'Company', ?, 'active', 'approved', 'governance_seed', ?)",
            (nid, node_payload, nname, T0),
        )

    conn.commit()
    return db, db_path


def _make_components(db):
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.knowledge.repository import GraphRepository

    candidate_repo = GraphChangeCandidateRepository(db)
    graph_repo = GraphRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
    engine = ApplyEngine(db, candidate_repo, graph_repo, validator)
    history = HistoryService(db, graph_repo)
    return candidate_repo, graph_repo, validator, workflow, engine, history


def _make_add_node_candidate(change_id=None, node=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    valid_from = kw.pop("valid_from", None)
    valid_to = kw.pop("valid_to", None)
    node = node or GraphNode(
        node_id="company:test-corp",
        node_type="Company",
        name="测试公司",
        aliases=["测试"],
        description="测试描述",
        status="active",
        valid_from=valid_from,
        valid_to=valid_to,
        evidence_ids=[EVIDENCE_UUID],
        version=1,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id=change_id,
        created_at=T0,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "add_node",
        "node": node,
        "edge": None,
        "current_knowledge": "",
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "添加新公司节点",
        "impact_scope": ["industry_a"],
        "conflicts": [],
        "verification_points": ["验证公司注册信息"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_modify_node_candidate(change_id=None, version=2, valid_from=T2,
                                name="测试公司v2", description="更新后的描述",
                                valid_to=None, evidence_ids=None,
                                current_knowledge=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    # node 级字段从 kw 中提取（不落入 GraphChange 顶层）
    node_id = kw.pop("node_id", "company:test-corp")
    node_type = kw.pop("node_type", "Company")
    status = kw.pop("status", "active")
    aliases = kw.pop("aliases", ["测试"])
    node = GraphNode(
        node_id=node_id,
        node_type=node_type,
        name=name,
        aliases=aliases,
        description=description,
        status=status,
        valid_from=valid_from,
        valid_to=valid_to,
        evidence_ids=evidence_ids or [EVIDENCE_UUID],
        version=version,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id=change_id,
        created_at=T0,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "modify_attribute",
        "node": node,
        "edge": None,
        "current_knowledge": current_knowledge or "",
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "修改节点信息",
        "impact_scope": ["industry_a"],
        "conflicts": [],
        "verification_points": ["验证变更"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_retire_node_candidate(change_id=None, version=2, retire_at=T2,
                                current_knowledge=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    node_id = kw.pop("node_id", "company:test-corp")
    node_type = kw.pop("node_type", "Company")
    name = kw.pop("name", "测试公司")
    aliases = kw.pop("aliases", ["测试"])
    description = kw.pop("description", "测试描述")
    evidence_ids = kw.pop("evidence_ids", [EVIDENCE_UUID])
    new_evidence_ids = kw.pop("new_evidence_ids", [EVIDENCE_UUID])
    node = GraphNode(
        node_id=node_id,
        node_type=node_type,
        name=name,
        aliases=aliases,
        description=description,
        status="retired",
        valid_from=retire_at,
        valid_to=retire_at,
        evidence_ids=evidence_ids,
        version=version,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id=change_id,
        created_at=T0,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "retire_node",
        "node": node,
        "edge": None,
        "current_knowledge": current_knowledge or "",
        "new_evidence_ids": new_evidence_ids,
        "suggested_change": "退休节点",
        "impact_scope": ["industry_a"],
        "conflicts": [],
        "verification_points": ["验证退休"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_add_edge_candidate(change_id=None, edge=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    valid_from = kw.pop("valid_from", None)
    valid_to = kw.pop("valid_to", None)
    assertion_type = kw.pop("assertion_type", "FACT")
    edge = edge or GraphEdge(
        edge_id="edge:test-1",
        source_node_id="company:src",
        relation="COMPETES_WITH",
        target_node_id="company:tgt",
        attributes={},
        assertion_type=assertion_type,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=0.8,
        evidence_ids=[EVIDENCE_UUID],
        review_status="candidate",
        version=1,
        originating_graph_change_id=change_id,
        created_at=T0,
        last_reviewed_at=None,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "add_edge",
        "node": None,
        "edge": edge,
        "current_knowledge": "",
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "添加竞争关系",
        "impact_scope": ["industry_a", "industry_b"],
        "conflicts": [],
        "verification_points": ["验证两家公司存在竞争关系"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_modify_edge_candidate(change_id=None, version=2, valid_from=T2,
                                confidence=0.95, attributes=None,
                                current_knowledge=None, assertion_type="FACT",
                                **kw):
    change_id = change_id or str(uuid.uuid4())
    edge_id = kw.pop("edge_id", "edge:test-1")
    source_node_id = kw.pop("source_node_id", "company:src")
    relation = kw.pop("relation", "COMPETES_WITH")
    target_node_id = kw.pop("target_node_id", "company:tgt")
    valid_to = kw.pop("valid_to", None)
    evidence_ids = kw.pop("evidence_ids", [EVIDENCE_UUID])
    edge = GraphEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        relation=relation,
        target_node_id=target_node_id,
        attributes=attributes or {"detail": "v2"},
        assertion_type=assertion_type,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
        evidence_ids=evidence_ids,
        review_status="candidate",
        version=version,
        originating_graph_change_id=change_id,
        created_at=T0,
        last_reviewed_at=None,
    )
    new_evidence_ids = kw.pop("new_evidence_ids", [EVIDENCE_UUID])
    defaults = {
        "graph_change_id": change_id,
        "change_type": "modify_attribute",
        "node": None,
        "edge": edge,
        "current_knowledge": current_knowledge or "",
        "new_evidence_ids": new_evidence_ids,
        "suggested_change": "修改边属性",
        "impact_scope": ["industry_a", "industry_b"],
        "conflicts": [],
        "verification_points": ["验证修改"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _make_retire_edge_candidate(change_id=None, version=2, retire_at=T2,
                                current_knowledge=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    edge_id = kw.pop("edge_id", "edge:test-1")
    source_node_id = kw.pop("source_node_id", "company:src")
    relation = kw.pop("relation", "COMPETES_WITH")
    target_node_id = kw.pop("target_node_id", "company:tgt")
    attributes = kw.pop("attributes", {})
    assertion_type = kw.pop("assertion_type", "FACT")
    confidence = kw.pop("confidence", 0.8)
    valid_from = kw.pop("valid_from", retire_at)
    valid_to = kw.pop("valid_to", retire_at)
    evidence_ids = kw.pop("evidence_ids", [EVIDENCE_UUID])
    edge = GraphEdge(
        edge_id=edge_id,
        source_node_id=source_node_id,
        relation=relation,
        target_node_id=target_node_id,
        attributes=attributes,
        assertion_type=assertion_type,
        valid_from=valid_from,
        valid_to=valid_to,
        confidence=confidence,
        evidence_ids=evidence_ids,
        review_status="candidate",
        version=version,
        originating_graph_change_id=change_id,
        created_at=T0,
        last_reviewed_at=None,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "retire_edge",
        "node": None,
        "edge": edge,
        "current_knowledge": current_knowledge or "",
        "new_evidence_ids": [EVIDENCE_UUID],
        "suggested_change": "退休边",
        "impact_scope": ["industry_a", "industry_b"],
        "conflicts": [],
        "verification_points": ["验证退休"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    defaults.update(kw)
    return GraphChange(**defaults)


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _import_review(workflow, gc, decision="批准", reviewer_id="reviewer-001",
                   reviewed_at=T1, patch=None):
    """构造填写后审阅 Markdown（M5 冻结 13-heading 格式）并 import；断言成功。"""
    result = _try_import_review(workflow, gc, decision=decision,
                                reviewer_id=reviewer_id,
                                reviewed_at=reviewed_at, patch=patch)
    assert result.status == "ok", f"review_import 失败: {result.errors}"
    return result


def _try_import_review(workflow, gc, decision="批准", reviewer_id="reviewer-001",
                       reviewed_at=T1, patch=None):
    """构造填写后审阅 Markdown 并 import（不断言，供攻击测试检查 fail-closed）。"""
    from research_os.knowledge.review_parser import parse_review_markdown

    candidate_hash = KnowledgeValidator.compute_candidate_hash(gc)
    gc_dump = gc.model_dump()

    sections = []
    sections.append("# 图谱变更候选")
    sections.append("")
    sections.append("## GraphChange ID")
    sections.append("")
    sections.append(f"- **graph_change_id**: `{gc_dump['graph_change_id']}`")
    sections.append(f"- **candidate_hash**: `{candidate_hash}`")
    sections.append("")
    sections.append("## 变更类型")
    sections.append("")
    sections.append(f"- **change_type**: `{gc_dump['change_type']}`")
    sections.append(f"- **review_status**: `{gc_dump['review_status']}`")
    sections.append(f"- **created_at**: {gc_dump['created_at']}")
    sections.append("")
    sections.append("## 当前知识")
    sections.append("")
    if gc_dump.get("current_knowledge"):
        sections.append("```json")
        sections.append(gc_dump["current_knowledge"])
        sections.append("```")
    else:
        sections.append("_（无当前知识——此为新节点/边）_")
    sections.append("")
    sections.append("## 新证据")
    sections.append("")
    sections.append(f"- **{EVIDENCE_UUID}**: 测试证据")
    sections.append("")
    if gc_dump.get("node"):
        sections.append("### 节点")
        sections.append("")
        sections.append(f"- **node_id**: `{gc_dump['node']['node_id']}`")
        sections.append("")
    if gc_dump.get("edge"):
        sections.append("### 边")
        sections.append("")
        sections.append(f"- **edge_id**: `{gc_dump['edge']['edge_id']}`")
        sections.append("")
    sections.append("## 建议变更")
    sections.append("")
    sections.append(gc_dump["suggested_change"])
    sections.append("")
    sections.append("## 影响范围")
    sections.append("")
    for item in gc_dump["impact_scope"]:
        sections.append(f"- {item}")
    sections.append("")
    sections.append("## 冲突信息")
    sections.append("")
    if gc_dump["conflicts"]:
        for item in gc_dump["conflicts"]:
            sections.append(f"- {item}")
    else:
        sections.append("_（无冲突）_")
    sections.append("")
    sections.append("## 验证节点")
    sections.append("")
    sections.append("- [ ] 验证公司注册信息")
    sections.append("")
    sections.append("## 审核选项")
    sections.append("")
    if decision == "批准":
        sections.append("- [x] 批准")
        sections.append("- [ ] 修改后批准")
        sections.append("- [ ] 暂缓")
        sections.append("- [ ] 拒绝")
    elif decision == "修改后批准":
        sections.append("- [ ] 批准")
        sections.append("- [x] 修改后批准")
        sections.append("- [ ] 暂缓")
        sections.append("- [ ] 拒绝")
    elif decision == "拒绝":
        sections.append("- [ ] 批准")
        sections.append("- [ ] 修改后批准")
        sections.append("- [ ] 暂缓")
        sections.append("- [x] 拒绝")
    sections.append("")
    sections.append("## Reviewer")
    sections.append("")
    sections.append("```yaml")
    sections.append("# 请填写以下字段：")
    sections.append("reviewer_type: human")
    sections.append(f'reviewer_id: "{reviewer_id}"      # 必填，非空')
    sections.append('display_name: ""     # 可选')
    sections.append(f'reviewed_at: "{reviewed_at}"      # ISO 8601 datetime，必填')
    sections.append("```")
    sections.append("")
    sections.append("## Review Notes")
    sections.append("")
    sections.append("_（请在此填写审核意见）_")
    sections.append("")
    sections.append("## Approved Patch")
    sections.append("")
    if decision == "修改后批准":
        sections.append(json.dumps(patch, ensure_ascii=False))
    else:
        sections.append("_（仅\"修改后批准\"时填写 JSON Patch 数组）_")
    sections.append("")
    sections.append("---")
    sections.append("*本文件为审阅模板，请填写后通过 review-import 导入。*")
    md = "\n".join(sections)

    # 不断言：直接交给 review_import，其内部 parse/M4 失败返回 error result
    return workflow.review_import(md)


def _apply_and_assert(engine, gc, expected="applied", applied_at=APPLIED_AT,
                      **kw):
    result = engine.apply(gc.graph_change_id, applied_at=applied_at, **kw)
    if expected in ("applied", "idempotent_noop"):
        assert result.status == expected, (
            f"apply 失败: {result.error_code} {result.errors}"
        )
    else:
        assert result.status == "APPLY_REJECTED", result.status
        assert result.error_code == expected, (
            f"error_code={result.error_code}，期望 {expected}；{result.errors}"
        )
    return result


def _seed_node_v1(db, candidate_repo, workflow, engine, applied_at=APPLIED_AT):
    """add_node v1 apply 并返回 v1 candidate（供后续 modify/retire 基线）。"""
    gc = _make_add_node_candidate()
    candidate_repo.append_candidate(gc)
    _import_review(workflow, gc, decision="批准")
    _apply_and_assert(engine, gc, applied_at=applied_at)
    return gc


def _current_knowledge_of(graph_repo, kind, identity, version):
    if kind == "node":
        payload = graph_repo.get_node_version(identity, version)
    else:
        payload = graph_repo.get_edge_version(identity, version)
    assert payload is not None, f"{kind} {identity} v{version} 不存在"
    return _canonical(payload)


def _count_table(db, table):
    row = db._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def _add_second_evidence(db, evidence_id, published_at, retrieved_at):
    """插入第二条 Evidence（entities 覆盖 company:test-corp / src/tgt）。"""
    conn = db._conn
    ri2_id = "44444444-4444-4444-4444-444444444444"
    ev = Evidence(
        evidence_id=evidence_id,
        source_id=SOURCE_UUID,
        raw_item_id=ri2_id,
        title="第二证据",
        publisher="测试",
        published_at=published_at,
        retrieved_at=retrieved_at,
        url="https://example.com/2",
        excerpt="第二摘录",
        evidence_type="news_report",
        independence_group="group-2",
        source_tier="B",
        access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (evidence_id, _canonical(ev.model_dump()), SOURCE_UUID, ri2_id,
         "group-2", "B"),
    )
    ri_payload = json.dumps({
        "raw_item_id": ri2_id,
        "source_id": SOURCE_UUID,
        "external_id": "ext-002",
        "url": "https://example.com/2",
        "title": "第二原始",
        "publisher": "测试",
        "author": "作者",
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "content_hash": SHA256_ZEROS,
        "content_excerpt": "第二摘录",
        "content_storage": "metadata_and_excerpt",
        "language": "zh-CN",
        "access_status": "ok",
        "entities": ["company:test-corp", "company:src", "company:tgt"],
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (ri2_id, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# Golden A — modify node
# ═══════════════════════════════════════════════════════════════

class TestGoldenAModifyNode:
    """Golden A：node v1 → candidate modify → approved → apply → v2。"""

    def test_modify_node_full_flow(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))

        # v1
        gc1 = _seed_node_v1(db, candidate_repo, workflow, engine)
        v1_payload = graph_repo.get_node_version("company:test-corp", 1)
        assert v1_payload is not None

        # modify → v2
        gc2 = _make_modify_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1),
        )
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        r2 = _apply_and_assert(engine, gc2)

        # v1 byte identical
        v1_after = graph_repo.get_node_version("company:test-corp", 1)
        assert _canonical(v1_after) == _canonical(v1_payload), \
            "v1 必须 byte-for-byte 保留（append-only）"
        # v2 approved + version=2
        v2 = graph_repo.get_node_version("company:test-corp", 2)
        assert v2 is not None
        assert v2["version"] == 2
        assert v2["review_status"] == "approved"
        assert v2["name"] == "测试公司v2"
        assert v2["valid_from"] == T2
        assert r2.target_version == 2

        # history：as_of before transition → v1；at transition → v2；v1 superseded
        hist_before = history.get_node_history("company:test-corp",
                                               as_of=T1)
        assert hist_before.resolved["version"] == 1
        assert hist_before.resolved["derived_status"] == "active"
        assert hist_before.resolved["is_active"] is True

        hist_at = history.get_node_history("company:test-corp", as_of=T2)
        assert hist_at.resolved["version"] == 2
        assert hist_at.resolved["derived_status"] == "active"
        # v1 derived superseded（as_of=T2 时）
        v1_entry = hist_at.versions[0]
        assert v1_entry.version == 1
        assert v1_entry.superseded_by_version == 2
        assert v1_entry.derived_status == "superseded"
        db.close()

    def test_exact_replay_modify_idempotent(self, tmp_path):
        """Golden A replay：modify 重复 apply → IDEMPOTENT_NOOP。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        gc2 = _make_modify_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        r1 = _apply_and_assert(engine, gc2)
        r2 = _apply_and_assert(engine, gc2, expected="idempotent_noop")
        assert r2.application_id == r1.application_id
        assert _count_table(db, "graph_nodes") == 4  # src + tgt + test-corp v1 + v2
        assert _count_table(db, "graph_applications") == 2
        db.close()

    def test_modify_v2_gap_to_v3(self, tmp_path):
        """连续两次 modify：v2 → v3，version chain 连续。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        v2_t = "2026-08-09T09:00:00+08:00"
        gc2 = _make_modify_node_candidate(
            version=2, valid_from=v2_t, name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        v3_t = "2026-08-10T09:00:00+08:00"
        gc3 = _make_modify_node_candidate(
            version=3, valid_from=v3_t, name="v3",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 2))
        candidate_repo.append_candidate(gc3)
        _import_review(workflow, gc3, decision="批准")
        _apply_and_assert(engine, gc3)

        hist = history.get_node_history("company:test-corp", as_of=v3_t)
        assert hist.resolved["version"] == 3
        assert [e.version for e in hist.versions] == [1, 2, 3]
        assert hist.versions[1].superseded_by_version == 3
        db.close()


# ═══════════════════════════════════════════════════════════════
# Golden B — modify edge
# ═══════════════════════════════════════════════════════════════

class TestGoldenBModifyEdge:
    """Golden B：edge v1 → change attributes/confidence → v2。"""

    def _seed_edge_v1(self, db, candidate_repo, workflow, engine,
                      assertion_type="FACT"):
        gc = _make_add_edge_candidate(assertion_type=assertion_type)
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        _apply_and_assert(engine, gc)
        return gc

    def test_modify_edge_full_flow(self, tmp_path):
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        self._seed_edge_v1(db, candidate_repo, workflow, engine)

        gc2 = _make_modify_edge_candidate(
            confidence=0.95,
            attributes={"detail": "v2"},
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        v2 = graph_repo.get_edge_version("edge:test-1", 2)
        assert v2 is not None
        assert v2["edge_id"] == "edge:test-1"
        assert v2["source_node_id"] == "company:src"
        assert v2["relation"] == "COMPETES_WITH"
        assert v2["target_node_id"] == "company:tgt"
        assert v2["assertion_type"] == "FACT"
        assert v2["confidence"] == 0.95
        assert v2["version"] == 2

        hist = history.get_edge_history("edge:test-1", as_of=T2)
        assert hist.resolved["version"] == 2
        assert hist.versions[0].superseded_by_version == 2
        db.close()

    def test_model_inference_stays_model_inference(self, tmp_path):
        """MODEL_INFERENCE modify 后仍为 MODEL_INFERENCE（不 promotion）。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        self._seed_edge_v1(db, candidate_repo, workflow, engine,
                           assertion_type="MODEL_INFERENCE")

        gc2 = _make_modify_edge_candidate(
            assertion_type="MODEL_INFERENCE",
            confidence=0.9,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        v2 = graph_repo.get_edge_version("edge:test-1", 2)
        assert v2["assertion_type"] == "MODEL_INFERENCE"
        db.close()


# ═══════════════════════════════════════════════════════════════
# Golden C — retire edge
# ═══════════════════════════════════════════════════════════════

class TestGoldenCRetireEdge:
    """Golden C：edge v1 active → retire_edge v2 tombstone。"""

    def test_retire_edge_full_flow(self, tmp_path):
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        v1_payload = graph_repo.get_edge_version("edge:test-1", 1)

        gc2 = _make_retire_edge_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        v2 = graph_repo.get_edge_version("edge:test-1", 2)
        assert v2 is not None
        assert v2["valid_from"] == T2
        assert v2["valid_to"] == T2
        # v1 untouched
        assert _canonical(graph_repo.get_edge_version("edge:test-1", 1)) \
            == _canonical(v1_payload)

        # before retire_at → active；at → retired；after → retired
        before = history.get_edge_history("edge:test-1", as_of=T1)
        assert before.resolved["version"] == 1
        assert before.resolved["derived_status"] == "active"
        at = history.get_edge_history("edge:test-1", as_of=T2)
        assert at.resolved["version"] == 2
        assert at.resolved["derived_status"] == "retired"
        assert at.resolved["is_active"] is False
        after = history.get_edge_history("edge:test-1", as_of=T3)
        assert after.resolved["version"] == 2
        assert after.resolved["derived_status"] == "retired"
        db.close()


# ═══════════════════════════════════════════════════════════════
# Golden D — retire node（先 retire incident edges）
# ═══════════════════════════════════════════════════════════════

class TestGoldenDRetireNode:
    """Golden D：retire incident edges → 再 retire node。"""

    def _setup_node_with_incident_edge(self, tmp_path):
        db, _ = _setup_db(
            tmp_path,
            raw_item_entities=["company:src", "company:tgt", "company:test-corp"])
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        # node v1（company:test-corp）
        _seed_node_v1(db, candidate_repo, workflow, engine)
        # incident edge：src → test-corp（origin 必须等于该 candidate 的 gc_id）
        incident_gc_id = str(uuid.uuid4())
        edge = GraphEdge(
            edge_id="edge:incident",
            source_node_id="company:src",
            relation="COMPETES_WITH",
            target_node_id="company:test-corp",
            attributes={},
            assertion_type="FACT",
            valid_from=None,
            valid_to=None,
            confidence=0.8,
            evidence_ids=[EVIDENCE_UUID],
            review_status="candidate",
            version=1,
            originating_graph_change_id=incident_gc_id,
            created_at=T0,
            last_reviewed_at=None,
        )
        gc_e = _make_add_edge_candidate(edge=edge,
                                        graph_change_id=incident_gc_id)
        candidate_repo.append_candidate(gc_e)
        _import_review(workflow, gc_e, decision="批准")
        _apply_and_assert(engine, gc_e)
        return db, candidate_repo, graph_repo, workflow, engine, history

    def test_node_retire_blocked_by_active_edge(self, tmp_path):
        """active incident edge → ACTIVE_INCIDENT_EDGES，0 writes。"""
        db, candidate_repo, graph_repo, workflow, engine, _ = (
            self._setup_node_with_incident_edge(tmp_path))
        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        gc_r = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        result = _apply_and_assert(engine, gc_r, expected="ACTIVE_INCIDENT_EDGES")

        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before
        db.close()

    def test_retire_edges_then_node(self, tmp_path):
        """先 retire incident edge → 再 retire node 成功。"""
        db, candidate_repo, graph_repo, workflow, engine, history = (
            self._setup_node_with_incident_edge(tmp_path))

        # retire incident edge first（triple 必须与 incident edge 一致：
        # source=company:src, relation=COMPETES_WITH, target=company:test-corp）
        gc_re = _make_retire_edge_candidate(
            edge_id="edge:incident",
            target_node_id="company:test-corp",
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:incident", 1))
        candidate_repo.append_candidate(gc_re)
        _import_review(workflow, gc_re, decision="批准")
        _apply_and_assert(engine, gc_re)

        # now retire node
        gc_rn = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_rn)
        _import_review(workflow, gc_rn, decision="批准")
        _apply_and_assert(engine, gc_rn)

        node_v2 = graph_repo.get_node_version("company:test-corp", 2)
        assert node_v2["status"] == "retired"
        assert node_v2["valid_from"] == node_v2["valid_to"] == T2

        # history：retire_at 后 retired
        hist = history.get_node_history("company:test-corp", as_of=T3)
        assert hist.resolved["version"] == 2
        assert hist.resolved["derived_status"] == "retired"
        db.close()

    def test_expired_edge_does_not_block(self, tmp_path):
        """edge 在 node retire_at 前已 expired → 不阻塞。"""
        db, candidate_repo, graph_repo, workflow, engine, _ = (
            self._setup_node_with_incident_edge(tmp_path))

        # incident edge 先 retire at earlier time，再 retire node at T2
        gc_re = _make_retire_edge_candidate(
            edge_id="edge:incident", target_node_id="company:test-corp",
            retire_at=T2,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:incident", 1))
        candidate_repo.append_candidate(gc_re)
        _import_review(workflow, gc_re, decision="批准")
        _apply_and_assert(engine, gc_re)

        gc_rn = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_rn)
        _import_review(workflow, gc_rn, decision="批准")
        _apply_and_assert(engine, gc_rn)
        db.close()


# ═══════════════════════════════════════════════════════════════
# Golden E — expiry / Golden F — future transition
# ═══════════════════════════════════════════════════════════════

class TestGoldenEFutureTransition:
    """Golden E：single version valid_to=T → expired；Golden F：future v2。"""

    def test_single_version_expiry(self, tmp_path):
        """Golden E：一个 version valid_to=T，无 successor。
        as_of < T → active；== T → expired；> T → expired。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        expiry_t = "2026-08-09T09:00:00+08:00"
        gc = _make_add_node_candidate(valid_to=expiry_t)
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        _apply_and_assert(engine, gc)

        before = history.get_node_history("company:test-corp",
                                          as_of="2026-08-09T08:59:00+08:00")
        assert before.resolved["derived_status"] == "active"
        at = history.get_node_history("company:test-corp", as_of=expiry_t)
        assert at.resolved["derived_status"] == "expired"
        assert at.resolved["is_active"] is False
        after = history.get_node_history("company:test-corp",
                                         as_of="2026-08-10T09:00:00+08:00")
        assert after.resolved["derived_status"] == "expired"
        db.close()

    def test_future_transition_not_visible_early(self, tmp_path):
        """Golden F：v2 valid_from=future T2；as_of < T2 → v1（不得提前生效）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        gc2 = _make_modify_node_candidate(
            version=2, valid_from=T2, name="future",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)
        # v2 已 persisted
        assert graph_repo.get_node_version("company:test-corp", 2) is not None

        # as_of < T2 → 仍 resolve v1（v2 未生效）
        hist = history.get_node_history("company:test-corp", as_of=T1)
        assert hist.resolved["version"] == 1
        assert hist.resolved["derived_status"] == "active"
        # as_of == T2 → v2 接管
        hist2 = history.get_node_history("company:test-corp", as_of=T2)
        assert hist2.resolved["version"] == 2
        assert hist2.versions[0].derived_status == "superseded"
        db.close()

    def test_gap_between_expiry_and_later_successor(self, tmp_path):
        """43. gap：v1 valid_to=T1 < v2 valid_from=T2 → gap 不填平。

        M7 apply 禁止在 expired 后产生 successor（MODIFY_TARGET_NOT_ACTIVE），
        因此 gap 只能来自历史遗留数据；这里用 SQL 直接构造（完整
        GraphChange origin 链），验证 history 语义：
        - gap 时点 resolved v1 expired
        - T2 后 resolved v2 active
        """
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        expiry_t = "2026-08-09T08:00:00+08:00"  # T1 < T2
        gc1 = _make_add_node_candidate(valid_to=expiry_t)
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)

        # 构造 v2 modify candidate（不 apply），直接 INSERT 为 persisted v2
        gc2 = _make_modify_node_candidate(
            version=2, valid_from=T2, name="later",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        v2_node = gc2.node.model_copy(
            update={"review_status": "approved", "last_reviewed_at": T1})
        db._conn.execute(
            "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("company:test-corp", 2, _canonical(v2_node.model_dump()),
             "Company", "later", "active", "approved", "graph_change", T0,
             T2, None, T1, gc2.graph_change_id),
        )
        db._conn.commit()

        # gap 时点：T1 ~ T2 → expired（v1），不得填平为 active
        gap_t = "2026-08-09T08:30:00+08:00"
        hist = history.get_node_history("company:test-corp", as_of=gap_t)
        assert hist.resolved["version"] == 1
        assert hist.resolved["derived_status"] == "expired"
        # T2 后 → v2
        hist2 = history.get_node_history("company:test-corp", as_of=T2)
        assert hist2.resolved["version"] == 2
        assert hist2.resolved["derived_status"] == "active"
        db.close()


# ═══════════════════════════════════════════════════════════════
# M7 modify / retire 攻击测试（apply 侧）
# ═══════════════════════════════════════════════════════════════

class TestM7ModifyAttacks:
    """modify_attribute 攻击（apply 侧 gates）。"""

    def _seed_v1(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        return db, candidate_repo, graph_repo, workflow, engine

    def _modify(self, db, candidate_repo, graph_repo, workflow, engine, **kw):
        gc = _make_modify_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1),
            **kw)
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        return engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

    def test_modify_missing_target(self, tmp_path):
        """1. modify missing target → M4 fail-closed（KGV-013/KGV-019 拦截）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        gc = _make_modify_node_candidate(
            current_knowledge=_canonical(_make_add_node_candidate()
                                         .node.model_dump()))
        candidate_repo.append_candidate(gc)
        result = _try_import_review(workflow, gc, decision="批准")
        assert result.status != "ok", "modify missing target 必须 fail-closed"
        db.close()

    def test_modify_identity_mutation_node_id(self, tmp_path):
        """4. identity mutation node_id → M4 fail-closed（entity/version 拒绝）。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        gc = _make_modify_node_candidate(
            node_id="company:other-corp",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        # M4 在 review 阶段即拦截（KGV-002 entity / KGV-013 version）
        result = _try_import_review(workflow, gc, decision="批准")
        assert result.status != "ok", "identity mutation 必须 fail-closed"
        db.close()

    def test_modify_identity_mutation_node_type(self, tmp_path):
        """5. identity mutation node_type → M4 fail-closed（KGV-002 entity_type /
        KGV-009 Industry 保护先拦截）。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        gc = _make_modify_node_candidate(
            node_type="Industry",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        result = _try_import_review(workflow, gc, decision="批准")
        assert result.status != "ok", "node_type mutation 必须 fail-closed"
        db.close()

    def test_modify_no_effective_change(self, tmp_path):
        """10. no effective business change → NO_EFFECTIVE_CHANGE。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        result = self._modify(db, candidate_repo, graph_repo, workflow, engine,
                              name="测试公司", description="测试描述")
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "NO_EFFECTIVE_CHANGE"
        db.close()

    def test_modify_transition_time_missing(self, tmp_path):
        """11. transition time missing → TRANSITION_TIME_MISSING。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        result = self._modify(db, candidate_repo, graph_repo, workflow, engine,
                              valid_from=None)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "TRANSITION_TIME_MISSING"
        db.close()

    def test_modify_transition_time_invalid_iso(self, tmp_path):
        """12. transition time invalid ISO → 拒绝（candidate schema 或
        TRANSITION_TIME_INVALID）。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        try:
            gc = _make_modify_node_candidate(
                valid_from="not-a-time",
                current_knowledge=_current_knowledge_of(
                    graph_repo, "node", "company:test-corp", 1))
        except Exception:
            db.close()
            return  # Pydantic 层已拒绝（fail-closed）
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("TRANSITION_TIME_INVALID",
                                     "M4_APPLY_PREFLIGHT_FAILED",
                                     "CANDIDATE_SCHEMA_INVALID")
        db.close()

    def test_modify_retrograde_transition(self, tmp_path):
        """13. retrograde transition → TRANSITION_TIME_NOT_MONOTONIC。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        # v1.valid_from 为 null（unbounded past），构造 v2 前先建一个带
        # valid_from 的 v2，再尝试 retrograde v3。
        v2_t = "2026-08-10T09:00:00+08:00"
        gc2 = _make_modify_node_candidate(
            version=2, valid_from=v2_t, name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        _apply_and_assert(engine, gc2)

        # v3.valid_from < v2.valid_from → retrograde
        gc3 = _make_modify_node_candidate(
            version=3, valid_from="2026-08-09T09:00:00+08:00", name="v3",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 2))
        candidate_repo.append_candidate(gc3)
        _import_review(workflow, gc3, decision="批准")
        result = engine.apply(gc3.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "TRANSITION_TIME_NOT_MONOTONIC"
        db.close()

    def test_modify_valid_from_gt_valid_to(self, tmp_path):
        """14. valid_from > valid_to → M4 KGV-014 拒绝。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        result = self._modify(db, candidate_repo, graph_repo, workflow, engine,
                              valid_from=T3, valid_to=T2)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("M4_APPLY_PREFLIGHT_FAILED",
                                     "M4_REVIEW_VALIDATION_FAILED",
                                     "M4_REPLACEMENT_VALIDATION_FAILED")
        db.close()

    def test_modify_retired_target(self, tmp_path):
        """2. modify retired target → MODIFY_TARGET_NOT_ACTIVE。"""
        db, candidate_repo, graph_repo, workflow, engine, _ = (
            self._seed_retired_node(tmp_path))
        gc = _make_modify_node_candidate(
            version=3,
            name="复活尝试",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 2))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "MODIFY_TARGET_NOT_ACTIVE"
        db.close()

    def test_modify_expired_target(self, tmp_path):
        """3. modify already-expired target → MODIFY_TARGET_NOT_ACTIVE。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        # v1 with valid_to 早于 transition
        expiry_t = "2026-08-09T08:00:00+08:00"
        gc1 = _make_add_node_candidate(valid_to=expiry_t)
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)

        gc2 = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        result = engine.apply(gc2.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "MODIFY_TARGET_NOT_ACTIVE"
        db.close()

    def _seed_retired_node(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        gc_r = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        _apply_and_assert(engine, gc_r)
        return db, candidate_repo, graph_repo, workflow, engine, None

    def test_modify_status_change_rejected(self, tmp_path):
        """modify 不得 active → retired（必须走 retire_node）。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        gc = _make_modify_node_candidate(
            status="retired",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "MODIFY_STATUS_CHANGE"
        db.close()

    def test_modify_edge_identity_mutation(self, tmp_path):
        """6-8. edge identity mutation（edge_id/triple → M4 fail-closed；
        assertion_type 偷换 → M7 IMMUTABLE_IDENTITY_CHANGED）。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)
        ck = _current_knowledge_of(graph_repo, "edge", "edge:test-1", 1)

        # 6-8a. edge_id / source / relation / target mutation → M4 import fail-closed
        for kwargs in [
            {"edge_id": "edge:other"},
            {"source_node_id": "company:other"},
            {"relation": "SUPPLIES"},
        ]:
            gc = self._make_edge_modify_with(current_knowledge=ck, **kwargs)
            candidate_repo.append_candidate(gc)
            result = _try_import_review(workflow, gc, decision="批准")
            assert result.status != "ok", f"identity mutation 必须 fail-closed: {kwargs}"

        # 8b. assertion_type FACT → MODEL_INFERENCE（偷换 epistemic class）
        #     通过 M4（MODEL_INFERENCE 有证据、无 tier 下限）→ M7 gate 拒绝
        gc8 = self._make_edge_modify_with(
            current_knowledge=ck, assertion_type="MODEL_INFERENCE")
        candidate_repo.append_candidate(gc8)
        _import_review(workflow, gc8, decision="批准")
        result = engine.apply(gc8.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "IMMUTABLE_IDENTITY_CHANGED"
        db.close()

    def _make_edge_modify_with(self, **kw):
        """构造 modify_edge candidate，支持覆盖 GraphEdge 字段。"""
        change_id = str(uuid.uuid4())
        base = GraphEdge(
            edge_id=kw.pop("edge_id", "edge:test-1"),
            source_node_id=kw.pop("source_node_id", "company:src"),
            relation=kw.pop("relation", "COMPETES_WITH"),
            target_node_id=kw.pop("target_node_id", "company:tgt"),
            attributes=kw.pop("attributes", {"detail": "v2"}),
            assertion_type=kw.pop("assertion_type", "FACT"),
            valid_from=kw.pop("valid_from", T2),
            valid_to=kw.pop("valid_to", None),
            confidence=kw.pop("confidence", 0.95),
            evidence_ids=kw.pop("evidence_ids", [EVIDENCE_UUID]),
            review_status="candidate",
            version=kw.pop("version", 2),
            originating_graph_change_id=change_id,
            created_at=T0,
            last_reviewed_at=None,
        )
        defaults = {
            "graph_change_id": change_id,
            "change_type": "modify_attribute",
            "node": None,
            "edge": base,
            "current_knowledge": kw.pop(
                "current_knowledge",
                _canonical(_make_add_edge_candidate().edge.model_dump())),
            "new_evidence_ids": [EVIDENCE_UUID],
            "suggested_change": "修改边属性",
            "impact_scope": ["industry_a", "industry_b"],
            "conflicts": [],
            "verification_points": ["验证修改"],
            "review_status": "candidate",
            "created_at": T0,
            "reviewed_at": None,
        }
        defaults.update(kw)
        return GraphChange(**defaults)

    def test_modify_edge_evidence_history_loss(self, tmp_path):
        """9. edge evidence drop → EVIDENCE_HISTORY_LOSS。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)

        # v1 evidence=[E1]；modify v2 evidence=[E2]（drop E1）
        e2 = "55555555-5555-5555-5555-555555555555"
        _add_second_evidence(db, e2, "2026-08-05T10:00:00+08:00",
                             "2026-08-06T10:00:00+08:00")
        gc2 = _make_modify_edge_candidate(
            confidence=0.99,
            evidence_ids=[e2],
            new_evidence_ids=[e2],
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        result = engine.apply(gc2.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "EVIDENCE_HISTORY_LOSS"
        db.close()

    def test_modify_node_evidence_history_loss(self, tmp_path):
        """9b. node evidence drop → EVIDENCE_HISTORY_LOSS。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_v1(tmp_path))
        e2 = "55555555-5555-5555-5555-555555555555"
        _add_second_evidence(db, e2, "2026-08-05T10:00:00+08:00",
                             "2026-08-06T10:00:00+08:00")
        # v1 evidence=[E1]；modify 到 v2 evidence=[E2]（drop E1）
        gc = _make_modify_node_candidate(
            name="v2",
            evidence_ids=[e2],
            new_evidence_ids=[e2],
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "EVIDENCE_HISTORY_LOSS"
        db.close()


    def test_modify_origin_kind_mutation_rejected(self, tmp_path):
        """modify 不得改写 origin_kind（provenance 不可变）：seed Company
        节点借 modify 改成 graph_change → IMMUTABLE_IDENTITY_CHANGED。"""
        db, _ = _setup_db(tmp_path,
                            raw_item_entities=["company:test-corp", "company:seed-a"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        # seed Company 节点（governance_seed，无证据）
        from research_os.knowledge.repository import GraphRepository
        seed_node = GraphNode(
            node_id="company:seed-a",
            node_type="Company",
            name="种子公司A",
            aliases=[],
            description="种子",
            status="active",
            valid_from=None,
            valid_to=None,
            evidence_ids=[],
            version=1,
            last_reviewed_at=None,
            review_status="approved",
            origin_kind="governance_seed",
            originating_graph_change_id=None,
            created_at=T0,
        )
        GraphRepository(db).append_node(seed_node)
        # entity（KGV-002）
        db._conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            ("company:seed-a",
             _canonical(Entity(entity_id="company:seed-a",
                               entity_type="company",
                               canonical_name="种子公司A").model_dump()),
             "company", "种子公司A"),
        )
        db._conn.commit()

        # modify candidate：origin_kind=graph_change（借 modify 改写 provenance）
        gc = GraphChange(
            graph_change_id=str(uuid.uuid4()),
            change_type="modify_attribute",
            node=GraphNode(
                node_id="company:seed-a",
                node_type="Company",
                name="种子公司Av2",
                aliases=[],
                description="修改后",
                status="active",
                valid_from=T2,
                valid_to=None,
                evidence_ids=[EVIDENCE_UUID],
                version=2,
                last_reviewed_at=None,
                review_status="candidate",
                origin_kind="graph_change",
                originating_graph_change_id=str(uuid.uuid4()),
                created_at=T0,
            ),
            edge=None,
            current_knowledge=_canonical(seed_node.model_dump()),
            new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="修改种子节点",
            impact_scope=[],
            conflicts=[],
            verification_points=[],
            review_status="candidate",
            created_at=T0,
            reviewed_at=None,
        )
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "IMMUTABLE_IDENTITY_CHANGED"
        db.close()

class TestM7RetireAttacks:
    """retire_node / retire_edge 攻击（apply 侧 gates）。"""

    def _seed_node(self, tmp_path):
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        return db, candidate_repo, graph_repo, workflow, engine

    def test_retire_evidence_history_loss(self, tmp_path):
        """retire 不得删减历史证据 → EVIDENCE_HISTORY_LOSS。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_node(tmp_path))
        e2 = "55555555-5555-5555-5555-555555555555"
        _add_second_evidence(db, e2, "2026-08-05T10:00:00+08:00",
                             "2026-08-06T10:00:00+08:00")
        # v1 evidence=[E1]；retire v2 evidence=[E2]（drop E1）
        gc = _make_retire_node_candidate(
            evidence_ids=[e2],
            new_evidence_ids=[e2],
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "EVIDENCE_HISTORY_LOSS"
        db.close()

    def test_retire_time_missing(self, tmp_path):
        """15. retire time missing → RETIRE_TIME_INVALID。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_node(tmp_path))
        gc = _make_retire_node_candidate(
            retire_at=None,
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        # retire_at=None → valid_from=valid_to=None → Pydantic 允许，
        # M7 gate 拒绝
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "RETIRE_TIME_INVALID"
        db.close()

    def test_retire_valid_from_ne_valid_to(self, tmp_path):
        """16. retire valid_from != valid_to → RETIRE_TIME_INVALID。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_node(tmp_path))
        gc = _make_retire_node_candidate(
            retire_at=T2,
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        # 篡改：valid_to != valid_from
        node = gc.node.model_copy(update={"valid_to": T3})
        gc2 = GraphChange(**{**gc.model_dump(), "node": node})
        candidate_repo.append_candidate(gc2)
        _import_review(workflow, gc2, decision="批准")
        result = engine.apply(gc2.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "RETIRE_TIME_INVALID"
        db.close()

    def test_retire_payload_mutation(self, tmp_path):
        """17. retire payload mutation → RETIRE_PAYLOAD_MUTATION。"""
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_node(tmp_path))
        gc = _make_retire_node_candidate(
            name="改名退休",  # 业务修改
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "RETIRE_PAYLOAD_MUTATION"
        db.close()

    def test_second_retire_rejected(self, tmp_path):
        """18. second retire → RETIRE_TARGET_NOT_ACTIVE。"""
        db, candidate_repo, graph_repo, workflow, engine, _ = (
            self._seed_retired_node(tmp_path))
        gc = _make_retire_node_candidate(
            version=3,
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 2))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("RETIRE_TARGET_NOT_ACTIVE",
                                     "M4_APPLY_PREFLIGHT_FAILED",
                                     "VERSION_GAP")
        db.close()

    def _seed_retired_node(self, tmp_path):
        db, candidate_repo, graph_repo, workflow, engine = (
            self._seed_node(tmp_path))
        gc_r = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        _apply_and_assert(engine, gc_r)
        return db, candidate_repo, graph_repo, workflow, engine, None

    def test_retire_edge_payload_mutation(self, tmp_path):
        """17b. retire_edge 同时改 confidence → RETIRE_PAYLOAD_MUTATION。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        gc1 = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)

        gc_r = _make_retire_edge_candidate(
            confidence=0.99,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        result = engine.apply(gc_r.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "RETIRE_PAYLOAD_MUTATION"
        db.close()

    def test_retire_edge_expired_before_retire_at(self, tmp_path):
        """retire_edge：latest 在 retire_at 前已 expired → RETIRE_TARGET_NOT_ACTIVE。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        # edge v1 with valid_to 早于 retire_at
        gc1 = _make_add_edge_candidate(valid_to="2026-08-09T08:00:00+08:00")
        candidate_repo.append_candidate(gc1)
        _import_review(workflow, gc1, decision="批准")
        _apply_and_assert(engine, gc1)

        gc_r = _make_retire_edge_candidate(
            retire_at=T2,
            current_knowledge=_current_knowledge_of(
                graph_repo, "edge", "edge:test-1", 1))
        candidate_repo.append_candidate(gc_r)
        _import_review(workflow, gc_r, decision="批准")
        result = engine.apply(gc_r.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "RETIRE_TARGET_NOT_ACTIVE"
        db.close()


class TestM7ApprovedWithChanges:
    """M7 approved_with_changes 路径（replacement modify / retire）。"""

    def _replace_patch(self, field_path, value):
        return [{"op": "replace", "path": field_path, "value": value}]

    def test_approved_with_changes_modify(self, tmp_path):
        """30. approved_with_changes modify → applied（replacement 生效）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        gc = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        # replacement patch：再改 description
        patch = self._replace_patch("/node/description", "修改后描述")
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied", (result.error_code, result.errors)

        v2 = graph_repo.get_node_version("company:test-corp", 2)
        assert v2["description"] == "修改后描述"
        assert review.resulting_graph_change_id is not None
        db.close()

    def test_approved_with_changes_retire(self, tmp_path):
        """31. approved_with_changes retire → applied。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        gc = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        # replacement patch 只改 verification_points（非业务字段）
        patch = self._replace_patch("/verification_points", ["复核通过"])
        _import_review(workflow, gc, decision="修改后批准", patch=patch)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied", (result.error_code, result.errors)

        v2 = graph_repo.get_node_version("company:test-corp", 2)
        assert v2["status"] == "retired"
        assert v2["valid_from"] == v2["valid_to"] == T2
        db.close()

    def test_replacement_tamper_rejected(self, tmp_path):
        """32. replacement tamper → REPLACEMENT_TAMPERED。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        gc = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        patch = self._replace_patch("/node/name", "篡改名称")
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)
        # 篡改 persisted replacement
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (_canonical({**gc.model_dump(), "suggested_change": "篡改"}),
             review.resulting_graph_change_id),
        )
        db._conn.commit()
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("REPLACEMENT_TAMPERED",
                                     "REPLACEMENT_SCHEMA_INVALID",
                                     "REPLACEMENT_PAYLOAD_INVALID")
        db.close()


class TestM7DryRunAndM6Regression:
    """dry-run 零写入 / M6 add regression / governance protection。"""

    def test_modify_dry_run_zero_writes(self, tmp_path):
        """47. modify dry-run → 零写入。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        gc = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT,
                              dry_run=True)
        assert result.status == "dry_run"
        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before
        db.close()

    def test_retire_node_dry_run_zero_writes(self, tmp_path):
        """retire node dry-run → 零写入（含 incident guard 预检）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        gc = _make_retire_node_candidate(
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT,
                              dry_run=True)
        assert result.status == "dry_run"
        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before
        db.close()

    def test_m6_add_node_regression(self, tmp_path):
        """52. M6 add_node regression。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        gc = _make_add_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied"
        assert result.target_version == 1
        db.close()

    def test_m6_add_edge_regression(self, tmp_path):
        """53. M6 add_edge regression。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        gc = _make_add_edge_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied"
        assert result.target_version == 1
        db.close()

    def test_governance_industry_modify_rejected(self, tmp_path):
        """44. governance Industry modify rejected（KGV-009）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        # Industry entity（KGV-002 要求 entity 存在）
        db._conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            ("industry:semiconductor",
             _canonical(Entity(entity_id="industry:semiconductor", entity_type="industry",
                               canonical_name="半导体").model_dump()),
             "industry", "半导体"),
        )
        db._conn.commit()
        from research_os.knowledge.repository import GraphRepository
        from research_os.models import GraphNode as _GN
        seed_node = _GN(
            node_id="industry:semiconductor",
            node_type="Industry",
            name="半导体",
            aliases=[],
            description="种子行业",
            status="active",
            valid_from=None,
            valid_to=None,
            evidence_ids=[],
            version=1,
            last_reviewed_at=None,
            review_status="approved",
            origin_kind="governance_seed",
            originating_graph_change_id=None,
            created_at=T0,
        )
        GraphRepository(db).append_node(seed_node)

        gc = GraphChange(
            graph_change_id=str(uuid.uuid4()),
            change_type="modify_attribute",
            node=GraphNode(
                node_id="industry:semiconductor",
                node_type="Industry",
                name="半导体v2",
                aliases=[],
                description="修改行业",
                status="active",
                valid_from=T2,
                valid_to=None,
                evidence_ids=[EVIDENCE_UUID],
                version=2,
                last_reviewed_at=None,
                review_status="candidate",
                origin_kind="graph_change",
                originating_graph_change_id=str(uuid.uuid4()),
                created_at=T0,
            ),
            edge=None,
            current_knowledge=_canonical(seed_node.model_dump()),
            new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="修改行业",
            impact_scope=[],
            conflicts=[],
            verification_points=[],
            review_status="candidate",
            created_at=T0,
            reviewed_at=None,
        )
        candidate_repo.append_candidate(gc)
        result = _try_import_review(workflow, gc, decision="批准")
        assert result.status != "ok", "Industry 普通候选修改必须被 KGV-009 拒绝"
        db.close()

    def test_governance_industry_retire_rejected(self, tmp_path):
        """45. governance Industry retire rejected（KGV-009）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        from research_os.knowledge.repository import GraphRepository
        db._conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            ("industry:semiconductor",
             _canonical(Entity(entity_id="industry:semiconductor", entity_type="industry",
                               canonical_name="半导体").model_dump()),
             "industry", "半导体"),
        )
        db._conn.commit()
        seed_node = GraphNode(
            node_id="industry:semiconductor",
            node_type="Industry",
            name="半导体",
            aliases=[],
            description="种子行业",
            status="active",
            valid_from=None,
            valid_to=None,
            evidence_ids=[],
            version=1,
            last_reviewed_at=None,
            review_status="approved",
            origin_kind="governance_seed",
            originating_graph_change_id=None,
            created_at=T0,
        )
        GraphRepository(db).append_node(seed_node)

        gc = GraphChange(
            graph_change_id=str(uuid.uuid4()),
            change_type="retire_node",
            node=GraphNode(
                node_id="industry:semiconductor",
                node_type="Industry",
                name="半导体",
                aliases=[],
                description="种子行业",
                status="retired",
                valid_from=T2,
                valid_to=T2,
                evidence_ids=[EVIDENCE_UUID],
                version=2,
                last_reviewed_at=None,
                review_status="candidate",
                origin_kind="graph_change",
                originating_graph_change_id=str(uuid.uuid4()),
                created_at=T0,
            ),
            edge=None,
            current_knowledge=_canonical(seed_node.model_dump()),
            new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="退休行业",
            impact_scope=[],
            conflicts=[],
            verification_points=[],
            review_status="candidate",
            created_at=T0,
            reviewed_at=None,
        )
        candidate_repo.append_candidate(gc)
        result = _try_import_review(workflow, gc, decision="批准")
        assert result.status != "ok", "Industry 普通候选修改必须被 KGV-009 拒绝"
        db.close()

    def test_original_graph_change_immutable(self, tmp_path):
        """49. original GraphChange immutable。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        gc = _make_add_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        _apply_and_assert(engine, gc)

        # 篡改 original GraphChange payload → 再次 apply 必须拒绝（不覆盖）
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        row = db._conn.execute(
            "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
            (gc.graph_change_id,),
        ).fetchone()
        tampered = json.loads(row["payload"])
        tampered["suggested_change"] = "篡改"
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (_canonical(tampered), gc.graph_change_id),
        )
        db._conn.commit()
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("CANDIDATE_HASH_MISMATCH",
                                     "APPLICATION_INTEGRITY_CONFLICT",
                                     "M4_APPLY_PREFLIGHT_FAILED")
        db.close()

    def test_graph_review_immutable(self, tmp_path):
        """50. GraphReview immutable。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine, _ = _make_components(db)
        gc = _make_add_node_candidate()
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")
        _apply_and_assert(engine, gc)

        db._conn.execute(
            "UPDATE graph_reviews SET payload = ? WHERE review_id = ?",
            ("{broken", review.review_id),
        )
        db._conn.commit()
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "REVIEW_PAYLOAD_INVALID"
        db.close()

    def test_old_graph_version_immutable(self, tmp_path):
        """51. old graph version immutable：SQL 篡改 v1 payload → history 必须
        fail-closed（HISTORY_INTEGRITY_CONFLICT），不能静默呈现被篡改的旧版本。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, history = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)

        # 直接 UPDATE v1 payload（改 name）→ column name 仍是旧值 → 不一致
        v1 = graph_repo.get_node_version("company:test-corp", 1)
        tampered = dict(v1)
        tampered["name"] = "被篡改"
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = 1",
            (_canonical(tampered), "company:test-corp"),
        )
        db._conn.commit()

        from research_os.knowledge.history import HistoryError
        with pytest.raises(HistoryError) as exc_info:
            history.get_node_history("company:test-corp")
        assert exc_info.value.error_code == "HISTORY_INTEGRITY_CONFLICT"
        db.close()


class TestM7AtomicityConcurrency:
    """M7 原子性 / 并发冲突 / COMMIT failure。"""

    def test_modify_atomic_rollback(self, tmp_path):
        """modify 事务失败 → ROLLBACK ALL（无 new version / 无 application）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        # 事务内 append 前注入失败（target append 冲突）：构造 v2 后手动插入
        # 同 version 不同 payload 的 v2 → IMMUTABLE_VERSION_CONFLICT
        gc = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 预插入冲突 v2（不同 payload）
        conflict_v2 = _make_modify_node_candidate(
            version=2, valid_from=T2, name="冲突v2",
            current_knowledge=_canonical(v1 := graph_repo.get_node_version(
                "company:test-corp", 1)))
        db._conn.execute(
            "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("company:test-corp", 2, _canonical(
                conflict_v2.node.model_dump()), "Company", "冲突v2", "active",
             "approved", "graph_change", T0, T2, None, T1, str(uuid.uuid4())),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code in ("TARGET_VERSION_CONFLICT",
                                     "VERSION_GAP",
                                     "M4_APPLY_PREFLIGHT_FAILED")
        # 没有新增 application（原子性）
        assert _count_table(db, "graph_applications") == apps_before
        assert _count_table(db, "graph_nodes") == nodes_before + 1  # 仅预插的冲突行
        db.close()

    def test_concurrent_modify_same_baseline(self, tmp_path):
        """27. 两个并发 modify candidate 同一 baseline → 最多一个 v2。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        ck = _current_knowledge_of(graph_repo, "node", "company:test-corp", 1)

        gc_a = _make_modify_node_candidate(name="并发A",
                                           current_knowledge=ck)
        gc_b = _make_modify_node_candidate(name="并发B",
                                           current_knowledge=ck)
        for gc in (gc_a, gc_b):
            candidate_repo.append_candidate(gc)
            _import_review(workflow, gc, decision="批准")

        # 顺序 apply（模拟串行化）：A 成功生成 v2，B 因 baseline stale 拒绝
        r_a = engine.apply(gc_a.graph_change_id, applied_at=APPLIED_AT)
        r_b = engine.apply(gc_b.graph_change_id, applied_at=APPLIED_AT)
        assert r_a.status == "applied"
        assert r_b.status == "APPLY_REJECTED"
        assert r_b.error_code in ("M4_APPLY_PREFLIGHT_FAILED",
                                  "VERSION_GAP",
                                  "STALE_REVIEW",
                                  "IMMUTABLE_VERSION_CONFLICT")
        v2 = graph_repo.get_node_version("company:test-corp", 2)
        assert v2["name"] == "并发A"
        assert _count_table(db, "graph_applications") == 2
        db.close()

    def test_commit_failure_modify_not_applied(self, tmp_path, monkeypatch):
        """commit failure → modify 不得 applied。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine, _ = (
            _make_components(db))
        _seed_node_v1(db, candidate_repo, workflow, engine)
        gc = _make_modify_node_candidate(
            name="v2",
            current_knowledge=_current_knowledge_of(
                graph_repo, "node", "company:test-corp", 1))
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        class _CommitFailTxn:
            def __enter__(self):
                return db._conn

            def __exit__(self, exc_type, exc_val, exc_tb):
                if exc_type is None:
                    raise sqlite3.OperationalError("simulated commit failure")
                return False

        monkeypatch.setattr(db, "immediate_transaction",
                            lambda: _CommitFailTxn())
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "APPLY_FAILED"
        db.close()
