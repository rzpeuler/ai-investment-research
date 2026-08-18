"""RequirementContextResolver（P7-D1 / R1）。

将 ScenarioDataRequirement + CanonicalRequestContext + Task 解析为
ResolvedRequirementContext。必须是 ScenarioRunner.validate_request() 之后执行；
scenario_window 复用现有权威窗口逻辑（morning/evening BriefWindowPolicy）。

R1：context inputs 由 NormalizedRequestContextAdapter 唯一产生（禁止 alias 猜测），
与 Orchestrator Task.entities 共享同一 adapter（§9）。

只读、确定性、零 LLM、零网络、零写入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from research_os.data_layer.request_context import CanonicalRequestContext
from research_os.models import ScenarioDataRequirement

# scenario_window 的权威窗口解析器（morning/evening 复用既有 BriefWindowPolicy）
_BRIEF_WINDOW_RESOLVERS: Dict[str, Any] = {}


def _register_brief_windows() -> None:
    from research_os.brief.window import evening_policy, morning_policy
    _BRIEF_WINDOW_RESOLVERS["morning_brief"] = morning_policy()
    _BRIEF_WINDOW_RESOLVERS["evening_brief"] = evening_policy()


@dataclass
class ResolvedRequirementContext:
    """内部 typed object（非公共 Schema，不新增第 86 个 Schema）。"""

    requirement: ScenarioDataRequirement
    scenario: str
    task_id: str
    as_of: str
    entity_ids: List[str] = field(default_factory=list)
    peer_entity_ids: List[str] = field(default_factory=list)
    industry_ids: List[str] = field(default_factory=list)
    window_start: Optional[str] = None
    window_end: Optional[str] = None
    watchlist_group: Optional[str] = None
    request_material_refs: List[str] = field(default_factory=list)
    unresolved: List[str] = field(default_factory=list)
    # R3：runtime semantic binding（生产 preflight 注入；checker 必须消费，不得绕回 generic spec）
    binding: Optional[Any] = None
    # R3：canonical field projector（runtime 计算 requirement-facing available_fields）
    projector: Optional[Any] = None
    # R3-05：prior-run 专用字段（RunArtifactChecker 只查 requested runs）
    previous_run_ids: List[str] = field(default_factory=list)


class RequirementContextResolver:
    """解析 Scenario requirement 的运行上下文；fail closed，不猜测。"""

    def __init__(self) -> None:
        _register_brief_windows()

    def resolve(
        self,
        requirement: ScenarioDataRequirement,
        scenario: str,
        task_id: str,
        canonical: CanonicalRequestContext,
        task_as_of: str,
    ) -> ResolvedRequirementContext:
        ctx = ResolvedRequirementContext(
            requirement=requirement,
            scenario=scenario,
            task_id=task_id,
            as_of=task_as_of,
        )
        ctx.previous_run_ids = list(canonical.previous_run_ids)
        self._resolve_scope(ctx, canonical)
        self._resolve_time(ctx, canonical)
        ctx.request_material_refs = list(canonical.request_material_refs)
        return ctx

    # ---------- scope ----------

    def _resolve_scope(self, ctx: ResolvedRequirementContext,
                       canonical: CanonicalRequestContext) -> None:
        scope_type = ctx.requirement.scope.scope_type
        if scope_type == "global":
            return
        if scope_type == "subject":
            ctx.entity_ids = list(canonical.subject_entity_ids)
            if not ctx.entity_ids:
                ctx.unresolved.append("subject")
            return
        if scope_type == "benchmark":
            ctx.entity_ids = list(canonical.benchmark_entity_ids)
            if not ctx.entity_ids:
                ctx.unresolved.append("benchmark")
            return
        if scope_type == "peers":
            ctx.peer_entity_ids = list(canonical.peer_entity_ids)
            if not ctx.peer_entity_ids:
                ctx.unresolved.append("peers")
            return
        if scope_type == "industry":
            ctx.industry_ids = list(canonical.industry_ids)
            if not ctx.industry_ids:
                ctx.unresolved.append("industry")
            return
        if scope_type == "watchlist":
            group = ctx.requirement.scope.watchlist_group
            if not group:
                ctx.unresolved.append("watchlist")
            ctx.watchlist_group = group
            return
        if scope_type == "scenario":
            # 场景级作用域由 scenario 自身决定；不猜测具体实体
            return
        # 未知 scope_type（Schema 已枚举，理论上不可达；fail closed）
        ctx.unresolved.append(scope_type)

    # ---------- time ----------

    def _resolve_time(self, ctx: ResolvedRequirementContext,
                      canonical: CanonicalRequestContext) -> None:
        policy = ctx.requirement.time_policy
        if policy == "scenario_window":
            self._resolve_scenario_window(ctx, canonical)
        elif policy == "explicit_request_window":
            ctx.window_start = canonical.explicit_window_start
            ctx.window_end = canonical.explicit_window_end
            if not ctx.window_start or not ctx.window_end:
                ctx.unresolved.append("window")
        elif policy in ("as_of_snapshot", "latest_available", "lookback_trading_days"):
            # as_of 来自 Task；lookback 交易日由既有业务窗口/行情路径决定，
            # data_layer 不重新实现日期计算（D0 冻结）。
            pass

    def _resolve_scenario_window(self, ctx: ResolvedRequirementContext,
                                 canonical: CanonicalRequestContext) -> None:
        """scenario_window 必须调用现有权威窗口逻辑，禁止第二套窗口计算。"""
        policy = _BRIEF_WINDOW_RESOLVERS.get(ctx.scenario)
        if policy is None:
            ctx.unresolved.append("scenario_window")
            return
        report_date = canonical.report_date
        if not report_date:
            ctx.unresolved.append("scenario_window")
            return
        try:
            day = date.fromisoformat(str(report_date))
        except ValueError:
            ctx.unresolved.append("scenario_window")
            return
        start, end = policy.window(day)
        ctx.window_start = start
        ctx.window_end = end
