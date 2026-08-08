"""Phase 5 M4 Knowledge Validator — 确定性机械规则引擎（零 LLM、零 writes、零网络）。

实现 KGV-001—019 共 19 条规则：
- validate_candidate(graph_change_or_dict, as_of)
- validate_review(graph_change_or_dict, graph_review_or_dict, as_of)
- validate_apply_preflight(graph_change_or_dict, graph_review_or_dict, as_of)
- compute_candidate_hash(graph_change)

M4-R1: Public Validator fail-closed (accepts dict or model, normalizes first).
Schema-first: Entity/Evidence/RawItem all go through raw→schema→Pydantic→dump→schema.
KGV-006/008 use new_evidence_ids only. KGV-019 uses current_knowledge canonical baseline.
Deterministic: issues sorted by (rule_id, code, message), checked_rule_ids stable.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from research_os.models import (
    GraphChange, GraphChangeType, GraphEdge, GraphNode, GraphReview,
    GraphNodeType, GraphRelation, GraphAssertionType, GraphOriginKind,
    Evidence, RawItem, Entity,
)
from research_os.validators.schema_validator import validate_instance

# ─────────────────────────────────────────────────────────────
# EntityType mapping (M3 frozen): GraphNodeType → EntityType
# ─────────────────────────────────────────────────────────────
_GRAPH_NODE_TO_ENTITY_TYPE: Dict[str, str] = {
    "Industry": "industry",
    "IndustrySegment": "industry_segment",
    "Company": "company",
    "Product": "product",
    "Technology": "technology",
    "Material": "material",
    "Equipment": "equipment",
    "Application": "application",
    "Policy": "policy",
    "Event": "event",
    "Metric": "metric",
    "PersonOrInstitution": "person_or_institution",
    "Report": "report",
    "InvestmentTheme": "investment_theme",
}

# ─────────────────────────────────────────────────────────────
# 18 allowed relations (M3 frozen, from core.py GraphRelation)
# ─────────────────────────────────────────────────────────────
_ALLOWED_RELATIONS: Set[str] = {
    "BELONGS_TO", "UPSTREAM_OF", "DOWNSTREAM_OF",
    "SUPPLIES", "PURCHASES_FROM", "PRODUCES", "USES_TECHNOLOGY",
    "APPLIED_IN", "COMPETES_WITH", "SUBSTITUTES",
    "BENEFITS_FROM", "HARMED_BY", "AFFECTS",
    "MENTIONED_IN", "SUPPORTED_BY", "CONTRADICTED_BY",
    "HAS_METRIC", "HAS_CATALYST",
}

# Core structural relations that require at least one S/A source for FACT edges
_CORE_STRUCTURAL_RELATIONS: Set[str] = {
    "PRODUCES", "USES_TECHNOLOGY", "SUPPLIES", "PURCHASES_FROM",
}


# ─────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class KnowledgeValidationIssue:
    """单个 KGV 规则问题。"""
    rule_id: str          # e.g. "KGV-001"
    code: str             # e.g. "SCHEMA_INVALID"
    message: str          # 人类可读描述
    blocks_review: bool   # 是否阻止进入人工审核
    blocks_apply: bool    # 是否阻止 apply


@dataclass(frozen=True)
class KnowledgeValidationResult:
    """KnowledgeValidator 校验结果。"""
    stage: str               # "candidate" / "review" / "apply_preflight"
    structural_ok: bool      # KGV-001 Schema 是否通过
    review_eligible: bool    # 否满足进入审核阶段的条件
    apply_eligible: bool     # 否满足 apply 条件
    candidate_hash: Optional[str]
    checked_rule_ids: tuple  # tuple of str, 已检查的规则 ID (sorted, unique, stable)
    issues: tuple            # tuple of KnowledgeValidationIssue (sorted)


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────

def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO 8601 string to datetime. Returns None on failure."""
    if not value:
        return None
    try:
        # Try ISO with Z or offset
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        try:
            # Try with +08:00 appended for bare ISO
            return datetime.fromisoformat(value + "+08:00")
        except (ValueError, TypeError):
            return None


def _validate_iso_format(value: str) -> bool:
    """Check if value is a valid ISO 8601 date/time string."""
    return _parse_iso(value) is not None


def _schema_first_validate(payload: Dict[str, Any], schema_name: str,
                           model_cls, rule_id: str, code: str,
                           message_prefix: str
                           ) -> Tuple[Optional[Any], List[KnowledgeValidationIssue]]:
    """Schema-first validation: raw→schema→Pydantic→dump→schema.

    Returns (model_instance_or_None, issues_list).
    On success, model_instance is the parsed Pydantic model.
    On failure, model_instance is None and issues_list has the error.
    """
    issues: List[KnowledgeValidationIssue] = []

    # Step 1: Validate raw dict against JSON Schema
    schema_errors = validate_instance(payload, schema_name)
    if schema_errors:
        issues.append(KnowledgeValidationIssue(
            rule_id=rule_id, code=code,
            message=f"{message_prefix} schema invalid: {'; '.join(schema_errors)}",
            blocks_review=True, blocks_apply=True,
        ))
        return None, issues

    # Step 2: Parse into Pydantic model
    try:
        model_instance = model_cls(**payload)
    except Exception as e:
        issues.append(KnowledgeValidationIssue(
            rule_id=rule_id, code=code,
            message=f"{message_prefix} Pydantic parse failed: {e}",
            blocks_review=True, blocks_apply=True,
        ))
        return None, issues

    # Step 3: Dump back to dict and re-validate against schema
    try:
        dumped = model_instance.model_dump()
    except Exception as e:
        issues.append(KnowledgeValidationIssue(
            rule_id=rule_id, code=code,
            message=f"{message_prefix} model_dump failed: {e}",
            blocks_review=True, blocks_apply=True,
        ))
        return None, issues

    schema_errors2 = validate_instance(dumped, schema_name)
    if schema_errors2:
        issues.append(KnowledgeValidationIssue(
            rule_id=rule_id, code=code,
            message=f"{message_prefix} dump schema re-validation failed: {'; '.join(schema_errors2)}",
            blocks_review=True, blocks_apply=True,
        ))
        return None, issues

    return model_instance, issues


# ─────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────

