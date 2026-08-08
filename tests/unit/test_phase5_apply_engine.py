"""M6 Deterministic Apply Engine 测试（Phase 5）。

覆盖：
- GraphReview selection（显式 / 0 / 1 / >1 / AMBIGUOUS）
- decision gate（deferred/rejected → NON_APPLICABLE_REVIEW_DECISION）
- approved add_node / add_edge apply（Golden E2E）
- approved_with_changes（replacement linkage / missing / tamper / 合法 patch 消除 conflict）
- idempotent replay（优先识别，audit integrity / target 一致 → IDEMPOTENT_NOOP）
- candidate hash / Evidence-after-review mutation / KGV-019 stale
- apply-time transformation（review_status=approved、last_reviewed_at=reviewed_at、
  applied_at 不污染业务时间、MODEL_INFERENCE 保持）
- 原子性（真实 SQLite rollback）、并发冲突（双连接 BEGIN IMMEDIATE）
- dry-run 零写入、M7 change_type 拒绝、APPLY_TIME_INVALID
- 确定性 application_id / idempotency_key

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
from research_os.knowledge.review_workflow import (
    ReviewWorkflow,
    build_replacement_graph_change,
)
from research_os.knowledge.review_parser import parse_review_markdown
from research_os.knowledge.apply_engine import ApplyEngine, ApplyResult

# ── 常量 ─────────────────────────────────────────────────────
T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"

APPLIED_AT = "2026-08-09T10:00:00+08:00"  # >= reviewed_at T1


# ── helpers ──────────────────────────────────────────────────

def _candidate_hash(gc: GraphChange) -> str:
    """candidate hash 唯一 authority（M4）。"""
    return KnowledgeValidator.compute_candidate_hash(gc)


def _make_node_candidate(change_id=None, **kw):
    change_id = change_id or str(uuid.uuid4())
    node = GraphNode(
        node_id="company:test-corp",
        node_type="Company",
        name="测试公司",
        aliases=["测试"],
        description="测试描述",
        status="active",
        valid_from=None,
        valid_to=None,
        evidence_ids=[EVIDENCE_UUID],
        version=1,
        last_reviewed_at=None,
        review_status="candidate",
        origin_kind="graph_change",
        originating_graph_change_id=str(uuid.uuid4()),
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


def _make_edge_candidate(change_id=None, assertion_type="FACT", **kw):
    change_id = change_id or str(uuid.uuid4())
    edge = GraphEdge(
        edge_id="edge:test-1",
        source_node_id="company:src",
        relation="COMPETES_WITH",
        target_node_id="company:tgt",
        attributes={},
        assertion_type=assertion_type,
        valid_from=None,
        valid_to=None,
        confidence=0.8,
        evidence_ids=[EVIDENCE_UUID],
        review_status="candidate",
        version=1,
        originating_graph_change_id=str(uuid.uuid4()),
        created_at=T0,
        last_reviewed_at=None,
    )
    defaults = {
        "graph_change_id": change_id,
        "change_type": "add_edge",
        "node": None,
        "edge": edge,
        "current_knowledge": "",  # add_edge 是新边，无当前知识（KGV-019 语义）
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


def _build_review_markdown(
    gc,
    decision="批准",
    reviewer_id="reviewer-001",
    reviewed_at=T1,
    notes="",
    patch=None,
):
    """构造可被 review-import 解析的填写后审阅 Markdown。"""
    candidate_hash = _candidate_hash(gc)
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
    elif decision == "暂缓":
        sections.append("- [ ] 批准")
        sections.append("- [ ] 修改后批准")
        sections.append("- [x] 暂缓")
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
    sections.append(notes or "_（请在此填写审核意见）_")
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
    return "\n".join(sections)


def _setup_db(tmp_path, raw_item_entities=None):
    """建立最小可 apply 的 SQLite DB。

    Args:
        raw_item_entities: raw_item 的 entities（KGV-006 覆盖要求）。
            node 用 ["company:test-corp"]；edge 用 ["company:src", "company:tgt"]。

    Returns:
        (db, db_path)
    """
    from research_os.storage import Database

    db_path = tmp_path / "apply.db"
    db = Database(db_path)
    db.initialize()
    conn = db._conn

    if raw_item_entities is None:
        raw_item_entities = ["company:test-corp"]

    # evidence
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

    # raw_item（entities 覆盖）
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

    # entities
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

    # graph_nodes（edge 端点，KGV-004）
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
    """构造 repos/validator/workflow/engine。"""
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.knowledge.repository import GraphRepository

    candidate_repo = GraphChangeCandidateRepository(db)
    graph_repo = GraphRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
    engine = ApplyEngine(db, candidate_repo, graph_repo, validator)
    return candidate_repo, graph_repo, validator, workflow, engine


def _import_review(workflow, gc, decision="批准", reviewer_id="reviewer-001",
                   reviewed_at=T1, patch=None):
    """构造 markdown 并 import；断言成功，返回 result。"""
    md = _build_review_markdown(gc, decision=decision,
                                reviewer_id=reviewer_id,
                                reviewed_at=reviewed_at, patch=patch)
    result = workflow.review_import(md)
    assert result.status == "ok", f"review_import 失败: {result.errors}"
    return result


def _count_table(db, table):
    row = db._conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
    return int(row["c"])


def _add_second_evidence(db, evidence_id, published_at, retrieved_at):
    """插入第二条 Evidence E2（含 raw_item 链，entities 覆盖 company:test-corp）。"""
    conn = db._conn
    ri2_id = "44444444-4444-4444-4444-444444444444"
    ev = Evidence(
        evidence_id=evidence_id,
        source_id=SOURCE_UUID,
        raw_item_id=ri2_id,
        title="第二条证据",
        publisher="测试发布者",
        published_at=published_at,
        retrieved_at=retrieved_at,
        url="https://example.com/e2",
        excerpt="测试摘录2",
        evidence_type="news_report",
        independence_group="group-2",
        source_tier="B",
        access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (evidence_id,
         json.dumps(ev.model_dump(), ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")),
         SOURCE_UUID, ri2_id, "group-2", "B"),
    )
    ri2 = {
        "raw_item_id": ri2_id, "source_id": SOURCE_UUID,
        "external_id": "ext-002", "url": "https://example.com/e2",
        "title": "第二条", "publisher": "测试", "author": "测试作者",
        "published_at": published_at,
        "retrieved_at": retrieved_at,
        "content_hash": SHA256_ZEROS, "content_excerpt": "摘录2",
        "content_storage": "metadata_and_excerpt", "language": "zh-CN",
        "access_status": "ok", "entities": ["company:test-corp"],
        "raw_category": "news",
    }
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (ri2_id, json.dumps(ri2, ensure_ascii=False),
         SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    conn.commit()


def _canonical(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _reject_code(result: ApplyResult) -> str:
    """从 APPLY_REJECTED 结果提取精确 error_code。"""
    assert result.status == "APPLY_REJECTED"
    assert result.error_code, "APPLY_REJECTED 必须有 error_code"
    return result.error_code


def _manual_review(db, gc, graph_repo, decision="approved",
                   reviewed_at=T1, patch=None):
    """绕过 review-import 的 M4 校验，手工构造并持久化 GraphReview。

    用于 M6 攻击测试：M4 在 import 阶段会拦截的 candidate
    （如 invalid version / retire 需要 persisted edge），
    直接构造 review 验证 M6 apply 的拒绝行为。
    """
    from research_os.models import GraphReviewer, GraphReview
    from research_os.knowledge.review_workflow import (
        compute_review_id, _make_replacement_gc_id,
    )

    reviewer = GraphReviewer(reviewer_type="human",
                             reviewer_id="reviewer-001",
                             display_name=None)
    intent = {
        "graph_change_id": gc.graph_change_id,
        "decision": decision,
        "reviewer": {"reviewer_type": "human", "reviewer_id": "reviewer-001",
                     "display_name": None},
        "reviewed_at": reviewed_at,
        "candidate_hash": _candidate_hash(gc),
        "review_patch": patch or [],
        "notes": "",
    }
    review_id = compute_review_id(intent)
    resulting = _make_replacement_gc_id(review_id) \
        if decision == "approved_with_changes" else None
    review = GraphReview(
        review_id=review_id,
        graph_change_id=gc.graph_change_id,
        decision=decision,
        reviewer=reviewer,
        reviewed_at=reviewed_at,
        candidate_hash=_candidate_hash(gc),
        review_patch=patch or [],
        notes="",
        resulting_graph_change_id=resulting,
    )
    graph_repo.append_review(review)
    return review_id


# ═══════════════════════════════════════════════════════════════
# 1. Review selection / decision gate
# ═══════════════════════════════════════════════════════════════

class TestApplyReviewSelection:
    """攻击 1/2/3/10/11：review selection 规则。"""

    def test_candidate_without_review_rejected(self, tmp_path):
        """1. candidate without review → APPLY_REJECTED (REVIEW_REQUIRED)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, _, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "REVIEW_REQUIRED"
        db.close()

    def test_review_not_found_rejected(self, tmp_path):
        """2. review not found → reject (REVIEW_NOT_FOUND)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        bogus_review = str(uuid.uuid4())
        result = engine.apply(gc.graph_change_id, review_id=bogus_review,
                              applied_at=APPLIED_AT)
        assert _reject_code(result) == "REVIEW_NOT_FOUND"
        db.close()

    def test_review_change_mismatch_rejected(self, tmp_path):
        """3. review 属于另一 candidate → reject (REVIEW_CHANGE_MISMATCH)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc_a = _make_node_candidate()
        gc_b = _make_node_candidate()
        candidate_repo.append_candidate(gc_a)
        candidate_repo.append_candidate(gc_b)
        review_a = _import_review(workflow, gc_a, decision="批准")

        result = engine.apply(gc_b.graph_change_id,
                              review_id=review_a.review_id,
                              applied_at=APPLIED_AT)
        assert _reject_code(result) == "REVIEW_CHANGE_MISMATCH"
        db.close()

    def test_deferred_rejected(self, tmp_path):
        """4. deferred → reject (NON_APPLICABLE_REVIEW_DECISION)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="暂缓")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "NON_APPLICABLE_REVIEW_DECISION"
        # 0 writes
        assert _count_table(db, "graph_nodes") == 2  # 仅 seed 端点
        assert _count_table(db, "graph_applications") == 0
        db.close()

    def test_rejected_rejected(self, tmp_path):
        """5. rejected → reject (NON_APPLICABLE_REVIEW_DECISION)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="拒绝")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "NON_APPLICABLE_REVIEW_DECISION"
        db.close()

    def test_ambiguous_review_selection(self, tmp_path):
        """10. same candidate 两条 review 无 --review-id → AMBIGUOUS。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准", reviewer_id="reviewer-A")
        _import_review(workflow, gc, decision="拒绝", reviewer_id="reviewer-B")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "AMBIGUOUS_REVIEW_SELECTION"
        db.close()

    def test_explicit_review_id_selects(self, tmp_path):
        """11. 两条 review + 显式 --review-id → deterministic 选择。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="拒绝", reviewer_id="reviewer-A")
        approved = _import_review(workflow, gc, decision="批准",
                                  reviewer_id="reviewer-B")

        result = engine.apply(gc.graph_change_id,
                              review_id=approved.review_id,
                              applied_at=APPLIED_AT)
        assert result.status == "applied"
        assert result.review_id == approved.review_id
        db.close()


