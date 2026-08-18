"""NormalizedRequestContextAdapter（P7-D1-R1）。

建立唯一确定性 Request Context Adapter：
scenario + Runner.validate_request() 后的 normalized request
→ canonical context inputs。

禁止 Generic Alias Guessing（request.get("entity") or request.get("entity_id") ...）。
必须按 scenario → exact normalized request contract 机械映射（§5-6）。

同一 adapter 同时用于 Orchestrator Task.entities 与 RequirementContextResolver，
避免 Task.entities 与 Resolver 两套解析不一致（§9）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class CanonicalRequestContext:
    """从真实 normalized request 提取的 canonical context inputs。"""

    scenario: str
    subject_entity_ids: List[str] = field(default_factory=list)
    benchmark_entity_ids: List[str] = field(default_factory=list)
    peer_entity_ids: List[str] = field(default_factory=list)
    industry_ids: List[str] = field(default_factory=list)
    explicit_window_start: Optional[str] = None
    explicit_window_end: Optional[str] = None
    report_date: Optional[str] = None
    request_material_refs: List[str] = field(default_factory=list)
    # R3-05：prior-run 专用字段（不得塞进 request_material_refs，§37-38）
    previous_run_ids: List[str] = field(default_factory=list)
    previous_report_paths: List[str] = field(default_factory=list)
    previous_cutoff: Optional[str] = None

    @property
    def task_entities(self) -> List[str]:
        """Orchestrator Task.entities 的 canonical 来源（subject + benchmark + peers 全量）。

        与 Resolver 共享同一 adapter，避免 Task.entities=[] 而 Resolver 认为有 subject。
        """
        merged: List[str] = []
        for group in (self.subject_entity_ids, self.benchmark_entity_ids,
                      self.peer_entity_ids):
            for e in group:
                if e not in merged:
                    merged.append(e)
        return merged


# scenario → normalized request 字段提取器（精确契约，禁止 alias 猜测）
_SCENARIO_SUBJECT_FIELDS: Dict[str, List[str]] = {
    # 实体字段按优先级顺序（每个 scenario 的正式契约）
    "abnormal_move_analysis": ["entity_id"],
    "stock_research_report": ["entity", "entity_id"],
    "stock_review": ["entity", "entity_id"],
    "earnings_expectation": ["company_entity_id"],
    "first_coverage": ["company_entity_id"],
    "daily_review": ["entities"],
    "evening_brief": ["entities"],
    "morning_brief": ["entities"],
    "industry_research": [],
    "theme_discovery": [],
}

_SCENARIO_INDUSTRY_FIELDS: Dict[str, List[str]] = {
    "industry_research": ["industry_id", "industry_ids"],
    "theme_discovery": ["industry_ids"],
    "first_coverage": ["industry_id"],
}

_SCENARIO_PEER_FIELDS: Dict[str, List[str]] = {
    "stock_research_report": ["peers", "peer_entity_ids"],
    "first_coverage": ["peers", "peer_entity_ids"],
}

_SCENARIO_BENCHMARK_FIELDS: Dict[str, List[str]] = {
    "stock_research_report": ["benchmark"],
    "abnormal_move_analysis": ["benchmark"],
}

_SCENARIO_WINDOW_FIELDS: Dict[str, List[str]] = {
    "abnormal_move_analysis": ["window_start", "window_end"],
    "stock_review": ["review_start", "review_end"],
    "daily_review": ["window_start", "window_end"],
    "theme_discovery": ["window_start", "window_end"],
}

_SCENARIO_REPORT_DATE_FIELDS: Dict[str, List[str]] = {
    "morning_brief": ["report_date"],
    "evening_brief": ["report_date"],
    "daily_review": ["review_business_date", "report_date"],
    "stock_review": ["review_date", "report_date"],
    "stock_research_report": ["date", "report_date"],
}


def _first_present(request: Dict[str, Any], fields: List[str]) -> Optional[Any]:
    for key in fields:
        if request.get(key) is not None:
            return request.get(key)
    return None


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _next_day_iso(day: str) -> str:
    from datetime import date, timedelta
    d = date.fromisoformat(str(day))
    return (d + timedelta(days=1)).isoformat() + "T00:00:00+08:00"


def _min_iso(a: str, b: Optional[str]) -> str:
    """取两个 ISO 时间中较早者（aware datetime 比较，避免跨时区字符串序错误）；b 为 None 返回 a。"""
    from research_os.utils.time import parse_iso
    a_dt = parse_iso(a)
    if b is None:
        return a
    return a if a_dt <= parse_iso(b) else b


def _abnormal_window(request: Dict[str, Any]):
    """复用 existing abnormal_move.resolve_window authority（§15）。

    仅当可以确定性证明时返回 (window_start, window_end)；否则 None（fail closed，
    不调用 wall-clock 假装历史窗口）。
    """
    analysis_date = request.get("analysis_date") or request.get("date")
    window_start = request.get("window_start")
    window_end = request.get("window_end")
    if window_start and window_end:
        return window_start, window_end
    if not analysis_date:
        return None
    try:
        from research_os.abnormal_move.window import resolve_window
        from research_os.abnormal_move.market_data_loader import TradingCalendar
        calendar = TradingCalendar()  # 确定性日历（无网络）
        resolved = resolve_window(str(analysis_date), calendar)
        return resolved.window_start.isoformat(), resolved.window_end.isoformat()
    except Exception:  # noqa: BLE001
        return None


class NormalizedRequestContextAdapter:
    """scenario → canonical context（确定性机械映射，零猜测）。"""

    def extract(self, scenario: str, normalized_request: Dict[str, Any]) -> CanonicalRequestContext:
        ctx = CanonicalRequestContext(scenario=scenario)

        # subject
        subject_value = _first_present(normalized_request, _SCENARIO_SUBJECT_FIELDS.get(scenario, []))
        if subject_value is not None:
            ctx.subject_entity_ids = _as_str_list(subject_value)
        # first_coverage 正式契约还包含 security_entity_id（并入 subject 集合）
        if scenario == "first_coverage":
            security = normalized_request.get("security_entity_id")
            if security and security not in ctx.subject_entity_ids:
                ctx.subject_entity_ids.append(str(security))

        # benchmark / peers / industry
        bm = _first_present(normalized_request, _SCENARIO_BENCHMARK_FIELDS.get(scenario, []))
        if bm is not None:
            ctx.benchmark_entity_ids = _as_str_list(bm)
        peers = _first_present(normalized_request, _SCENARIO_PEER_FIELDS.get(scenario, []))
        if peers is not None:
            ctx.peer_entity_ids = _as_str_list(peers)
        ind = _first_present(normalized_request, _SCENARIO_INDUSTRY_FIELDS.get(scenario, []))
        if ind is not None:
            ctx.industry_ids = _as_str_list(ind)

        # R2-02：统一 Scenario Time Context（按 scenario 复用既有业务权威，禁止第二套规则）
        self._resolve_time_context(ctx, scenario, normalized_request)

        # report_date
        rd = _first_present(normalized_request, _SCENARIO_REPORT_DATE_FIELDS.get(scenario, []))
        if rd is not None:
            ctx.report_date = str(rd)

        # request material refs（用户上传/指定文件）
        for key in ("financial_files", "documents", "manual_files",
                    "request_document_refs", "material_refs"):
            val = normalized_request.get(key)
            if val:
                ctx.request_material_refs.extend(_as_str_list(val))
        # R3-05：prior-run 专用字段（DailyReview 真实契约，§38）
        ctx.previous_run_ids = _as_str_list(normalized_request.get("previous_run_ids"))
        ctx.previous_report_paths = _as_str_list(normalized_request.get("previous_report_paths"))
        pc = normalized_request.get("previous_cutoff")
        ctx.previous_cutoff = str(pc) if pc is not None else None
        return ctx

    # ---------- R2-02：Scenario Time Context ----------

    def _resolve_time_context(self, ctx: CanonicalRequestContext, scenario: str,
                              request: Dict[str, Any]) -> None:
        """按 scenario 的正式时间权威解析窗口；as_of_snapshot requirement 不需要窗口。

        显式窗口只用于 time_policy=explicit_request_window 的 requirement（checker 真正过滤）。
        """
        # 显式窗口（原样保留；abnormal 优先显式，其次 resolve_window）
        ws = request.get("window_start")
        we = request.get("window_end")

        if scenario == "daily_review":
            # DailyReview 既有权威：day_start = review_business_date 00:00；day_end = 次日 00:00；
            # effective_end = min(day_end, as_of)；窗口 [start, end)
            day = request.get("review_business_date") or request.get("report_date")
            if day:
                ctx.explicit_window_start = f"{day}T00:00:00+08:00"
                day_end = _next_day_iso(day)
                as_of = request.get("as_of")
                ctx.explicit_window_end = _min_iso(day_end, as_of) if as_of else day_end
            return
        if scenario == "stock_review":
            # StockReview 既有权威：start = review_start 00:00；raw_end = review_end 23:59:59；
            # effective_end = min(raw_end, as_of)
            rs = request.get("review_start")
            re_ = request.get("review_end")
            if rs:
                ctx.explicit_window_start = f"{rs}T00:00:00+08:00"
            if re_:
                raw_end = f"{re_}T23:59:59+08:00"
                as_of = request.get("as_of")
                ctx.explicit_window_end = _min_iso(raw_end, as_of) if as_of else raw_end
            return
        if scenario == "abnormal_move_analysis":
            # 优先级：显式 window → existing abnormal_move.resolve_window authority → unresolved
            if ws and we:
                ctx.explicit_window_start = ws
                ctx.explicit_window_end = we
                return
            resolved = _abnormal_window(request)
            if resolved is not None:
                ctx.explicit_window_start, ctx.explicit_window_end = resolved
            # 无法证明的 window 保持 None（fail closed，不调用 wall-clock 假装历史窗口）
            return
        # 其他场景：显式窗口原样（若无显式 → None；as_of_snapshot 不需要窗口）
        ctx.explicit_window_start = ws
        ctx.explicit_window_end = we