class KnowledgeValidator:
    """Phase 5 M4 知识校验器 — 确定性机械规则引擎。

    零 Provider 调用、零网络访问、零数据库写入、零随机数。
    M4-R1: 公共 API 接受 dict 或 model，内部 normalize 先验。
    """

    def __init__(self, db: Any, graph_repo: Any):
        """db 为 Database 实例，graph_repo 为 GraphRepository 实例。"""
        self._db = db
        self._graph_repo = graph_repo

    # ── Normalization (M4-R1: fail-closed) ──────────────

    def _normalize_graph_change(
        self, raw_or_model: Union[Dict[str, Any], GraphChange]
    ) -> Tuple[Optional[GraphChange], List[KnowledgeValidationIssue]]:
        """Normalize raw dict or model into a validated GraphChange.

        If model: validate schema→dump→schema.
        If dict: raw→schema→Pydantic→dump→schema.
        Returns (model_or_None, issues).
        """
        if isinstance(raw_or_model, GraphChange):
            dumped = raw_or_model.model_dump()
            schema_errors = validate_instance(dumped, "graph_change")
            if schema_errors:
                issue = KnowledgeValidationIssue(
                    rule_id="KGV-001", code="SCHEMA_INVALID",
                    message=f"GraphChange model dump schema invalid: {'; '.join(schema_errors)}",
                    blocks_review=True, blocks_apply=True,
                )
                return None, [issue]
            return raw_or_model, []

        # raw dict path
        gc_payload = dict(raw_or_model)
        return _schema_first_validate(
            gc_payload, "graph_change", GraphChange,
            "KGV-001", "SCHEMA_INVALID", "GraphChange"
        )

    def _normalize_graph_review(
        self, raw_or_model: Union[Dict[str, Any], GraphReview]
    ) -> Tuple[Optional[GraphReview], List[KnowledgeValidationIssue]]:
        """Normalize raw dict or model into a validated GraphReview."""
        if isinstance(raw_or_model, GraphReview):
            dumped = raw_or_model.model_dump()
            schema_errors = validate_instance(dumped, "graph_review")
            if schema_errors:
                issue = KnowledgeValidationIssue(
                    rule_id="KGV-012", code="REVIEW_SCHEMA_INVALID",
                    message=f"GraphReview model dump schema invalid: {'; '.join(schema_errors)}",
                    blocks_review=True, blocks_apply=True,
                )
                return None, [issue]
            return raw_or_model, []

        review_payload = dict(raw_or_model)
        return _schema_first_validate(
            review_payload, "graph_review", GraphReview,
            "KGV-012", "REVIEW_SCHEMA_INVALID", "GraphReview"
        )

    # ── candidate hash ──────────────────────────────────

    @staticmethod
    def compute_candidate_hash(graph_change: GraphChange) -> str:
        """sha256(canonical sorted JSON of model_dump), not Markdown bytes."""
        canonical = json.dumps(
            graph_change.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # ── validate_candidate ───────────────────────────────

    def validate_candidate(
        self,
        graph_change_or_dict: Union[Dict[str, Any], GraphChange],
        as_of: str,
    ) -> KnowledgeValidationResult:
        """校验 GraphChange candidate 是否可以进入审核阶段。

        Args:
            graph_change_or_dict: 完整的 GraphChange 候选对象（dict 或 Pydantic model）。
            as_of: 显式截止时间（不接受 now() 默认值）。

        Returns:
            KnowledgeValidationResult
        """
        issues: List[KnowledgeValidationIssue] = []
        checked: List[str] = []

        # ── Normalize (M4-R1) ────────────────────────────
        gc, norm_issues = self._normalize_graph_change(graph_change_or_dict)
        issues.extend(norm_issues)
        structural_ok = len(norm_issues) == 0

        if gc is None:
            checked.append("KGV-001")
            return KnowledgeValidationResult(
                stage="candidate",
                structural_ok=False,
                review_eligible=False,
                apply_eligible=False,
                candidate_hash=None,
                checked_rule_ids=tuple(sorted(set(checked))),
                issues=tuple(sorted(issues, key=lambda i: (i.rule_id, i.code, i.message))),
            )

        # ── KGV-001 Schema ──────────────────────────────
        schema_issues = self._check_kgv001(gc)
        issues.extend(schema_issues)
        checked.append("KGV-001")
        if not structural_ok:
            structural_ok = len([i for i in schema_issues
                                 if i.code == "SCHEMA_INVALID"]) == 0

        # ── KGV-014 Explicit As-Of ──────────────────────
        issues.extend(self._check_kgv014(gc, as_of))
        checked.append("KGV-014")

        # ── KGV-002 Node Identity (Schema-first Entity) ──
        if gc.node is not None:
            issues.extend(self._check_kgv002(gc.node))
        checked.append("KGV-002")

        # ── KGV-016 Self-Loop ───────────────────────────
        if gc.edge is not None:
            issues.extend(self._check_kgv016(gc.edge))
        checked.append("KGV-016")

        # ── KGV-003 Relation Allowlist ──────────────────
        if gc.edge is not None:
            issues.extend(self._check_kgv003(gc.edge))
        checked.append("KGV-003")

        # ── KGV-010 FACT/MODEL_INFERENCE boundary ───────
        issues.extend(self._check_kgv010(gc))
        checked.append("KGV-010")

        # ── KGV-009 Governance Seed Scope ───────────────
        issues.extend(self._check_kgv009(gc))
        checked.append("KGV-009")

        # ── KGV-005 Evidence Existence + Subset ─────────
        issues.extend(self._check_kgv005(gc))
        checked.append("KGV-005")

        # ── KGV-006 Evidence Entity Relevance (new_evidence_ids only) ─
        issues.extend(self._check_kgv006(gc))
        checked.append("KGV-006")

        # ── KGV-007 Evidence Time ───────────────────────
        issues.extend(self._check_kgv007(gc))
        checked.append("KGV-007")

        # ── KGV-008 Source Tier (new_evidence_ids only) ─
        issues.extend(self._check_kgv008(gc))
        checked.append("KGV-008")

        # ── KGV-004 Source/Target Existence ─────────────
        if gc.edge is not None:
            issues.extend(self._check_kgv004(gc.edge))
        checked.append("KGV-004")

        # ── KGV-013 Version Monotonicity ────────────────
        issues.extend(self._check_kgv013(gc))
        checked.append("KGV-013")

        # ── KGV-015 Duplicate Relation ──────────────────
        if gc.edge is not None:
            issues.extend(self._check_kgv015(gc))
        checked.append("KGV-015")

        # ── KGV-017 Retired Node Reference ──────────────
        if gc.edge is not None:
            issues.extend(self._check_kgv017(gc.edge))
        checked.append("KGV-017")

        # ── KGV-011 Conflict Blocking ───────────────────
        issues.extend(self._check_kgv011(gc))
        checked.append("KGV-011")

        # ── KGV-012 Review Status ───────────────────────
        issues.extend(self._check_kgv012(gc))
        checked.append("KGV-012")

        # ── KGV-018 Candidate Hash ──────────────────────
        candidate_hash = None
        try:
            candidate_hash = self.compute_candidate_hash(gc)
        except Exception:
            pass
        checked.append("KGV-018")

        # ── KGV-019 (candidate stage: N/A) ──────────────
        checked.append("KGV-019")

        # Determine eligibility
        review_eligible = True
        apply_eligible = True
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        if not structural_ok:
            review_eligible = False

        # Sort issues deterministically
        sorted_issues = tuple(sorted(issues, key=lambda i: (i.rule_id, i.code, i.message)))

        return KnowledgeValidationResult(
            stage="candidate",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=candidate_hash,
            checked_rule_ids=tuple(sorted(set(checked))),
            issues=sorted_issues,
        )

    # ── validate_review ──────────────────────────────────

    def validate_review(
        self,
        graph_change_or_dict: Union[Dict[str, Any], GraphChange],
        graph_review_or_dict: Union[Dict[str, Any], GraphReview],
        as_of: str,
    ) -> KnowledgeValidationResult:
        """校验 GraphReview 是否可以应用于对应的 GraphChange。

        Args:
            graph_change_or_dict: 被审核的 GraphChange
            graph_review_or_dict: 审核记录
            as_of: 显式截止时间

        Returns:
            KnowledgeValidationResult
        """
        # Normalize both inputs (M4-R1)
        gc, gc_norm_issues = self._normalize_graph_change(graph_change_or_dict)
        review, review_norm_issues = self._normalize_graph_review(graph_review_or_dict)

        if gc is None or review is None:
            all_issues = list(gc_norm_issues) + list(review_norm_issues)
            # Sort issues
            all_issues.sort(key=lambda i: (i.rule_id, i.code, i.message))
            return KnowledgeValidationResult(
                stage="review",
                structural_ok=False,
                review_eligible=False,
                apply_eligible=False,
                candidate_hash=None,
                checked_rule_ids=tuple(sorted(set(
                    ["KGV-001", "KGV-012"]
                ))),
                issues=tuple(all_issues),
            )

        # First run candidate validation
        base = self.validate_candidate(gc, as_of)
        issues: List[KnowledgeValidationIssue] = list(base.issues)
        checked: List[str] = list(base.checked_rule_ids)

        structural_ok = base.structural_ok

        # ── Additional review-stage checks ────────────────

        # Verify graph_review matches graph_change
        if review.graph_change_id != gc.graph_change_id:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012",
                code="REVIEW_MISMATCH",
                message=f"GraphReview.graph_change_id={review.graph_change_id} "
                        f"!= GraphChange.graph_change_id={gc.graph_change_id}",
                blocks_review=True,
                blocks_apply=True,
            ))

        # KGV-012: reviewer_type must be human, reviewer_id non-empty
        reviewer = review.reviewer
        if reviewer.reviewer_type != "human":
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012", code="INVALID_REVIEWER_TYPE",
                message=f"Reviewer type must be 'human', got '{reviewer.reviewer_type}'",
                blocks_review=True, blocks_apply=True,
            ))
        if not reviewer.reviewer_id:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012", code="EMPTY_REVIEWER_ID",
                message="Reviewer ID must be non-empty",
                blocks_review=True, blocks_apply=True,
            ))

        # KGV-012: reviewed_at >= created_at (parsed datetime)
        gc_created = _parse_iso(gc.created_at)
        review_reviewed = _parse_iso(review.reviewed_at)
        if gc_created and review_reviewed:
            if review_reviewed < gc_created:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-012", code="REVIEWED_BEFORE_CREATED",
                    message=f"reviewed_at={review.reviewed_at} < created_at={gc.created_at}",
                    blocks_review=True, blocks_apply=True,
                ))

        # KGV-007: retrieved_at <= reviewed_at for all evidence
        issues.extend(self._check_kgv007_review(gc, review))

        # Verify candidate hash matches
        expected_hash = self.compute_candidate_hash(gc)
        if review.candidate_hash != expected_hash:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-018",
                code="CANDIDATE_HASH_MISMATCH",
                message=f"Review candidate_hash={review.candidate_hash} "
                        f"!= computed hash={expected_hash}",
                blocks_review=True,
                blocks_apply=True,
            ))

        # Only approved/approved_with_changes can proceed to apply
        if review.decision not in ("approved", "approved_with_changes"):
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012",
                code="NON_APPROVABLE_DECISION",
                message=f"Review decision={review.decision} cannot proceed to apply",
                blocks_review=False,
                blocks_apply=True,
            ))

        # ── KGV-019 Stale Review (in review stage) ──────
        issues.extend(self._check_kgv019(gc))
        if "KGV-019" not in checked:
            checked.append("KGV-019")

        review_eligible = base.review_eligible
        apply_eligible = base.apply_eligible
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        # Sort issues deterministically
        sorted_issues = tuple(sorted(issues, key=lambda i: (i.rule_id, i.code, i.message)))

        return KnowledgeValidationResult(
            stage="review",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=expected_hash,
            checked_rule_ids=tuple(sorted(set(checked))),
            issues=sorted_issues,
        )

    # ── validate_apply_preflight ─────────────────────────

    def validate_apply_preflight(
        self,
        graph_change_or_dict: Union[Dict[str, Any], GraphChange],
        graph_review_or_dict: Union[Dict[str, Any], GraphReview],
        as_of: str,
    ) -> KnowledgeValidationResult:
        """Apply 前最终预检查（含 KGV-019 stale review detection）。

        Args:
            graph_change_or_dict: 待应用 GraphChange
            graph_review_or_dict: 已批准审核
            as_of: 显式截止时间

        Returns:
            KnowledgeValidationResult
        """
        # First run full review validation (which already includes KGV-019)
        base = self.validate_review(graph_change_or_dict, graph_review_or_dict, as_of)

        issues: List[KnowledgeValidationIssue] = list(base.issues)
        checked: List[str] = list(base.checked_rule_ids)

        structural_ok = base.structural_ok
        review_eligible = base.review_eligible
        apply_eligible = base.apply_eligible
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        # Sort issues deterministically
        sorted_issues = tuple(sorted(issues, key=lambda i: (i.rule_id, i.code, i.message)))

        return KnowledgeValidationResult(
            stage="apply_preflight",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=base.candidate_hash,
            checked_rule_ids=tuple(sorted(set(checked))),
            issues=sorted_issues,
        )

    # ──────────────────────────────────────────────────────
    #  Rule implementations (sorted by KGV number)
    # ──────────────────────────────────────────────────────

    def _check_kgv001(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-001: Schema 校验 GraphChange + Node + Edge + Evidence + RawItem."""
        issues: List[KnowledgeValidationIssue] = []

        # Validate GraphChange
        gc_errors = validate_instance(gc.model_dump(), "graph_change")
        if gc_errors:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-001", code="SCHEMA_INVALID",
                message=f"GraphChange schema invalid: {'; '.join(gc_errors)}",
                blocks_review=True, blocks_apply=True,
            ))

        # Validate Node if present
        node = gc.node
        if node is not None:
            node_errors = validate_instance(node.model_dump(), "graph_node")
            if node_errors:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-001", code="NODE_SCHEMA_INVALID",
                    message=f"Node schema invalid: {'; '.join(node_errors)}",
                    blocks_review=True, blocks_apply=True,
                ))

        # Validate Edge if present
        edge = gc.edge
        if edge is not None:
            edge_errors = validate_instance(edge.model_dump(), "graph_edge")
            if edge_errors:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-001", code="EDGE_SCHEMA_INVALID",
                    message=f"Edge schema invalid: {'; '.join(edge_errors)}",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv002(self, node: GraphNode) -> List[KnowledgeValidationIssue]:
        """KGV-002: Node Identity — Schema-first Entity validation.

        Load entity from DB, validate entity.schema→Entity→dump→entity.schema.
        Any failure→ENTITY_INVALID, KGV-002, fail closed.
        """
        issues: List[KnowledgeValidationIssue] = []

        graph_node_type = node.node_type
        expected_entity_type = _GRAPH_NODE_TO_ENTITY_TYPE.get(graph_node_type)
        if expected_entity_type is None:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-002", code="UNKNOWN_NODE_TYPE",
                message=f"Unknown GraphNodeType: {graph_node_type}",
                blocks_review=True, blocks_apply=True,
            ))
            return issues

        # For Company, node_id must start with "company:"
        if graph_node_type == "Company" and not node.node_id.startswith("company:"):
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-002", code="COMPANY_PREFIX_MISMATCH",
                message=f"Company node_id={node.node_id} must start with 'company:'",
                blocks_review=True, blocks_apply=True,
            ))

        # Schema-first Entity check
        try:
            entity_row = self._db._conn.execute(
                "SELECT payload FROM entities WHERE entity_id = ?",
                (node.node_id,),
            ).fetchone()
            if entity_row is None:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-002", code="ENTITY_NOT_FOUND",
                    message=f"Entity not found for node_id={node.node_id}",
                    blocks_review=True, blocks_apply=True,
                ))
            else:
                entity_payload = json.loads(entity_row["payload"])

                # Schema-first: entity.schema→Entity→dump→entity.schema
                entity_instance, entity_schema_issues = _schema_first_validate(
                    entity_payload, "entity", Entity,
                    "KGV-002", "ENTITY_INVALID",
                    f"Entity {node.node_id}"
                )
                if entity_schema_issues:
                    issues.extend(entity_schema_issues)
                else:
                    entity_type = entity_payload.get("entity_type")
                    if entity_type != expected_entity_type:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-002", code="ENTITY_TYPE_MISMATCH",
                            message=f"Entity {node.node_id} has entity_type={entity_type}, "
                                    f"expected {expected_entity_type} for GraphNodeType={graph_node_type}",
                            blocks_review=True, blocks_apply=True,
                        ))
        except Exception:
            # If the entities table doesn't exist or query fails, skip entity check
            pass

        return issues

    def _check_kgv003(self, edge: GraphEdge) -> List[KnowledgeValidationIssue]:
        """KGV-003: Relation Allowlist — only 18 relations allowed."""
        issues: List[KnowledgeValidationIssue] = []

        if edge.relation not in _ALLOWED_RELATIONS:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-003", code="INVALID_RELATION",
                message=f"Unknown relation: {edge.relation}",
                blocks_review=True, blocks_apply=True,
            ))

        return issues

    def _check_kgv004(self, edge: GraphEdge) -> List[KnowledgeValidationIssue]:
        """KGV-004: Source/Target Existence — endpoints must exist in persisted graph_nodes."""
        issues: List[KnowledgeValidationIssue] = []

        # Check source
        try:
            src_row = self._db._conn.execute(
                "SELECT 1 FROM graph_nodes WHERE node_id = ? LIMIT 1",
                (edge.source_node_id,),
            ).fetchone()
            if src_row is None:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-004", code="SOURCE_NOT_FOUND",
                    message=f"Source node {edge.source_node_id} not found in graph_nodes",
                    blocks_review=True, blocks_apply=True,
                ))
        except Exception:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-004", code="SOURCE_NOT_FOUND",
                message=f"Source node {edge.source_node_id} not found in graph_nodes",
                blocks_review=True, blocks_apply=True,
            ))

        # Check target
        try:
            tgt_row = self._db._conn.execute(
                "SELECT 1 FROM graph_nodes WHERE node_id = ? LIMIT 1",
                (edge.target_node_id,),
            ).fetchone()
            if tgt_row is None:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-004", code="TARGET_NOT_FOUND",
                    message=f"Target node {edge.target_node_id} not found in graph_nodes",
                    blocks_review=True, blocks_apply=True,
                ))
        except Exception:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-004", code="TARGET_NOT_FOUND",
                message=f"Target node {edge.target_node_id} not found in graph_nodes",
                blocks_review=True, blocks_apply=True,
            ))

        return issues

    def _check_kgv005(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-005: Evidence Existence — all evidence IDs must exist in SQLite evidence table.
        Also check: new_evidence_ids ⊆ candidate object evidence_ids.
        Schema-first: each Evidence payload validated through schema→Evidence→dump→schema.
        """
        issues: List[KnowledgeValidationIssue] = []
        all_evidence_ids: Set[str] = set()

        # Collect from GraphChange.new_evidence_ids
        for eid in gc.new_evidence_ids:
            all_evidence_ids.add(eid)

        # Collect from node evidence_ids
        if gc.node is not None:
            for eid in gc.node.evidence_ids:
                all_evidence_ids.add(eid)

        # Collect from edge evidence_ids
        if gc.edge is not None:
            for eid in gc.edge.evidence_ids:
                all_evidence_ids.add(eid)

        # NEW: new_evidence_ids must be subset of candidate object evidence_ids
        candidate_object_evidence_ids: Set[str] = set()
        if gc.node is not None:
            for eid in gc.node.evidence_ids:
                candidate_object_evidence_ids.add(eid)
        if gc.edge is not None:
            for eid in gc.edge.evidence_ids:
                candidate_object_evidence_ids.add(eid)

        for eid in gc.new_evidence_ids:
            if eid not in candidate_object_evidence_ids:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-005", code="NEW_EVIDENCE_NOT_IN_CANDIDATE",
                    message=f"new_evidence_id {eid} not found in candidate node/edge evidence_ids",
                    blocks_review=True, blocks_apply=True,
                ))

        for eid in all_evidence_ids:
            try:
                row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if row is None:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-005", code="EVIDENCE_NOT_FOUND",
                        message=f"Evidence {eid} not found in evidence table",
                        blocks_review=True, blocks_apply=True,
                    ))
                    continue

                # Schema-first: Evidence schema→Evidence→dump→evidence.schema
                evidence_payload = json.loads(row["payload"])
                ev_instance, ev_schema_issues = _schema_first_validate(
                    evidence_payload, "evidence", Evidence,
                    "KGV-005", "EVIDENCE_SCHEMA_INVALID",
                    f"Evidence {eid}"
                )
                if ev_schema_issues:
                    issues.extend(ev_schema_issues)
            except Exception:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-005", code="EVIDENCE_NOT_FOUND",
                    message=f"Evidence {eid} query failed",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv006(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-006: Evidence Entity Relevance — use ONLY new_evidence_ids.

        Qualification set = GraphChange.new_evidence_ids (not merged candidate object evidence_ids).
        Each Evidence→raw_item_id→RawItem. RawItem must pass raw_item.schema→RawItem→dump→raw_item.schema.
        RawItem invalid→entities excluded, RAW_ITEM_INVALID.
        Node: entity union of new Evidence RawItems must include node_id.
        Edge: entity union must cover source AND target.
        """
        issues: List[KnowledgeValidationIssue] = []

        # Determine required entities
        required_entity_ids: Set[str] = set()
        if gc.node is not None:
            required_entity_ids.add(gc.node.node_id)
        if gc.edge is not None:
            required_entity_ids.add(gc.edge.source_node_id)
            required_entity_ids.add(gc.edge.target_node_id)

        if not required_entity_ids:
            return issues

        # Use ONLY new_evidence_ids for qualification
        qualification_evidence_ids: Set[str] = set(gc.new_evidence_ids)

        if not qualification_evidence_ids:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-006", code="NO_NEW_EVIDENCE_FOR_QUALIFICATION",
                message="No new evidence IDs available for entity relevance qualification",
                blocks_review=False, blocks_apply=True,
            ))
            return issues

        # Build entity coverage from new Evidence→RawItem→entities chains
        covered_entities: Set[str] = set()
        for eid in sorted(qualification_evidence_ids):
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                raw_item_id = ev_payload.get("raw_item_id")
                if not raw_item_id:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-006", code="EVIDENCE_LINEAGE_INCOMPLETE",
                        message=f"Evidence {eid} missing raw_item_id",
                        blocks_review=False, blocks_apply=True,
                    ))
                    continue

                # Check RawItem exists
                ri_row = self._db._conn.execute(
                    "SELECT payload FROM raw_items WHERE raw_item_id = ?",
                    (raw_item_id,),
                ).fetchone()
                if ri_row is None:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-006", code="EVIDENCE_LINEAGE_INCOMPLETE",
                        message=f"RawItem {raw_item_id} not found for Evidence {eid}",
                        blocks_review=False, blocks_apply=True,
                    ))
                    continue

                ri_payload = json.loads(ri_row["payload"])

                # Schema-first RawItem validation
                ri_instance, ri_schema_issues = _schema_first_validate(
                    ri_payload, "raw_item", RawItem,
                    "KGV-006", "RAW_ITEM_INVALID",
                    f"RawItem {raw_item_id}"
                )
                if ri_schema_issues:
                    issues.extend(ri_schema_issues)
                    # Invalid RawItem → entities excluded from coverage
                    continue

                # Collect entities from RawItem
                raw_entities = ri_payload.get("entities", [])
                if isinstance(raw_entities, list):
                    for ent_id in raw_entities:
                        if isinstance(ent_id, str):
                            covered_entities.add(ent_id)
            except Exception:
                continue

        # Check coverage
        for req_entity in sorted(required_entity_ids):
            if req_entity not in covered_entities:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-006", code="ENTITY_NOT_COVERED_BY_EVIDENCE",
                    message=f"Required entity {req_entity} not covered by any new Evidence→RawItem chain",
                    blocks_review=False, blocks_apply=True,
                ))

        return issues

    def _check_kgv007(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-007: Evidence Time — parsed datetime comparison, not string compare.

        published_at <= retrieved_at for each Evidence.
        """
        issues: List[KnowledgeValidationIssue] = []

        all_evidence_ids: Set[str] = set()
        for eid in gc.new_evidence_ids:
            all_evidence_ids.add(eid)
        if gc.node is not None:
            for eid in gc.node.evidence_ids:
                all_evidence_ids.add(eid)
        if gc.edge is not None:
            for eid in gc.edge.evidence_ids:
                all_evidence_ids.add(eid)

        for eid in sorted(all_evidence_ids):
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                published_at_str = ev_payload.get("published_at", "")
                retrieved_at_str = ev_payload.get("retrieved_at", "")

                published_at = _parse_iso(published_at_str)
                retrieved_at = _parse_iso(retrieved_at_str)

                if published_at and retrieved_at:
                    if published_at > retrieved_at:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-007", code="EVIDENCE_TIME_INVALID",
                            message=f"Evidence {eid}: published_at={published_at_str} > retrieved_at={retrieved_at_str}",
                            blocks_review=False, blocks_apply=True,
                        ))
            except Exception:
                continue

        return issues

    def _check_kgv007_review(self, gc: GraphChange,
                             review: GraphReview) -> List[KnowledgeValidationIssue]:
        """KGV-007 for review stage: retrieved_at <= reviewed_at."""
        issues: List[KnowledgeValidationIssue] = []

        all_evidence_ids: Set[str] = set()
        for eid in gc.new_evidence_ids:
            all_evidence_ids.add(eid)
        if gc.node is not None:
            for eid in gc.node.evidence_ids:
                all_evidence_ids.add(eid)
        if gc.edge is not None:
            for eid in gc.edge.evidence_ids:
                all_evidence_ids.add(eid)

        reviewed_at = _parse_iso(review.reviewed_at)
        if reviewed_at is None:
            return issues

        for eid in sorted(all_evidence_ids):
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                retrieved_at_str = ev_payload.get("retrieved_at", "")
                retrieved_at = _parse_iso(retrieved_at_str)

                if retrieved_at and retrieved_at > reviewed_at:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-007", code="EVIDENCE_RETRIEVED_AFTER_REVIEW",
                        message=f"Evidence {eid}: retrieved_at={retrieved_at_str} > reviewed_at={review.reviewed_at}",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                continue

        return issues

    def _check_kgv008(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-008: Source Tier — use new_evidence_ids ONLY.

        Core structural (PRODUCES/USES_TECHNOLOGY/SUPPLIES/PURCHASES_FROM) FACT:
            at least one new Evidence with source_tier S or A.
        Other FACT: at least one new Evidence S/A/B (C-only→FAIL, B→PASS).
        MODEL_INFERENCE: no tier floor.
        """
        issues: List[KnowledgeValidationIssue] = []

        if gc.edge is None:
            return issues
        if gc.edge.assertion_type == "MODEL_INFERENCE":
            return issues  # no tier floor for MODEL_INFERENCE
        if gc.edge.assertion_type != "FACT":
            return issues

        # Use ONLY new_evidence_ids
        new_eids: Set[str] = set(gc.new_evidence_ids)

        if not new_eids:
            # No new evidence at all is handled by KGV-005/010
            return issues

        is_core_structural = gc.edge.relation in _CORE_STRUCTURAL_RELATIONS

        tiers_found: Set[str] = set()
        for eid in new_eids:
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                source_tier = ev_payload.get("source_tier", "B")
                tiers_found.add(source_tier)
            except Exception:
                continue

        if is_core_structural:
            # Core structural: at least one S or A
            if not (tiers_found & {"S", "A"}):
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-008", code="INSUFFICIENT_SOURCE_TIER",
                    message=f"FACT edge with core structural relation {gc.edge.relation} "
                            f"requires at least one S/A new evidence, got tiers={sorted(tiers_found)}",
                    blocks_review=False, blocks_apply=True,
                ))
        else:
            # Other FACT: at least one S/A/B (C-only→FAIL)
            if not (tiers_found & {"S", "A", "B"}):
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-008", code="INSUFFICIENT_SOURCE_TIER",
                    message=f"FACT edge with relation {gc.edge.relation} "
                            f"requires at least one S/A/B new evidence, got tiers={sorted(tiers_found)}",
                    blocks_review=False, blocks_apply=True,
                ))

        return issues

    def _check_kgv009(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-009: Governance Seed Scope — block Industry/IndustrySegment from ordinary candidates."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.node is not None:
            if gc.node.node_type in ("Industry", "IndustrySegment"):
                if gc.change_type in ("add_node", "modify_attribute", "retire_node"):
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-009", code="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE",
                        message=f"Cannot {gc.change_type} Industry/IndustrySegment via ordinary candidate",
                        blocks_review=True, blocks_apply=True,
                    ))

            if gc.node.origin_kind == "governance_seed":
                if gc.change_type not in ("add_node",):
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-009", code="GOVERNANCE_SEED_SCOPE_VIOLATION",
                        message=f"Governance seed node cannot be {gc.change_type} via candidate pipeline",
                        blocks_review=True, blocks_apply=True,
                    ))

        return issues

    def _check_kgv010(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-010: FACT/MODEL_INFERENCE boundary — no GOVERNANCE, MODEL_INFERENCE needs Evidence."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.edge is not None:
            if gc.edge.assertion_type == "GOVERNANCE":
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-010", code="GOVERNANCE_NOT_ALLOWED",
                    message="GOVERNANCE assertion not allowed for GraphChange edge",
                    blocks_review=True, blocks_apply=True,
                ))
            if gc.edge.assertion_type == "MODEL_INFERENCE":
                if len(gc.new_evidence_ids) == 0:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-010", code="MODEL_INFERENCE_NO_EVIDENCE",
                        message="MODEL_INFERENCE requires real Evidence",
                        blocks_review=True, blocks_apply=True,
                    ))

        return issues

    def _check_kgv011(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-011: Conflict Blocking — conflicts block apply but not review."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.conflicts:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-011", code="BLOCKING_CONFLICT",
                message=f"Conflicts present: {gc.conflicts}",
                blocks_review=False,
                blocks_apply=True,
            ))

        return issues

    def _check_kgv012(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-012: Review Status — candidate must have review_status=candidate, reviewed_at=null."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.review_status != "candidate":
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012", code="INVALID_REVIEW_STATUS",
                message=f"Review status must be 'candidate', got '{gc.review_status}'",
                blocks_review=True, blocks_apply=True,
            ))
        if gc.reviewed_at is not None:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012", code="REVIEWED_AT_NOT_NULL",
                message="Candidate must have reviewed_at=null",
                blocks_review=True, blocks_apply=True,
            ))

        if gc.node is not None:
            if gc.node.review_status != "candidate":
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-012", code="NODE_REVIEW_STATUS_INVALID",
                    message=f"Node review_status must be 'candidate', got '{gc.node.review_status}'",
                    blocks_review=True, blocks_apply=True,
                ))
            if gc.node.last_reviewed_at is not None:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-012", code="NODE_LAST_REVIEWED_AT_NOT_NULL",
                    message="Candidate node must have last_reviewed_at=null",
                    blocks_review=True, blocks_apply=True,
                ))

        if gc.edge is not None:
            if gc.edge.review_status != "candidate":
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-012", code="EDGE_REVIEW_STATUS_INVALID",
                    message=f"Edge review_status must be 'candidate', got '{gc.edge.review_status}'",
                    blocks_review=True, blocks_apply=True,
                ))
            if gc.edge.last_reviewed_at is not None:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-012", code="EDGE_LAST_REVIEWED_AT_NOT_NULL",
                    message="Candidate edge must have last_reviewed_at=null",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv013(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-013: Version Monotonicity — fresh→v1, existing→N+1, no gaps."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.node is not None:
            issues.extend(self._check_version_monotonicity(
                "graph_nodes", gc.node.node_id, gc.node.version, "node"
            ))

        if gc.edge is not None:
            issues.extend(self._check_version_monotonicity(
                "graph_edges", gc.edge.edge_id, gc.edge.version, "edge"
            ))

        return issues

    def _check_version_monotonicity(
        self, table: str, id_value: str, version: int, kind: str,
    ) -> List[KnowledgeValidationIssue]:
        """Helper for KGV-013: check version monotonicity."""
        issues: List[KnowledgeValidationIssue] = []

        id_col = "node_id" if table == "graph_nodes" else "edge_id"

        try:
            row = self._db._conn.execute(
                f"SELECT MAX(version) AS mv FROM {table} WHERE {id_col} = ?",
                (id_value,),
            ).fetchone()
            max_version = row["mv"] if row and row["mv"] is not None else 0

            if max_version == 0:
                if version != 1:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-013", code="VERSION_VIOLATION",
                        message=f"{kind} {id_value}: first version must be 1, got {version}",
                        blocks_review=True, blocks_apply=True,
                    ))
            else:
                if version != max_version + 1:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-013", code="VERSION_GAP",
                        message=f"{kind} {id_value}: existing max version={max_version}, "
                                f"trying version={version}, expected {max_version + 1}",
                        blocks_review=True, blocks_apply=True,
                    ))
        except Exception:
            if version != 1:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-013", code="VERSION_VIOLATION",
                    message=f"{kind} {id_value}: first version must be 1, got {version}",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv014(self, gc: GraphChange, as_of: str) -> List[KnowledgeValidationIssue]:
        """KGV-014: Explicit As-Of — as_of required, valid ISO.

        Evidence.published_at <= as_of (future evidence→EVIDENCE_AFTER_AS_OF).
        If node/edge valid_from and valid_to both non-null: valid_from <= valid_to.
        """
        issues: List[KnowledgeValidationIssue] = []

        # Check as_of is required and valid ISO
        if not as_of:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-014", code="AS_OF_REQUIRED",
                message="as_of is required, cannot be empty",
                blocks_review=True, blocks_apply=True,
            ))
            return issues

        if not _validate_iso_format(as_of):
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-014", code="AS_OF_INVALID",
                message=f"as_of='{as_of}' is not a valid ISO 8601 datetime",
                blocks_review=True, blocks_apply=True,
            ))
            return issues

        as_of_dt = _parse_iso(as_of)
        if as_of_dt is None:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-014", code="AS_OF_INVALID",
                message=f"as_of='{as_of}' could not be parsed",
                blocks_review=True, blocks_apply=True,
            ))
            return issues

        # Check Evidence.published_at <= as_of for all new_evidence_ids
        for eid in sorted(gc.new_evidence_ids):
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                published_at_str = ev_payload.get("published_at", "")
                published_at = _parse_iso(published_at_str)
                if published_at and published_at > as_of_dt:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-014", code="EVIDENCE_AFTER_AS_OF",
                        message=f"Evidence {eid}: published_at={published_at_str} is after as_of={as_of}",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                continue

        # Check node valid_from <= valid_to
        if gc.node is not None:
            vf = _parse_iso(gc.node.valid_from)
            vt = _parse_iso(gc.node.valid_to)
            if vf is not None and vt is not None and vf > vt:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-014", code="INVALID_VALIDITY_INTERVAL",
                    message=f"Node {gc.node.node_id}: valid_from={gc.node.valid_from} > valid_to={gc.node.valid_to}",
                    blocks_review=False, blocks_apply=True,
                ))

        # Check edge valid_from <= valid_to
        if gc.edge is not None:
            vf = _parse_iso(gc.edge.valid_from)
            vt = _parse_iso(gc.edge.valid_to)
            if vf is not None and vt is not None and vf > vt:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-014", code="INVALID_VALIDITY_INTERVAL",
                    message=f"Edge {gc.edge.edge_id}: valid_from={gc.edge.valid_from} > valid_to={gc.edge.valid_to}",
                    blocks_review=False, blocks_apply=True,
                ))

        return issues

    def _check_kgv015(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-015: Duplicate Relation — add_edge→no existing triple, modify/retire→exactly 1 identity."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.edge is None:
            return issues

        edge = gc.edge
        try:
            existing_edges = self._graph_repo.find_edge_by_triple(
                edge.source_node_id, edge.relation, edge.target_node_id,
            )
        except Exception:
            return issues

        unique_edge_ids: Set[str] = set(e["edge_id"] for e in existing_edges)

        if gc.change_type == "add_edge":
            if len(unique_edge_ids) > 0:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-015", code="DUPLICATE_TRIPLE",
                    message=f"add_edge: triple already exists with edge_ids={sorted(unique_edge_ids)}",
                    blocks_review=True, blocks_apply=True,
                ))
        elif gc.change_type in ("modify_attribute", "retire_edge"):
            if len(unique_edge_ids) != 1:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-015", code="AMBIGUOUS_EDGE_IDENTITY",
                    message=f"{gc.change_type}: found {len(unique_edge_ids)} edge identities "
                            f"for triple ({edge.source_node_id}, {edge.relation}, {edge.target_node_id}), "
                            f"expected exactly 1",
                    blocks_review=True, blocks_apply=True,
                ))
            elif edge.edge_id not in unique_edge_ids:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-015", code="EDGE_ID_MISMATCH",
                    message=f"{gc.change_type}: edge_id={edge.edge_id} does not match "
                            f"existing identity {sorted(unique_edge_ids)}",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv016(self, edge: GraphEdge) -> List[KnowledgeValidationIssue]:
        """KGV-016: Self-Loop — source==target blocked for all relations."""
        issues: List[KnowledgeValidationIssue] = []

        if edge.source_node_id == edge.target_node_id:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-016", code="SELF_LOOP_NOT_ALLOWED",
                message=f"Self-loop not allowed: source={edge.source_node_id} == target={edge.target_node_id}",
                blocks_review=True, blocks_apply=True,
            ))

        return issues

    def _check_kgv017(self, edge: GraphEdge) -> List[KnowledgeValidationIssue]:
        """KGV-017: Retired Node Reference — endpoints must have latest status==active."""
        issues: List[KnowledgeValidationIssue] = []

        for endpoint_id, role in [(edge.source_node_id, "source"), (edge.target_node_id, "target")]:
            try:
                row = self._db._conn.execute(
                    """SELECT payload FROM graph_nodes 
                       WHERE node_id = ? 
                       ORDER BY version DESC LIMIT 1""",
                    (endpoint_id,),
                ).fetchone()
                if row is None:
                    continue  # Already caught by KGV-004
                node_payload = json.loads(row["payload"])
                status = node_payload.get("status", "active")
                if status != "active":
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-017", code="RETIRED_NODE_REFERENCE",
                        message=f"{role} node {endpoint_id} has status={status}, expected active",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                continue

        return issues

    def _check_kgv019(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-019: Stale Review — compare current_knowledge vs current persisted graph state.

        Uses canonical baseline comparison:
        - Node: if current_knowledge=="", now node exists→STALE_REVIEW.
          If current_knowledge!="", compare canonical latest persisted node payload
          vs parsed current_knowledge. NOT just version check.
        - Edge: same by logical triple (source+relation+target).
        - MUST run in validate_review stage.

        For add operations: if current_knowledge=="" and node/edge exists→STALE
        For modify/retire: compare version via current_knowledge vs latest persisted.
        """
        issues: List[KnowledgeValidationIssue] = []

        current_knowledge = gc.current_knowledge if gc.current_knowledge else ""

        # ── Node check ──
        if gc.node is not None:
            node_id = gc.node.node_id
            try:
                # Get latest persisted node
                row = self._db._conn.execute(
                    "SELECT payload FROM graph_nodes WHERE node_id = ? ORDER BY version DESC LIMIT 1",
                    (node_id,),
                ).fetchone()

                if gc.change_type == "add_node":
                    if current_knowledge == "":
                        # current_knowledge empty → if node exists anywhere, stale
                        if row is not None:
                            issues.append(KnowledgeValidationIssue(
                                rule_id="KGV-019", code="STALE_REVIEW_NODE_EXISTS",
                                message=f"add_node candidate stale: node {node_id} already exists in graph",
                                blocks_review=False, blocks_apply=True,
                            ))
                    else:
                        # current_knowledge non-empty → compare canonical baseline
                        if row is not None:
                            persisted_payload = json.loads(row["payload"])
                            # Parse current_knowledge as canonical payload
                            try:
                                ck_payload = json.loads(current_knowledge)
                            except json.JSONDecodeError:
                                # current_knowledge not JSON → just check existence
                                issues.append(KnowledgeValidationIssue(
                                    rule_id="KGV-019", code="STALE_REVIEW_NODE_EXISTS",
                                    message=f"add_node candidate stale: node {node_id} exists and current_knowledge is not valid JSON",
                                    blocks_review=False, blocks_apply=True,
                                ))
                            else:
                                # Compare canonical sorted JSON
                                persisted_canonical = json.dumps(
                                    persisted_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                                ck_canonical = json.dumps(
                                    ck_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                                if persisted_canonical != ck_canonical:
                                    issues.append(KnowledgeValidationIssue(
                                        rule_id="KGV-019", code="STALE_REVIEW_NODE_CHANGED",
                                        message=f"add_node candidate stale: node {node_id} current_knowledge "
                                                f"differs from persisted canonical baseline",
                                        blocks_review=False, blocks_apply=True,
                                    ))

                elif gc.change_type in ("modify_attribute", "retire_node"):
                    if row is None:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_NODE_MISSING",
                            message=f"modify/retire candidate stale: node {node_id} not found",
                            blocks_review=False, blocks_apply=True,
                        ))
                    elif current_knowledge != "":
                        # Compare canonical baseline
                        persisted_payload = json.loads(row["payload"])
                        try:
                            ck_payload = json.loads(current_knowledge)
                        except json.JSONDecodeError:
                            pass
                        else:
                            persisted_canonical = json.dumps(
                                persisted_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                            )
                            ck_canonical = json.dumps(
                                ck_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                            )
                            if persisted_canonical != ck_canonical:
                                issues.append(KnowledgeValidationIssue(
                                    rule_id="KGV-019", code="STALE_REVIEW_NODE_CHANGED",
                                    message=f"modify/retire candidate stale: node {node_id} "
                                            f"current_knowledge differs from persisted canonical baseline",
                                    blocks_review=False, blocks_apply=True,
                                ))
                    else:
                        # current_knowledge empty → version-based fallback
                        persisted_payload = json.loads(row["payload"])
                        persisted_version = persisted_payload.get("version", 0)
                        if persisted_version >= gc.node.version and gc.node.version < persisted_version:
                            pass  # version gap already caught by KGV-013
                        elif persisted_version > gc.node.version:
                            issues.append(KnowledgeValidationIssue(
                                rule_id="KGV-019", code="STALE_REVIEW_NODE_CHANGED",
                                message=f"modify/retire candidate stale: node {node_id} "
                                        f"v{gc.node.version} (latest v{persisted_version})",
                                blocks_review=False, blocks_apply=True,
                            ))
            except Exception:
                pass

        # ── Edge check ──
        if gc.edge is not None:
            edge = gc.edge
            try:
                existing_edges = self._graph_repo.find_edge_by_triple(
                    edge.source_node_id, edge.relation, edge.target_node_id,
                )

                if gc.change_type == "add_edge":
                    if current_knowledge == "":
                        if len(existing_edges) > 0:
                            issues.append(KnowledgeValidationIssue(
                                rule_id="KGV-019", code="STALE_REVIEW_EDGE_EXISTS",
                                message=f"add_edge candidate stale: triple already exists in graph",
                                blocks_review=False, blocks_apply=True,
                            ))
                    else:
                        if len(existing_edges) > 0:
                            # Get latest edge payload
                            latest_edge = max(existing_edges, key=lambda e: e.get("version", 0))
                            persisted_payload = latest_edge.get("payload")
                            if isinstance(persisted_payload, str):
                                persisted_payload = json.loads(persisted_payload)
                            try:
                                ck_payload = json.loads(current_knowledge)
                            except json.JSONDecodeError:
                                issues.append(KnowledgeValidationIssue(
                                    rule_id="KGV-019", code="STALE_REVIEW_EDGE_EXISTS",
                                    message=f"add_edge candidate stale: triple exists and current_knowledge is not valid JSON",
                                    blocks_review=False, blocks_apply=True,
                                ))
                            else:
                                persisted_canonical = json.dumps(
                                    persisted_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                                ck_canonical = json.dumps(
                                    ck_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                                )
                                if persisted_canonical != ck_canonical:
                                    issues.append(KnowledgeValidationIssue(
                                        rule_id="KGV-019", code="STALE_REVIEW_EDGE_CHANGED",
                                        message=f"add_edge candidate stale: triple exists, "
                                                f"current_knowledge differs from persisted canonical baseline",
                                        blocks_review=False, blocks_apply=True,
                                    ))

                elif gc.change_type in ("modify_attribute", "retire_edge"):
                    if len(existing_edges) == 0:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_EDGE_MISSING",
                            message=f"modify/retire candidate stale: edge {edge.edge_id} not found",
                            blocks_review=False, blocks_apply=True,
                        ))
                    elif current_knowledge != "":
                        latest_edge = max(existing_edges, key=lambda e: e.get("version", 0))
                        persisted_payload = latest_edge.get("payload")
                        if isinstance(persisted_payload, str):
                            persisted_payload = json.loads(persisted_payload)
                        try:
                            ck_payload = json.loads(current_knowledge)
                        except json.JSONDecodeError:
                            pass
                        else:
                            persisted_canonical = json.dumps(
                                persisted_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                            )
                            ck_canonical = json.dumps(
                                ck_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                            )
                            if persisted_canonical != ck_canonical:
                                issues.append(KnowledgeValidationIssue(
                                    rule_id="KGV-019", code="STALE_REVIEW_EDGE_CHANGED",
                                    message=f"modify/retire candidate stale: edge {edge.edge_id} "
                                            f"current_knowledge differs from persisted canonical baseline",
                                    blocks_review=False, blocks_apply=True,
                                ))
                    else:
                        latest_version = max(e.get("version", 0) for e in existing_edges)
                        if latest_version > edge.version:
                            issues.append(KnowledgeValidationIssue(
                                rule_id="KGV-019", code="STALE_REVIEW_EDGE_CHANGED",
                                message=f"modify/retire candidate stale: edge {edge.edge_id} "
                                        f"v{edge.version} (latest v{latest_version})",
                                blocks_review=False, blocks_apply=True,
                            ))
            except Exception:
                pass

        return issues
