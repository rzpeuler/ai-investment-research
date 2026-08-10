"""Scenario-specific minimal public request builders."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Any, Dict, Optional

from research_os.dashboard.models import IndustryResult, ResolutionResult, TemporalResult
from research_os.dashboard.system_default_resolver import SystemDefaultResolver


class ClarificationRequired(ValueError):
    """The user must provide authority-safe missing information."""


def _depth(draft: dict, request: dict) -> None:
    if draft.get("depth_hint"):
        request["depth"] = draft["depth_hint"]


def _live(request: dict, research_live: bool) -> None:
    SystemDefaultResolver.add_research_live(request, research_live)


def build_morning(draft, target, temporal, industry, reference_now, research_live):
    request: Dict[str, Any] = {}
    if temporal.status == "resolved": request["report_date"] = temporal.end_date
    _live(request, research_live)
    return request


def build_evening(draft, target, temporal, industry, reference_now, research_live):
    return build_morning(draft, target, temporal, industry, reference_now, research_live)


def build_daily(draft, target, temporal, industry, reference_now, research_live):
    request: Dict[str, Any] = {}
    if temporal.status == "resolved": request["review_business_date"] = temporal.end_date
    return request


def _require_target(target: Optional[ResolutionResult]) -> ResolutionResult:
    if target is None or target.status != "resolved":
        raise ClarificationRequired((target.message if target else "请提供唯一研究目标。"))
    return target


def build_abnormal(draft, target, temporal, industry, reference_now, research_live):
    target = _require_target(target)
    request = {"entity_id": target.entity}
    if temporal.status == "resolved":
        request.update({"analysis_date": temporal.end_date, "as_of": temporal.as_of})
    return request


def build_equity(draft, target, temporal, industry, reference_now, research_live):
    target = _require_target(target)
    request = {"entity": target.entity}
    if temporal.status == "resolved": request.update({"date": temporal.end_date, "as_of": temporal.as_of})
    _depth(draft, request); _live(request, research_live)
    return request


def build_stock_review(draft, target, temporal, industry, reference_now, research_live):
    target = _require_target(target)
    request = {"entity": target.entity}
    if temporal.status == "resolved":
        request.update({"review_start": temporal.start_date, "review_end": temporal.end_date, "as_of": temporal.as_of})
    _depth(draft, request)
    return request


def _require_industry(industry: Optional[IndustryResult]) -> IndustryResult:
    if industry is None or industry.status != "resolved":
        raise ClarificationRequired((industry.message if industry else "请提供唯一行业。"))
    return industry


def build_industry(draft, target, temporal, industry, reference_now, research_live):
    industry = _require_industry(industry)
    request = {
        "industry_id": industry.industry_id, "industry_name": industry.industry_name,
        "as_of": SystemDefaultResolver(reference_now).required_as_of(temporal),
    }
    _depth(draft, request); _live(request, research_live)
    return request


def build_theme(draft, target, temporal, industry, reference_now, research_live):
    request: Dict[str, Any] = {
        "keywords": list(draft.get("theme_keywords") or []),
        "industry_ids": [industry.industry_id] if industry and industry.status == "resolved" else [],
        "as_of": SystemDefaultResolver(reference_now).required_as_of(temporal),
    }
    if not request["keywords"] and not request["industry_ids"]:
        raise ClarificationRequired("请提供至少一个主题关键词或唯一行业。")
    _depth(draft, request); _live(request, research_live)
    return request


_FORECAST = re.compile(r"(?:FY)?(20\d{2})(?:\s*[-至到]\s*(?:FY)?(20\d{2}))?")


def _forecast_period(expression: Optional[str]) -> dict:
    match = _FORECAST.search(expression or "")
    if not match:
        raise ClarificationRequired("请明确预测期间，例如 2027年或 FY2027-FY2029。")
    start_year = int(match.group(1)); end_year = int(match.group(2) or start_year)
    if end_year < start_year or end_year - start_year > 10:
        raise ClarificationRequired("预测期间无效或跨度过长，请重新明确。")
    return {
        "start": f"{start_year}-01-01", "end": f"{end_year}-12-31",
        "periods": [f"FY{year}" for year in range(start_year, end_year + 1)],
    }


_VALUE = re.compile(r"(-?\d+(?:\.\d+)?)\s*(%|亿元|万元|元|倍|个|万台|台)?")


def _assumptions(items: list, known_at: str, forecast: dict) -> list[dict]:
    result = []
    for item in items:
        expression = item.get("value_expression") or item.get("statement", "")
        match = _VALUE.search(expression)
        if not match:
            raise ClarificationRequired("每条假设都需要明确的数值与口径。")
        result.append({
            "driver": item.get("metric_expression") or item.get("statement"),
            "value": match.group(1), "unit": match.group(2) or "unspecified",
            "period": item.get("period_expression") or forecast["periods"][0],
            "source_type": "user_input", "invalidates_when": "用户撤回或更新该显式假设",
            "known_at": known_at,
        })
    if not result:
        raise ClarificationRequired("请至少提供一条带明确数值的用户假设。")
    return result


def build_earnings(draft, target, temporal, industry, reference_now, research_live):
    target = _require_target(target)
    if not target.company_entity_id:
        raise ClarificationRequired("未找到权威公司主体画像。")
    forecast = _forecast_period(draft.get("forecast_period_expression"))
    as_of = SystemDefaultResolver(reference_now).required_as_of(temporal)
    request = {
        "company_entity_id": target.company_entity_id, "as_of": as_of,
        "forecast_period": forecast,
        "assumptions": _assumptions(list(draft.get("explicit_assumptions") or []), as_of, forecast),
    }
    _live(request, research_live)
    return request


def build_first_coverage(draft, target, temporal, industry, reference_now, research_live):
    target = _require_target(target); industry = _require_industry(industry)
    if not target.company_entity_id or not target.security_entity_id:
        raise ClarificationRequired("首次覆盖需要权威公司与证券画像。")
    request = {
        "company_entity_id": target.company_entity_id,
        "security_entity_id": target.security_entity_id,
        "industry_id": industry.industry_id, "industry_name": industry.industry_name,
        "as_of": SystemDefaultResolver(reference_now).required_as_of(temporal),
    }
    _depth(draft, request); _live(request, research_live)
    return request
