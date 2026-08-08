"""M6 Deterministic Apply Engine：将已批准的人工审核确定性应用到图谱。

核心契约（Decision #36）：
- 只 apply `add_node` / `add_edge`；modify/retire → CHANGE_TYPE_REQUIRES_M7
- ZERO LLM / ZERO Provider / ZERO network
- GraphReview selection：显式 --review-id 或 0/1/>1 确定性规则，
  禁止 latest/approved/timestamp/first-row 自动策略
- Review 与 original GraphChange 均 Schema-first（Markdown NOT AUTHORITATIVE）
- approved：effective = original；validate_apply_preflight 全绿
- approved_with_changes：replacement 确定性 linkage + 重新构造验证
  （build_replacement_graph_change 唯一 helper），replacement tamper 拒绝
- candidate hash 唯一 authority = KnowledgeValidator.compute_candidate_hash()
- apply-time transformation：复制 effective node/edge dump，只改
  review_status=approved、last_reviewed_at=review.reviewed_at；
  MODEL_INFERENCE 保持不变；applied_at 只属于 graph_applications audit
- 不 UPDATE GraphChange / GraphReview（byte-for-byte immutable）
- idempotency key 确定性（不含 applied_at）；idempotent replay 优先识别
- BEGIN IMMEDIATE 事务消除 TOCTOU；任一步失败 ROLLBACK ALL
- dry-run：完整预检，0 writes / 0 mkdir
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any, Optional, Tuple

from research_os.models import GraphChange, GraphReview, GraphNode, GraphEdge
from research_os.validators.schema_validator import validate_instance
from research_os.knowledge.review_workflow import (
    build_replacement_graph_change,
    _make_replacement_gc_id,
)
from research_os.utils.time import now_iso, parse_iso

# M6 支持（真正 apply）的 change_type
_SUPPORTED_CHANGE_TYPES = ("add_node", "add_edge")

# 允许继续的 review decision
_APPLICABLE_DECISIONS = ("approved", "approved_with_changes")


def _canonical_json(obj: Any) -> str:
    """确定性紧凑 JSON（用于 canonical 对比与 intent）。"""
    return json.dumps(
        obj,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def schema_first_graph_change(candidate_dict: dict
                              ) -> Tuple[Optional[GraphChange], Optional[str]]:
    """raw graph_change.schema → GraphChange → model_dump → graph_change.schema。"""
    schema_errors = validate_instance(candidate_dict, "graph_change")
    if schema_errors:
        return None, f"GraphChange schema invalid: {'; '.join(schema_errors)}"
    try:
        gc = GraphChange(**candidate_dict)
    except Exception as e:
        return None, f"GraphChange Pydantic parse failed: {e}"
    try:
        dumped = gc.model_dump()
    except Exception as e:
        return None, f"GraphChange model_dump failed: {e}"
    schema_errors2 = validate_instance(dumped, "graph_change")
    if schema_errors2:
        return None, f"GraphChange dump schema re-validation failed: {'; '.join(schema_errors2)}"
    return gc, None


def schema_first_graph_review(review_dict: dict
                              ) -> Tuple[Optional[GraphReview], Optional[str]]:
    """raw graph_review.schema → GraphReview → model_dump → graph_review.schema。"""
    schema_errors = validate_instance(review_dict, "graph_review")
    if schema_errors:
        return None, f"GraphReview schema invalid: {'; '.join(schema_errors)}"
    try:
        review = GraphReview(**review_dict)
    except Exception as e:
        return None, f"GraphReview Pydantic parse failed: {e}"
    try:
        dumped = review.model_dump()
    except Exception as e:
        return None, f"GraphReview model_dump failed: {e}"
    schema_errors2 = validate_instance(dumped, "graph_review")
    if schema_errors2:
        return None, f"GraphReview dump schema re-validation failed: {'; '.join(schema_errors2)}"
    return review, None


@dataclass(frozen=True)
class ApplyResult:
    """M6 apply 显式结果（状态 + 内部 error code）。"""
    status: str  # "applied" / "idempotent_noop" / "dry_run" / "APPLY_REJECTED"
    original_graph_change_id: str
    effective_graph_change_id: str
    review_id: str
    application_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    target_kind: Optional[str] = None
    target_id: Optional[str] = None
    target_version: Optional[int] = None
    applied_at: Optional[str] = None
    dry_run: bool = False
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


class ApplyEngine:
    """M6 确定性 apply 引擎（零 LLM / 零 Provider / 零 network）。"""

    def __init__(self, db, candidate_repo, graph_repo, validator):
        self._db = db
        self._candidate_repo = candidate_repo
        self._graph_repo = graph_repo
        self._validator = validator

    # ── public API ──────────────────────────────────────────

    def apply(
        self,
        change_id: str,
        review_id: Optional[str] = None,
        applied_at: Optional[str] = None,
        dry_run: bool = False,
    ) -> ApplyResult:
        """确定性 apply 一个已批准人工审核的 GraphChange。

        Args:
            change_id: original reviewed GraphChange ID（不是默认 replacement ID）。
            review_id: 显式 GraphReview ID（disambiguation）。
            applied_at: 显式 ISO 时间；未提供则 capture now_iso() once。
            dry_run: 完整预检，0 writes。

        Returns:
            ApplyResult
        """
        # 1. Load original candidate（Schema-first）
        candidate_dict = self._candidate_repo.get_candidate(change_id)
        if candidate_dict is None:
            return self._reject(change_id, "CANDIDATE_NOT_FOUND",
                                f"Candidate not found: {change_id}")
        original_gc, err = schema_first_graph_change(candidate_dict)
        if err:
            return self._reject(change_id, "CANDIDATE_SCHEMA_INVALID", err)

        # 2. Review selection
        selected = self._select_review(change_id, review_id)
        if isinstance(selected, str):  # error code
            return self._reject(change_id, selected, self._last_error)

        # 3. Review Schema-first
        review, err = schema_first_graph_review(selected)
        if err:
            return self._reject(change_id, "REVIEW_SCHEMA_INVALID", err)

        # 4. Decision gate
        if review.decision not in _APPLICABLE_DECISIONS:
            return self._reject(
                change_id, "NON_APPLICABLE_REVIEW_DECISION",
                f"decision={review.decision} 不允许 apply（仅 approved / approved_with_changes）",
                review_id=review.review_id,
            )

        # 5. applied_at（capture once）+ 时间门禁
        # 使用 parse_iso 做 datetime 语义比较（KGV-014 同款），避免
        # naive/带时区字符串字典序比较的误判（now_iso 为 naive 无时区后缀，
        # reviewed_at 通常带 +08:00）。
        if applied_at is None:
            applied_at = now_iso()
        try:
            applied_dt = parse_iso(applied_at)
            reviewed_dt = parse_iso(review.reviewed_at)
        except ValueError as e:
            return self._reject(
                change_id, "APPLY_TIME_INVALID",
                f"时间解析失败: {e}",
                review_id=review.review_id,
            )
        if applied_dt < reviewed_dt:
            return self._reject(
                change_id, "APPLY_TIME_INVALID",
                f"applied_at={applied_at} < reviewed_at={review.reviewed_at}",
                review_id=review.review_id,
            )

        # 6. Candidate hash 验证（review 绑定 original，M4 authority）
        computed_hash = self._validator.compute_candidate_hash(original_gc)
        if review.candidate_hash != computed_hash:
            return self._reject(
                change_id, "CANDIDATE_HASH_MISMATCH",
                f"review.candidate_hash={review.candidate_hash} 与当前 candidate "
                f"hash={computed_hash} 不一致（candidate 被修改）",
                review_id=review.review_id,
            )

        # 7. Effective GraphChange 解析
        if review.decision == "approved":
            if review.review_patch:
                return self._reject(
                    change_id, "APPROVED_PATCH_NOT_EMPTY",
                    "approved 决策要求 review_patch 为空",
                    review_id=review.review_id,
                )
            if review.resulting_graph_change_id is not None:
                return self._reject(
                    change_id, "APPROVED_RESULTING_ID_NOT_NULL",
                    "approved 决策要求 resulting_graph_change_id 为 null",
                    review_id=review.review_id,
                )
            effective_gc = original_gc
        else:  # approved_with_changes
            # 8. deterministic linkage
            expected_resulting = _make_replacement_gc_id(review.review_id)
            if review.resulting_graph_change_id != expected_resulting:
                return self._reject(
                    change_id, "REPLACEMENT_ID_MISMATCH",
                    f"review.resulting_graph_change_id={review.resulting_graph_change_id} "
                    f"!= expected {expected_resulting}",
                    review_id=review.review_id,
                )
            # 9. load persisted replacement（Schema-first）
            repl_dict = self._candidate_repo.get_candidate(review.resulting_graph_change_id)
            if repl_dict is None:
                return self._reject(
                    change_id, "REPLACEMENT_MISSING",
                    f"replacement GraphChange {review.resulting_graph_change_id} 缺失",
                    review_id=review.review_id,
                )
            persisted_repl, rerr = schema_first_graph_change(repl_dict)
            if rerr:
                return self._reject(change_id, "REPLACEMENT_SCHEMA_INVALID", rerr,
                                    review_id=review.review_id)
            if persisted_repl.review_status != "candidate":
                return self._reject(
                    change_id, "REPLACEMENT_NOT_CANDIDATE",
                    f"replacement review_status={persisted_repl.review_status}（要求 candidate）",
                    review_id=review.review_id,
                )
            if persisted_repl.reviewed_at is not None:
                return self._reject(
                    change_id, "REPLACEMENT_REVIEWED_AT_NOT_NULL",
                    "replacement reviewed_at 必须为 null",
                    review_id=review.review_id,
                )
            # 10. 重新构造 expected replacement（唯一 helper，禁止第二套算法）
            try:
                expected_repl = build_replacement_graph_change(original_gc, review)
            except Exception as e:
                return self._reject(change_id, "REPLACEMENT_REBUILD_FAILED", str(e),
                                    review_id=review.review_id)
            expected_canonical = _canonical_json(expected_repl.model_dump())
            persisted_canonical = _canonical_json(persisted_repl.model_dump())
            if expected_canonical != persisted_canonical:
                return self._reject(
                    change_id, "REPLACEMENT_TAMPERED",
                    "persisted replacement canonical payload 与重新构造的 expected "
                    "replacement 不一致（replacement 被篡改）",
                    review_id=review.review_id,
                )
            effective_gc = expected_repl

        # 11. Effective candidate hash
        effective_hash = self._validator.compute_candidate_hash(effective_gc)

        # 12. change_type gate
        if effective_gc.change_type not in _SUPPORTED_CHANGE_TYPES:
            return self._reject(
                change_id, "CHANGE_TYPE_REQUIRES_M7",
                f"change_type={effective_gc.change_type} 属于 M7（modify/retire），M6 不实现",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 13. Build approved target（transformation）
        try:
            target_kind, target_id, target_version, target_dump = (
                self._build_approved_target(effective_gc, review)
            )
        except Exception as e:
            return self._reject(
                change_id, "TARGET_BUILD_FAILED", str(e),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 14. Idempotency（确定性，不含 applied_at）
        idem_key, app_id = self._compute_idempotency(
            change_id, effective_gc, review, effective_hash,
            target_kind, target_id, target_version,
        )

        # 15. Idempotent replay preflight（必须在 M4 gates 之前！
        #     第二次 apply 时 target 已存在，若先跑 KGV duplicate/stale 会错误 reject）
        try:
            existing_app = self._graph_repo.get_application_by_idempotency_key(idem_key)
        except Exception as e:
            return self._reject(change_id, "APPLICATION_READ_FAILED", str(e),
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if existing_app is not None:
            return self._replay_result(
                change_id, effective_gc, review, idem_key, app_id,
                target_kind, target_id, target_version, target_dump,
                existing_app, applied_at, dry_run,
            )

        # 16. M4 validation 组合门（仅新 apply）
        gate = self._validate_gates(original_gc, effective_gc, review, applied_at)
        if gate is not None:
            return gate

        # 17. Current-graph / version preflight（dry-run 也执行）
        preflight_err = self._target_preflight(
            target_kind, target_id, target_version, target_dump
        )
        if preflight_err is not None:
            return self._reject(
                change_id, preflight_err[0], preflight_err[1],
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 18. dry-run：完整预检，0 writes
        if dry_run:
            return ApplyResult(
                status="dry_run",
                original_graph_change_id=change_id,
                effective_graph_change_id=effective_gc.graph_change_id,
                review_id=review.review_id,
                application_id=app_id,
                idempotency_key=idem_key,
                target_kind=target_kind,
                target_id=target_id,
                target_version=target_version,
                applied_at=applied_at,
                dry_run=True,
            )

        # 19. BEGIN IMMEDIATE 事务（消除 TOCTOU；任一步失败 ROLLBACK ALL）
        try:
            with self._db.immediate_transaction() as conn:
                # 事务内 recheck idempotency（并发窗口内已有写入）
                existing = conn.execute(
                    "SELECT application_id, payload, applied_at FROM graph_applications "
                    "WHERE idempotency_key = ?",
                    (idem_key,),
                ).fetchone()
                if existing is not None:
                    existing_app = {
                        "application_id": existing["application_id"],
                        "payload": json.loads(existing["payload"]),
                        "applied_at": existing["applied_at"],
                    }
                    raise _InTxnReplay(existing_app)

                # 事务内 rerun current-state M4 validation（锁内最新状态）
                gate = self._validate_gates(original_gc, effective_gc, review, applied_at)
                if gate is not None:
                    raise ValueError("; ".join(gate.errors))

                # recheck target/version（append 方法内部强校验）
                if target_kind == "node":
                    node = GraphNode(**target_dump)
                    result = self._graph_repo.append_node(node, conn=conn)
                else:
                    edge = GraphEdge(**target_dump)
                    result = self._graph_repo.append_edge(edge, conn=conn)
                if result not in ("inserted", "idempotent_noop"):
                    raise ValueError(f"target append failed: {result}")

                # append GraphApplication（INSERT ONLY）
                payload = {
                    "application_id": app_id,
                    "original_graph_change_id": change_id,
                    "effective_graph_change_id": effective_gc.graph_change_id,
                    "review_id": review.review_id,
                    "decision": review.decision,
                    "review_candidate_hash": review.candidate_hash,
                    "effective_candidate_hash": effective_hash,
                    "target_kind": target_kind,
                    "target_id": target_id,
                    "target_version": target_version,
                    "applied_at": applied_at,
                    "status": "applied",
                }
                app_result = self._graph_repo.append_application(
                    app_id,
                    effective_gc.graph_change_id,
                    review.review_id,
                    idem_key,
                    payload,
                    applied_at,
                    conn=conn,
                )
                if app_result not in ("inserted", "idempotent_noop"):
                    raise ValueError(f"application append failed: {app_result}")
        except _InTxnReplay as replay:
            # 事务内发现已存在 application（并发窗口）：走 replay 验证
            return self._replay_result(
                change_id, effective_gc, review, idem_key, app_id,
                target_kind, target_id, target_version, target_dump,
                replay.existing_app, applied_at, dry_run=False,
            )
        except Exception as e:
            return self._reject(
                change_id, "APPLY_FAILED", str(e),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        return ApplyResult(
            status="applied",
            original_graph_change_id=change_id,
            effective_graph_change_id=effective_gc.graph_change_id,
            review_id=review.review_id,
            application_id=app_id,
            idempotency_key=idem_key,
            target_kind=target_kind,
            target_id=target_id,
            target_version=target_version,
            applied_at=applied_at,
        )

    # ── review selection ────────────────────────────────────

    def _select_review(self, change_id: str, review_id: Optional[str]) -> Any:
        """GraphReview selection（显式 --review-id 或 0/1/>1 确定性规则）。

        Returns:
            review dict；或 error code 字符串（错误详情存于 self._last_error）。
        """
        if review_id is not None:
            try:
                row = self._db._conn.execute(
                    "SELECT payload FROM graph_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            except Exception as e:
                self._last_error = f"DB error reading review {review_id}: {e}"
                return "REVIEW_READ_FAILED"
            if row is None:
                self._last_error = f"Review not found: {review_id}"
                return "REVIEW_NOT_FOUND"
            review_dict = json.loads(row["payload"])
            if review_dict.get("graph_change_id") != change_id:
                self._last_error = (
                    f"REVIEW_CHANGE_MISMATCH: review {review_id} 属于 "
                    f"graph_change {review_dict.get('graph_change_id')}，不是 {change_id}"
                )
                return "REVIEW_CHANGE_MISMATCH"
            return review_dict

        try:
            rows = self._db._conn.execute(
                "SELECT payload FROM graph_reviews WHERE graph_change_id = ? "
                "ORDER BY reviewed_at, review_id",
                (change_id,),
            ).fetchall()
        except Exception as e:
            self._last_error = f"DB error reading reviews for {change_id}: {e}"
            return "REVIEW_READ_FAILED"

        if not rows:
            self._last_error = (
                f"REVIEW_REQUIRED: candidate {change_id} 没有任何人工审核记录"
            )
            return "REVIEW_REQUIRED"
        if len(rows) > 1:
            ids = [json.loads(r["payload"]).get("review_id") for r in rows]
            self._last_error = (
                f"AMBIGUOUS_REVIEW_SELECTION: candidate {change_id} 有 {len(rows)} "
                f"条审核记录 {ids}，必须显式提供 --review-id"
            )
            return "AMBIGUOUS_REVIEW_SELECTION"
        return json.loads(rows[0]["payload"])

    # ── M4 validation 组合门 ────────────────────────────────

    def _validate_gates(self, original_gc, effective_gc, review, applied_at):
        """M4 validation 组合门（approved / approved_with_changes）。

        Returns:
            None（通过）或 ApplyResult（APPLY_REJECTED）。
        """
        if review.decision == "approved":
            vres = self._validator.validate_apply_preflight(
                original_gc, review, applied_at
            )
            if not (vres.structural_ok and vres.review_eligible and vres.apply_eligible):
                msgs = [f"{i.rule_id}: {i.message}" for i in vres.issues
                        if i.blocks_review or i.blocks_apply]
                return self._reject(
                    original_gc.graph_change_id, "M4_APPLY_PREFLIGHT_FAILED",
                    "approved apply preflight 未全绿: " + "; ".join(msgs),
                    review_id=review.review_id,
                    effective_gc_id=effective_gc.graph_change_id,
                )
            return None

        # approved_with_changes
        vres = self._validator.validate_review(original_gc, review, applied_at)
        if not (vres.structural_ok and vres.review_eligible):
            msgs = [f"{i.rule_id}: {i.message}" for i in vres.issues
                    if i.blocks_review]
            return self._reject(
                original_gc.graph_change_id, "M4_REVIEW_VALIDATION_FAILED",
                "original review validation 未通过: " + "; ".join(msgs),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        # KGV-019 stale：即使 review_eligible=true 也必须 reject
        kgv019 = [i for i in vres.issues if i.rule_id == "KGV-019"]
        if kgv019:
            msgs = [f"{i.rule_id}: {i.message}" for i in kgv019]
            return self._reject(
                original_gc.graph_change_id, "STALE_REVIEW",
                "KGV-019 stale review 阻止 apply: " + "; ".join(msgs),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        # replacement validate_candidate（全绿要求）
        cres = self._validator.validate_candidate(effective_gc, applied_at)
        if not (cres.structural_ok and cres.review_eligible and cres.apply_eligible):
            msgs = [f"{i.rule_id}: {i.message}" for i in cres.issues
                    if i.blocks_review or i.blocks_apply]
            return self._reject(
                original_gc.graph_change_id, "M4_REPLACEMENT_VALIDATION_FAILED",
                "replacement candidate validation 未全绿: " + "; ".join(msgs),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        return None

    # ── approved target transformation ──────────────────────

    def _build_approved_target(self, effective_gc, review):
        """从 effective candidate 构造 approved core object（Schema-first）。

        - 复制 effective node/edge model_dump
        - 只改变 review_status=approved、last_reviewed_at=review.reviewed_at
        - add_node 要求 status=active，否则 ADD_NODE_NOT_ACTIVE

        Returns:
            (target_kind, target_id, target_version, target_dump)
        """
        if effective_gc.node is not None:
            node_dump = effective_gc.node.model_dump()
            node_dump["review_status"] = "approved"
            node_dump["last_reviewed_at"] = review.reviewed_at
            if node_dump.get("status") != "active":
                raise ValueError(
                    f"ADD_NODE_NOT_ACTIVE: node {node_dump['node_id']} "
                    f"status={node_dump.get('status')}（add_node 要求 active）"
                )
            # Schema-first
            schema_errors = validate_instance(node_dump, "graph_node")
            if schema_errors:
                raise ValueError(
                    f"approved node schema invalid: {'; '.join(schema_errors)}"
                )
            node = GraphNode(**node_dump)
            dumped = node.model_dump()
            schema_errors2 = validate_instance(dumped, "graph_node")
            if schema_errors2:
                raise ValueError(
                    f"approved node dump schema invalid: {'; '.join(schema_errors2)}"
                )
            return "node", node.node_id, node.version, dumped

        if effective_gc.edge is not None:
            edge_dump = effective_gc.edge.model_dump()
            edge_dump["review_status"] = "approved"
            edge_dump["last_reviewed_at"] = review.reviewed_at
            # Schema-first
            schema_errors = validate_instance(edge_dump, "graph_edge")
            if schema_errors:
                raise ValueError(
                    f"approved edge schema invalid: {'; '.join(schema_errors)}"
                )
            edge = GraphEdge(**edge_dump)
            dumped = edge.model_dump()
            schema_errors2 = validate_instance(dumped, "graph_edge")
            if schema_errors2:
                raise ValueError(
                    f"approved edge dump schema invalid: {'; '.join(schema_errors2)}"
                )
            return "edge", edge.edge_id, edge.version, dumped

        raise ValueError("effective GraphChange 缺少 node 与 edge")

    # ── idempotency ─────────────────────────────────────────

    def _compute_idempotency(self, change_id, effective_gc, review,
                             effective_hash, target_kind, target_id,
                             target_version) -> Tuple[str, str]:
        """确定性 idempotency key + application ID（均不含 applied_at）。"""
        intent = {
            "original_graph_change_id": change_id,
            "effective_graph_change_id": effective_gc.graph_change_id,
            "review_id": review.review_id,
            "effective_candidate_hash": effective_hash,
            "target_kind": target_kind,
            "target_id": target_id,
            "target_version": target_version,
        }
        canonical = _canonical_json(intent)
        idem_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        app_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "graph-application:" + idem_key))
        return idem_key, app_id

    # ── target/version preflight ────────────────────────────

    def _target_preflight(self, target_kind, target_id, target_version,
                          target_dump) -> Optional[Tuple[str, str]]:
        """current-graph / version preflight（dry-run 与写前共用）。

        - 目标 (id, version) 已存在且 payload 一致 → TARGET_ALREADY_EXISTS_IDEMPOTENT
        - 已存在但 payload 不同 → TARGET_VERSION_CONFLICT
        - 版本规则：首个版本必须 1，后续必须 N+1（与 append_node/append_edge 一致）

        Returns:
            None（可写）或 (error_code, message)。
        """
        if target_kind == "node":
            existing = self._graph_repo.get_node_version(target_id, target_version)
            latest = self._graph_repo.get_latest_node_version(target_id)
        else:
            existing = self._graph_repo.get_edge_version(target_id, target_version)
            latest = self._graph_repo.get_latest_edge_version(target_id)
        if existing is not None:
            if _canonical_json(existing) == _canonical_json(target_dump):
                return ("TARGET_ALREADY_EXISTS_IDEMPOTENT",
                        f"{target_kind} {target_id} v{target_version} 已存在且 payload 一致")
            return ("TARGET_VERSION_CONFLICT",
                    f"{target_kind} {target_id} v{target_version} 已存在但 payload 不同")
        # 版本规则（与 append 权威一致）
        if target_version > 1 and latest is None:
            return ("VERSION_VIOLATION",
                    f"{target_kind} {target_id} 首个版本必须是 1，got version={target_version}")
        if latest is not None and target_version != latest + 1:
            return ("VERSION_GAP",
                    f"{target_kind} {target_id} 已有 max version={latest}，"
                    f"got version={target_version}（期望 {latest + 1}）")
        return None

    # ── replay verification ─────────────────────────────────

    def _replay_result(self, change_id, effective_gc, review, idem_key, app_id,
                       target_kind, target_id, target_version, target_dump,
                       existing_app, applied_at, dry_run) -> ApplyResult:
        """已存在 GraphApplication 的 replay 验证。

        - application audit integrity + target 存在 + payload 一致
          → IDEMPOTENT_NOOP（返回已有 application_id/applied_at）
        - 任何不一致 → APPLICATION_INTEGRITY_CONFLICT（不得冒充幂等）
        """
        app_payload = existing_app.get("payload") or {}
        # audit integrity：派生字段必须一致
        if app_payload.get("target_kind") != target_kind:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT",
                                "application.target_kind 不一致",
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if app_payload.get("target_id") != target_id:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT",
                                "application.target_id 不一致",
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if app_payload.get("target_version") != target_version:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT",
                                "application.target_version 不一致",
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if app_payload.get("effective_graph_change_id") != effective_gc.graph_change_id:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT",
                                "application.effective_graph_change_id 不一致",
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if app_payload.get("review_id") != review.review_id:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT",
                                "application.review_id 不一致",
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)

        # target 存在 + payload 一致
        if target_kind == "node":
            persisted = self._graph_repo.get_node_version(target_id, target_version)
        else:
            persisted = self._graph_repo.get_edge_version(target_id, target_version)
        if persisted is None:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                f"application 存在但 target {target_kind} {target_id} "
                f"v{target_version} 缺失",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        if _canonical_json(persisted) != _canonical_json(target_dump):
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                f"application 存在但 target {target_kind} {target_id} "
                f"v{target_version} payload 不一致（被篡改）",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 全部一致 → IDEMPOTENT_NOOP
        stored_applied_at = existing_app.get("applied_at") or app_payload.get("applied_at")
        return ApplyResult(
            status="idempotent_noop",
            original_graph_change_id=change_id,
            effective_graph_change_id=effective_gc.graph_change_id,
            review_id=review.review_id,
            application_id=existing_app.get("application_id") or app_id,
            idempotency_key=idem_key,
            target_kind=target_kind,
            target_id=target_id,
            target_version=target_version,
            applied_at=stored_applied_at,
            dry_run=dry_run,
        )

    # ── helpers ─────────────────────────────────────────────

    def _reject(self, change_id, error_code: str, message: str, *,
                review_id: str = "", effective_gc_id: str = "") -> ApplyResult:
        """构造 APPLY_REJECTED 结果（error code 明确）。"""
        return ApplyResult(
            status="APPLY_REJECTED",
            original_graph_change_id=change_id,
            effective_graph_change_id=effective_gc_id or change_id,
            review_id=review_id,
            errors=(f"{error_code}: {message}",),
        )


class _InTxnReplay(Exception):
    """事务内发现已存在 application（并发窗口）——内部信号。"""

    def __init__(self, existing_app: dict):
        super().__init__("idempotent replay detected inside transaction")
        self.existing_app = existing_app