# ═══════════════════════════════════════════════════════════════
# 2. approved path：Golden E2E
# ═══════════════════════════════════════════════════════════════

class TestApplyApproved:
    """攻击 6/7 + Golden A/B/D：approved add_node / add_edge apply。"""

    def test_approved_add_node_applies(self, tmp_path):
        """6. 恰一条 approved review → add_node applies（Golden A）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        assert result.target_kind == "node"
        assert result.target_id == "company:test-corp"
        assert result.target_version == 1
        assert result.application_id is not None
        assert result.idempotency_key is not None

        # approved core node v1
        node = graph_repo.get_node_version("company:test-corp", 1)
        assert node is not None
        assert node["review_status"] == "approved"
        assert node["last_reviewed_at"] == T1  # == GraphReview.reviewed_at
        # created_at 保留 candidate 值（不被 applied_at 覆盖）
        assert node["created_at"] == gc.created_at
        # originating_graph_change_id 保留
        assert node["originating_graph_change_id"] == gc.node.originating_graph_change_id

        # application audit
        app = graph_repo.get_application(result.application_id)
        assert app["status"] == "applied"
        assert app["original_graph_change_id"] == gc.graph_change_id
        assert app["effective_graph_change_id"] == gc.graph_change_id
        assert app["review_id"] == review.review_id
        assert app["target_kind"] == "node"
        assert app["applied_at"] == APPLIED_AT

        # 血缘：graph_application.graph_change_id == effective
        row = db._conn.execute(
            "SELECT graph_change_id FROM graph_applications WHERE application_id = ?",
            (result.application_id,),
        ).fetchone()
        assert row["graph_change_id"] == gc.graph_change_id

        db.close()

    def test_approved_add_edge_applies(self, tmp_path):
        """7. approved add_edge → FACT GraphEdge（Golden B）。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_edge_candidate(assertion_type="FACT")
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        assert result.target_kind == "edge"
        assert result.target_id == "edge:test-1"

        edge = graph_repo.get_edge_version("edge:test-1", 1)
        assert edge is not None
        assert edge["assertion_type"] == "FACT"
        assert edge["review_status"] == "approved"
        assert edge["last_reviewed_at"] == T1  # == GraphReview.reviewed_at
        assert edge["created_at"] == gc.created_at
        db.close()

    def test_model_inference_edge_preserved(self, tmp_path):
        """31. MODEL_INFERENCE edge apply 后仍为 MODEL_INFERENCE（Golden D）。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_edge_candidate(assertion_type="MODEL_INFERENCE")
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        edge = graph_repo.get_edge_version("edge:test-1", 1)
        assert edge["assertion_type"] == "MODEL_INFERENCE"
        db.close()

    def test_applied_at_does_not_rewrite_valid_from_or_created_at(self, tmp_path):
        """29/30. applied_at 不重写 valid_from / created_at。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        gc_dict = gc.model_dump()
        gc_dict["node"]["valid_from"] = "2026-08-01T00:00:00+08:00"
        gc = GraphChange(**gc_dict)
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        node = graph_repo.get_node_version("company:test-corp", 1)
        assert node["valid_from"] == "2026-08-01T00:00:00+08:00"
        assert node["created_at"] == T0
        db.close()

    def test_original_graph_change_immutable_after_apply(self, tmp_path):
        """32. apply 后 graph_changes payload byte-for-byte 不变。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        original = candidate_repo.get_candidate(gc.graph_change_id)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied"

        after = candidate_repo.get_candidate(gc.graph_change_id)
        assert _canonical(after) == _canonical(original)
        db.close()

    def test_graph_review_immutable_after_apply(self, tmp_path):
        """33. apply 后 GraphReview payload byte-for-byte 不变。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")
        original_review = graph_repo.get_review(review.review_id)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied"

        after = graph_repo.get_review(review.review_id)
        assert _canonical(after) == _canonical(original_review)
        db.close()


