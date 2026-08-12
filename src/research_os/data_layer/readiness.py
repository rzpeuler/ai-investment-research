"""DataReadinessService（P7-D1 / R1）。

判断"当前已经存在的权威数据"是否满足某个 ScenarioDataRequirement。
严格只读：ZERO NETWORK / ZERO WRITE / ZERO LLM。
不得调用 Router.resolve() / Collector / HTTP client / Source fetcher / LLM。
"""
from __future__ import annotations

from typing import Any, List, Optional

from research_os.data_layer.checkers import (
    SCOPE_MISMATCH,
    ReadinessCheckerRegistry,
)
from research_os.data_layer.context import ResolvedRequirementContext
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.models import DataReadiness, ScenarioDataRequirement


class DataReadinessService:
    """只读 readiness 判定。一次 preflight 捕获一个 checked_at；as_of = Task.as_of。"""

    def __init__(self, checker_registry: ReadinessCheckerRegistry):
        self._checkers = checker_registry

    def evaluate(
        self,
        requirement: ScenarioDataRequirement,
        ctx: ResolvedRequirementContext,
        view: Any,
        checked_at: str,
        provenance: Optional[ReadinessProvenanceResolver] = None,
        binding: Optional[Any] = None,
        projector: Optional[Any] = None,
    ) -> DataReadiness:
        checker = self._checkers.get(requirement.data_type)  # 缺 checker → CONFIG ERROR
        result = checker.check(
            ctx, requirement, view, provenance or self._checkers._provenance)
        # R3-02：available_fields 按 requirement-facing canonical field names 计算
        if binding is not None and projector is not None:
            canonical_available = self._canonical_available_fields(
                binding, projector, ctx, result)
            result.available_fields = canonical_available
            # §127/R3：按 canonical available 重算 status（projection 字段数据齐全 → 不降级 PARTIAL）
            result = self._reconcile_status(requirement, result, canonical_available)
        return self._to_readiness(requirement, ctx, result, checked_at)

    @staticmethod
    def _reconcile_status(requirement, result, canonical_available):
        """canonical 后：missing 按 canonical 字段算；若缺失字段已由投影满足，
        将 PARTIAL 提升为 READY（除非 coverage/freshness 等其他原因仍不足）。"""
        from research_os.data_layer.checkers import (
            COVERAGE_BELOW_MINIMUM,
            COVERAGE_NOT_MEASURABLE,
            FRESHNESS_UNPROVEN,
            MISSING_REQUIRED_FIELDS,
            STALE_DATA,
        )
        missing = [f for f in requirement.minimum_fields if f not in canonical_available]
        if result.status in ("READY", "PARTIAL"):
            if not missing:
                # 移除仅因字段缺失导致的 PARTIAL 标记
                if MISSING_REQUIRED_FIELDS in result.warnings:
                    result.warnings.remove(MISSING_REQUIRED_FIELDS)
                # 若仍有非字段原因（coverage/freshness）→ 保持 PARTIAL；否则 READY
                non_field_issue = any(w in result.warnings for w in (
                    COVERAGE_BELOW_MINIMUM, COVERAGE_NOT_MEASURABLE,
                    FRESHNESS_UNPROVEN, STALE_DATA,
                ))
                if not non_field_issue:
                    result.status = "READY"
        return result

    @staticmethod
    def _canonical_available_fields(binding, projector, ctx, result) -> List[str]:
        """R3-02：按 Binding 的 minimum_field_sources 投影判定 canonical available_fields。

        所有 minimum_fields 至少经过 Projector / direct-field authority 判定（§14）。
        """
        canonical = set()
        for field, source in binding.minimum_field_sources.items():
            if source == "direct":
                # direct field：result.available_fields 已含（authority payload 判定）
                if field in result.available_fields:
                    canonical.add(field)
                continue
            # projection：对任一 eligible record 判定
            if hasattr(result, "eligible_payloads") and result.eligible_payloads:
                for payload in result.eligible_payloads:
                    if projector.has_field(payload, field, source, {
                        "industry_ids": ctx.industry_ids,
                        "entity_ids": ctx.entity_ids,
                    }):
                        canonical.add(field)
                        break
        # 保留非 minimum 的其他可用字段（仍属 canonical authority fields）
        canonical.update(f for f in result.available_fields
                         if f not in binding.minimum_field_sources)
        return sorted(canonical)

    @staticmethod
    def _to_readiness(
        requirement: ScenarioDataRequirement,
        ctx: ResolvedRequirementContext,
        result,
        checked_at: str,
    ) -> DataReadiness:
        warnings = list(result.warnings)
        if ctx.unresolved and SCOPE_MISMATCH not in warnings:
            warnings.append(SCOPE_MISMATCH)
        # open-world coverage：无合法 denominator 时 coverage=null（不得发明百分比）
        return DataReadiness(
            requirement_id=requirement.requirement_id,
            data_type=requirement.data_type,
            checked_at=checked_at,
            as_of=ctx.as_of,
            status=result.status,
            available_fields=sorted(result.available_fields),
            missing_fields=sorted(
                set(requirement.minimum_fields) - set(result.available_fields)),
            coverage_ratio=result.coverage_ratio,
            freshness_age_seconds=result.freshness_age_seconds,
            eligible_record_count=result.eligible_record_count,
            ineligible_record_count=result.ineligible_record_count,
            source_tiers_present=sorted(result.source_tiers_present),
            record_refs=result.record_refs,
            warnings=warnings,
        )
