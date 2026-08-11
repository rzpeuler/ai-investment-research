"""Immutable central chat scenario registry."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Callable

from research_os.dashboard import request_builder as builders
from research_os.dashboard import deterministic_drafts as drafts
from research_os.orchestrator.runners import DEFAULT_SCENARIOS


class TargetPolicy(str, Enum):
    OPTIONAL = "optional"
    ENTITY_REQUIRED = "entity_required"
    INDUSTRY_REQUIRED = "industry_required"
    PROFILE_REQUIRED = "profile_required"
    PROFILE_AND_INDUSTRY_REQUIRED = "profile_and_industry_required"


class TimePolicy(str, Enum):
    OPTIONAL = "optional"
    REPORT_DATE_OPTIONAL = "report_date_optional"
    SYSTEM_AS_OF = "system_as_of"


class CompletionRequirement(str, Enum):
    TARGET = "target"
    INDUSTRY = "industry"
    THEME_OR_INDUSTRY = "theme_or_industry"
    FORECAST_PERIOD = "forecast_period"
    ASSUMPTION = "assumption"


class IndustryPolicy(str, Enum):
    IGNORE_PROFILE = "ignore_profile"
    EXPLICIT = "explicit"
    EXPLICIT_OR_PROFILE = "explicit_or_profile"


@dataclass(frozen=True)
class ScenarioChatSpec:
    scenario_id: str
    display_label: str
    chat_input_schema_name: str
    target_policy: TargetPolicy
    time_policy: TimePolicy
    completion_policy: tuple[CompletionRequirement, ...]
    minimal_request_builder: Callable
    deterministic_draft_builder: Callable[[str], dict]
    industry_policy: IndustryPolicy = IndustryPolicy.IGNORE_PROFILE


_SPECS = {
    "morning_brief": ScenarioChatSpec("morning_brief", "每日晨报", "chat_morning_brief_input", TargetPolicy.OPTIONAL, TimePolicy.REPORT_DATE_OPTIONAL, (), builders.build_morning, drafts.brief),
    "abnormal_move_analysis": ScenarioChatSpec("abnormal_move_analysis", "异动分析", "chat_abnormal_move_analysis_input", TargetPolicy.ENTITY_REQUIRED, TimePolicy.OPTIONAL, (CompletionRequirement.TARGET,), builders.build_abnormal, drafts.abnormal),
    "stock_research_report": ScenarioChatSpec("stock_research_report", "个股研报", "chat_stock_research_report_input", TargetPolicy.ENTITY_REQUIRED, TimePolicy.OPTIONAL, (CompletionRequirement.TARGET,), builders.build_equity, drafts.stock),
    "evening_brief": ScenarioChatSpec("evening_brief", "每日晚报", "chat_evening_brief_input", TargetPolicy.OPTIONAL, TimePolicy.REPORT_DATE_OPTIONAL, (), builders.build_evening, drafts.brief),
    "daily_review": ScenarioChatSpec("daily_review", "每日复盘", "chat_daily_review_input", TargetPolicy.OPTIONAL, TimePolicy.OPTIONAL, (), builders.build_daily, drafts.daily),
    "stock_review": ScenarioChatSpec("stock_review", "个股复盘", "chat_stock_review_input", TargetPolicy.ENTITY_REQUIRED, TimePolicy.OPTIONAL, (CompletionRequirement.TARGET,), builders.build_stock_review, drafts.stock),
    "industry_research": ScenarioChatSpec("industry_research", "行业研究", "chat_industry_research_input", TargetPolicy.INDUSTRY_REQUIRED, TimePolicy.SYSTEM_AS_OF, (CompletionRequirement.INDUSTRY,), builders.build_industry, drafts.complex_requires_llm, IndustryPolicy.EXPLICIT),
    "theme_discovery": ScenarioChatSpec("theme_discovery", "主题发现", "chat_theme_discovery_input", TargetPolicy.OPTIONAL, TimePolicy.SYSTEM_AS_OF, (CompletionRequirement.THEME_OR_INDUSTRY,), builders.build_theme, drafts.complex_requires_llm, IndustryPolicy.EXPLICIT),
    "earnings_expectation": ScenarioChatSpec("earnings_expectation", "财报预期", "chat_earnings_expectation_input", TargetPolicy.PROFILE_REQUIRED, TimePolicy.SYSTEM_AS_OF, (CompletionRequirement.TARGET, CompletionRequirement.FORECAST_PERIOD, CompletionRequirement.ASSUMPTION), builders.build_earnings, drafts.complex_requires_llm),
    "first_coverage": ScenarioChatSpec("first_coverage", "首次覆盖", "chat_first_coverage_input", TargetPolicy.PROFILE_AND_INDUSTRY_REQUIRED, TimePolicy.SYSTEM_AS_OF, (CompletionRequirement.TARGET, CompletionRequirement.INDUSTRY), builders.build_first_coverage, drafts.complex_requires_llm, IndustryPolicy.EXPLICIT_OR_PROFILE),
}
CHAT_SCENARIO_SPECS = MappingProxyType({scenario: _SPECS[scenario] for scenario in DEFAULT_SCENARIOS})
