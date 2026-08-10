from __future__ import annotations

from datetime import datetime
from types import MappingProxyType

import pytest

from research_os.dashboard.models import ChatRequest
from research_os.dashboard.industry_resolver import IndustryResolver
from research_os.dashboard.scenario_specs import (
    CHAT_SCENARIO_SPECS, CompletionRequirement, IndustryPolicy, TargetPolicy, TimePolicy,
)
from research_os.dashboard.safety import safe_llm_clarification
from research_os.dashboard.target_resolver import ResearchTargetResolver
from research_os.dashboard.temporal_resolver import TemporalResolver
from research_os.orchestrator.runners import DEFAULT_SCENARIOS
from research_os.storage import Database


NOW = datetime(2026, 8, 10, 9, 30, 0)


def _profile_db() -> Database:
    from research_os.models import CompanyProfile, FormerName, SecurityProfile

    db = Database(":memory:")
    db.initialize()
    common = {"created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}
    db.upsert(CompanyProfile(
        company_profile_id="cp1", entity_id="company:maotai", canonical_name="贵州茅台",
        industry_ids=["industry:liquor"], fiscal_year_end="12-31",
        reporting_currency="CNY", ownership_type="state_owned", valid_from="2001-01-01",
        **common,
    ))
    db.upsert(SecurityProfile(
        security_profile_id="sp1", security_entity_id="security:600519.SH",
        company_entity_id="company:maotai", symbol="600519.SH", exchange="SH",
        board="main", security_type="common_share", listing_date="2001-08-27",
        currency="CNY", share_class="A", current_name="贵州茅台",
        former_names=[FormerName(name="茅台股份", valid_from="2001-08-27")], **common,
    ))
    return db


def test_scenario_specs_are_immutable_and_exactly_cover_runtime_scenarios():
    assert isinstance(CHAT_SCENARIO_SPECS, MappingProxyType)
    assert tuple(CHAT_SCENARIO_SPECS) == DEFAULT_SCENARIOS
    with pytest.raises(TypeError):
        CHAT_SCENARIO_SPECS["x"] = object()  # type: ignore[index]
    assert all(spec.display_label.strip() for spec in CHAT_SCENARIO_SPECS.values())


def test_target_resolver_full_symbol_entity_only_and_profile_authority():
    db = _profile_db()
    resolver = ResearchTargetResolver(db)
    direct = resolver.resolve(["000001.SZ"], "stock_review")
    assert direct.status == "resolved" and direct.entity == "000001.SZ"
    authoritative = resolver.resolve(["茅台股份"], "first_coverage")
    assert authoritative.status == "resolved"
    assert authoritative.company_entity_id == "company:maotai"
    assert authoritative.security_entity_id == "security:600519.SH"
    db.close()


def test_target_resolver_never_guesses_exchange_for_bare_code():
    db = _profile_db()
    result = ResearchTargetResolver(db).resolve(["000001"], "stock_research_report")
    assert result.status == "clarification"
    assert result.entity is None
    db.close()


def test_target_resolver_reports_authority_failure_distinct_from_no_match():
    class BrokenDb:
        def query(self, sql):
            raise RuntimeError("database unavailable")
    assert ResearchTargetResolver(BrokenDb()).resolve(["贵州茅台"], "stock_review").status == "failure"


def test_target_resolver_uses_one_authoritative_snapshot_per_resolution():
    db = _profile_db()
    resolver = ResearchTargetResolver(db)
    original = resolver._profiles
    calls = 0

    def counted_profiles():
        nonlocal calls
        calls += 1
        return original()

    resolver._profiles = counted_profiles
    result = resolver.resolve(["贵州茅台"], "first_coverage")
    assert result.status == "resolved"
    assert calls == 1
    db.close()


def test_scenario_policy_fields_are_typed_enums():
    for spec in CHAT_SCENARIO_SPECS.values():
        assert isinstance(spec.target_policy, TargetPolicy)
        assert isinstance(spec.time_policy, TimePolicy)
        assert isinstance(spec.industry_policy, IndustryPolicy)
        assert all(isinstance(item, CompletionRequirement) for item in spec.completion_policy)


@pytest.mark.parametrize("unsafe", [
    "请提供目标价", "需要买卖建议吗", "给出增减持建议", "需要仓位建议吗",
    "请确认交易建议", "这只可以买", "现在上车", "需要荐股", "生成交易信号",
    "你要买还是卖？", "Do you want stock picks?", "Should I provide trading advice?",
    "Would you buy Tesla?",
])
def test_llm_clarification_output_policy_replaces_forbidden_language(unsafe):
    fallback = "请补充研究场景所需的信息。"
    assert safe_llm_clarification(unsafe, fallback) == fallback


@pytest.mark.parametrize(
    ("text", "start", "end"),
    [
        ("今天", "2026-08-10", "2026-08-10"),
        ("昨天", "2026-08-09", "2026-08-09"),
        ("最近7天", "2026-08-04", "2026-08-10"),
        ("本周", "2026-08-10", "2026-08-10"),
        ("本月", "2026-08-01", "2026-08-10"),
        ("2026-07-31", "2026-07-31", "2026-07-31"),
        ("2026年7月31日", "2026-07-31", "2026-07-31"),
    ],
)
def test_temporal_resolver_supported_expressions(text, start, end):
    result = TemporalResolver().resolve(text, NOW)
    assert result.status == "resolved"
    assert result.start_date == start and result.end_date == end


def test_temporal_resolver_omits_when_user_did_not_express_time():
    assert TemporalResolver().resolve(None, NOW).status == "omitted"


def test_historical_explicit_date_derives_end_of_day_as_of_not_future_knowledge():
    result = TemporalResolver().resolve("2026-07-31", NOW)
    assert result.as_of == "2026-07-31T23:59:59"


def test_chat_request_requires_message_and_keeps_switches_independent():
    request = ChatRequest(message="今天晨报", llm_enabled=False, research_live=True)
    assert request.llm_enabled is False and request.research_live is True


def test_industry_resolver_uses_only_latest_active_approved_graph_authority():
    db = Database(":memory:"); db.initialize()
    db._conn.execute(
        "INSERT INTO graph_nodes (node_id,version,payload,node_type,name,status,review_status,origin_kind,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        ("industry:liquor", 1, "{}", "Industry", "白酒", "active", "approved", "governance_seed", "2026-01-01T00:00:00"),
    )
    result = IndustryResolver(db).resolve([" 白 酒 "])
    assert result.status == "resolved" and result.industry_id == "industry:liquor"
    db.close()


def test_industry_resolver_refuses_ambiguous_authoritative_names():
    db = Database(":memory:"); db.initialize()
    for node_id in ("industry:a", "industry:b"):
        db._conn.execute(
            "INSERT INTO graph_nodes (node_id,version,payload,node_type,name,status,review_status,origin_kind,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (node_id, 1, "{}", "Industry", "同名行业", "active", "approved", "governance_seed", "2026-01-01T00:00:00"),
        )
    assert IndustryResolver(db).resolve(["同名行业"]).status == "clarification"
    db.close()
