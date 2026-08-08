"""M5 Review Workflow：人工审核导入/导出协调器。

核心流程：
- review_export: load candidate → hash → render Markdown
- review_import: parse → load → verify → validate → patch → persist
- JSON Patch applier: 受限 RFC6902，路径白名单
- Deterministic IDs: UUID5 确定性生成
- 原子持久化: 单事务内完成全部写入
- 幂等回放: 相同输入重复执行产生相同结果
"""
from __future__ import annotations

import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models import (
    GraphChange, GraphReview, GraphReviewer,
    GraphPatchValueOperation, GraphPatchRemoveOperation,
)
from research_os.validators.schema_validator import validate_model, validate_instance
from research_os.knowledge.review_renderer import review_export_markdown
from research_os.knowledge.review_parser import parse_review_markdown, ParsedReview

# ── UUID5 namespace ──────────────────────────────────────────
_NAMESPACE_URL = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # standard DNS namespace


def _make_deterministic_id(seed: str) -> str:
    """UUID5 确定性 ID 生成。"""
    return str(uuid.uuid5(_NAMESPACE_URL, seed))


def _make_review_id(graph_change: GraphChange) -> str:
    """GraphReview 确定性 ID。

    uuid5(NAMESPACE_URL, "graph_review:" + sha256(canonical GraphChange))
    """
    canonical = json.dumps(
        graph_change.model_dump(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    content_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return _make_deterministic_id(f"graph_review:{content_hash}")


def _make_replacement_gc_id(review_id: str) -> str:
    """Replacement GraphChange 确定性 ID。

    uuid5(NAMESPACE_URL, "replacement:" + review_id)
    """
    return _make_deterministic_id(f"replacement:{review_id}")


# ── JSON Patch applier ────────────────────────────────────────

# 路径白名单（与 graph_review.schema.json 一致）
_ALLOWED_PATCH_PATHS = {
    "/suggested_change", "/impact_scope", "/conflicts", "/verification_points",
    "/new_evidence_ids",
    "/node/name", "/node/aliases", "/node/description", "/node/status",
    "/node/valid_from", "/node/valid_to", "/node/evidence_ids",
    "/edge/attributes", "/edge/valid_from", "/edge/valid_to",
    "/edge/confidence", "/edge/evidence_ids",
}

# 阻止修改的系统字段（不可通过任何 path 修改）
_BLOCKED_SYSTEM_FIELDS = {
    "graph_change_id", "change_type", "review_status", "created_at", "reviewed_at",
    "node_id", "edge_id", "node_type", "source_node_id", "relation", "target_node_id",
    "version", "origin_kind", "originating_graph_change_id", "assertion_type",
    "last_reviewed_at",
}


def _resolve_pointer(obj: dict, pointer: str) -> Any:
    """解析 JSON Pointer (RFC6901)。"""
    if pointer == "" or pointer == "/":
        return obj
    parts = pointer.strip("/").split("/")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]
    current = obj
    for part in parts:
        if isinstance(current, dict):
            if part not in current:
                raise KeyError(f"pointer {pointer}: key {part} not found")
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                raise KeyError(
                    f"pointer {pointer}: invalid array index {part}"
                )
            if idx >= len(current):
                raise KeyError(
                    f"pointer {pointer}: index {idx} out of range (len={len(current)})"
                )
            current = current[idx]
        else:
            raise KeyError(
                f"pointer {pointer}: cannot index into {type(current).__name__}"
            )
    return current


def _check_path_allowed(path: str) -> bool:
    """检查 patch path 是否在白名单内（含子路径）。"""
    for allowed in _ALLOWED_PATCH_PATHS:
        if path == allowed or path.startswith(allowed + "/"):
            return True
    return False


def _check_system_field(path: str) -> Optional[str]:
    """检查 path 是否指向阻止的系统字段。返回被阻止的字段名或 None。"""
    # 规范化 pointer
    parts = [p for p in path.strip("/").split("/") if p]
    for part in parts:
        if part in _BLOCKED_SYSTEM_FIELDS:
            return part
    return None


def apply_json_patch(obj: dict, patch_ops: List[dict]) -> dict:
    """受限 RFC6902 JSON Patch 应用器。

    支持: add, replace, remove。
    路径白名单限制。
    阻止系统字段修改。

    Args:
        obj: 原始对象 dict。
        patch_ops: JSON Patch 操作列表。

    Returns:
        修改后的对象副本。

    Raises:
        ValueError: 路径不在白名单 / 系统字段 / 操作非法。
    """
    result = copy.deepcopy(obj)

    for i, op in enumerate(patch_ops):
        op_type = op.get("op")
        path = op.get("path", "")

        blocked = _check_system_field(path)
        if blocked:
            raise ValueError(
                f"Patch op[{i}]: 禁止修改系统字段 '{blocked}' (path: {path})"
            )

        if not _check_path_allowed(path):
            raise ValueError(
                f"Patch op[{i}]: 路径不在白名单: {path}"
            )

        if op_type == "add":
            value = op.get("value")
            _apply_add(result, path, value)
        elif op_type == "replace":
            value = op.get("value")
            _apply_replace(result, path, value)
        elif op_type == "remove":
            _apply_remove(result, path)
        else:
            raise ValueError(f"Patch op[{i}]: 不支持的操作 '{op_type}'")

    return result


def _apply_add(obj: dict, pointer: str, value: Any) -> None:
    """JSON Pointer add 操作。"""
    if pointer == "" or pointer == "/":
        raise ValueError("无法对根对象执行 add 操作")

    parts = pointer.strip("/").split("/")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]

    # 遍历到倒数第二个部分
    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                current[part] = {}
            current = current[part]
        elif isinstance(current, list):
            try:
                idx = int(part)
            except ValueError:
                raise ValueError(f"add: invalid array index {part}")
            if idx >= len(current):
                raise ValueError(f"add: index {idx} out of range")
            current = current[idx]
        else:
            raise ValueError(f"add: cannot traverse {type(current).__name__}")

    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
    elif isinstance(current, list):
        if final == "-":
            current.append(value)
        else:
            try:
                idx = int(final)
            except ValueError:
                raise ValueError(f"add: invalid array index {final}")
            if idx > len(current):
                raise ValueError(f"add: index {idx} out of range (len={len(current)})")
            current.insert(idx, value)
    else:
        raise ValueError(f"add: cannot add to {type(current).__name__}")


