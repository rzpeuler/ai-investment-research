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

        # window（显式请求窗口；scenario_window 由 Resolver 复用 BriefWindowPolicy）
        ws = _first_present(normalized_request, [f for f in _SCENARIO_WINDOW_FIELDS.get(scenario, []) if f.startswith("window_start")])
        we = _first_present(normalized_request, [f for f in _SCENARIO_WINDOW_FIELDS.get(scenario, []) if f.startswith("window_end")])
        if ws is None:
            ws = normalized_request.get("window_start")
        if we is None:
            we = normalized_request.get("window_end")
        if scenario == "stock_review":
            # 正式契约 review_start/review_end
            ws = normalized_request.get("review_start") or ws
            we = normalized_request.get("review_end") or we
        ctx.explicit_window_start = ws
        ctx.explicit_window_end = we

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
        return ctx
