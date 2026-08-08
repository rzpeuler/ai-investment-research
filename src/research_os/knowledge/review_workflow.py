"""M5 Review Workflow：人工审核导入/导出协调器。

核心流程：
- review_export: load persisted candidate → Schema-first → hash (M4 authority)
  → Evidence fail-closed load → render → file conflict preflight → deterministic write
  （artifact 路径：knowledge/candidates/{graph_change_id}.md，不创建第二个 reviews/ 目录）
- review_import: parse → load → verify → Schema-first GraphReview → M4 validate_review
  → patch apply（如适用）→ replacement build → M4 validate_candidate → atomic persist
- JSON Patch applier: 受限 RFC6902（add/replace/remove），路径白名单
- Deterministic IDs:
  - GraphReview ID = UUID5(DNS, "graph-review:" + sha256(canonical review intent))
  - Replacement GraphChange ID = UUID5(DNS, "graph-review-result:" + review_id)
- 原子持久化: 单事务内完成 GraphReview + replacement GraphChange（如适用）写入
- 幂等回放: 相同输入重复执行产生相同结果，不创建重复记录
- review intent 绑定：同一 candidate 的不同 decision/reviewer/reviewed_at/notes/patch
  产生不同 review_id，形成不同 audit records
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from research_os.models import (
    Evidence,
    GraphChange, GraphReview, GraphReviewer,
)
from research_os.validators.schema_validator import validate_instance
from research_os.knowledge.review_renderer import review_export_markdown
from research_os.knowledge.review_parser import (
    parse_review_markdown,
    _strip_fenced_blocks, _extract_between, _is_frozen_patch_placeholder,
)

# ── UUID5 namespace（冻结协议） ──────────────────────────────
# review ID 与 replacement ID 均使用标准 DNS namespace。
_NAMESPACE_DNS = uuid.NAMESPACE_DNS


def _make_deterministic_id(seed: str) -> str:
    """UUID5 确定性 ID 生成。"""
    return str(uuid.uuid5(_NAMESPACE_DNS, seed))


def _build_review_intent(
    graph_change_id: str,
    decision: str,
    reviewer: GraphReviewer,
    reviewed_at: str,
    candidate_hash: str,
    review_patch: List[dict],
    notes: str,
) -> dict:
    """构造规范 review intent。

    reviewer 使用完整 deterministic representation：
    reviewer_type / reviewer_id / display_name。
    """
    return {
        "graph_change_id": graph_change_id,
        "decision": decision,
        "reviewer": {
            "reviewer_type": reviewer.reviewer_type,
            "reviewer_id": reviewer.reviewer_id,
            "display_name": reviewer.display_name,
        },
        "reviewed_at": reviewed_at,
        "candidate_hash": candidate_hash,
        "review_patch": review_patch,
        "notes": notes,
    }


def compute_review_id(review_intent: dict) -> str:
    """GraphReview 确定性 ID（冻结协议，review-intent 绑定）。

    canonical_intent = json.dumps(intent, ensure_ascii=False, sort_keys=True,
                                  separators=(",", ":"))
    intent_sha256 = sha256(canonical_intent)
    review_id = UUID5(DNS, "graph-review:" + intent_sha256)

    要求：
    - same exact review → same review_id
    - same candidate + different decision/reviewer/reviewed_at/notes/patch
      → different review_id
    """
    canonical_intent = json.dumps(
        review_intent,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    intent_sha256 = hashlib.sha256(canonical_intent.encode("utf-8")).hexdigest()
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, "graph-review:" + intent_sha256))


def _make_review_id(review_intent: dict) -> str:
    """别名：compute_review_id（review-intent 绑定，删除旧的 candidate-only ID）。"""
    return compute_review_id(review_intent)


def _make_replacement_gc_id(review_id: str) -> str:
    """Replacement GraphChange 确定性 ID（冻结协议）。

    resulting_graph_change_id = UUID5(DNS, "graph-review-result:" + review_id)

    要求：
    - same exact review → same replacement ID
    - different review → different replacement ID
    """
    return _make_deterministic_id(f"graph-review-result:{review_id}")


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
            if idx < 0:
                raise KeyError(
                    f"pointer {pointer}: negative array index {idx} not allowed"
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
            if idx < 0:
                raise ValueError(f"add: negative array index {idx} not allowed")
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
            if idx < 0:
                raise ValueError(f"add: negative array index {idx} not allowed")
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


# ── Replacement 确定性构造（M5 + M6 唯一实现） ────────────────

def build_replacement_graph_change(
    original_graph_change: GraphChange,
    graph_review: GraphReview,
) -> GraphChange:
    """从 original GraphChange + GraphReview.review_patch 确定性构造 replacement。

    纯函数：pure / deterministic / zero write / zero LLM。
    M5 `review_import` 与 M6 Apply Engine 共用（唯一实现，禁止第二套算法）。

    Replacement 保持 candidate-shaped：
    - graph_change_id = GraphReview.resulting_graph_change_id
    - review_status = "candidate"（NOT "approved"）
    - reviewed_at = null
    - created_at = GraphReview.reviewed_at
    - node/edge: originating_graph_change_id = resulting id、
      created_at = reviewed_at、review_status = "candidate"、
      last_reviewed_at = null

    完成完整 Schema-first（raw graph_change.schema → GraphChange →
    model_dump → graph_change.schema）。

    Raises:
        ValueError: 决策不是 approved_with_changes / patch 为空 /
            resulting_graph_change_id 缺失 / patch 应用失败 / Schema 失败。
    """
    if graph_review.decision != "approved_with_changes":
        raise ValueError(
            f"build_replacement_graph_change 要求 approved_with_changes，"
            f"got {graph_review.decision}"
        )
    if not graph_review.review_patch:
        raise ValueError("approved_with_changes 要求非空 review_patch")
    if graph_review.resulting_graph_change_id is None:
        raise ValueError("approved_with_changes 要求 resulting_graph_change_id 非空")

    resulting_gc_id = graph_review.resulting_graph_change_id
    patch_ops = [
        op.model_dump() if hasattr(op, "model_dump") else op
        for op in graph_review.review_patch
    ]

    gc_dict = original_graph_change.model_dump()
    patched = apply_json_patch(gc_dict, patch_ops)

    # Replacement 是 NEW candidate（candidate-shaped）
    patched["graph_change_id"] = resulting_gc_id
    patched["review_status"] = "candidate"
    patched["reviewed_at"] = None
    patched["created_at"] = graph_review.reviewed_at

    # Node/edge: originating_graph_change_id = replacement id,
    # created_at = reviewed_at, review_status = "candidate", last_reviewed_at = null
    if patched.get("node"):
        patched["node"]["review_status"] = "candidate"
        patched["node"]["last_reviewed_at"] = None
        patched["node"]["originating_graph_change_id"] = resulting_gc_id
        patched["node"]["created_at"] = graph_review.reviewed_at
    if patched.get("edge"):
        patched["edge"]["review_status"] = "candidate"
        patched["edge"]["last_reviewed_at"] = None
        patched["edge"]["originating_graph_change_id"] = resulting_gc_id
        patched["edge"]["created_at"] = graph_review.reviewed_at

    # Schema-first
    schema_errors = validate_instance(patched, "graph_change")
    if schema_errors:
        raise ValueError(
            f"Replacement GraphChange schema invalid: {'; '.join(schema_errors)}"
        )
    try:
        replacement_gc = GraphChange(**patched)
    except Exception as e:
        raise ValueError(f"Replacement GraphChange Pydantic parse failed: {e}") from e
    dumped = replacement_gc.model_dump()
    schema_errors2 = validate_instance(dumped, "graph_change")
    if schema_errors2:
        raise ValueError(
            f"Replacement GraphChange dump schema re-validation failed: "
            f"{'; '.join(schema_errors2)}"
        )
    return replacement_gc


# ── Import / Export 结果 ──────────────────────────────────────

@dataclass
class ExportResult:
    """review_export 返回结果。"""
    status: str  # "ok" / "idempotent_noop" / "dry_run" / "error" / "REVIEW_EXPORT_FILE_CONFLICT"
    graph_change_id: str = ""
    candidate_hash: str = ""
    markdown: str = ""
    markdown_path: str = ""
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
    candidate_hash: str = ""
    review_eligible: bool = False
    apply_eligible: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


# ── ReviewWorkflow ────────────────────────────────────────────

class ReviewWorkflow:
    """M5 人工审核工作流协调器。"""

    def __init__(self, db, candidate_repo, graph_repo, validator,
                 knowledge_dir: Optional[Path] = None):
        """初始化。

        Args:
            db: Database 实例。
            candidate_repo: GraphChangeCandidateRepository 实例。
            graph_repo: GraphRepository 实例。
            validator: KnowledgeValidator 实例。
            knowledge_dir: 项目 knowledge/ 目录（artifact 写入目标）；
                None 时 review_export 只返回 Markdown 不写文件。
        """
        self._db = db
        self._candidate_repo = candidate_repo
        self._graph_repo = graph_repo
        self._validator = validator
        self._knowledge_dir = Path(knowledge_dir) if knowledge_dir is not None else None

    # ── Schema-first helpers ─────────────────────────────────

    @staticmethod
    def _schema_first_graph_change(candidate_dict: dict
                                   ) -> Tuple[Optional[GraphChange], Optional[str]]:
        """Persisted GraphChange Schema-first：
        raw graph_change.schema → GraphChange → model_dump → graph_change.schema。

        Returns (model_or_None, error_or_None)。
        """
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

    @staticmethod
    def _schema_first_graph_review(review_raw: dict
                                   ) -> Tuple[Optional[GraphReview], Optional[str]]:
        """GraphReview Schema-first：
        raw graph_review.schema → GraphReview → model_dump → graph_review.schema。

        Returns (model_or_None, error_or_None)。
        """
        schema_errors = validate_instance(review_raw, "graph_review")
        if schema_errors:
            return None, f"GraphReview schema invalid: {'; '.join(schema_errors)}"
        try:
            review = GraphReview(**review_raw)
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

    # ── Evidence fail-closed ─────────────────────────────────

    def _load_evidence_fail_closed(self, gc: GraphChange
                                   ) -> Tuple[Optional[List[dict]], Optional[str]]:
        """加载 candidate 引用的全部 Evidence（fail-closed）。

        每条 Evidence 必须：
        - 存在（DB 行）
        - payload JSON 可解析
        - evidence.schema valid
        - Pydantic valid
        - model_dump schema valid

        任何 missing / DB failure / invalid JSON / invalid Schema → (None, error)。
        禁止生成偷偷缺少 Evidence 的人工审核文件。
        """
        all_evidence_ids = set(gc.new_evidence_ids)
        if gc.node is not None:
            all_evidence_ids.update(gc.node.evidence_ids)
        if gc.edge is not None:
            all_evidence_ids.update(gc.edge.evidence_ids)

        records: List[dict] = []
        for eid in sorted(all_evidence_ids):
            try:
                row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
            except Exception as e:
                return None, f"Evidence DB failure for {eid}: {e}"
            if row is None:
                return None, f"Evidence missing: {eid}"
            try:
                payload = json.loads(row["payload"])
            except Exception as e:
                return None, f"Evidence {eid} invalid JSON: {e}"
            schema_errors = validate_instance(payload, "evidence")
            if schema_errors:
                return None, f"Evidence {eid} schema invalid: {'; '.join(schema_errors)}"
            try:
                ev = Evidence(**payload)
            except Exception as e:
                return None, f"Evidence {eid} Pydantic parse failed: {e}"
            try:
                dumped = ev.model_dump()
            except Exception as e:
                return None, f"Evidence {eid} model_dump failed: {e}"
            schema_errors2 = validate_instance(dumped, "evidence")
            if schema_errors2:
                return None, f"Evidence {eid} dump schema invalid: {'; '.join(schema_errors2)}"
            records.append(dumped)
        return records, None

    # ── human-edit 检测（review-export 文件冲突） ────────────

    @staticmethod
    def _detect_human_edit(md_text: str) -> bool:
        """检测审阅文件是否已有人工填写内容。

        任一检测命中 → True（不得覆盖）：
        - 任何审核 checkbox 已选中（- [x] / - [X]，fenced 外）
        - reviewer_id 已填写真实值（带引号或无引号）
        - reviewed_at 已填写真实值（带引号或无引号）
        - Approved Patch 已填写人工内容（非冻结占位符）
        - Review Notes 已填写人工内容（非冻结占位符）
        """
        # 1. checkbox 已选中（fenced-aware）
        clean = _strip_fenced_blocks(md_text)
        for line in clean.split("\n"):
            if re.match(r"-\s*\[[xX]\]", line.strip()):
                return True
        # 2. reviewer_id 真实值（支持带引号 / 无引号两种 YAML 写法）
        m = re.search(r"reviewer_id:\s*(?:\"([^\"]*)\"|(\S+))", md_text)
        if m and ((m.group(1) or "").strip() or (m.group(2) or "").strip()):
            return True
        # 3. reviewed_at 真实值
        m = re.search(r"reviewed_at:\s*(?:\"([^\"]*)\"|(\S+))", md_text)
        if m and ((m.group(1) or "").strip() or (m.group(2) or "").strip()):
            return True
        # 4. Approved Patch 人工内容
        patch_section = _extract_between(md_text, "## Approved Patch", None)
        if "---" in patch_section:
            patch_section = patch_section.split("---")[0]
        content = patch_section.strip()
        if content and not _is_frozen_patch_placeholder(content):
            return True
        # 5. Review Notes 人工内容（防覆盖人工填写但未勾选 checkbox 的笔记）
        notes_section = _extract_between(md_text, "## Review Notes", "## Approved Patch")
        notes_content = notes_section.strip()
        if notes_content and notes_content not in (
            "_（请在此填写审核意见）_",  # M5 review template 占位符
            "_（待填写）_",              # M3 candidate template 占位符
        ):
            return True
        return False

    # ── export ────────────────────────────────────────────────

    def _export_target_path(self, graph_change_id: str) -> Optional[Path]:
        """artifact 目标路径：knowledge/candidates/{graph_change_id}.md。"""
        if self._knowledge_dir is None:
            return None
        return self._knowledge_dir / "candidates" / f"{graph_change_id}.md"

    def review_export(
        self,
        graph_change_id: str,
        dry_run: bool = False,
    ) -> ExportResult:
        """导出 GraphChange candidate 为审阅 Markdown artifact。

        非 dry-run 流程：
        load persisted GraphChange → raw Schema → Pydantic → dump Schema
        → candidate hash（M4 authority）→ Evidence load/validate（fail-closed）
        → render → file conflict preflight → deterministic write。

        文件冲突：
        - 不存在 → 正常写入（status=ok）
        - 已存在且 bytes 完全相同 → idempotent_noop
        - 已存在 M3 untouched candidate template → deterministic upgrade（status=ok）
        - 已有人类 edit → REVIEW_EXPORT_FILE_CONFLICT（不得覆盖）

        dry-run：执行完整 preflight（load/Schema/hash/Evidence/render/path/conflict），
        0 file writes，0 mkdir。

        Args:
            graph_change_id: 候选 GraphChange ID。
            dry_run: 不写文件，仅预检。

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

        # 2. Schema-first validate
        gc, err = self._schema_first_graph_change(candidate_dict)
        if err:
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=err,
            )

        # 3. Verify review_status=candidate
        if gc.review_status != "candidate":
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                error=f"GraphChange review_status is '{gc.review_status}', not 'candidate'",
            )

        # 4. Compute candidate hash（M4 authority）
        candidate_hash = self._validator.compute_candidate_hash(gc)

        # 5. Load evidence（fail-closed）
        evidence_records, ev_err = self._load_evidence_fail_closed(gc)
        if ev_err:
            return ExportResult(
                status="error",
                graph_change_id=graph_change_id,
                candidate_hash=candidate_hash,
                error=ev_err,
            )

        # 6. Render Markdown
        markdown = review_export_markdown(gc, evidence_records, candidate_hash)

        # 7. Target path + file conflict preflight
        target_path = self._export_target_path(graph_change_id)

        if target_path is not None and target_path.exists():
            existing = target_path.read_text(encoding="utf-8")
            if existing == markdown:
                # 已存在且 bytes 完全相同
                if dry_run:
                    return ExportResult(
                        status="dry_run",
                        graph_change_id=graph_change_id,
                        candidate_hash=candidate_hash,
                        markdown=markdown,
                        markdown_path=str(target_path),
                    )
                return ExportResult(
                    status="idempotent_noop",
                    graph_change_id=graph_change_id,
                    candidate_hash=candidate_hash,
                    markdown=markdown,
                    markdown_path=str(target_path),
                )
            if self._detect_human_edit(existing):
                # 已有人类 edit，不得覆盖
                return ExportResult(
                    status="REVIEW_EXPORT_FILE_CONFLICT",
                    graph_change_id=graph_change_id,
                    candidate_hash=candidate_hash,
                    markdown=markdown,
                    markdown_path=str(target_path),
                    error=(
                        f"REVIEW_EXPORT_FILE_CONFLICT: {target_path.name} "
                        f"已包含人工审核内容，拒绝覆盖"
                    ),
                )
            # 已存在 M3 untouched candidate template → deterministic upgrade（继续写入）

        # 8. dry-run：预检完成，0 writes / 0 mkdir
        if dry_run:
            return ExportResult(
                status="dry_run",
                graph_change_id=graph_change_id,
                candidate_hash=candidate_hash,
                markdown=markdown,
                markdown_path=str(target_path) if target_path is not None else "",
            )

        # 9. Deterministic write
        if target_path is not None:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(markdown, encoding="utf-8")
            return ExportResult(
                status="ok",
                graph_change_id=graph_change_id,
                candidate_hash=candidate_hash,
                markdown=markdown,
                markdown_path=str(target_path),
            )

        # 无 knowledge_dir：仅返回 Markdown（兼容旧调用，不写文件）
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

        流程: parse → load GraphChange（Schema-first）→ hash verify →
              build GraphReview（Schema-first）→ M4 validate_review →
              patch apply（如适用）→ replacement build（Schema-first）→
              M4 validate_candidate → atomic persist。

        import gate = review_eligible（结构性/审核问题）。
        apply_eligible=false（conflict/stale/deferred/rejected）不阻止持久化
        合法人工审核历史。

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

        # 2. Load GraphChange candidate（Schema-first）
        candidate_dict = self._candidate_repo.get_candidate(parsed.graph_change_id)
        if candidate_dict is None:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[f"Candidate not found: {parsed.graph_change_id}"],
            )

        gc, err = self._schema_first_graph_change(candidate_dict)
        if err:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                errors=[f"INVALID_REVIEW: {err}"],
            )

        # 3. Verify candidate hash（M4 authority 重算）
        computed_hash = self._validator.compute_candidate_hash(gc)
        if parsed.candidate_hash != computed_hash:
            return ImportResult(
                status="error",
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                candidate_hash=computed_hash,
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

        # 5. Build GraphReview（review-intent 确定性 ID + Schema-first）
        reviewer = GraphReviewer(
            reviewer_type="human",
            reviewer_id=parsed.reviewer_id,
            display_name=parsed.display_name,
        )

        review_intent = _build_review_intent(
            graph_change_id=parsed.graph_change_id,
            decision=parsed.decision,
            reviewer=reviewer,
            reviewed_at=parsed.reviewed_at,
            candidate_hash=parsed.candidate_hash,
            review_patch=parsed.review_patch,
            notes=parsed.review_notes,
        )
        review_id = compute_review_id(review_intent)

        resulting_gc_id: Optional[str] = None
        if parsed.decision == "approved_with_changes":
            resulting_gc_id = _make_replacement_gc_id(review_id)

        review_raw = {
            "review_id": review_id,
            "graph_change_id": parsed.graph_change_id,
            "decision": parsed.decision,
            "reviewer": {
                "reviewer_type": reviewer.reviewer_type,
                "reviewer_id": reviewer.reviewer_id,
                "display_name": reviewer.display_name,
            },
            "reviewed_at": parsed.reviewed_at,
            "candidate_hash": parsed.candidate_hash,
            "review_patch": parsed.review_patch,
            "notes": parsed.review_notes,
            "resulting_graph_change_id": resulting_gc_id,
        }
        review, rev_err = self._schema_first_graph_review(review_raw)
        if rev_err:
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                candidate_hash=parsed.candidate_hash,
                errors=[f"INVALID_REVIEW: {rev_err}"],
            )

        # 6. M4 validate_review
        as_of = parsed.reviewed_at or gc.created_at
        validation_result = self._validator.validate_review(gc, review, as_of)

        # M5 import gate: 只以 review_eligible 为门禁。
        # apply_eligible=false（conflict/stale/deferred/rejected）不阻止持久化
        # 合法人工审核历史——见 M5-R2 spec item #20。
        if not validation_result.review_eligible:
            issue_msgs = [f"{i.rule_id}: {i.message}" for i in validation_result.issues
                          if i.blocks_review]
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                candidate_hash=parsed.candidate_hash,
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

        # 7. Patch apply（仅 approved_with_changes）——使用唯一确定性 helper
        replacement_gc: Optional[GraphChange] = None
        expected_replacement_canonical: Optional[str] = None
        if parsed.decision == "approved_with_changes":
            if not parsed.review_patch:
                return ImportResult(
                    status="error",
                    review_id=review_id,
                    graph_change_id=parsed.graph_change_id,
                    decision=parsed.decision,
                    dry_run=dry_run,
                    candidate_hash=parsed.candidate_hash,
                    errors=["approved_with_changes 要求非空 review_patch"],
                )
            try:
                replacement_gc = build_replacement_graph_change(gc, review)
            except Exception as e:
                return ImportResult(
                    status="error",
                    review_id=review_id,
                    graph_change_id=parsed.graph_change_id,
                    decision=parsed.decision,
                    dry_run=dry_run,
                    candidate_hash=parsed.candidate_hash,
                    errors=[f"Replacement build failed: {e}"],
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
                    candidate_hash=parsed.candidate_hash,
                    errors=[f"Replacement validation failed: {'; '.join(issue_msgs)}"],
                )

            expected_replacement_canonical = json.dumps(
                replacement_gc.model_dump(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )

        # 9. Idempotent replay preflight（写之前检测）
        existing_review_row = None
        try:
            existing_review_row = self._db._conn.execute(
                "SELECT payload FROM graph_reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        except Exception as e:
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                candidate_hash=parsed.candidate_hash,
                errors=[f"Persistence preflight failed: {e}"],
            )

        if existing_review_row is not None:
            existing_payload = existing_review_row["payload"]
            review_canonical = json.dumps(
                review.model_dump(),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            if existing_payload != review_canonical:
                return ImportResult(
                    status="error",
                    review_id=review_id,
                    graph_change_id=parsed.graph_change_id,
                    decision=parsed.decision,
                    dry_run=dry_run,
                    candidate_hash=parsed.candidate_hash,
                    errors=[
                        f"IMMUTABLE_REVIEW_CONFLICT: review_id={review_id} "
                        f"already exists with different payload"
                    ],
                )
            # 幂等回放：approved_with_changes 必须验证 replacement 完整性
            if resulting_gc_id is not None:
                existing_replacement = self._candidate_repo.get_candidate(
                    resulting_gc_id
                )
                if existing_replacement is None:
                    return ImportResult(
                        status="error",
                        review_id=review_id,
                        graph_change_id=parsed.graph_change_id,
                        decision=parsed.decision,
                        dry_run=dry_run,
                        candidate_hash=parsed.candidate_hash,
                        review_eligible=validation_result.review_eligible,
                        apply_eligible=validation_result.apply_eligible,
                        errors=[f"REPLACEMENT_MISSING: replacement GraphChange "
                                f"{resulting_gc_id} 缺失，不能返回幂等成功"],
                    )
                existing_canonical = json.dumps(
                    existing_replacement,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if existing_canonical != expected_replacement_canonical:
                    return ImportResult(
                        status="error",
                        review_id=review_id,
                        graph_change_id=parsed.graph_change_id,
                        decision=parsed.decision,
                        dry_run=dry_run,
                        candidate_hash=parsed.candidate_hash,
                        review_eligible=validation_result.review_eligible,
                        apply_eligible=validation_result.apply_eligible,
                        errors=[f"IMMUTABLE_CANDIDATE_CONFLICT: replacement "
                                f"{resulting_gc_id} 已存在但 payload 不同"],
                    )
            return ImportResult(
                status="idempotent_noop",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                resulting_graph_change_id=resulting_gc_id,
                candidate_hash=parsed.candidate_hash,
                review_eligible=validation_result.review_eligible,
                apply_eligible=validation_result.apply_eligible,
                warnings=warnings,
            )

        # 10. Dry-run: stop here
        # 注意：幂等 preflight 在 dry-run 之前执行——若 review 已存在，
        # dry-run 会如实报告 idempotent_noop（而非 dry_run），避免误导用户
        # "本次是全新导入"。0 DB 写入保证不变。
        if dry_run:
            return ImportResult(
                status="dry_run",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                resulting_graph_change_id=resulting_gc_id,
                dry_run=True,
                candidate_hash=parsed.candidate_hash,
                review_eligible=validation_result.review_eligible,
                apply_eligible=validation_result.apply_eligible,
                warnings=warnings,
            )

        # 11. Atomic persist（all or nothing）
        try:
            with self._db.transaction() as conn:
                # approved_with_changes: 先 replacement 后 review（同一事务，all or nothing）
                if replacement_gc is not None and resulting_gc_id:
                    repl_result = self._candidate_repo.append_candidate(
                        replacement_gc, conn=conn
                    )
                    if repl_result not in ("inserted", "idempotent_noop"):
                        raise ValueError(
                            f"Failed to persist replacement: {repl_result}"
                        )
                result = self._graph_repo.append_review(review, conn=conn)
                if result not in ("inserted", "idempotent_noop"):
                    raise ValueError(f"Failed to persist review: {result}")
        except Exception as e:
            return ImportResult(
                status="error",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                dry_run=dry_run,
                candidate_hash=parsed.candidate_hash,
                errors=[f"Persistence failed: {e}"],
            )

        # 事务内出现 idempotent（并发/异常状态）：按幂等回放处理
        if result == "idempotent_noop":
            if resulting_gc_id is not None:
                existing_replacement = self._candidate_repo.get_candidate(
                    resulting_gc_id
                )
                if existing_replacement is None:
                    return ImportResult(
                        status="error",
                        review_id=review_id,
                        graph_change_id=parsed.graph_change_id,
                        decision=parsed.decision,
                        candidate_hash=parsed.candidate_hash,
                        errors=[f"REPLACEMENT_MISSING: replacement GraphChange "
                                f"{resulting_gc_id} 缺失，不能返回幂等成功"],
                    )
                existing_canonical = json.dumps(
                    existing_replacement,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                if existing_canonical != expected_replacement_canonical:
                    return ImportResult(
                        status="error",
                        review_id=review_id,
                        graph_change_id=parsed.graph_change_id,
                        decision=parsed.decision,
                        candidate_hash=parsed.candidate_hash,
                        errors=[f"IMMUTABLE_CANDIDATE_CONFLICT: replacement "
                                f"{resulting_gc_id} 已存在但 payload 不同"],
                    )
            return ImportResult(
                status="idempotent_noop",
                review_id=review_id,
                graph_change_id=parsed.graph_change_id,
                decision=parsed.decision,
                resulting_graph_change_id=resulting_gc_id,
                candidate_hash=parsed.candidate_hash,
                review_eligible=validation_result.review_eligible,
                apply_eligible=validation_result.apply_eligible,
                warnings=warnings,
            )

        return ImportResult(
            status="ok",
            review_id=review_id,
            graph_change_id=parsed.graph_change_id,
            decision=parsed.decision,
            resulting_graph_change_id=resulting_gc_id,
            candidate_hash=parsed.candidate_hash,
            review_eligible=validation_result.review_eligible,
            apply_eligible=validation_result.apply_eligible,
            warnings=warnings,
        )