# ═══════════════════════════════════════════════════════════════
# 3. Idempotency / deterministic IDs
# ═══════════════════════════════════════════════════════════════

class TestApplyIdempotency:
    """攻击 8/9/34/35/36/37/38/39：幂等回放与 audit integrity。"""

    def test_second_exact_apply_idempotent_noop(self, tmp_path):
        """8. 第二次精确 apply → idempotent_noop（无新 audit）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r1.status == "applied"
        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        r2 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert r2.status == "idempotent_noop"
        # 9. 返回已有 application_id / applied_at，不产生新 audit
        assert r2.application_id == r1.application_id
        assert r2.applied_at == r1.applied_at
        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before
        assert r2.idempotency_key == r1.idempotency_key
        db.close()

    def test_deterministic_application_id_and_key(self, tmp_path):
        """35/36. deterministic application_id + idempotency_key。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        # 独立重算
        expected_key = hashlib.sha256(
            json.dumps({
                "original_graph_change_id": gc.graph_change_id,
                "effective_graph_change_id": gc.graph_change_id,
                "review_id": r1.review_id,
                "effective_candidate_hash": _candidate_hash(gc),
                "target_kind": "node",
                "target_id": "company:test-corp",
                "target_version": 1,
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        assert r1.idempotency_key == expected_key
        expected_app_id = str(uuid.uuid5(
            uuid.NAMESPACE_DNS, "graph-application:" + expected_key))
        assert r1.application_id == expected_app_id
        # 不含 applied_at（换 applied_at 仍同 key）
        r2 = engine.apply(gc.graph_change_id,
                          applied_at="2026-08-10T10:00:00+08:00")
        assert r2.idempotency_key == r1.idempotency_key
        assert r2.status == "idempotent_noop"
        assert r2.applied_at == r1.applied_at  # 保留已有 applied_at
        db.close()

    def test_application_exists_target_missing_conflict(self, tmp_path):
        """37. application 存在但 target 缺失 → APPLICATION_INTEGRITY_CONFLICT。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r1.status == "applied"
        # 攻击：删除 target node
        db._conn.execute(
            "DELETE FROM graph_nodes WHERE node_id = 'company:test-corp'")
        db._conn.commit()

        r2 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(r2) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_application_exists_target_payload_differs_conflict(self, tmp_path):
        """38. application 存在但 target payload 不同 → conflict。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r1.status == "applied"
        # 攻击：篡改 target payload
        node = graph_repo.get_node_version("company:test-corp", 1)
        node["name"] = "被篡改"
        tampered = json.dumps(node, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = 1",
            (tampered, "company:test-corp"),
        )
        db._conn.commit()

        r2 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(r2) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_application_payload_tampered_conflict(self, tmp_path):
        """39. GraphApplication payload 被篡改 → conflict。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r1.status == "applied"
        # 攻击：篡改 application payload 中 target_id
        app = graph_repo.get_application(r1.application_id)
        app["target_id"] = "company:evil"
        tampered = json.dumps(app, ensure_ascii=False, sort_keys=True,
                              separators=(",", ":"))
        db._conn.execute(
            "UPDATE graph_applications SET payload = ? WHERE application_id = ?",
            (tampered, r1.application_id),
        )
        db._conn.commit()

        r2 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(r2) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()


# ═══════════════════════════════════════════════════════════════
# 4. Mutation detection（candidate/evidence/graph 修改）
# ═══════════════════════════════════════════════════════════════

class TestApplyMutationDetection:
    """攻击 12/13/14/15/16：apply 时重新验证。"""

    def test_candidate_mutated_after_review_rejected(self, tmp_path):
        """12. candidate SQL 修改 → hash mismatch → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 攻击：直接修改 graph_changes payload
        mutated = candidate_repo.get_candidate(gc.graph_change_id)
        mutated["suggested_change"] = "被修改"
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (json.dumps(mutated, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), gc.graph_change_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "CANDIDATE_HASH_MISMATCH"
        db.close()

    def test_evidence_deleted_after_review_rejected(self, tmp_path):
        """13. Evidence 被删除 → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        db._conn.execute("DELETE FROM evidence WHERE evidence_id = ?",
                         (EVIDENCE_UUID,))
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert result.error_code == "M4_APPLY_PREFLIGHT_FAILED"
        db.close()

    def test_evidence_schema_invalid_after_review_rejected(self, tmp_path):
        """14. Evidence raw Schema 损坏 → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            ('{"evidence_id": 123, "broken": true}', EVIDENCE_UUID),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        db.close()

    def test_graph_changed_after_review_stale_rejected(self, tmp_path):
        """15. graph 在 review 后变化 → KGV-019 stale → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 攻击：review 后手动插入同 node_id（graph changed）
        node_payload = json.dumps({
            "node_id": "company:test-corp", "node_type": "Company",
            "name": "已存在", "status": "active", "version": 1,
            "origin_kind": "governance_seed", "review_status": "approved",
            "created_at": T0, "evidence_ids": [],
        }, ensure_ascii=False)
        db._conn.execute(
            "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES ('company:test-corp', 1, ?, 'Company', '已存在', 'active', 'approved', 'governance_seed', ?)",
            (node_payload, T0),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "M4_APPLY_PREFLIGHT_FAILED"
        assert any("KGV-019" in e for e in result.errors)
        db.close()

    def test_blocking_conflict_approved_rejected(self, tmp_path):
        """16. approved + blocking conflict → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate(conflicts=["冲突数据源：源A vs 源B"])
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "M4_APPLY_PREFLIGHT_FAILED"
        assert any("KGV-011" in e for e in result.errors)
        db.close()


# ═══════════════════════════════════════════════════════════════
# 5. version / endpoint rules
# ═══════════════════════════════════════════════════════════════

class TestApplyVersionRules:
    """攻击 17/18/19/20：版本与端点规则。"""

    def test_invalid_version_rejected(self, tmp_path):
        """17. invalid version → reject（M4 KGV-013 或 VERSION 规则）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, _, engine = _make_components(db)
        gc = _make_node_candidate()
        gc_dict = gc.model_dump()
        gc_dict["node"]["version"] = 5
        gc = GraphChange(**gc_dict)
        candidate_repo.append_candidate(gc)
        # M4 KGV-013 在 import 阶段拦截 invalid version，手工构造 review 验证 apply 拒绝
        _manual_review(db, gc, graph_repo, decision="approved")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert _count_table(db, "graph_applications") == 0
        db.close()

    def test_add_node_version_gt1_without_baseline_rejected(self, tmp_path):
        """18. add_node version>1 无基线 → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, _, engine = _make_components(db)
        gc = _make_node_candidate()
        gc_dict = gc.model_dump()
        gc_dict["node"]["version"] = 2
        gc = GraphChange(**gc_dict)
        candidate_repo.append_candidate(gc)
        _manual_review(db, gc, graph_repo, decision="approved")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert _count_table(db, "graph_applications") == 0
        db.close()

    def test_duplicate_edge_triple_rejected(self, tmp_path):
        """19. duplicate add_edge triple → reject。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_edge_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 攻击：graph_edges 已有相同 triple 的边（不同 edge_id）
        dup_edge = GraphEdge(
            edge_id="edge:existing-1",
            source_node_id="company:src",
            relation="COMPETES_WITH",
            target_node_id="company:tgt",
            attributes={},
            assertion_type="FACT",
            valid_from=None, valid_to=None,
            confidence=0.9,
            evidence_ids=[EVIDENCE_UUID],
            review_status="approved",
            version=1,
            originating_graph_change_id=str(uuid.uuid4()),
            created_at=T0,
            last_reviewed_at=T1,
        )
        graph_repo.append_edge(dup_edge)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert any("KGV-003" in e or "AMBIGUOUS" in e or "edge" in e.lower()
                   for e in result.errors)
        db.close()

    def test_retired_endpoint_rejected(self, tmp_path):
        """20. retired/inactive endpoint → reject（KGV-017）。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_edge_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 攻击：source 端点 retired
        node = json.loads(db._conn.execute(
            "SELECT payload FROM graph_nodes WHERE node_id = 'company:src' AND version = 1"
        ).fetchone()["payload"])
        node["status"] = "retired"
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ?, status = 'retired' WHERE node_id = 'company:src' AND version = 1",
            (json.dumps(node, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")),),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert any("KGV-017" in e or "RETIRED" in e.upper() for e in result.errors)
        db.close()


# ═══════════════════════════════════════════════════════════════
# 6. approved_with_changes path
# ═══════════════════════════════════════════════════════════════

class TestApplyApprovedWithChanges:
    """攻击 21/22/23/24/25/26 + Golden C。"""

    def test_approved_with_changes_applies_replacement(self, tmp_path):
        """21. approved_with_changes → persisted replacement applied（Golden C）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        # effective = replacement
        assert result.effective_graph_change_id == review.resulting_graph_change_id
        assert result.effective_graph_change_id != gc.graph_change_id

        # GraphReview.resulting_graph_change_id == application.effective == core.originating
        app = graph_repo.get_application(result.application_id)
        assert app["effective_graph_change_id"] == review.resulting_graph_change_id
        node = graph_repo.get_node_version("company:test-corp", 1)
        assert node["originating_graph_change_id"] == review.resulting_graph_change_id

        # 34. graph_application.graph_change_id == effective_graph_change_id
        row = db._conn.execute(
            "SELECT graph_change_id FROM graph_applications WHERE application_id = ?",
            (result.application_id,),
        ).fetchone()
        assert row["graph_change_id"] == review.resulting_graph_change_id

        # original candidate 未 apply
        assert graph_repo.get_node_version("company:test-corp", 1)["originating_graph_change_id"] \
            == review.resulting_graph_change_id
        db.close()

    def test_replacement_id_mismatch_rejected(self, tmp_path):
        """22. replacement ID 不匹配 graph-review-result 协议 → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)
        rid = review.review_id

        # 攻击：篡改 review payload 中的 resulting_graph_change_id
        # （payload 是 Schema-first 的数据源；篡改 payload 破坏 deterministic linkage）
        saved = db._conn.execute(
            "SELECT payload FROM graph_reviews WHERE review_id = ?", (rid,)
        ).fetchone()
        review_payload = json.loads(saved["payload"])
        review_payload["resulting_graph_change_id"] = str(uuid.uuid4())
        db._conn.execute(
            "UPDATE graph_reviews SET payload = ?, resulting_graph_change_id = ? "
            "WHERE review_id = ?",
            (json.dumps(review_payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")),
             review_payload["resulting_graph_change_id"], rid),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, review_id=rid,
                              applied_at=APPLIED_AT)
        assert _reject_code(result) == "REPLACEMENT_ID_MISMATCH"
        db.close()

    def test_replacement_missing_rejected(self, tmp_path):
        """23. replacement 缺失 → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)
        # 攻击：删除 replacement
        from research_os.knowledge.review_workflow import _make_review_id, _build_review_intent, _make_replacement_gc_id
        from research_os.models import GraphReviewer
        md = _build_review_markdown(gc, decision="修改后批准", patch=patch)
        parsed = parse_review_markdown(md)
        reviewer = GraphReviewer(reviewer_type="human",
                                 reviewer_id=parsed.reviewer_id,
                                 display_name=parsed.display_name)
        intent = _build_review_intent(parsed.graph_change_id, parsed.decision,
                                      reviewer, parsed.reviewed_at,
                                      parsed.candidate_hash, parsed.review_patch,
                                      parsed.review_notes)
        rid = _make_review_id(intent)
        repl_id = _make_replacement_gc_id(rid)
        db._conn.execute(
            "DELETE FROM graph_changes WHERE graph_change_id = ?", (repl_id,))
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, review_id=rid,
                              applied_at=APPLIED_AT)
        assert _reject_code(result) == "REPLACEMENT_MISSING"
        db.close()

    def test_replacement_tampered_rejected(self, tmp_path):
        """24. replacement payload 被篡改 → reject（REPLACEMENT_TAMPERED）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)

        # 攻击：篡改 replacement payload
        repl = candidate_repo.get_candidate(review.resulting_graph_change_id)
        repl["suggested_change"] = "被篡改"
        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            (json.dumps(repl, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), review.resulting_graph_change_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "REPLACEMENT_TAMPERED"
        db.close()

    def test_replacement_patch_clears_conflict_applies(self, tmp_path):
        """25. replacement 合法 patch 消除 conflict → 可 apply。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate(conflicts=["冲突数据源：源A vs 源B"])
        candidate_repo.append_candidate(gc)
        # patch 清空 conflicts
        patch = [{"op": "replace", "path": "/conflicts", "value": []}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)

        assert result.status == "applied"
        node = graph_repo.get_node_version("company:test-corp", 1)
        assert node is not None
        assert node["conflicts"] == [] if "conflicts" in node else True
        db.close()

    def test_replacement_still_has_conflict_rejected(self, tmp_path):
        """26. replacement 仍有 blocking conflict → reject。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate(conflicts=["冲突数据源：源A vs 源B"])
        candidate_repo.append_candidate(gc)
        # patch 只改 suggested_change，保留 conflicts
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "M4_REPLACEMENT_VALIDATION_FAILED"
        assert any("KGV-011" in e for e in result.errors)
        db.close()

    def test_replay_approved_with_changes_idempotent(self, tmp_path):
        """approved_with_changes 二次 apply → idempotent_noop。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)

        r1 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r1.status == "applied"
        r2 = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r2.status == "idempotent_noop"
        assert r2.application_id == r1.application_id
        db.close()

    def test_approved_with_changes_stale_review_rejected(self, tmp_path):
        """approved_with_changes + KGV-019 stale → STALE_REVIEW（显式门）。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        # add_node + current_knowledge 非空且无 persisted node
        # → KGV-019 STALE_REVIEW_NODE_CHANGED（blocks_apply=True, blocks_review=False）
        gc = _make_node_candidate(current_knowledge=json.dumps({"node": "旧状态"}))
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "STALE_REVIEW"
        assert any("KGV-019" in e for e in result.errors)
        db.close()


# ═══════════════════════════════════════════════════════════════
# 7. dry-run / M7 / time
# ═══════════════════════════════════════════════════════════════

class TestApplyDryRunAndM7:
    """攻击 43/44/45/46/47/48/49：dry-run 零写入、M7 拒绝、时间门禁。"""

    def test_dry_run_add_node_zero_writes(self, tmp_path):
        """43. dry-run add_node → 零写入。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        counts_before = (
            _count_table(db, "graph_nodes"),
            _count_table(db, "graph_applications"),
        )
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT,
                              dry_run=True)

        assert result.status == "dry_run"
        assert result.dry_run is True
        assert result.application_id is not None  # 预检给出确定性 ID
        assert (_count_table(db, "graph_nodes"),
                _count_table(db, "graph_applications")) == counts_before
        db.close()

    def test_dry_run_add_edge_zero_writes(self, tmp_path):
        """44. dry-run add_edge → 零写入。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_edge_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        counts_before = (
            _count_table(db, "graph_edges"),
            _count_table(db, "graph_applications"),
        )
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT,
                              dry_run=True)
        assert result.status == "dry_run"
        assert (_count_table(db, "graph_edges"),
                _count_table(db, "graph_applications")) == counts_before
        db.close()

    def test_dry_run_approved_with_changes_zero_writes(self, tmp_path):
        """45. dry-run approved_with_changes → 零写入。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        _import_review(workflow, gc, decision="修改后批准", patch=patch)

        counts_before = (
            _count_table(db, "graph_nodes"),
            _count_table(db, "graph_applications"),
            _count_table(db, "graph_changes"),
            _count_table(db, "graph_reviews"),
        )
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT,
                              dry_run=True)
        assert result.status == "dry_run"
        assert (_count_table(db, "graph_nodes"),
                _count_table(db, "graph_applications"),
                _count_table(db, "graph_changes"),
                _count_table(db, "graph_reviews")) == counts_before
        db.close()

    def test_modify_attribute_requires_m7(self, tmp_path):
        """46. modify_attribute → CHANGE_TYPE_REQUIRES_M7。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate(change_type="modify_attribute")
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "CHANGE_TYPE_REQUIRES_M7"
        assert _count_table(db, "graph_applications") == 0
        db.close()

    def test_retire_node_requires_m7(self, tmp_path):
        """47. retire_node → CHANGE_TYPE_REQUIRES_M7。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate(change_type="retire_node")
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "CHANGE_TYPE_REQUIRES_M7"
        db.close()

    def test_retire_edge_requires_m7(self, tmp_path):
        """48. retire_edge → CHANGE_TYPE_REQUIRES_M7。"""
        db, _ = _setup_db(tmp_path, raw_item_entities=["company:src", "company:tgt"])
        candidate_repo, graph_repo, _, _, engine = _make_components(db)
        gc = _make_edge_candidate(change_type="retire_edge")
        candidate_repo.append_candidate(gc)
        # M4 KGV-015 在 import 阶段拦截 retire（需 persisted edge），手工构造 review
        _manual_review(db, gc, graph_repo, decision="approved")

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "CHANGE_TYPE_REQUIRES_M7"
        assert _count_table(db, "graph_applications") == 0
        db.close()

    def test_applied_at_before_reviewed_at_rejected(self, tmp_path):
        """49. applied_at < reviewed_at → APPLY_TIME_INVALID。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准", reviewed_at=T1)

        result = engine.apply(gc.graph_change_id,
                              applied_at="2026-08-08T12:00:00+08:00")  # < T1
        assert _reject_code(result) == "APPLY_TIME_INVALID"
        db.close()


# ═══════════════════════════════════════════════════════════════
# 8. atomicity / concurrency
# ═══════════════════════════════════════════════════════════════

class TestApplyAtomicity:
    """攻击 40/41：真实 SQLite 原子性。"""

    def test_application_failure_rolls_back_target(self, tmp_path, monkeypatch):
        """40. target 写入成功 + application 写入强制失败 → 整体 rollback。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        nodes_before = _count_table(db, "graph_nodes")
        apps_before = _count_table(db, "graph_applications")

        # 强制 append_application 在事务内抛错（模拟 INSERT 失败）
        original = graph_repo.append_application

        def _boom(*args, **kwargs):
            raise sqlite3.OperationalError("simulated application insert failure")

        monkeypatch.setattr(graph_repo, "append_application", _boom)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"

        # 真实 rollback：target 与 application 均未写入
        assert _count_table(db, "graph_nodes") == nodes_before
        assert _count_table(db, "graph_applications") == apps_before
        db.close()

    def test_target_conflict_rolls_back_application(self, tmp_path, monkeypatch):
        """41. target append 失败 → application 不回写。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        # 预置冲突 target（同 id/version 不同 payload → append_node 抛 IMMUTABLE）
        node = GraphNode(
            node_id="company:test-corp", node_type="Company",
            name="不同", status="active", version=1,
            evidence_ids=[EVIDENCE_UUID], review_status="approved",
            origin_kind="graph_change",
            originating_graph_change_id=str(uuid.uuid4()),
            created_at=T0, last_reviewed_at=T1,
        )
        graph_repo.append_node(node)

        apps_before = _count_table(db, "graph_applications")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "APPLY_REJECTED"
        assert _count_table(db, "graph_applications") == apps_before
        db.close()


class TestApplyConcurrency:
    """攻击 42：双连接并发互斥候选，BEGIN IMMEDIATE 消除 TOCTOU。"""

    def test_two_connections_conflicting_candidates(self, tmp_path):
        """双连接 + 互斥 candidate：最多一个 commit，无 half application。

        每个 worker thread 在自己的线程内创建 Database connection
        （SQLite 默认线程保护 check_same_thread=True），仍为
        same SQLite file + two independent connections + BEGIN IMMEDIATE。
        """
        from research_os.storage import Database
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        db_path = tmp_path / "concurrent.db"
        # 主线程先 initialize 一次（建表），两个 worker 复用文件
        setup_db = Database(db_path)
        setup_db.initialize()
        _seed_concurrent(setup_db)
        setup_db.close()

        results = {}
        # Barrier(3)：主线程 + worker A + worker B。
        # 每个 worker 在自己的线程内完成 setup（candidate + review 写操作）
        # 与 apply；barrier 保证双方 setup 完成后同时竞争 apply。
        barrier = threading.Barrier(3)

        def run_a():
            db_a = Database(db_path)
            candidate_repo_a = GraphChangeCandidateRepository(db_a)
            graph_repo_a = GraphRepository(db_a)
            validator_a = KnowledgeValidator(db_a, graph_repo_a)
            workflow_a = ReviewWorkflow(db_a, candidate_repo_a, graph_repo_a,
                                        validator_a)
            gc_a = _make_node_candidate(change_id=str(uuid.uuid4()))
            candidate_repo_a.append_candidate(gc_a)
            _import_review(workflow_a, gc_a, decision="批准")
            engine_a = ApplyEngine(db_a, candidate_repo_a, graph_repo_a,
                                   validator_a)
            barrier.wait()
            results["a"] = engine_a.apply(gc_a.graph_change_id,
                                          applied_at=APPLIED_AT)
            db_a.close()

        def run_b():
            db_b = Database(db_path)
            candidate_repo_b = GraphChangeCandidateRepository(db_b)
            graph_repo_b = GraphRepository(db_b)
            validator_b = KnowledgeValidator(db_b, graph_repo_b)
            workflow_b = ReviewWorkflow(db_b, candidate_repo_b, graph_repo_b,
                                        validator_b)
            gc_b = _make_node_candidate(change_id=str(uuid.uuid4()))
            candidate_repo_b.append_candidate(gc_b)
            _import_review(workflow_b, gc_b, decision="批准")
            engine_b = ApplyEngine(db_b, candidate_repo_b, graph_repo_b,
                                   validator_b)
            barrier.wait()
            results["b"] = engine_b.apply(gc_b.graph_change_id,
                                          applied_at=APPLIED_AT)
            db_b.close()

        ta = threading.Thread(target=run_a)
        tb = threading.Thread(target=run_b)
        ta.start()
        tb.start()
        barrier.wait()  # 主线程释放
        ta.join(timeout=60)
        tb.join(timeout=60)

        statuses = {k: v.status for k, v in results.items()}
        # 最多一个 committed。两 worker 目标同一 node v1 但不同 change_id
        # （⇒ 不同 idempotency key、node payload 因随机
        # originating_graph_change_id 不同）；BEGIN IMMEDIATE 写锁串行化后，
        # 后到者因 target payload 差异触发 version conflict 或 M4 gate reject，
        # 不可能两个都 applied。
        committed = [k for k, s in statuses.items() if s == "applied"]
        assert len(committed) <= 1, f"两个互斥 candidate 都 commit: {statuses}"

        # 无 half application：applications 一致性
        check_db = Database(db_path)
        apps = _count_table(check_db, "graph_applications")
        if committed:
            assert apps == 1
        assert apps <= 1
        check_db.close()

    def test_second_connection_blocks_until_first_commits(self, tmp_path):
        """BEGIN IMMEDIATE：第二连接等待写锁，事务内 recheck 幂等。"""
        from research_os.storage import Database
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        from research_os.knowledge.repository import GraphRepository

        db_path = tmp_path / "lock.db"
        db_a = Database(db_path)
        db_a.initialize()
        _seed_concurrent(db_a)
        candidate_repo_a = GraphChangeCandidateRepository(db_a)
        graph_repo_a = GraphRepository(db_a)
        validator_a = KnowledgeValidator(db_a, graph_repo_a)
        workflow_a = ReviewWorkflow(db_a, candidate_repo_a, graph_repo_a, validator_a)
        gc = _make_node_candidate()
        candidate_repo_a.append_candidate(gc)
        _import_review(workflow_a, gc, decision="批准")
        engine_a = ApplyEngine(db_a, candidate_repo_a, graph_repo_a, validator_a)

        # 手动持有 BEGIN IMMEDIATE 写锁
        db_a._conn.commit()
        db_a._conn.execute("BEGIN IMMEDIATE")

        results = {}

        def run_b():
            # worker 线程在自己的线程内创建 Database connection
            db_b = Database(db_path)
            candidate_repo_b = GraphChangeCandidateRepository(db_b)
            graph_repo_b = GraphRepository(db_b)
            validator_b = KnowledgeValidator(db_b, graph_repo_b)
            engine_b = ApplyEngine(db_b, candidate_repo_b, graph_repo_b,
                                   validator_b)
            results["b"] = engine_b.apply(gc.graph_change_id,
                                          applied_at=APPLIED_AT)
            db_b.close()

        tb = threading.Thread(target=run_b)
        tb.start()
        tb.join(timeout=2)
        assert tb.is_alive(), "连接 B 应因写锁阻塞"

        # 释放锁（连接 A commit）
        db_a._conn.execute("COMMIT")
        db_a._conn.commit()
        tb.join(timeout=60)

        assert results["b"].status == "applied"
        db_a.close()


# ═══════════════════════════════════════════════════════════════
# 9. M6-R1：immediate transaction 语义
# ═══════════════════════════════════════════════════════════════

class TestImmediateTransactionSemantics:
    """M6-R1：COMMIT 失败传播 / 无隐式 commit / rollback context。"""

    def test_active_transaction_conflict(self, tmp_path):
        """pre-existing transaction → immediate_transaction 不得自动 commit。"""
        from research_os.storage import Database

        db_path = tmp_path / "txn.db"
        db = Database(db_path)
        conn = db._conn
        conn.execute("CREATE TABLE IF NOT EXISTS t (x)")
        conn.execute("INSERT INTO t VALUES (1)")
        assert conn.in_transaction is True  # 调用者已有隐式事务

        with pytest.raises(RuntimeError, match="ACTIVE_TRANSACTION_CONFLICT"):
            with db.immediate_transaction():
                pass

        # 调用者已有事务未被自动 commit（work 保留）
        assert conn.in_transaction is True
        assert conn.execute("SELECT COUNT(*) AS c FROM t").fetchone()["c"] == 1
        conn.rollback()
        db.close()

    def test_commit_failure_propagates(self):
        """COMMIT 失败必须异常传播（不得 silent success）。"""
        from research_os.storage.db import _ImmediateTransaction

        class _FakeDb:
            def __init__(self, conn):
                self._conn = conn

        class _FailingCommitConn:
            def __init__(self):
                self.in_transaction = False

            def execute(self, sql, *args):
                if sql.startswith("BEGIN"):
                    self.in_transaction = True
                    return None
                if sql.startswith("COMMIT"):
                    self.in_transaction = False
                    raise sqlite3.OperationalError("simulated commit failure")
                if sql.startswith("ROLLBACK"):
                    self.in_transaction = False
                    return None
                return None

        fake = _FailingCommitConn()
        txn = _ImmediateTransaction(_FakeDb(fake))
        with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
            with txn:
                pass

    def test_rollback_failure_preserves_original_exception(self):
        """业务异常 + ROLLBACK 失败：保留原始异常并附加 rollback context。"""
        from research_os.storage.db import _ImmediateTransaction

        class _FakeDb:
            def __init__(self, conn):
                self._conn = conn

        class _FailingRollbackConn:
            def __init__(self):
                self.in_transaction = False

            def execute(self, sql, *args):
                if sql.startswith("BEGIN"):
                    self.in_transaction = True
                    return None
                if sql.startswith("ROLLBACK"):
                    raise sqlite3.OperationalError("simulated rollback failure")
                return None

        fake = _FailingRollbackConn()
        txn = _ImmediateTransaction(_FakeDb(fake))
        with pytest.raises(RuntimeError, match="ROLLBACK failed after ValueError"):
            with txn:
                raise ValueError("original business error")

    def test_commit_failure_engine_not_applied(self, tmp_path, monkeypatch):
        """COMMIT 失败 → ApplyEngine 不得返回 applied。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
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


# ═══════════════════════════════════════════════════════════════
# 10. M6-R1：GraphApplication tamper attacks（payload + columns）
# ═══════════════════════════════════════════════════════════════

class TestApplicationTamperAttacks:
    """M6-R1：第一次 apply 后直接 SQL 篡改 application payload/columns。"""

    def _apply_once(self, tmp_path):
        """建立已 apply 状态，返回 (db, engine, gc, app_id)。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")
        r = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert r.status == "applied"
        return db, engine, gc, r.application_id

    def _tamper_payload(self, db, app_id, field, value):
        row = db._conn.execute(
            "SELECT payload FROM graph_applications WHERE application_id = ?",
            (app_id,),
        ).fetchone()
        payload = json.loads(row["payload"])
        payload[field] = value
        db._conn.execute(
            "UPDATE graph_applications SET payload = ? WHERE application_id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), app_id),
        )
        db._conn.commit()

    def _tamper_column(self, db, app_id, column, value):
        db._conn.execute(
            f"UPDATE graph_applications SET {column} = ? WHERE application_id = ?",
            (value, app_id),
        )
        db._conn.commit()

    def test_payload_application_id_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "application_id", str(uuid.uuid4()))
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_original_graph_change_id_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "original_graph_change_id",
                             str(uuid.uuid4()))
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_decision_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "decision", "deferred")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_review_candidate_hash_tampered(self, tmp_path):
        """review_candidate_hash 篡改 → reject。"""
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "review_candidate_hash", "a" * 64)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_effective_candidate_hash_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "effective_candidate_hash", "b" * 64)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_status_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "status", "revoked")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_payload_applied_at_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_payload(db, app_id, "applied_at",
                             "2026-08-10T00:00:00+08:00")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_column_application_id_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_column(db, app_id, "application_id", str(uuid.uuid4()))
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_column_graph_change_id_tampered(self, tmp_path):
        """graph_change_id 改为另一个合法 GraphChange → reject。"""
        db, engine, gc, app_id = self._apply_once(tmp_path)
        # 另一个合法 candidate（满足 FK）
        other = _make_node_candidate()
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        GraphChangeCandidateRepository(db).append_candidate(other)
        self._tamper_column(db, app_id, "graph_change_id",
                            other.graph_change_id)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_column_review_id_tampered(self, tmp_path):
        """review_id 改为另一个已存在 review → reject。"""
        db, engine, gc, app_id = self._apply_once(tmp_path)
        # 另一个 candidate 的合法 review（满足 FK；用 edge candidate 避免
        # 与已 apply 的 node 冲突 KGV-013）
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        candidate_repo = GraphChangeCandidateRepository(db)
        other = _make_edge_candidate()
        candidate_repo.append_candidate(other)
        _, graph_repo, _, workflow, _ = _make_components(db)
        md2 = _build_review_markdown(other, decision="批准",
                                     reviewer_id="reviewer-other")
        result2 = workflow.review_import(md2)
        assert result2.status == "ok", f"import failed: {result2.errors}"
        self._tamper_column(db, app_id, "review_id", result2.review_id)
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()

    def test_column_applied_at_tampered(self, tmp_path):
        db, engine, gc, app_id = self._apply_once(tmp_path)
        self._tamper_column(db, app_id, "applied_at",
                            "2026-08-10T00:00:00+08:00")
        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()


