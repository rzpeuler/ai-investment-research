"""Immutable central chat scenario registry."""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from research_os.dashboard import request_builder as builders
from research_os.dashboard import deterministic_drafts as drafts
from research_os.orchestrator.runners import DEFAULT_SCENARIOS


@dataclass(frozen=True)
class ScenarioChatSpec:
    scenario_id: str
    chat_input_schema_name: str
    target_policy: str
    time_policy: str
    completion_policy: tuple[str, ...]
    minimal_request_builder: Callable
    deterministic_draft_builder: Callable[[str], dict]


_SPECS = {
    "morning_brief": ScenarioChatSpec("morning_brief", "chat_morning_brief_input", "optional", "report_date_optional", (), builders.build_morning, drafts.brief),
    "abnormal_move_analysis": ScenarioChatSpec("abnormal_move_analysis", "chat_abnormal_move_analysis_input", "entity_required", "optional", ("target",), builders.build_abnormal, drafts.abnormal),
    "stock_research_report": ScenarioChatSpec("stock_research_report", "chat_stock_research_report_input", "entity_required", "optional", ("target",), builders.build_equity, drafts.stock),
    "evening_brief": ScenarioChatSpec("evening_brief", "chat_evening_brief_input", "optional", "report_date_optional", (), builders.build_evening, drafts.brief),
    "daily_review": ScenarioChatSpec("daily_review", "chat_daily_review_input", "optional", "optional", (), builders.build_daily, drafts.daily),
    "stock_review": ScenarioChatSpec("stock_review", "chat_stock_review_input", "entity_required", "optional", ("target",), builders.build_stock_review, drafts.stock),
    "industry_research": ScenarioChatSpec("industry_research", "chat_industry_research_input", "industry_required", "system_as_of", ("industry",), builders.build_industry, drafts.complex_requires_llm),
    "theme_discovery": ScenarioChatSpec("theme_discovery", "chat_theme_discovery_input", "optional", "system_as_of", ("theme_or_industry",), builders.build_theme, drafts.complex_requires_llm),
    "earnings_expectation": ScenarioChatSpec("earnings_expectation", "chat_earnings_expectation_input", "profile_required", "system_as_of", ("target", "forecast_period", "assumption"), builders.build_earnings, drafts.complex_requires_llm),
    "first_coverage": ScenarioChatSpec("first_coverage", "chat_first_coverage_input", "profile_and_industry_required", "system_as_of", ("target", "industry"), builders.build_first_coverage, drafts.complex_requires_llm),
}
CHAT_SCENARIO_SPECS = MappingProxyType({scenario: _SPECS[scenario] for scenario in DEFAULT_SCENARIOS})
