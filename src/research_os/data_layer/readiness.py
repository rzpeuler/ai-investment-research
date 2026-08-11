"""DataReadinessService（P7-D1）。

判断"当前已经存在的权威数据"是否满足某个 ScenarioDataRequirement。
严格只读：ZERO NETWORK / ZERO WRITE / ZERO LLM。
不得调用 Router.resolve() / Collector / HTTP client / Source fetcher / LLM。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from research_os.data_layer.checkers import (
    SCOPE_MISMATCH,
    ReadinessCheckResult,
    ReadinessCheckerRegistry,
)
from research_os.data_layer.context import ResolvedRequirementContext
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
    ) -> DataReadiness:
        checker = self._checkers.get(requirement.data_type)  # 缺 checker → CONFIG ERROR
        result = checker.check(ctx, requirement, view)
        return self._to_readiness(requirement, ctx, result, checked_at)

    @staticmethod
    def _to_readiness(
        requirement: ScenarioDataRequirement,
        ctx: ResolvedRequirementContext,
        result: ReadinessCheckResult,
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
