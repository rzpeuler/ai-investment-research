"""M6 Deterministic Apply Engine：将已批准的人工审核确定性应用到图谱。

核心契约（Decision #36 + M6-R1 safety closure）：
- 只 apply `add_node` / `add_edge`；modify/retire → CHANGE_TYPE_REQUIRES_M7
- ZERO LLM / ZERO Provider / ZERO network
- GraphReview selection：显式 --review-id 或 0/1/>1 确定性规则，
  禁止 latest/approved/timestamp/first-row 自动策略；全部 fail-closed
- Review 与 original GraphChange 均 Schema-first（Markdown NOT AUTHORITATIVE）
- strict reads：candidate / review / target / application 的 SQL/JSON/Schema
  失败全部映射为结构化 APPLY_REJECTED，无 uncaught decode
- approved：effective = original；validate_apply_preflight 全绿
- approved_with_changes：replacement 确定性 linkage + 重建验证 + tamper 拒绝；
  effective Evidence 必须满足 review-time information closure
  （published_at / retrieved_at <= reviewed_at）
- candidate hash 唯一 authority = KnowledgeValidator.compute_candidate_hash()
- apply-time transformation：只改 review_status=approved、
  last_reviewed_at=review.reviewed_at；MODEL_INFERENCE 保持；applied_at 只属 audit
- 不 UPDATE GraphChange / GraphReview（byte-for-byte immutable）
- idempotency key 确定性（不含 applied_at）；idempotent replay 优先识别，
  replay 验证完整 application audit（canonical payload 全等 + 全部 DB columns）
- BEGIN IMMEDIATE 事务消除 TOCTOU；COMMIT 失败传播；无隐式 commit；
  事务内 gate 失败保留精确 error_code；任一步失败 ROLLBACK ALL
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
from research_os.knowledge.history import HistoryService
from research_os.utils.time import now_iso, parse_iso

# M6/M7 支持（真正 apply）的 change_type
_SUPPORTED_CHANGE_TYPES = (
    "add_node", "add_edge",
    "modify_attribute", "retire_node", "retire_edge",
)

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
    """M6 apply 显式结果（状态 + 精确 error_code + 人类可读 errors）。"""
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
    error_code: Optional[str] = None  # 精确机械 code（成功为 null）
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


class ApplyEngine:
    """M6 确定性 apply 引擎（零 LLM / 零 Provider / 零 network）。"""

    def __init__(self, db, candidate_repo, graph_repo, validator):
        self._db = db
        self._candidate_repo = candidate_repo
        self._graph_repo = graph_repo
        self._validator = validator
        # M7：incident-edge guard / retire 判定复用同一 deterministic history service
        self._history = HistoryService(db, graph_repo)
        self._last_error: str = ""

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
            ApplyResult（error_code 精确；成功为 null）
        """
        # 1. Load original candidate（strict loader，Schema-first）
        original_gc, cand_err = self._load_graph_change_strict(change_id)
        if cand_err is not None:
            return self._reject(change_id, cand_err[0], cand_err[1])

        # 2. Review selection（fail-closed）
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
        # naive/带时区字符串字典序比较的误判。
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
            # 9. load persisted replacement（strict loader，Schema-first）
            persisted_repl, repl_err = self._load_graph_change_strict(
                review.resulting_graph_change_id,
                missing_code="REPLACEMENT_MISSING",
                read_code="REPLACEMENT_READ_FAILED",
                payload_code="REPLACEMENT_PAYLOAD_INVALID",
                schema_code="REPLACEMENT_SCHEMA_INVALID",
            )
            if repl_err is not None:
                return self._reject(change_id, repl_err[0], repl_err[1],
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
        except _TargetBuildError as e:
            # 精确机械 error_code（如 ADD_NODE_NOT_ACTIVE），
            # 调用方不需要从 errors 字符串反解析
            return self._reject(
                change_id, e.error_code, str(e),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
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
        # 使用双 deterministic identity（application_id OR idempotency_key）：
        # 任一 identity 被 SQL 篡改都必须可发现并拒绝，而不是跳过 replay 验证。
        try:
            existing_app = self._graph_repo.get_application_by_identity(app_id, idem_key)
        except Exception as e:
            return self._reject(change_id, "APPLICATION_INTEGRITY_CONFLICT", str(e),
                                review_id=review.review_id,
                                effective_gc_id=effective_gc.graph_change_id)
        if existing_app is not None:
            return self._replay_result(
                change_id, effective_gc, review, idem_key, app_id,
                effective_hash,
                target_kind, target_id, target_version, target_dump,
                existing_app, applied_at, dry_run,
            )

        # 16. M4 validation 组合门（仅新 apply）
        gate = self._validate_gates(original_gc, effective_gc, review, applied_at)
        if gate is not None:
            return gate

        # 17. Current-graph / version preflight（strict read；dry-run 也执行）
        preflight_err = self._target_preflight(
            target_kind, target_id, target_version, target_dump
        )
        if preflight_err is not None:
            return self._reject(
                change_id, preflight_err[0], preflight_err[1],
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 17b. M7 lifecycle gates（modify/retire：identity immutable、transition
        #      time、evidence preservation、NO_EFFECTIVE_CHANGE、retire tombstone、
        #      incident-edge guard；add 类型跳过）。事务外 preflight（dry-run 也执行）
        m7_err = self._m7_lifecycle_gates(
            effective_gc.change_type,
            target_kind, target_id, target_version, target_dump,
            conn=None,
        )
        if m7_err is not None:
            return self._reject(
                change_id, m7_err[0], m7_err[1],
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

        # 19. BEGIN IMMEDIATE 事务（消除 TOCTOU；COMMIT 失败传播；任一步失败 ROLLBACK ALL）
        try:
            with self._db.immediate_transaction() as conn:
                # 事务内 recheck idempotency（双 identity；并发窗口内已有写入）
                existing_rows = conn.execute(
                    "SELECT application_id, graph_change_id, review_id, "
                    "idempotency_key, payload, applied_at "
                    "FROM graph_applications "
                    "WHERE application_id = ? OR idempotency_key = ?",
                    (app_id, idem_key),
                ).fetchall()
                if len(existing_rows) > 1:
                    raise ValueError(
                        "APPLICATION_DUAL_IDENTITY_CONFLICT: 事务内 application_id "
                        "与 idempotency_key 命中不同行（audit corruption）"
                    )
                if len(existing_rows) == 1:
                    existing = existing_rows[0]
                    try:
                        existing_payload = json.loads(existing["payload"])
                    except Exception as json_err:
                        raise ValueError(
                            "APPLICATION_DUAL_IDENTITY_CONFLICT: 事务内 "
                            f"application payload invalid JSON: {json_err}"
                        ) from json_err
                    existing_app = {
                        "application_id": existing["application_id"],
                        "graph_change_id": existing["graph_change_id"],
                        "review_id": existing["review_id"],
                        "idempotency_key": existing["idempotency_key"],
                        "payload": existing_payload,
                        "applied_at": existing["applied_at"],
                    }
                    raise _InTxnReplay(existing_app)

                # 事务内 rerun current-state M4 validation（锁内最新状态），
                # gate 失败保留原始 error_code（_InTxnRejected signal）
                gate = self._validate_gates(original_gc, effective_gc, review,
                                            applied_at)
                if gate is not None:
                    raise _InTxnRejected(gate)

                # 事务内 rerun M7 lifecycle gates（锁内最新状态，含
                # incident-edge guard；任何失败 ROLLBACK ALL）
                m7_err = self._m7_lifecycle_gates(
                    effective_gc.change_type,
                    target_kind, target_id, target_version, target_dump,
                    conn=conn,
                )
                if m7_err is not None:
                    raise _InTxnRejected(self._reject(
                        change_id, m7_err[0], m7_err[1],
                        review_id=review.review_id,
                        effective_gc_id=effective_gc.graph_change_id,
                    ))

                # recheck target/version（append 方法内部强校验）
                if target_kind == "node":
                    node = GraphNode(**target_dump)
                    result = self._graph_repo.append_node(node, conn=conn)
                else:
                    edge = GraphEdge(**target_dump)
                    result = self._graph_repo.append_edge(edge, conn=conn)
                if result not in ("inserted", "idempotent_noop"):
                    raise ValueError(f"target append failed: {result}")

                # append GraphApplication（INSERT ONLY，完整 immutable）
                payload = self._build_application_payload(
                    app_id, change_id, effective_gc, review, effective_hash,
                    target_kind, target_id, target_version, applied_at,
                )
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
                effective_hash,
                target_kind, target_id, target_version, target_dump,
                replay.existing_app, applied_at, dry_run=False,
            )
        except _InTxnRejected as rejected:
            # 事务内 gate 失败：ROLLBACK 后返回原始 ApplyResult（保留精确 error_code）
            return rejected.result
        except Exception as e:
            return self._reject(
                change_id, self._map_apply_exception(e), str(e),
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

    # ── strict graph-change loader（M6-R1） ─────────────────

    def _load_graph_change_strict(
        self,
        graph_change_id: str,
        *,
        missing_code: str = "CANDIDATE_NOT_FOUND",
        read_code: str = "CANDIDATE_READ_FAILED",
        payload_code: str = "CANDIDATE_PAYLOAD_INVALID",
        schema_code: str = "CANDIDATE_SCHEMA_INVALID",
    ) -> Tuple[Optional[GraphChange], Optional[Tuple[str, str]]]:
        """M6 strict candidate/replacement loader。

        直接 SELECT payload FROM graph_changes，然后 Schema-first：
        - DB error → (None, (read_code, msg))
        - missing → (None, (missing_code, msg))
        - invalid JSON → (None, (payload_code, msg))
        - raw schema → GraphChange → dump schema（任一失败 → schema_code）

        Returns:
            (GraphChange, None) 或 (None, (error_code, message))
        """
        try:
            row = self._db._conn.execute(
                "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
                (graph_change_id,),
            ).fetchone()
        except Exception as e:
            return None, (read_code, f"DB error reading graph_change {graph_change_id}: {e}")
        if row is None:
            return None, (missing_code, f"GraphChange not found: {graph_change_id}")
        try:
            candidate_dict = json.loads(row["payload"])
        except Exception as e:
            return None, (payload_code,
                          f"GraphChange {graph_change_id} payload invalid JSON: {e}")
        gc, err = schema_first_graph_change(candidate_dict)
        if err:
            return None, (schema_code, err)
        return gc, None

    # ── review selection（fail-closed） ──────────────────────

    def _select_review(self, change_id: str, review_id: Optional[str]) -> Any:
        """GraphReview selection（显式 --review-id 或 0/1/>1 确定性规则）。

        SQL error / JSON decode / malformed payload / 合法 JSON 非 dict
        全部 fail-closed（REVIEW_READ_FAILED / REVIEW_PAYLOAD_INVALID）。
        显式路径用 DB graph_change_id column 做 association precheck，
        payload 最终仍必须 Schema-first。

        >1 reviews 时直接使用 DB review_id column 的稳定排序，
        不解析 payload 得到 review IDs。

        Returns:
            review dict；或 error code 字符串（错误详情存于 self._last_error）。
        """
        if review_id is not None:
            try:
                row = self._db._conn.execute(
                    "SELECT review_id, graph_change_id, payload "
                    "FROM graph_reviews WHERE review_id = ?",
                    (review_id,),
                ).fetchone()
            except Exception as e:
                self._last_error = f"REVIEW_READ_FAILED: DB error reading review {review_id}: {e}"
                return "REVIEW_READ_FAILED"
            if row is None:
                self._last_error = f"REVIEW_NOT_FOUND: Review not found: {review_id}"
                return "REVIEW_NOT_FOUND"
            # DB graph_change_id column 做 association precheck
            if row["graph_change_id"] != change_id:
                self._last_error = (
                    f"REVIEW_CHANGE_MISMATCH: review {review_id} 属于 "
                    f"graph_change {row['graph_change_id']}，不是 {change_id}"
                )
                return "REVIEW_CHANGE_MISMATCH"
            try:
                review_dict = json.loads(row["payload"])
            except Exception as e:
                self._last_error = f"REVIEW_PAYLOAD_INVALID: review {review_id} payload invalid JSON: {e}"
                return "REVIEW_PAYLOAD_INVALID"
            if not isinstance(review_dict, dict):
                self._last_error = (
                    f"REVIEW_PAYLOAD_INVALID: review {review_id} payload 顶层"
                    f"必须是 object，got {type(review_dict).__name__}"
                )
                return "REVIEW_PAYLOAD_INVALID"
            return review_dict

        try:
            rows = self._db._conn.execute(
                "SELECT review_id, payload FROM graph_reviews "
                "WHERE graph_change_id = ? ORDER BY review_id",
                (change_id,),
            ).fetchall()
        except Exception as e:
            self._last_error = f"REVIEW_READ_FAILED: DB error reading reviews for {change_id}: {e}"
            return "REVIEW_READ_FAILED"

        if not rows:
            self._last_error = (
                f"REVIEW_REQUIRED: candidate {change_id} 没有任何人工审核记录"
            )
            return "REVIEW_REQUIRED"
        if len(rows) > 1:
            # DB review_id column 的稳定排序（不解析 payload）
            ids = [r["review_id"] for r in rows]
            self._last_error = (
                f"AMBIGUOUS_REVIEW_SELECTION: candidate {change_id} 有 {len(rows)} "
                f"条审核记录 {ids}，必须显式提供 --review-id"
            )
            return "AMBIGUOUS_REVIEW_SELECTION"
        try:
            review_dict = json.loads(rows[0]["payload"])
        except Exception as e:
            self._last_error = (
                f"REVIEW_PAYLOAD_INVALID: selected review payload invalid JSON: {e}"
            )
            return "REVIEW_PAYLOAD_INVALID"
        if not isinstance(review_dict, dict):
            self._last_error = (
                f"REVIEW_PAYLOAD_INVALID: selected review payload 顶层必须是 "
                f"object，got {type(review_dict).__name__}"
            )
            return "REVIEW_PAYLOAD_INVALID"
        return review_dict

    # ── M4 validation 组合门 ────────────────────────────────

    def _validate_gates(self, original_gc, effective_gc, review, applied_at):
        """M4 validation 组合门（approved / approved_with_changes）。

        approved_with_changes 的 effective Evidence 必须满足 review-time
        information closure（published_at / retrieved_at <= reviewed_at），
        因此 replacement 的 validate_candidate 使用 as_of=review.reviewed_at。

        Returns:
            None（通过）或 ApplyResult（APPLY_REJECTED，error_code 精确）。
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

        # review-time information closure：
        # effective replacement 的全部 Evidence 必须 retrieved_at <= reviewed_at
        # （人工审核发生在 reviewed_at；不能因为 apply 时已拿到 Evidence
        #   就认为审核时见过它——复用 M4 KGV-007 review 逻辑，不改语义）
        closure_issues = self._validator.evidence_review_time_closure(
            effective_gc, review
        )
        retrieved_after = [i for i in closure_issues
                           if i.code == "EVIDENCE_RETRIEVED_AFTER_REVIEW"]
        if retrieved_after:
            msgs = [f"{i.rule_id}: {i.message}" for i in retrieved_after]
            return self._reject(
                original_gc.graph_change_id, "EVIDENCE_RETRIEVED_AFTER_REVIEW",
                "effective Evidence 在 review 之后才被获取: " + "; ".join(msgs),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        lookup_failed = [i for i in closure_issues
                         if i.code == "EVIDENCE_LOOKUP_FAILED"]
        if lookup_failed:
            msgs = [f"{i.rule_id}: {i.message}" for i in lookup_failed]
            return self._reject(
                original_gc.graph_change_id, "EVIDENCE_LOOKUP_FAILED",
                "effective Evidence review-time 检查失败: " + "; ".join(msgs),
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # replacement validate_candidate：
        # as_of = review.reviewed_at（review-time information cutoff；
        #      replacement 的 published_at <= reviewed_at 由 KGV-014 保证）
        cres = self._validator.validate_candidate(effective_gc, review.reviewed_at)
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
          （抛 _TargetBuildError("ADD_NODE_NOT_ACTIVE")，由 apply 映射精确
           error_code，调用方不得从 errors 字符串反解析）
        - retire_node 要求 status=retired（tombstone），否则
          RETIRE_PAYLOAD_MUTATION
        - modify/retire 的 identity / evidence / transition 等 M7 gates
          在 _m7_lifecycle_gates() 中校验（需要 latest persisted 对比）

        Returns:
            (target_kind, target_id, target_version, target_dump)
        Raises:
            _TargetBuildError: 带 error_code 的目标构造失败
            ValueError: 其他目标构造失败（Schema 等）
        """
        ct = effective_gc.change_type
        if effective_gc.node is not None:
            node_dump = effective_gc.node.model_dump()
            node_dump["review_status"] = "approved"
            node_dump["last_reviewed_at"] = review.reviewed_at
            if ct == "add_node" and node_dump.get("status") != "active":
                raise _TargetBuildError(
                    "ADD_NODE_NOT_ACTIVE",
                    f"node {node_dump['node_id']} status={node_dump.get('status')}"
                    f"（add_node 要求 active）",
                )
            if ct == "retire_node" and node_dump.get("status") != "retired":
                raise _TargetBuildError(
                    "RETIRE_PAYLOAD_MUTATION",
                    f"retire_node 要求 status=retired，got "
                    f"{node_dump.get('status')}",
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

    # ── M7 lifecycle gates（modify / retire） ────────────────

    def _m7_lifecycle_gates(self, change_type, target_kind, target_id,
                            target_version, target_dump,
                            conn=None) -> Optional[Tuple[str, str]]:
        """M7 lifecycle gates（modify_attribute / retire_node / retire_edge）。

        事务外 preflight 与事务内 rerun 共用（conn 参数区分读源）。
        add_node / add_edge 跳过（M6 语义不变）。

        Gates（Decision #37）：
        - modify：transition_at 显式（TRANSITION_TIME_MISSING /
          TRANSITION_TIME_INVALID）、identity immutable
          （IMMUTABLE_IDENTITY_CHANGED）、active-at-transition
          （MODIFY_TARGET_NOT_ACTIVE）、transition monotonic
          （TRANSITION_TIME_NOT_MONOTONIC）、evidence 只增
          （EVIDENCE_HISTORY_LOSS）、至少一个真实业务变化
          （NO_EFFECTIVE_CHANGE）
        - retire：valid_from == valid_to == retire_at
          （RETIRE_TIME_INVALID）、payload 不允许业务修改
          （RETIRE_PAYLOAD_MUTATION）、target 在 retire_at 前 active
          （RETIRE_TARGET_NOT_ACTIVE）、incident-edge guard
          （ACTIVE_INCIDENT_EDGES / INCIDENT_EDGE_CHECK_FAILED）

        Returns:
            None（通过）或 (error_code, message)。
        """
        if change_type in ("add_node", "add_edge"):
            return None
        dbc = conn or self._db._conn

        # strict read：latest persisted（fail-closed）
        try:
            latest_version, latest_payload = self._read_latest_persisted(
                dbc, target_kind, target_id)
        except Exception as e:
            return ("TARGET_READ_FAILED",
                    f"{target_kind} {target_id} latest 读取失败: {e}")
        if latest_version is None:
            return ("M7_TARGET_MISSING",
                    f"{target_kind} {target_id} 不存在（modify/retire 需要已存在 target）")
        if target_version != latest_version + 1:
            return ("VERSION_GAP",
                    f"{target_kind} {target_id} 已有 max version={latest_version}，"
                    f"got version={target_version}（期望 {latest_version + 1}）")

        if change_type == "modify_attribute":
            return self._modify_gates(target_kind, latest_payload, target_dump, dbc)
        if change_type == "retire_node":
            return self._retire_node_gates(latest_payload, target_dump, dbc)
        # retire_edge
        return self._retire_edge_gates(latest_payload, target_dump, dbc)

    def _read_latest_persisted(self, dbc, target_kind, target_id):
        """strict read latest persisted payload（M7 gates 共用）。"""
        if target_kind == "node":
            latest_version = self._graph_repo.get_latest_node_version(target_id)
            if latest_version is None:
                return None, None
            payload = self._graph_repo.get_node_version(target_id, latest_version)
        else:
            latest_version = self._graph_repo.get_latest_edge_version(target_id)
            if latest_version is None:
                return None, None
            payload = self._graph_repo.get_edge_version(target_id, latest_version)
        if payload is None:
            raise ValueError(
                f"{target_kind} {target_id} latest v{latest_version} 缺失"
            )
        if not isinstance(payload, dict):
            raise ValueError(
                f"{target_kind} {target_id} latest payload 顶层非 object"
            )
        return latest_version, payload

    def _modify_gates(self, target_kind, latest, target,
                      dbc) -> Optional[Tuple[str, str]]:
        """modify_attribute gates（node / edge）。"""
        vf = target.get("valid_from")
        if vf is None:
            return ("TRANSITION_TIME_MISSING",
                    f"modify {target_kind} 要求显式 transition_at（valid_from 非 null）")
        try:
            vf_dt = parse_iso(vf)
        except ValueError as e:
            return ("TRANSITION_TIME_INVALID", f"transition_at 非法 ISO: {e}")

        if target_kind == "node":
            # identity immutable（node_id / node_type / origin_kind 全部不可变：
            # origin_kind 变化 = provenance 静默改写，禁止借 modify 把
            # governance_seed 改为 graph_change）
            if (target.get("node_id") != latest.get("node_id")
                    or target.get("node_type") != latest.get("node_type")):
                return ("IMMUTABLE_IDENTITY_CHANGED",
                        f"modify node 不得改变 identity（node_id/node_type）")
            if target.get("origin_kind") != latest.get("origin_kind"):
                return ("IMMUTABLE_IDENTITY_CHANGED",
                        f"modify node 不得改变 origin_kind（provenance 不可改写）："
                        f"{latest.get('origin_kind')} -> {target.get('origin_kind')}")
            if target.get("status") != "active":
                return ("MODIFY_STATUS_CHANGE",
                        f"modify node status 必须保持 active，got "
                        f"{target.get('status')}（retire 必须走 retire_node）")
            # active-at-transition
            if latest.get("status") != "active":
                return ("MODIFY_TARGET_NOT_ACTIVE",
                        f"latest node status={latest.get('status')}（要求 active）")
            if latest.get("valid_to") is not None \
                    and parse_iso(latest["valid_to"]) < vf_dt:
                return ("MODIFY_TARGET_NOT_ACTIVE",
                        f"predecessor.valid_to={latest.get('valid_to')} < "
                        f"transition_at={vf}（transition 前已 expired）")
            # transition monotonic
            if latest.get("valid_from") is not None \
                    and parse_iso(latest["valid_from"]) >= vf_dt:
                return ("TRANSITION_TIME_NOT_MONOTONIC",
                        f"successor.valid_from={vf} <= "
                        f"predecessor.valid_from={latest.get('valid_from')}")
            # evidence 只增
            old_ev = set(latest.get("evidence_ids") or [])
            new_ev = set(target.get("evidence_ids") or [])
            if not old_ev <= new_ev:
                return ("EVIDENCE_HISTORY_LOSS",
                        f"modify node 不得删除历史 Evidence："
                        f"missing={sorted(old_ev - new_ev)}")
            # NO_EFFECTIVE_CHANGE：业务字段（name/aliases/description/valid_to）
            business_same = (
                target.get("name") == latest.get("name")
                and (target.get("aliases") or []) == (latest.get("aliases") or [])
                and target.get("description") == latest.get("description")
                and target.get("valid_to") == latest.get("valid_to")
            )
            if business_same:
                return ("NO_EFFECTIVE_CHANGE",
                        "modify node 无真实业务字段变化"
                        "（仅 version/created_at/review/evidence/valid_from 变化）")
            return None

        # ── edge ──
        for f in ("edge_id", "source_node_id", "relation",
                  "target_node_id", "assertion_type"):
            if target.get(f) != latest.get(f):
                return ("IMMUTABLE_IDENTITY_CHANGED",
                        f"modify edge 不得改变 identity 字段 {f}")
        # active-at-transition（edge 无 status：valid_to / retired origin）
        if latest.get("valid_to") is not None \
                and parse_iso(latest["valid_to"]) < vf_dt:
            return ("MODIFY_TARGET_NOT_ACTIVE",
                    f"predecessor.valid_to={latest.get('valid_to')} < "
                    f"transition_at={vf}（transition 前已 expired）")
        if self._is_retired_edge(latest, dbc):
            return ("MODIFY_TARGET_NOT_ACTIVE",
                    f"latest edge {latest.get('edge_id')} 已 retired（不能复活）")
        # transition monotonic
        if latest.get("valid_from") is not None \
                and parse_iso(latest["valid_from"]) >= vf_dt:
            return ("TRANSITION_TIME_NOT_MONOTONIC",
                    f"successor.valid_from={vf} <= "
                    f"predecessor.valid_from={latest.get('valid_from')}")
        # evidence 只增
        old_ev = set(latest.get("evidence_ids") or [])
        new_ev = set(target.get("evidence_ids") or [])
        if not old_ev <= new_ev:
            return ("EVIDENCE_HISTORY_LOSS",
                    f"modify edge 不得删除历史 Evidence："
                    f"missing={sorted(old_ev - new_ev)}")
        # NO_EFFECTIVE_CHANGE：业务字段（attributes/confidence/valid_to）
        business_same = (
            (target.get("attributes") or {}) == (latest.get("attributes") or {})
            and target.get("confidence") == latest.get("confidence")
            and target.get("valid_to") == latest.get("valid_to")
        )
        if business_same:
            return ("NO_EFFECTIVE_CHANGE",
                    "modify edge 无真实业务字段变化"
                    "（仅 version/created_at/review/evidence/valid_from 变化）")
        return None

    def _retire_node_gates(self, latest, target, dbc) -> Optional[Tuple[str, str]]:
        """retire_node gates（含 incident-edge guard）。"""
        vf = target.get("valid_from")
        vt = target.get("valid_to")
        if vf is None or vt is None or vf != vt:
            return ("RETIRE_TIME_INVALID",
                    "retire_node 要求 valid_from == valid_to == retire_at，均非 null")
        try:
            vf_dt = parse_iso(vf)
        except ValueError as e:
            return ("RETIRE_TIME_INVALID", f"retire_at 非法 ISO: {e}")
        # payload 不允许业务修改（含 origin_kind provenance）
        for f in ("node_id", "node_type", "name", "aliases", "description",
                  "origin_kind"):
            if target.get(f) != latest.get(f):
                return ("RETIRE_PAYLOAD_MUTATION",
                        f"retire_node 不得同时修改业务字段 {f}")
        if target.get("status") != "retired":
            return ("RETIRE_PAYLOAD_MUTATION",
                    f"retire_node status 必须为 retired，got {target.get('status')}")
        # evidence_ids = stable union old + new（不得删减历史证据）
        old_ev = set(latest.get("evidence_ids") or [])
        new_ev = set(target.get("evidence_ids") or [])
        if not old_ev <= new_ev:
            return ("EVIDENCE_HISTORY_LOSS",
                    f"retire_node 不得删除历史 Evidence："
                    f"missing={sorted(old_ev - new_ev)}")
        # target 在 retire_at 前 active
        if latest.get("status") != "active":
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"latest node status={latest.get('status')}（要求 active）")
        if latest.get("valid_to") is not None \
                and parse_iso(latest["valid_to"]) < vf_dt:
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"latest 在 retire_at={vf} 前已 expired"
                    f"（valid_to={latest.get('valid_to')}）")
        # M7-R1 retrograde retire：predecessor 尚未开始生效
        # （retire_at < predecessor.valid_from；== 保持既有语义，不改为拒绝）
        if latest.get("valid_from") is not None \
                and vf_dt < parse_iso(latest["valid_from"]):
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"retire_at={vf} < predecessor.valid_from="
                    f"{latest.get('valid_from')}（predecessor 尚未生效）")
        # incident-edge guard
        return self._incident_edge_guard(latest.get("node_id"), vf, dbc)

    def _retire_edge_gates(self, latest, target, dbc) -> Optional[Tuple[str, str]]:
        """retire_edge gates。"""
        vf = target.get("valid_from")
        vt = target.get("valid_to")
        if vf is None or vt is None or vf != vt:
            return ("RETIRE_TIME_INVALID",
                    "retire_edge 要求 valid_from == valid_to == retire_at，均非 null")
        try:
            vf_dt = parse_iso(vf)
        except ValueError as e:
            return ("RETIRE_TIME_INVALID", f"retire_at 非法 ISO: {e}")
        # 只允许 lifecycle boundary / evidence / version / review 变化
        for f in ("edge_id", "source_node_id", "relation", "target_node_id",
                  "assertion_type", "attributes", "confidence"):
            if target.get(f) != latest.get(f):
                return ("RETIRE_PAYLOAD_MUTATION",
                        f"retire_edge 不得同时修改字段 {f}")
        # evidence_ids = stable union old + new（不得删减历史证据）
        old_ev = set(latest.get("evidence_ids") or [])
        new_ev = set(target.get("evidence_ids") or [])
        if not old_ev <= new_ev:
            return ("EVIDENCE_HISTORY_LOSS",
                    f"retire_edge 不得删除历史 Evidence："
                    f"missing={sorted(old_ev - new_ev)}")
        # target 在 retire_at 前 active（未 expired / 未 retired）
        if latest.get("valid_to") is not None \
                and parse_iso(latest["valid_to"]) <= vf_dt:
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"latest 在 retire_at={vf} 时已 expired"
                    f"（valid_to={latest.get('valid_to')}）")
        if self._is_retired_edge(latest, dbc):
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"latest edge {latest.get('edge_id')} 已 retired（second retire 拒绝）")
        # M7-R1 retrograde retire：predecessor 尚未开始生效
        # （retire_at < predecessor.valid_from；== 保持既有语义，不改为拒绝）
        if latest.get("valid_from") is not None \
                and vf_dt < parse_iso(latest["valid_from"]):
            return ("RETIRE_TARGET_NOT_ACTIVE",
                    f"retire_at={vf} < predecessor.valid_from="
                    f"{latest.get('valid_from')}（predecessor 尚未生效）")
        return None

    def _is_retired_edge(self, payload: dict, dbc) -> bool:
        """edge 是否 retire tombstone：origin GraphChange.change_type == retire_edge。

        禁止仅凭 valid_from == valid_to 猜测 retire（Decision #37）。
        """
        gc_id = payload.get("originating_graph_change_id")
        if gc_id is None:
            return False
        try:
            ct = self._graph_repo.get_graph_change_type(gc_id, conn=dbc)
        except Exception as e:
            raise ValueError(
                f"edge {payload.get('edge_id')} origin GraphChange 读取失败: {e}"
            ) from e
        return ct == "retire_edge"

    def _incident_edge_guard(self, node_id: str, retire_at: str,
                             dbc) -> Optional[Tuple[str, str]]:
        """retire_node 的 incident-edge guard。

        在 retire_at 时点扫描 source/target == node_id 的全部 edge identities，
        用 M7 history semantics（HistoryService.resolve_edge_as_of）判断是否 active。
        任一 active → ACTIVE_INCIDENT_EDGES（禁止 cascade）。
        DB error / invalid JSON / invalid schema / broken chain → fail-closed
        （INCIDENT_EDGE_CHECK_FAILED，不得当作“没有 active edge”）。
        """
        try:
            rows = dbc.execute(
                "SELECT DISTINCT edge_id FROM graph_edges "
                "WHERE source_node_id = ? OR target_node_id = ?",
                (node_id, node_id),
            ).fetchall()
        except Exception as e:
            return ("INCIDENT_EDGE_CHECK_FAILED",
                    f"incident edge 查询失败: {e}")
        for row in rows:
            edge_id = row["edge_id"]
            try:
                resolved = self._history.resolve_edge_as_of(
                    edge_id, retire_at, conn=dbc)
            except Exception as e:
                return ("INCIDENT_EDGE_CHECK_FAILED",
                        f"incident edge {edge_id} 在 {retire_at} 解析失败: {e}")
            if resolved is not None and resolved.get("is_active"):
                return ("ACTIVE_INCIDENT_EDGES",
                        f"node {node_id} 在 {retire_at} 仍有 active incident edge "
                        f"{edge_id}（必须先 retire 该 edge）")
        return None

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

    def _build_application_payload(
        self, app_id, change_id, effective_gc, review, effective_hash,
        target_kind, target_id, target_version, applied_at,
    ) -> dict:
        """GraphApplication internal audit payload（status=applied）。"""
        return {
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

    # ── target/version strict preflight ─────────────────────

    def _target_preflight(self, target_kind, target_id, target_version,
                          target_dump) -> Optional[Tuple[str, str]]:
        """current-graph / version preflight（strict read；dry-run 与写前共用）。

        DB error / invalid JSON / malformed persisted target 全部
        → 结构化 (error_code, message)。

        Returns:
            None（可写）或 (error_code, message)。
        """
        try:
            if target_kind == "node":
                existing = self._graph_repo.get_node_version(target_id, target_version)
                latest = self._graph_repo.get_latest_node_version(target_id)
            else:
                existing = self._graph_repo.get_edge_version(target_id, target_version)
                latest = self._graph_repo.get_latest_edge_version(target_id)
        except Exception as e:
            return ("TARGET_READ_FAILED",
                    f"{target_kind} {target_id} 读取失败: {e}")
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

    # ── replay verification（完整 audit） ────────────────────

    def _replay_result(self, change_id, effective_gc, review, idem_key, app_id,
                       effective_hash,
                       target_kind, target_id, target_version, target_dump,
                       existing_app, applied_at, dry_run) -> ApplyResult:
        """已存在 GraphApplication 的 replay 验证（完整 audit）。

        必须验证：
        1. expected audit canonical payload 与 stored payload 全对象相等
           （使用 stored applied_at 构造 expected payload）
        2. DB columns：application_id / graph_change_id / review_id /
           idempotency_key / applied_at 全部与 deterministic 值一致
        3. target 存在、version 精确、canonical payload 精确

        任一不一致 → APPLICATION_INTEGRITY_CONFLICT（不得冒充幂等）。
        """
        app_payload = existing_app.get("payload") or {}
        stored_applied_at = existing_app.get("applied_at") or app_payload.get("applied_at")

        # 1. expected audit canonical payload（使用 stored applied_at）
        expected_payload = self._build_application_payload(
            app_id, change_id, effective_gc, review, effective_hash,
            target_kind, target_id, target_version,
            stored_applied_at if stored_applied_at is not None else applied_at,
        )
        if _canonical_json(app_payload) != _canonical_json(expected_payload):
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "application payload 与 expected audit 不一致（被篡改）",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 2. DB columns 全部验证
        if existing_app.get("application_id") != app_id:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "application_id 与 deterministic app_id 不一致",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        if existing_app.get("graph_change_id") != effective_gc.graph_change_id:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "graph_change_id 与 effective_graph_change_id 不一致",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        if existing_app.get("review_id") != review.review_id:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "review_id 不一致",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        if existing_app.get("idempotency_key") != idem_key:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "idempotency_key 与 deterministic idem_key 不一致",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
        if existing_app.get("applied_at") != expected_payload["applied_at"]:
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                "applied_at column 与 expected payload 不一致",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )

        # 3. target 存在 + payload 一致（strict read）
        try:
            if target_kind == "node":
                persisted = self._graph_repo.get_node_version(target_id, target_version)
            else:
                persisted = self._graph_repo.get_edge_version(target_id, target_version)
        except Exception as e:
            # replay 场景：application 已存在但 target 状态异常（invalid JSON /
            # DB error）→ 完整性冲突（不得 fail-open 冒充幂等）
            return self._reject(
                change_id, "APPLICATION_INTEGRITY_CONFLICT",
                f"application 存在但 target {target_kind} {target_id} "
                f"v{target_version} 读取失败: {e}",
                review_id=review.review_id,
                effective_gc_id=effective_gc.graph_change_id,
            )
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

    @staticmethod
    def _map_apply_exception(exc: Exception) -> str:
        """把事务内异常映射为精确 error code。"""
        msg = str(exc)
        if msg.startswith("IMMUTABLE_APPLICATION_CONFLICT"):
            return "APPLICATION_INTEGRITY_CONFLICT"
        if msg.startswith("IMMUTABLE_VERSION_CONFLICT"):
            return "TARGET_VERSION_CONFLICT"
        if msg.startswith("VERSION_VIOLATION"):
            return "VERSION_VIOLATION"
        if msg.startswith("VERSION_GAP"):
            return "VERSION_GAP"
        if "ACTIVE_TRANSACTION_CONFLICT" in msg:
            return "ACTIVE_TRANSACTION_CONFLICT"
        if msg.startswith("APPLICATION_DUAL_IDENTITY_CONFLICT"):
            # 事务内双 identity 命中不同行（audit corruption）→ 契约 code，
            # 与事务外步骤 15 一致
            return "APPLICATION_INTEGRITY_CONFLICT"
        if msg.startswith("REPLACEMENT_"):
            return "REPLACEMENT_" + msg.split(":", 1)[0].split("_", 1)[-1]
        return "APPLY_FAILED"

    def _reject(self, change_id, error_code: str, message: str, *,
                review_id: str = "", effective_gc_id: str = "") -> ApplyResult:
        """构造 APPLY_REJECTED 结果（error_code 精确机械 code）。"""
        return ApplyResult(
            status="APPLY_REJECTED",
            original_graph_change_id=change_id,
            effective_graph_change_id=effective_gc_id or change_id,
            review_id=review_id,
            error_code=error_code,
            errors=(message,),
        )


class _InTxnReplay(Exception):
    """事务内发现已存在 application（并发窗口）——内部信号。"""

    def __init__(self, existing_app: dict):
        super().__init__("idempotent replay detected inside transaction")
        self.existing_app = existing_app


class _TargetBuildError(Exception):
    """approved target 构造失败，携带精确 error_code（如 ADD_NODE_NOT_ACTIVE）。

    由 apply() 映射为结构化 ApplyResult.error_code，
    调用方无需从 errors 字符串反解析。
    """

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


class _InTxnRejected(Exception):
    """事务内 gate 失败（并发窗口内最新状态）——保留原始 ApplyResult。"""

    def __init__(self, result: ApplyResult):
        super().__init__(result.errors[0] if result.errors else "rejected inside transaction")
        self.result = result