def _apply_replace(obj: dict, pointer: str, value: Any) -> None:
    """JSON Pointer replace 操作。"""
    _resolve_pointer(obj, pointer)  # 确保路径存在
    parts = pointer.strip("/").split("/")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]

    if len(parts) == 1:
        obj[parts[0]] = value
        return

    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            idx = int(part)
            current = current[idx]

    final = parts[-1]
    if isinstance(current, dict):
        current[final] = value
    elif isinstance(current, list):
        idx = int(final)
        current[idx] = value


def _apply_remove(obj: dict, pointer: str) -> None:
    """JSON Pointer remove 操作。"""
    _resolve_pointer(obj, pointer)  # 确保路径存在
    parts = pointer.strip("/").split("/")
    parts = [p.replace("~1", "/").replace("~0", "~") for p in parts]

    current = obj
    for part in parts[:-1]:
        if isinstance(current, dict):
            current = current[part]
        elif isinstance(current, list):
            idx = int(part)
            current = current[idx]

    final = parts[-1]
    if isinstance(current, dict):
        del current[final]
    elif isinstance(current, list):
        idx = int(final)
        del current[idx]


# ── Import / Export 结果 ──────────────────────────────────────

@dataclass
class ExportResult:
    """review_export 返回结果。"""
    status: str  # "ok" / "error"
    graph_change_id: str = ""
    candidate_hash: str = ""
    markdown: str = ""
    error: str = ""


@dataclass
class ImportResult:
    """review_import 返回结果。"""
    status: str  # "ok" / "idempotent_noop" / "dry_run" / "error"
    review_id: str = ""
    graph_change_id: str = ""
    decision: str = ""
    resulting_graph_change_id: Optional[str] = None
    dry_run: bool = False
    review_eligible: bool = False
    apply_eligible: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── ReviewWorkflow ────────────────────────────────────────────

