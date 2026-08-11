"""RequirementContextResolver（P7-D1）。

将 ScenarioDataRequirement + normalized request + Task 解析为
ResolvedRequirementContext。必须是 ScenarioRunner.validate_request() 之后执行；
scenario_window 必须复用现有权威窗口逻辑（morning/evening BriefWindowPolicy），
禁止在 data_layer 重新实现第二套窗口计算。

只读、确定性、零 LLM、零网络、零写入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from research_os.models import ScenarioDataRequirement
from research_os.utils.time import parse_iso

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


class RequirementContextResolver:
    """解析 Scenario requirement 的运行上下文；fail closed，不猜测。"""

    def __init__(self) -> None:
        _register_brief_windows()

    def resolve(
        self,
        requirement: ScenarioDataRequirement,
        scenario: str,
        task_id: str,
        normalized_request: Dict[str, Any],
        task_as_of: str,
    ) -> ResolvedRequirementContext:
        ctx = ResolvedRequirementContext(
            requirement=requirement,
            scenario=scenario,
            task_id=task_id,
            as_of=task_as_of,
        )
        self._resolve_scope(ctx, normalized_request)
        self._resolve_time(ctx, normalized_request)
        return ctx

    # ---------- scope ----------

    def _resolve_scope(self, ctx: ResolvedRequirementContext,
                       normalized_request: Dict[str, Any]) -> None:
        scope_type = ctx.requirement.scope.scope_type
        if scope_type == "global":
            return
        if scope_type == "subject":
            entity_ids = list(normalized_request.get("entities") or [])
            if not entity_ids:
                ctx.unresolved.append("subject")
            ctx.entity_ids = entity_ids
            return
        if scope_type == "benchmark":
            benchmark = normalized_request.get("benchmark")
            if benchmark:
                ctx.entity_ids = [str(benchmark)]
            else:
                ctx.unresolved.append("benchmark")
            return
        if scope_type == "peers":
            peers = list(normalized_request.get("peers") or [])
            ctx.peer_entity_ids = peers
            if not peers:
                ctx.unresolved.append("peers")
            return
        if scope_type == "industry":
            industries = list(normalized_request.get("industries")
                              or normalized_request.get("industry_ids") or [])
            ctx.industry_ids = industries
            if not industries:
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
                      normalized_request: Dict[str, Any]) -> None:
        policy = ctx.requirement.time_policy
        if policy == "scenario_window":
            self._resolve_scenario_window(ctx, normalized_request)
        elif policy == "explicit_request_window":
            ctx.window_start = normalized_request.get("window_start")
            ctx.window_end = normalized_request.get("window_end")
            if not ctx.window_start or not ctx.window_end:
                ctx.unresolved.append("window")
        elif policy in ("as_of_snapshot", "latest_available", "lookback_trading_days"):
            # as_of 来自 Task；lookback 交易日由既有业务窗口/行情路径决定，
            # data_layer 不重新实现日期计算（D0 冻结）。
            pass

    def _resolve_scenario_window(self, ctx: ResolvedRequirementContext,
                                 normalized_request: Dict[str, Any]) -> None:
        """scenario_window 必须调用现有权威窗口逻辑，禁止第二套窗口计算。"""
        policy = _BRIEF_WINDOW_RESOLVERS.get(ctx.scenario)
        if policy is None:
            ctx.unresolved.append("scenario_window")
            return
        report_date = normalized_request.get("report_date") or normalized_request.get("date")
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
