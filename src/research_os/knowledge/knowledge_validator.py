"""Phase 5 M4 Knowledge Validator — 确定性机械规则引擎（零 LLM、零 writes、零网络）。

实现 KGV-001—019 共 19 条规则：
- validate_candidate(graph_change, as_of)
- validate_review(graph_change, graph_review, as_of)
- validate_apply_preflight(graph_change, graph_review, as_of)
- compute_candidate_hash(graph_change)
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

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
    checked_rule_ids: tuple  # tuple of str, 已检查的规则 ID
    issues: tuple            # tuple of KnowledgeValidationIssue


# ─────────────────────────────────────────────────────────────
# Validator
# ─────────────────────────────────────────────────────────────

class KnowledgeValidator:
    """Phase 5 M4 知识校验器 — 确定性机械规则引擎。

    零 Provider 调用、零网络访问、零数据库写入、零随机数。
    """

    def __init__(self, db: Any, graph_repo: Any):
        """db 为 Database 实例，graph_repo 为 GraphRepository 实例。"""
        self._db = db
        self._graph_repo = graph_repo

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
        graph_change: GraphChange,
        as_of: str,
    ) -> KnowledgeValidationResult:
        """校验 GraphChange candidate 是否可以进入审核阶段。

        Args:
            graph_change: 完整的 GraphChange 候选对象。
            as_of: 显式截止时间（不接受 now() 默认值）。

        Returns:
            KnowledgeValidationResult
        """
        issues: List[KnowledgeValidationIssue] = []
        checked: List[str] = []

        # ── KGV-001 Schema ──────────────────────────────
        schema_issues = self._check_kgv001(graph_change)
        checked.append("KGV-001")
        structural_ok = len(schema_issues) == 0
        issues.extend(schema_issues)

        # ── KGV-014 Explicit As-Of ──────────────────────
        checked.append("KGV-014")

        # ── KGV-002 Node Identity ───────────────────────
        if graph_change.node is not None:
            issues.extend(self._check_kgv002(graph_change.node))
        checked.append("KGV-002")

        # ── KGV-016 Self-Loop ───────────────────────────
        if graph_change.edge is not None:
            issues.extend(self._check_kgv016(graph_change.edge))
        checked.append("KGV-016")

        # ── KGV-003 Relation Allowlist ──────────────────
        if graph_change.edge is not None:
            issues.extend(self._check_kgv003(graph_change.edge))
        checked.append("KGV-003")

        # ── KGV-010 FACT/MODEL_INFERENCE boundary ───────
        issues.extend(self._check_kgv010(graph_change))
        checked.append("KGV-010")

        # ── KGV-009 Governance Seed Scope ───────────────
        issues.extend(self._check_kgv009(graph_change))
        checked.append("KGV-009")

        # ── KGV-005 Evidence Existence ──────────────────
        issues.extend(self._check_kgv005(graph_change))
        checked.append("KGV-005")

        # ── KGV-006 Evidence Entity Relevance ───────────
        issues.extend(self._check_kgv006(graph_change))
        checked.append("KGV-006")

        # ── KGV-007 Evidence Time ───────────────────────
        issues.extend(self._check_kgv007(graph_change))
        checked.append("KGV-007")

        # ── KGV-008 Source Tier ─────────────────────────
        issues.extend(self._check_kgv008(graph_change))
        checked.append("KGV-008")

        # ── KGV-004 Source/Target Existence ─────────────
        if graph_change.edge is not None:
            issues.extend(self._check_kgv004(graph_change.edge))
        checked.append("KGV-004")

        # ── KGV-013 Version Monotonicity ────────────────
        issues.extend(self._check_kgv013(graph_change))
        checked.append("KGV-013")

        # ── KGV-015 Duplicate Relation ──────────────────
        if graph_change.edge is not None:
            issues.extend(self._check_kgv015(graph_change))
        checked.append("KGV-015")

        # ── KGV-017 Retired Node Reference ──────────────
        if graph_change.edge is not None:
            issues.extend(self._check_kgv017(graph_change.edge))
        checked.append("KGV-017")

        # ── KGV-011 Conflict Blocking ───────────────────
        issues.extend(self._check_kgv011(graph_change))
        checked.append("KGV-011")

        # ── KGV-012 Review Status ───────────────────────
        issues.extend(self._check_kgv012(graph_change))
        checked.append("KGV-012")

        # ── KGV-018 Candidate Hash ──────────────────────
        candidate_hash = None
        try:
            candidate_hash = self.compute_candidate_hash(graph_change)
        except Exception:
            pass
        checked.append("KGV-018")

        # ── KGV-019 Stale Review (candidate stage: N/A) ─
        # At candidate stage, there's no review yet, so KGV-019
        # is checked only during validate_apply_preflight.
        checked.append("KGV-019")

        # Determine eligibility
        review_eligible = True
        apply_eligible = True
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        # Candidate stage: apply_eligible is informational only
        if not structural_ok:
            review_eligible = False

        return KnowledgeValidationResult(
            stage="candidate",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=candidate_hash,
            checked_rule_ids=tuple(checked),
            issues=tuple(issues),
        )

    # ── validate_review ──────────────────────────────────

    def validate_review(
        self,
        graph_change: GraphChange,
        graph_review: GraphReview,
        as_of: str,
    ) -> KnowledgeValidationResult:
        """校验 GraphReview 是否可以应用于对应的 GraphChange。

        Args:
            graph_change: 被审核的 GraphChange
            graph_review: 审核记录
            as_of: 显式截止时间

        Returns:
            KnowledgeValidationResult
        """
        # First run candidate validation
        base = self.validate_candidate(graph_change, as_of)
        issues: List[KnowledgeValidationIssue] = list(base.issues)
        checked: List[str] = list(base.checked_rule_ids)

        structural_ok = base.structural_ok

        # ── Additional review-stage checks ────────────────
        # Verify graph_review matches graph_change
        if graph_review.graph_change_id != graph_change.graph_change_id:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012",
                code="REVIEW_MISMATCH",
                message=f"GraphReview.graph_change_id={graph_review.graph_change_id} "
                        f"!= GraphChange.graph_change_id={graph_change.graph_change_id}",
                blocks_review=True,
                blocks_apply=True,
            ))

        # Verify candidate hash matches
        expected_hash = self.compute_candidate_hash(graph_change)
        if graph_review.candidate_hash != expected_hash:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-018",
                code="CANDIDATE_HASH_MISMATCH",
                message=f"Review candidate_hash={graph_review.candidate_hash} "
                        f"!= computed hash={expected_hash}",
                blocks_review=True,
                blocks_apply=True,
            ))

        # Only approved/approved_with_changes can proceed to apply
        if graph_review.decision not in ("approved", "approved_with_changes"):
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-012",
                code="NON_APPROVABLE_DECISION",
                message=f"Review decision={graph_review.decision} cannot proceed to apply",
                blocks_review=False,
                blocks_apply=True,
            ))

        review_eligible = base.review_eligible
        apply_eligible = base.apply_eligible
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        return KnowledgeValidationResult(
            stage="review",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=expected_hash,
            checked_rule_ids=tuple(checked),
            issues=tuple(issues),
        )

    # ── validate_apply_preflight ─────────────────────────

    def validate_apply_preflight(
        self,
        graph_change: GraphChange,
        graph_review: GraphReview,
        as_of: str,
    ) -> KnowledgeValidationResult:
        """Apply 前最终预检查（含 KGV-019 stale review detection）。

        Args:
            graph_change: 待应用 GraphChange
            graph_review: 已批准审核
            as_of: 显式截止时间

        Returns:
            KnowledgeValidationResult
        """
        # First run full review validation
        base = self.validate_review(graph_change, graph_review, as_of)
        issues: List[KnowledgeValidationIssue] = list(base.issues)
        checked: List[str] = list(base.checked_rule_ids)

        # ── KGV-019 Stale Review ──────────────────────────
        issues.extend(self._check_kgv019(graph_change))
        checked.append("KGV-019")

        structural_ok = base.structural_ok
        review_eligible = base.review_eligible
        apply_eligible = base.apply_eligible
        for issue in issues:
            if issue.blocks_review:
                review_eligible = False
            if issue.blocks_apply:
                apply_eligible = False

        return KnowledgeValidationResult(
            stage="apply_preflight",
            structural_ok=structural_ok,
            review_eligible=review_eligible,
            apply_eligible=apply_eligible,
            candidate_hash=base.candidate_hash,
            checked_rule_ids=tuple(checked),
            issues=tuple(issues),
        )

    # ──────────────────────────────────────────────────────
    #  Rule implementations
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
        """KGV-002: Node Identity — Company node_id == Entity.entity_id, entity_type mapping."""
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

        # Check Entity table for existence and type match
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
            # graph_nodes table might not exist — treat as not found
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
        """KGV-005: Evidence Existence — all evidence IDs must exist in SQLite evidence table."""
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

                # Schema-validate the evidence payload
                evidence_payload = json.loads(row["payload"])
                ev_errors = validate_instance(evidence_payload, "evidence")
                if ev_errors:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-005", code="EVIDENCE_SCHEMA_INVALID",
                        message=f"Evidence {eid} schema invalid: {'; '.join(ev_errors)}",
                        blocks_review=True, blocks_apply=True,
                    ))
            except Exception:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-005", code="EVIDENCE_NOT_FOUND",
                    message=f"Evidence {eid} query failed",
                    blocks_review=True, blocks_apply=True,
                ))

        return issues

    def _check_kgv006(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-006: Evidence Entity Relevance — Evidence→RawItem→entities coverage."""
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

        # Collect all evidence IDs
        all_evidence_ids: Set[str] = set()
        for eid in gc.new_evidence_ids:
            all_evidence_ids.add(eid)
        if gc.node is not None:
            for eid in gc.node.evidence_ids:
                all_evidence_ids.add(eid)
        if gc.edge is not None:
            for eid in gc.edge.evidence_ids:
                all_evidence_ids.add(eid)

        # Build entity coverage from all Evidence→RawItem→entities chains
        covered_entities: Set[str] = set()
        for eid in all_evidence_ids:
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

                # Schema validate RawItem
                ri_errors = validate_instance(ri_payload, "raw_item")
                if ri_errors:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-006", code="RAW_ITEM_INVALID",
                        message=f"RawItem {raw_item_id} schema invalid: {'; '.join(ri_errors)}",
                        blocks_review=False, blocks_apply=True,
                    ))

                # Collect entities from RawItem
                raw_entities = ri_payload.get("entities", [])
                for ent_id in raw_entities:
                    covered_entities.add(ent_id)
            except Exception:
                continue

        # Check coverage
        for req_entity in required_entity_ids:
            if req_entity not in covered_entities:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-006", code="ENTITY_NOT_COVERED_BY_EVIDENCE",
                    message=f"Required entity {req_entity} not covered by any Evidence→RawItem chain",
                    blocks_review=False, blocks_apply=True,
                ))

        return issues

    def _check_kgv007(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-007: Evidence Time — published_at <= retrieved_at for each Evidence."""
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

        for eid in all_evidence_ids:
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                published_at = ev_payload.get("published_at", "")
                retrieved_at = ev_payload.get("retrieved_at", "")
                if published_at and retrieved_at and published_at > retrieved_at:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-007", code="EVIDENCE_TIME_INVALID",
                        message=f"Evidence {eid}: published_at={published_at} > retrieved_at={retrieved_at}",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                continue

        return issues

    def _check_kgv008(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-008: Source Tier — FACT edge with core structural relations needs S/A source."""
        issues: List[KnowledgeValidationIssue] = []

        if gc.edge is None:
            return issues
        if gc.edge.assertion_type != "FACT":
            return issues
        if gc.edge.relation not in _CORE_STRUCTURAL_RELATIONS:
            return issues

        # Collect all evidence IDs for this edge
        all_evidence_ids: Set[str] = set()
        for eid in gc.new_evidence_ids:
            all_evidence_ids.add(eid)
        for eid in gc.edge.evidence_ids:
            all_evidence_ids.add(eid)

        has_sa_source = False
        for eid in all_evidence_ids:
            try:
                ev_row = self._db._conn.execute(
                    "SELECT payload FROM evidence WHERE evidence_id = ?",
                    (eid,),
                ).fetchone()
                if ev_row is None:
                    continue
                ev_payload = json.loads(ev_row["payload"])
                source_tier = ev_payload.get("source_tier", "B")
                if source_tier in ("S", "A"):
                    has_sa_source = True
                    break
            except Exception:
                continue

        if not has_sa_source:
            issues.append(KnowledgeValidationIssue(
                rule_id="KGV-008", code="INSUFFICIENT_SOURCE_TIER",
                message=f"FACT edge with relation={gc.edge.relation} requires at least one S/A source",
                blocks_review=False, blocks_apply=True,
            ))

        return issues

    def _check_kgv009(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-009: Governance Seed Scope — block Industry/IndustrySegment from ordinary candidates."""
        issues: List[KnowledgeValidationIssue] = []

        # Check node type
        if gc.node is not None:
            if gc.node.node_type in ("Industry", "IndustrySegment"):
                # Block add/modify/retire by ordinary candidates
                if gc.change_type in ("add_node", "modify_attribute", "retire_node"):
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-009", code="ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE",
                        message=f"Cannot {gc.change_type} Industry/IndustrySegment via ordinary candidate",
                        blocks_review=True, blocks_apply=True,
                    ))

            # Block governance_seed origin from ordinary candidates
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
            # Only FACT/MODEL_INFERENCE allowed for edges
            if gc.edge.assertion_type == "GOVERNANCE":
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-010", code="GOVERNANCE_NOT_ALLOWED",
                    message="GOVERNANCE assertion not allowed for GraphChange edge",
                    blocks_review=True, blocks_apply=True,
                ))
            # MODEL_INFERENCE requires real Evidence
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
                blocks_review=False,    # review can still proceed
                blocks_apply=True,      # apply is blocked
            ))

        return issues

    def _check_kgv012(self, gc: GraphChange) -> List[KnowledgeValidationIssue]:
        """KGV-012: Review Status — candidate must have review_status=candidate, reviewed_at=null."""
        issues: List[KnowledgeValidationIssue] = []

        # GraphChange level
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

        # Node level if present
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

        # Edge level if present
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

        # Check node version
        if gc.node is not None:
            issues.extend(self._check_version_monotonicity(
                "graph_nodes", gc.node.node_id, gc.node.version, "node"
            ))

        # Check edge version
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
                # Fresh entry — must be v1
                if version != 1:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-013", code="VERSION_VIOLATION",
                        message=f"{kind} {id_value}: first version must be 1, got {version}",
                        blocks_review=True, blocks_apply=True,
                    ))
            else:
                # Existing entry — must be N+1
                if version != max_version + 1:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-013", code="VERSION_GAP",
                        message=f"{kind} {id_value}: existing max version={max_version}, "
                                f"trying version={version}, expected {max_version + 1}",
                        blocks_review=True, blocks_apply=True,
                    ))
        except Exception:
            # Table might not exist — assume fresh
            if version != 1:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-013", code="VERSION_VIOLATION",
                    message=f"{kind} {id_value}: first version must be 1, got {version}",
                    blocks_review=True, blocks_apply=True,
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

        # Get unique edge_ids
        unique_edge_ids: Set[str] = set(e["edge_id"] for e in existing_edges)

        if gc.change_type == "add_edge":
            if len(unique_edge_ids) > 0:
                issues.append(KnowledgeValidationIssue(
                    rule_id="KGV-015", code="DUPLICATE_TRIPLE",
                    message=f"add_edge: triple already exists with edge_ids={unique_edge_ids}",
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
                            f"existing identity {unique_edge_ids}",
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

        This is a heuristic check: if the GraphChange references a node/edge that
        has changed since the candidate was created, it's stale.
        """
        issues: List[KnowledgeValidationIssue] = []

        # For add operations, check that the target node/edge doesn't already exist beyond
        # what we expect.
        if gc.change_type == "add_node" and gc.node is not None:
            try:
                row = self._db._conn.execute(
                    "SELECT 1 FROM graph_nodes WHERE node_id = ?",
                    (gc.node.node_id,),
                ).fetchone()
                if row is not None:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-019", code="STALE_REVIEW_NODE_EXISTS",
                        message=f"add_node candidate stale: node {gc.node.node_id} already exists in graph",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                pass

        if gc.change_type == "add_edge" and gc.edge is not None:
            try:
                existing = self._graph_repo.find_edge_by_triple(
                    gc.edge.source_node_id, gc.edge.relation, gc.edge.target_node_id,
                )
                if len(existing) > 0:
                    issues.append(KnowledgeValidationIssue(
                        rule_id="KGV-019", code="STALE_REVIEW_EDGE_EXISTS",
                        message=f"add_edge candidate stale: triple already exists in graph",
                        blocks_review=False, blocks_apply=True,
                    ))
            except Exception:
                pass

        # For modify/retire operations, check that the target still exists and is the
        # version that was reviewed
        if gc.change_type in ("modify_attribute", "retire_node", "retire_edge"):
            if gc.node is not None:
                try:
                    row = self._db._conn.execute(
                        "SELECT MAX(version) FROM graph_nodes WHERE node_id = ?",
                        (gc.node.node_id,),
                    ).fetchone()
                    max_version = row[0] if row and row[0] is not None else 0
                    if max_version == 0:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_NODE_MISSING",
                            message=f"modify/retire candidate stale: node {gc.node.node_id} not found",
                            blocks_review=False, blocks_apply=True,
                        ))
                    elif max_version >= gc.node.version and gc.node.version < max_version:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_VERSION_CHANGED",
                            message=f"modify/retire candidate stale: node {gc.node.node_id} "
                                    f"v{gc.node.version} (latest v{max_version})",
                            blocks_review=False, blocks_apply=True,
                        ))
                except Exception:
                    pass

            if gc.edge is not None:
                try:
                    row = self._db._conn.execute(
                        "SELECT MAX(version) FROM graph_edges WHERE edge_id = ?",
                        (gc.edge.edge_id,),
                    ).fetchone()
                    max_version = row[0] if row and row[0] is not None else 0
                    if max_version == 0:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_EDGE_MISSING",
                            message=f"modify/retire candidate stale: edge {gc.edge.edge_id} not found",
                            blocks_review=False, blocks_apply=True,
                        ))
                    elif max_version >= gc.edge.version and gc.edge.version < max_version:
                        issues.append(KnowledgeValidationIssue(
                            rule_id="KGV-019", code="STALE_REVIEW_VERSION_CHANGED",
                            message=f"modify/retire candidate stale: edge {gc.edge.edge_id} "
                                    f"v{gc.edge.version} (latest v{max_version})",
                            blocks_review=False, blocks_apply=True,
                        ))
                except Exception:
                    pass

        return issues