# ═══════════════════════════════════════════════════════════════
# 11. M6-R1：malformed payload attacks
# ═══════════════════════════════════════════════════════════════

class TestMalformedPayloadAttacks:
    """M6-R1：candidate/review/replacement/target payload 损坏 → structured reject。"""

    def test_candidate_payload_invalid_json(self, tmp_path):
        """original graph_changes.payload invalid JSON → CANDIDATE_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        _import_review(workflow, gc, decision="批准")

        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            ("{broken json", gc.graph_change_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "CANDIDATE_PAYLOAD_INVALID"
        db.close()

    def test_replacement_payload_invalid_json(self, tmp_path):
        """replacement payload invalid JSON → REPLACEMENT_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        patch = [{"op": "replace", "path": "/suggested_change", "value": "更新"}]
        review = _import_review(workflow, gc, decision="修改后批准", patch=patch)

        db._conn.execute(
            "UPDATE graph_changes SET payload = ? WHERE graph_change_id = ?",
            ("{broken json", review.resulting_graph_change_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "REPLACEMENT_PAYLOAD_INVALID"
        db.close()

    def test_review_payload_invalid_json(self, tmp_path):
        """selected graph_reviews.payload invalid JSON → REVIEW_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")

        db._conn.execute(
            "UPDATE graph_reviews SET payload = ? WHERE review_id = ?",
            ("{broken json", review.review_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "REVIEW_PAYLOAD_INVALID"
        db.close()

    def test_review_payload_invalid_json_explicit_review_id(self, tmp_path):
        """显式 --review-id 且 payload 损坏 → REVIEW_PAYLOAD_INVALID。"""
        db, _ = _setup_db(tmp_path)
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        review = _import_review(workflow, gc, decision="批准")

        db._conn.execute(
            "UPDATE graph_reviews SET payload = ? WHERE review_id = ?",
            ("{broken json", review.review_id),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, review_id=review.review_id,
                              applied_at=APPLIED_AT)
        assert _reject_code(result) == "REVIEW_PAYLOAD_INVALID"
        db.close()

    def test_persisted_target_invalid_json_during_replay(self, tmp_path):
        """replay 时 persisted target payload invalid JSON → APPLICATION_INTEGRITY_CONFLICT。"""
        db, engine, gc, _ = _apply_and_return_all(tmp_path)

        # 攻击：target node payload 损坏（application 已存在）
        db._conn.execute(
            "UPDATE graph_nodes SET payload = ? WHERE node_id = ? AND version = 1",
            ("{broken json", "company:test-corp"),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "APPLICATION_INTEGRITY_CONFLICT"
        db.close()


def _apply_and_return_all(tmp_path):
    """建立已 apply 状态（供 replay/malformed 测试），返回 (db, engine, gc, app_id)。"""
    db, _ = _setup_db(tmp_path)
    candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
    gc = _make_node_candidate()
    candidate_repo.append_candidate(gc)
    _import_review(workflow, gc, decision="批准")
    r = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
    assert r.status == "applied"
    return db, engine, gc, r.application_id


# ═══════════════════════════════════════════════════════════════
# 12. M6-R1：effective Evidence review-time closure
# ═══════════════════════════════════════════════════════════════

class TestEvidenceReviewTimeClosure:
    """M6-R1：approved_with_changes 的 effective Evidence 必须满足
    published_at / retrieved_at <= reviewed_at。"""

    E2 = "55555555-5555-5555-5555-555555555555"

    def _replacement_with_e2(self, db, workflow, gc):
        """构造引用 E1+E2 的 approved_with_changes review。"""
        patch = [
            {"op": "replace", "path": "/new_evidence_ids",
             "value": [EVIDENCE_UUID, self.E2]},
            {"op": "replace", "path": "/node/evidence_ids",
             "value": [EVIDENCE_UUID, self.E2]},
        ]
        md = _build_review_markdown(gc, decision="修改后批准", patch=patch)
        result = workflow.review_import(md)
        assert result.status == "ok", f"import failed: {result.errors}"
        return result

    def test_attack_a_evidence_retrieved_after_review(self, tmp_path):
        """Attack A：E2.published_at < T1 但 retrieved_at > T1（< applied_at）
        → EVIDENCE_RETRIEVED_AFTER_REVIEW。"""
        db, _ = _setup_db(tmp_path)
        # E2: published 08-05 (< T1 08-08T14:00)，retrieved 08-09 (> T1，< applied 08-09T10:00)
        _add_second_evidence(db, self.E2,
                             published_at="2026-08-05T10:00:00+08:00",
                             retrieved_at="2026-08-09T08:00:00+08:00")
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        self._replacement_with_e2(db, workflow, gc)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "EVIDENCE_RETRIEVED_AFTER_REVIEW"
        db.close()

    def test_attack_b_evidence_mutated_after_review(self, tmp_path):
        """Attack B：先合法完成 review，review 后 SQL mutation E2 时间
        （published/retrieved = T1 + delta，但 <= applied_at）→ reject。"""
        db, _ = _setup_db(tmp_path)
        # E2 初始合法：retrieved_at < T1
        _add_second_evidence(db, self.E2,
                             published_at="2026-08-05T10:00:00+08:00",
                             retrieved_at="2026-08-06T10:00:00+08:00")
        candidate_repo, _, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        self._replacement_with_e2(db, workflow, gc)

        # 攻击：review 后 mutation E2 时间（仍 <= applied_at）
        row = db._conn.execute(
            "SELECT payload FROM evidence WHERE evidence_id = ?", (self.E2,)
        ).fetchone()
        payload = json.loads(row["payload"])
        payload["published_at"] = "2026-08-08T15:00:00+08:00"  # > T1
        payload["retrieved_at"] = "2026-08-08T16:00:00+08:00"  # > T1
        db._conn.execute(
            "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
            (json.dumps(payload, ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")), self.E2),
        )
        db._conn.commit()

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert _reject_code(result) == "EVIDENCE_RETRIEVED_AFTER_REVIEW"
        db.close()

    def test_evidence_within_review_time_applies(self, tmp_path):
        """E2 时间全部 <= reviewed_at → apply 成功。"""
        db, _ = _setup_db(tmp_path)
        _add_second_evidence(db, self.E2,
                             published_at="2026-08-05T10:00:00+08:00",
                             retrieved_at="2026-08-06T10:00:00+08:00")
        candidate_repo, graph_repo, _, workflow, engine = _make_components(db)
        gc = _make_node_candidate()
        candidate_repo.append_candidate(gc)
        self._replacement_with_e2(db, workflow, gc)

        result = engine.apply(gc.graph_change_id, applied_at=APPLIED_AT)
        assert result.status == "applied"
        node = graph_repo.get_node_version("company:test-corp", 1)
        assert node is not None
        db.close()


def _seed_concurrent(db):
    """并发测试的 DB 种子（evidence/raw_item/entities/端点 nodes）。"""
    conn = db._conn
    ev = Evidence(
        evidence_id=EVIDENCE_UUID, source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID, title="测试证据",
        publisher="测试发布者",
        published_at="2026-08-01T10:00:00+08:00",
        retrieved_at="2026-08-02T10:00:00+08:00",
        url="https://example.com", excerpt="测试摘录",
        evidence_type="news_report", independence_group="group-1",
        source_tier="B", access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID,
         json.dumps(ev.model_dump(), ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")),
         SOURCE_UUID, RAW_ITEM_UUID, "group-1", "B"),
    )
    ri = {
        "raw_item_id": RAW_ITEM_UUID, "source_id": SOURCE_UUID,
        "external_id": "ext-001", "url": "https://example.com",
        "title": "测试", "publisher": "测试", "author": "测试作者",
        "published_at": "2026-08-01T10:00:00+08:00",
        "retrieved_at": "2026-08-02T10:00:00+08:00",
        "content_hash": SHA256_ZEROS, "content_excerpt": "测试摘录",
        "content_storage": "metadata_and_excerpt", "language": "zh-CN",
        "access_status": "ok", "entities": ["company:test-corp"],
        "raw_category": "news",
    }
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, json.dumps(ri, ensure_ascii=False),
         SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    for eid, ename in [("company:test-corp", "测试公司"),
                       ("company:src", "源公司"),
                       ("company:tgt", "目标公司")]:
        ent = Entity(entity_id=eid, entity_type="company", canonical_name=ename)
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, json.dumps(ent.model_dump(), ensure_ascii=False,
                             sort_keys=True, separators=(",", ":")),
             "company", ename),
        )
    conn.commit()