class ReviewWorkflow:
    """M5 人工审核工作流协调器。"""

    def __init__(self, db, candidate_repo, graph_repo, validator):
        """初始化。

        Args:
            db: Database 实例。
            candidate_repo: GraphChangeCandidateRepository 实例。
            graph_repo: GraphRepository 实例。
            validator: KnowledgeValidator 实例。
        """
        self._db = db
        self._candidate_repo = candidate_repo
        self._graph_repo = graph_repo
        self._validator = validator

    # ── export ────────────────────────────────────────────────

    def review_export(
        self,
        graph_change_id: str,
        dry_run: bool = False,
    ) -> ExportResult:
        """导出 GraphChange candidate 为审阅 Markdown。

        Args:
            graph_change_id: 候选 GraphChange ID。
            dry_run: 不写文件，仅返回 Markdown。

        Returns:
            ExportResult
        """
        # 1. Load candidate
        candidate_dict = self._candidate_repo.get_candidate(graph_change_id)
        if candidate_dict is None:
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=f"Candidate not found: {graph_change_id}",
            )

        # 2. Parse to GraphChange model
        try:
            gc = GraphChange(**candidate_dict)
        except Exception as e:
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=f"Failed to parse candidate: {e}",
            )

        # 3. Verify review_status=candidate
        if gc.review_status != "candidate":
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=f"GraphChange review_status is '{gc.review_status}', not 'candidate'",
            )

        # 4. Schema-first validate
        schema_errors = validate_instance(gc.model_dump(), "graph_change")
        if schema_errors:
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=f"Schema validation failed: {'; '.join(schema_errors)}",
            )

        # 5. Compute candidate hash
        canonical = json.dumps(
            gc.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        candidate_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        # 6. Load evidence records
        evidence_records = []
        all_evidence_ids = set(gc.new_evidence_ids)
        if gc.node is not None:
            all_evidence_ids.update(gc.node.evidence_ids)
        if gc.edge is not None:
            all_evidence_ids.update(gc.edge.evidence_ids)

        for eid in sorted(all_evidence_ids):
            try:
                row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if row:
                    evidence_records.append(json.loads(row["payload"]))
            except Exception:
                pass

        # 7. Render Markdown
        markdown = review_export_markdown(gc, evidence_records)

        return ExportResult(
            status="ok",
            graph_change_id=graph_change_id,
            candidate_hash=candidate_hash,
            markdown=markdown,
        )

    # ── import ────────────────────────────────────────────────

    def review_import(
        self,
        md_text: str,
        dry_run: bool = False,
    ) -> ImportResult:
        """导入人工审阅 Markdown 并持久化。

        流程: parse → load GraphChange → hash verify → build GraphReview →
              M4 validate_review → patch apply（如适用）→
              replacement build → M4 validate_candidate → atomic persist

        Args:
            md_text: 填写后的审阅 Markdown。
            dry_run: 完整预检但零 DB 写入。

        Returns:
            ImportResult
        """
        warnings: List[str] = []

        # 1. Parse
        parsed = parse_review_markdown(md_text)
        if not parsed.is_valid:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=parsed.errors,
            )

        # 2. Load GraphChange candidate
        candidate_dict = self._candidate_repo.get_candidate(parsed.graph_change_id)
        if candidate_dict is None:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[f"Candidate not found: {parsed.graph_change_id}"],
            )

        try:
            gc = GraphChange(**candidate_dict)
        except Exception as e:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[f"Failed to parse candidate: {e}"],
            )

        # 3. Verify candidate hash
        canonical = json.dumps(
            gc.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        computed_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        if parsed.candidate_hash != computed_hash:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[
                    f"Candidate hash mismatch: "
                    f"review has {parsed.candidate_hash}, "
                    f"computed {computed_hash}"
                ],
            )

        # 4. Check that candidate hasn't already been reviewed
        if gc.review_status != "candidate":
            warnings.append(
                f"GraphChange review_status is already '{gc.review_status}', not 'candidate'"
            )

        # 5. Build GraphReview
        review_id = _make_review_id(gc)

        # Build patch operations as Pydantic models
        patch_ops = []
        for p in parsed.review_patch:
            op_type = p.get("op")
            path = p.get("path", "")
            if op_type in ("add", "replace"):
                patch_ops.append(GraphPatchValueOperation(
                    op=op_type,
                    path=path,
                    value=p.get("value"),
                ))
            elif op_type == "remove":
                patch_ops.append(GraphPatchRemoveOperation(
                    op=op_type,
                    path=path,
                ))

        resulting_gc_id: Optional[str] = None
        if parsed.decision == "approved_with_changes":
            resulting_gc_id = _make_replacement_gc_id(review_id)

        reviewer = GraphReviewer(
            reviewer_type="human",
            reviewer_id=parsed.reviewer_id,
            display_name=parsed.display_name,
        )

        review = GraphReview(
            review_id=review_id,
            graph_change_id=parsed.graph_change_id,
            decision=parsed.decision,
            reviewer=reviewer,
            reviewed_at=parsed.reviewed_at,
            candidate_hash=parsed.candidate_hash,
            review_patch=patch_ops,
            notes=parsed.review_notes,
            resulting_graph_change_id=resulting_gc_id,
        )

        # 6. M4 validate_review
        as_of = parsed.reviewed_at or gc.created_at
        validation_result = self._validator.validate_review(gc, review, as_of)

        # M5 import gate: only block on review_eligible=false (structural/review issues).
        # apply_eligible issues (conflicts, stale baseline) do NOT block import —
        # they are reported as warnings. See M5-R1 spec item #7.
        if not validation_result.review_eligible:
            issue_msgs = [f"{i.rule_id}: {i.message}" for i in validation_result.issues
                          if i.blocks_review]
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                review_eligible=False,
                apply_eligible=validation_result.apply_eligible,
                errors=[f"M4 validation failed: {'; '.join(issue_msgs)}"],
            )

        # Collect apply-blocking issues as warnings
        if not validation_result.apply_eligible:
            apply_warnings = [f"{i.rule_id}: {i.message}" for i in validation_result.issues
                              if i.blocks_apply]
            if apply_warnings:
                warnings.append(f"M4 apply not eligible: {'; '.join(apply_warnings)}")

        # 7. Patch apply（仅 approved_with_changes）
        replacement_gc: Optional[GraphChange] = None
        if parsed.decision == "approved_with_changes" and parsed.review_patch:
            try:
                gc_dict = copy.deepcopy(candidate_dict)
                patched = apply_json_patch(gc_dict, parsed.review_patch)

                # Replacement is a NEW candidate (M5-R1 item #5):
                # - graph_change_id = replacement_id (UUID5 from review_id)
                # - review_status = "candidate" (NOT "approved")
                # - reviewed_at = null
                # - created_at = review.reviewed_at
                patched["graph_change_id"] = resulting_gc_id
                patched["review_status"] = "candidate"
                patched["reviewed_at"] = None
                patched["created_at"] = parsed.reviewed_at

                # Node/edge: originating_graph_change_id = replacement_id,
                # created_at = reviewed_at, review_status = "candidate",
                # last_reviewed_at = null
                if patched.get("node"):
                    patched["node"]["review_status"] = "candidate"
                    patched["node"]["last_reviewed_at"] = None
                    patched["node"]["originating_graph_change_id"] = resulting_gc_id
                    patched["node"]["created_at"] = parsed.reviewed_at
                if patched.get("edge"):
                    patched["edge"]["review_status"] = "candidate"
                    patched["edge"]["last_reviewed_at"] = None
                    patched["edge"]["originating_graph_change_id"] = resulting_gc_id
                    patched["edge"]["created_at"] = parsed.reviewed_at

                replacement_gc = GraphChange(**patched)
            except Exception as e:
                return ImportResult(
                    status="error",
                    review_id=review_id,
                    graph_change_id=parsed.graph_change_id,
                    decision=parsed.decision,
                    dry_run=dry_run,
                    errors=[f"Patch apply failed: {e}"],
                )

            # 8. M4 validate_candidate on replacement
            replacement_validation = self._validator.validate_candidate(
                replacement_gc, as_of
            )
            if not replacement_validation.review_eligible:
                issue_msgs = [
                    f"{i.rule_id}: {i.message}"
                    for i in replacement_validation.issues
                    if i.blocks_review
                ]
                return ImportResult(
                    status="error",
                    review_id=review_id,
                    graph_change_id=parsed.graph_change_id,
                    decision=parsed.decision,
                    dry_run=dry_run,
                    errors=[f"Replacement validation failed: {'; '.join(issue_msgs)}"],
                )

        # 9. Dry-run: stop here
        if dry_run:
            return ImportResult(
                status="dry_run",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                resulting_graph_change_id=resulting_gc_id,
                dry_run=True,
                warnings=warnings,
            )

        # 10. Atomic persist
        try:
            with self._db.transaction() as conn:
                # Persist GraphReview
                result = self._graph_repo.append_review(review, conn=conn)

                if result == "idempotent_noop":
                    # Check if there's already a replacement saved
                    existing_replacement = None
                    if resulting_gc_id:
                        try:
                            existing_replacement = self._candidate_repo.get_candidate(
                                resulting_gc_id
                            )
                        except Exception:
                            pass

                    return ImportResult(
                        status="idempotent_noop",
                        review_id=review_id,
                        graph_change_id=parsed.graph_change_id,
                        decision=parsed.decision,
                        resulting_graph_change_id=resulting_gc_id,
                        warnings=warnings,
                    )

                # Persist replacement GraphChange if applicable
                if replacement_gc is not None and resulting_gc_id:
                    repl_result = self._candidate_repo.append_candidate(
                        replacement_gc, conn=conn
                    )
                    # Idempotency is fine for replacement too
                    if repl_result not in ("inserted", "idempotent_noop"):
                        raise ValueError(
                            f"Failed to persist replacement: {repl_result}"
                        )

        except Exception as e:
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[f"Persistence failed: {e}"],
            )

        return ImportResult(
            status="ok",
            review_id=review_id,
            graph_change_id=parsed.graph_change_id,
            decision=parsed.decision,
            resulting_graph_change_id=resulting_gc_id,
            warnings=warnings,
        )
