from __future__ import annotations

from datetime import datetime

import pytest

from research_os.dashboard.models import IndustryResult, ResolutionResult, TemporalResult
from research_os.dashboard.scenario_specs import CHAT_SCENARIO_SPECS
from research_os.llm.client import LlmClient
from research_os.llm.provider import FakeLlmProvider
from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES


NOW = datetime(2026, 8, 10, 9, 30)
TARGET = ResolutionResult(
    status="resolved", entity="600519.SH", symbol="600519.SH",
    company_entity_id="company:maotai", security_entity_id="security:600519.SH",
    company_name="贵州茅台", industry_ids=("industry:liquor",),
)
TEMPORAL = TemporalResult(
    status="resolved", start_date="2026-08-04", end_date="2026-08-10",
    as_of="2026-08-10T09:30:00",
)
INDUSTRY = IndustryResult(status="resolved", industry_id="industry:liquor", industry_name="白酒")


def _draft(scenario):
    base = {"depth_hint": None}
    if scenario == "theme_discovery":
        base["theme_keywords"] = ["消费复苏"]
    if scenario == "earnings_expectation":
        base.update({
            "forecast_period_expression": "FY2027-FY2028",
            "explicit_assumptions": [{
                "statement": "收入增长10%", "metric_expression": "收入增长率",
                "value_expression": "10%", "period_expression": "FY2027",
            }],
        })
    return base


@pytest.mark.parametrize("runner_type", DEFAULT_RUNNER_TYPES)
def test_each_scenario_builder_emits_request_accepted_by_runner(runner_type):
    runner = runner_type()
    spec = CHAT_SCENARIO_SPECS[runner.scenario]
    request = spec.minimal_request_builder(
        _draft(runner.scenario), TARGET, TEMPORAL, INDUSTRY, NOW, False
    )
    normalized = runner.validate_request(request)
    assert isinstance(normalized, dict)


def test_only_user_explicit_time_is_sent_to_default_authority_scenarios():
    omitted = TemporalResult(status="omitted")
    for scenario in ("morning_brief", "evening_brief", "daily_review"):
        request = CHAT_SCENARIO_SPECS[scenario].minimal_request_builder(
            {}, None, omitted, None, NOW, False
        )
        assert not ({"report_date", "review_business_date", "as_of"} & set(request))


def test_earnings_known_at_and_as_of_are_same_turn_reference_time():
    request = CHAT_SCENARIO_SPECS["earnings_expectation"].minimal_request_builder(
        _draft("earnings_expectation"), TARGET, TemporalResult(status="omitted"), None, NOW, False
    )
    assert request["as_of"] == "2026-08-10T09:30:00"
    assert request["assumptions"][0]["known_at"] == request["as_of"]


def test_chat_stage_budget_blocks_retries_and_pro_after_invalid_schema():
    provider = FakeLlmProvider(behavior=lambda request, schema: {
        "ok": True, "output": {"unexpected": True}, "model_id": "fake",
    })
    client = LlmClient(provider=provider, configured=True)
    from research_os.dashboard.schema_extractor import ChatSchemaExtractor
    result = ChatSchemaExtractor(client).extract(
        "做贵州茅台复盘", CHAT_SCENARIO_SPECS["stock_review"]
    )
    assert result.status == "clarification"
    assert len(provider.calls) == 1
    assert provider.calls[0].requested_model_class == "flash"


def test_valid_schema_hallucinated_target_is_rejected_before_resolver():
    output = {
        "company_mentions": ["贵州茅台"], "temporal_expression": None,
        "research_question": None, "research_focus": [], "depth_hint": None,
        "complete": True, "clarification_question": None,
    }
    provider = FakeLlmProvider(behavior=lambda request, schema: {
        "ok": True, "output": output, "model_id": "fake",
    })
    client = LlmClient(provider=provider, configured=True)
    from research_os.dashboard.schema_extractor import ChatSchemaExtractor
    result = ChatSchemaExtractor(client).extract(
        "帮我复盘这家公司", CHAT_SCENARIO_SPECS["stock_review"]
    )
    assert result.status == "clarification"
    assert len(provider.calls) == 1


def test_hallucinated_assumption_companion_fields_are_rejected():
    output = {
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "FY2027",
        "metric_expressions": ["收入"], "scenario_expressions": [],
        "explicit_assumptions": [{
            "statement": "收入增长10%", "metric_expression": "利润率",
            "value_expression": "50%", "period_expression": "FY2027",
        }],
        "complete": True, "clarification_question": None,
    }
    provider = FakeLlmProvider(behavior=lambda request, schema: {
        "ok": True, "output": output, "model_id": "fake",
    })
    client = LlmClient(provider=provider, configured=True)
    from research_os.dashboard.schema_extractor import ChatSchemaExtractor
    result = ChatSchemaExtractor(client).extract(
        "贵州茅台FY2027收入增长10%", CHAT_SCENARIO_SPECS["earnings_expectation"]
    )
    assert result.status == "clarification"
    assert len(provider.calls) == 1


def test_hallucinated_theme_keyword_is_rejected():
    output = {
        "theme_keywords": ["机器人"], "industry_mentions": [],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }
    provider = FakeLlmProvider(behavior=lambda request, schema: {
        "ok": True, "output": output, "model_id": "fake",
    })
    from research_os.dashboard.schema_extractor import ChatSchemaExtractor
    result = ChatSchemaExtractor(LlmClient(provider=provider, configured=True)).extract(
        "挖掘低空经济主题", CHAT_SCENARIO_SPECS["theme_discovery"]
    )
    assert result.status == "clarification"


@pytest.mark.parametrize(("phrase", "depth"), [
    ("快速分析", "fast"), ("标准分析", "standard"), ("做深度分析", "deep"),
    ("fast analysis", "fast"), ("standard analysis", "standard"), ("deep analysis", "deep"),
])
def test_depth_hint_supports_anchored_chinese_and_english_mapping(phrase, depth):
    output = {
        "company_mentions": ["贵州茅台"], "temporal_expression": None,
        "research_question": None, "research_focus": [], "depth_hint": depth,
        "complete": True, "clarification_question": None,
    }
    provider = FakeLlmProvider(behavior=lambda request, schema: {
        "ok": True, "output": output, "model_id": "fake",
    })
    from research_os.dashboard.schema_extractor import ChatSchemaExtractor
    result = ChatSchemaExtractor(LlmClient(provider=provider, configured=True)).extract(
        f"贵州茅台{phrase}", CHAT_SCENARIO_SPECS["stock_review"]
    )
    assert result.status == "resolved"


@pytest.mark.parametrize("runner_type", DEFAULT_RUNNER_TYPES)
def test_classification_only_research_focus_never_changes_minimal_request(runner_type):
    runner = runner_type()
    spec = CHAT_SCENARIO_SPECS[runner.scenario]
    base = _draft(runner.scenario)
    classified = {**base, "research_focus": ["模型分类标签"]}
    assert spec.minimal_request_builder(base, TARGET, TEMPORAL, INDUSTRY, NOW, False) == \
           spec.minimal_request_builder(classified, TARGET, TEMPORAL, INDUSTRY, NOW, False)
