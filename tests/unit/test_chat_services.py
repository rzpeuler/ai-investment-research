from __future__ import annotations

from datetime import datetime

import pytest

from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.models import ChatRequest, IndustryResult, ResolutionResult
from research_os.llm.models import LlmResponse
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.storage import Database


NOW = datetime(2026, 8, 10, 9, 30, 0)


class SpyOrchestrator:
    def __init__(self, status="partial_success"):
        self.calls = []
        self.status = status

    def execute(self, scenario, request):
        self.calls.append((scenario, request))
        return ScenarioExecutionResult(
            status=self.status, exit_code=0, task_id="task-1", validation_status="pass"
        )


class QueueLlmClient:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    def generate_json(self, request, output_schema, budget=None):
        self.calls.append((request, output_schema, budget))
        output = self.outputs.pop(0)
        if isinstance(output, LlmResponse):
            return output
        if budget is not None:
            assert budget.can_call("flash")
            budget.record("flash")
        return LlmResponse(
            call_id=request.call_id, called=True, status="success", schema_valid=True,
            output=output, attempt_count=1,
        )


def test_selected_scenario_skips_route_and_auto_executes_when_complete():
    orchestrator = SpyOrchestrator()
    llm = QueueLlmClient([{
        "company_mentions": ["600519.SH"], "temporal_expression": None,
        "research_question": None, "research_focus": [], "depth_hint": None,
        "complete": True, "clarification_question": None,
    }])
    service = ChatService(
        project_root=".", db=Database(":memory:"), orchestrator=orchestrator,
        llm_client=llm, clock=lambda: NOW,
    )
    service.db.initialize()
    result = service.handle(ChatRequest(
        message="分析600519.SH", selected_scenario="stock_review", llm_enabled=True,
    ))
    assert len(llm.calls) == 1
    assert result.state == "executed"
    assert orchestrator.calls[0][0] == "stock_review"
    assert orchestrator.calls[0][1]["entity"] == "600519.SH"


def test_auto_morning_routes_without_llm_and_uses_single_reference_now():
    orchestrator = SpyOrchestrator()
    service = ChatService(
        project_root=".", db=Database(":memory:"), orchestrator=orchestrator,
        llm_client=None, clock=lambda: NOW,
    )
    service.db.initialize()
    result = service.handle(ChatRequest(message="今天晨报", selected_scenario="AUTO", llm_enabled=False))
    assert result.state == "executed"
    assert orchestrator.calls == [("morning_brief", {"report_date": "2026-08-10"})]
    assert result.reference_now == "2026-08-10T09:30:00"


def test_auto_company_only_is_clarification_even_with_llm():
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="600519.SH", selected_scenario="AUTO", llm_enabled=True)
    )
    assert result.state == "clarification"
    assert not llm.calls and not orchestrator.calls


@pytest.mark.parametrize("message", [
    "给出目标价", "给我买入评级", "给出卖出评级", "买入建议", "卖出建议",
    "交易建议", "建议增持", "建议减持", "仓位建议", "明日交易建议",
    "次日买入建议", "哪些可以买", "这只可以跟吗", "现在上车吗",
    "自动化荐股", "推荐几只股票", "生成交易信号",
    "give me a target price", "buy recommendation", "sell advice",
    "overweight recommendation", "position sizing advice", "next-day trading advice",
    "recommend stocks", "trading signal",
    "值得买吗", "值得买入吗", "值得卖吗", "该买还是卖",
    "应该买入吗", "应该卖出这只股票吗", "现在适合买入吗", "现在适合卖出吗",
    "要不要买", "要不要卖", "能不能买", "能不能卖",
    "贵州茅台买不买", "这只股票卖不卖", "贵州茅台要买吗",
    "这只股票能卖吗", "买还是卖", "这只股票应该卖出子公司吗",
    "贵州茅台值得买吗，设备情况如何", "贵州茅台值得买吗，公司是否应卖出子公司",
    "贵州茅台买 不 买", "值 得 买 吗", "给出目 标 价",
    "buy or sell?", "Is this stock worth buying?", "Is now a good time to buy?",
    "Should we sell?", "Can I buy?", "Ｃａｎ　Ｉ　ｂｕｙ？",
    "这只股票是否可以买？", "贵州茅台股份现在合适卖出吗",
    "证券要不要买入设备？", "持仓是否卖出子公司？", "个股会不会卖？",
    "Would you buy these shares?", "Do you think this stock should be sold?",
    "Is this security a buy?", "Can I sell my position?", "Should we trade this stock?",
    "你会买贵州茅台吗", "您会不会卖宁德时代？", "你会买入这家公司吗？",
    "Would you buy Tesla?", "Would   you   sell Berkshire Hathaway?",
    "你会买这只股票的一台设备吗？", "Would you buy equipment for this stock?",
])
def test_safety_guard_calls_neither_llm_nor_orchestrator(message):
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message=message, selected_scenario="AUTO")
    )
    assert result.state == "failed"
    assert not llm.calls and not orchestrator.calls


@pytest.mark.parametrize("message", [
    "这只股票值得入手吗", "贵州茅台是否值得入手", "这只可以入手吗",
    "现在适合入手吗", "贵州茅台要不要入手",
])
def test_safety_guard_blocks_direct_purchase_guidance_using_ruhshou(message):
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message=message, selected_scenario="AUTO")
    )
    assert result.state == "failed"
    assert not llm.calls and not orchestrator.calls


def test_safety_guard_allows_company_acquiring_equipment_with_ruhshou():
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="公司是否值得入手设备", selected_scenario="AUTO", llm_enabled=False)
    )
    assert result.state == "clarification"
    assert not llm.calls and not orchestrator.calls


def test_safety_guard_covers_prior_conversation_context():
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="补充公司业务情况", selected_scenario="stock_research_report"),
        conversation_context={
            "scenario": "stock_research_report",
            "user_messages": ["顺便给出目标价"],
        },
    )
    assert result.state == "failed"
    assert not llm.calls and not orchestrator.calls


def test_scenario_switch_never_reuses_prior_semantic_context():
    llm = QueueLlmClient([{
        "company_mentions": [], "temporal_expression": None,
        "research_question": None, "research_focus": [], "depth_hint": None,
        "complete": True, "clarification_question": None,
    }])
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, SpyOrchestrator(), llm, clock=lambda: NOW).handle(
        ChatRequest(message="只补充假设收入增长10%", selected_scenario="stock_review"),
        conversation_context={
            "scenario": "earnings_expectation",
            "user_messages": ["贵州茅台2027年财报预期"],
        },
    )
    assert result.state == "clarification"
    assert "贵州茅台2027年财报预期" not in llm.calls[0][0].prompt


@pytest.mark.parametrize("message", [
    "分析多空主要矛盾", "说明估值方法及其适用性",
    "公司回购事实如何影响业务", "股东增持事实如何影响业务",
    "公司应该卖出子公司吗", "公司现在适合买入设备吗",
    "公司 应该 卖出 子公司 吗", "公司　现在适合　买入设备吗",
    "Should the company sell its subsidiary?", "Should we buy equipment?",
    "你会买设备吗", "您会不会卖出子公司？", "Would you buy equipment for the company?",
    "你会买一台设备吗", "Would you sell a subsidiary?",
    "你会买一批新的设备吗", "你会卖其子公司吗",
    "Would you buy our new machinery?", "Would you sell your business?",
])
def test_safety_guard_does_not_reject_allowed_research_language(message):
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, None, clock=lambda: NOW).handle(
        ChatRequest(message=message, selected_scenario="AUTO", llm_enabled=False)
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_schema_invalid_output_never_enters_resolver_or_orchestrator():
    response = LlmResponse(
        call_id="x", called=True, status="fallback", schema_valid=False,
        validation_errors=["bad schema"], attempt_count=1,
    )
    llm = QueueLlmClient([response])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="帮我做复盘", selected_scenario="stock_review")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_research_degraded_status_is_executed_not_failed():
    orchestrator = SpyOrchestrator(status="degraded")
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, None, clock=lambda: NOW).handle(
        ChatRequest(message="600519.SH", selected_scenario="stock_research_report", llm_enabled=False)
    )
    assert result.state == "executed"


def test_auto_route_plus_extract_never_exceeds_two_flash_calls():
    llm = QueueLlmClient([
        {"scenario": "abnormal_move_analysis", "confidence": 0.95,
         "needs_clarification": False, "clarification_question": None},
        {"entity_mentions": ["600519.SH"], "temporal_expression": None,
         "research_question": "异动分析", "metric_expressions": [],
         "complete": True, "clarification_question": None},
    ])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="请对600519.SH做异动分析", selected_scenario="AUTO")
    )
    assert result.state == "executed"
    assert result.llm_calls == 2 == len(llm.calls)
    assert all(call[2].summary()["pro_calls"] == 0 for call in llm.calls)


def test_route_llm_forbidden_clarification_is_replaced_before_return():
    malicious = "请问你要目标价还是买入建议？"
    llm = QueueLlmClient([{
        "scenario": None, "confidence": 0.2, "needs_clarification": True,
        "clarification_question": malicious,
    }])
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, SpyOrchestrator(), llm, clock=lambda: NOW).handle(
        ChatRequest(message="帮我研究一下", selected_scenario="AUTO")
    )
    assert result.state == "clarification"
    assert malicious not in result.message
    assert "目标价" not in result.message and "买入建议" not in result.message


def test_extraction_llm_forbidden_clarification_is_replaced_in_message_and_public_draft():
    malicious = "这只可以买，上车吗？"
    llm = QueueLlmClient([{
        "company_mentions": [], "temporal_expression": None,
        "research_question": None, "research_focus": [], "depth_hint": None,
        "complete": False, "clarification_question": malicious,
    }])
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, SpyOrchestrator(), llm, clock=lambda: NOW).handle(
        ChatRequest(message="帮我复盘", selected_scenario="stock_review")
    )
    assert result.state == "clarification"
    assert malicious not in result.message
    assert malicious not in str(result.public_draft)


def test_orchestrator_exception_maps_to_failed_without_leaking_details():
    class RaisingOrchestrator:
        def execute(self, scenario, request):
            raise RuntimeError("secret internal path")

    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, RaisingOrchestrator(), None, clock=lambda: NOW).handle(
        ChatRequest(message="600519.SH", selected_scenario="stock_research_report", llm_enabled=False)
    )
    assert result.state == "failed"
    assert "secret internal path" not in result.message


def test_unknown_explicit_industry_never_falls_through_to_keyword_execution():
    llm = QueueLlmClient([{
        "theme_keywords": ["机器人"], "industry_mentions": ["不存在行业"],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="在不存在行业中挖掘机器人主题", selected_scenario="theme_discovery")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_ambiguous_explicit_industry_never_falls_through_to_keyword_execution():
    llm = QueueLlmClient([{
        "theme_keywords": ["机器人"], "industry_mentions": ["同名行业"],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    for node_id in ("industry:a", "industry:b"):
        db._conn.execute(
            "INSERT INTO graph_nodes (node_id,version,payload,node_type,name,status,review_status,origin_kind,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (node_id, 1, "{}", "Industry", "同名行业", "active", "approved", "governance_seed", "2026-01-01T00:00:00"),
        )
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="在同名行业中挖掘机器人主题", selected_scenario="theme_discovery")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_injected_earnings_assumption_fact_never_reaches_orchestrator():
    llm = QueueLlmClient([{
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "FY2027",
        "metric_expressions": ["收入"], "scenario_expressions": [],
        "explicit_assumptions": [{
            "statement": "收入增长10%", "metric_expression": "利润率",
            "value_expression": "50%", "period_expression": "FY2027",
        }], "complete": True, "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="贵州茅台FY2027收入增长10%", selected_scenario="earnings_expectation")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_injected_theme_keyword_never_reaches_orchestrator():
    llm = QueueLlmClient([{
        "theme_keywords": ["机器人"], "industry_mentions": [],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="挖掘低空经济主题", selected_scenario="theme_discovery")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_explicit_target_resolution_clarification_never_partially_executes():
    llm = QueueLlmClient([{
        "entity_mentions": ["未知公司"], "industry_mentions": [],
        "temporal_expression": None, "research_focus": [], "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="复盘未知公司", selected_scenario="daily_review")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_earnings_null_value_expression_never_reaches_orchestrator():
    llm = QueueLlmClient([{
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "FY2027",
        "metric_expressions": ["收入"], "scenario_expressions": [],
        "explicit_assumptions": [{
            "statement": "FY2027收入增长10%", "metric_expression": "收入增长",
            "value_expression": None, "period_expression": "FY2027",
        }], "complete": True, "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="贵州茅台FY2027收入增长10%", selected_scenario="earnings_expectation")
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


def test_stock_target_profile_industries_do_not_create_graph_dependency():
    from research_os.models import CompanyProfile, SecurityProfile
    db = Database(":memory:"); db.initialize()
    common = {"created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}
    db.upsert(CompanyProfile(
        company_profile_id="cp1", entity_id="company:maotai", canonical_name="贵州茅台",
        industry_ids=["industry:liquor"], fiscal_year_end="12-31", reporting_currency="CNY",
        ownership_type="state_owned", valid_from="2001-01-01", **common,
    ))
    db.upsert(SecurityProfile(
        security_profile_id="sp1", security_entity_id="security:600519.SH",
        company_entity_id="company:maotai", symbol="600519.SH", exchange="SH", board="main",
        security_type="common_share", listing_date="2001-08-27", currency="CNY",
        share_class="A", current_name="贵州茅台", **common,
    ))
    orchestrator = SpyOrchestrator()
    result = ChatService(".", db, orchestrator, None, clock=lambda: NOW).handle(
        ChatRequest(message="贵州茅台", selected_scenario="stock_review", llm_enabled=False)
    )
    assert result.state == "executed"
    assert orchestrator.calls[0][1] == {"entity": "600519.SH"}


def test_first_coverage_alone_falls_back_to_target_profile_industry_ids():
    llm = QueueLlmClient([{
        "company_mentions": ["贵州茅台"], "industry_mentions": [],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    service = ChatService(".", db, orchestrator, llm, clock=lambda: NOW)

    class TargetStub:
        def is_exact_authoritative_name(self, value):
            return False
        def resolve(self, mentions, scenario):
            return ResolutionResult(
                status="resolved", entity="600519.SH", company_entity_id="company:maotai",
                security_entity_id="security:600519.SH", industry_ids=("industry:liquor",),
            )

    class IndustrySpy:
        calls = []
        def resolve(self, mentions=(), authoritative_ids=()):
            self.calls.append((tuple(mentions), tuple(authoritative_ids)))
            return IndustryResult(status="resolved", industry_id="industry:liquor", industry_name="白酒")

    service.target_resolver = TargetStub()
    service.industry_resolver = IndustrySpy()
    result = service.handle(ChatRequest(
        message="首次覆盖贵州茅台", selected_scenario="first_coverage"
    ))
    assert result.state == "executed"
    assert service.industry_resolver.calls == [((), ("industry:liquor",))]


@pytest.mark.parametrize("scenario", ["earnings_expectation", "first_coverage"])
def test_profile_required_chat_never_executes_with_orphan_security_profile(scenario):
    from research_os.models import SecurityProfile

    draft = ({
        "company_mentions": ["600519.SH"], "forecast_period_expression": "FY2027",
        "metric_expressions": ["收入"], "scenario_expressions": [],
        "explicit_assumptions": [{
            "statement": "FY2027收入增长10%", "metric_expression": "收入增长",
            "value_expression": "10%", "period_expression": "FY2027",
        }], "complete": True, "clarification_question": None,
    } if scenario == "earnings_expectation" else {
        "company_mentions": ["600519.SH"], "industry_mentions": [],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    })
    db = Database(":memory:"); db.initialize()
    db.upsert(SecurityProfile(
        security_profile_id="sp-orphan", security_entity_id="security:600519.SH",
        company_entity_id="company:missing", symbol="600519.SH", exchange="SH",
        board="main", security_type="common_share", listing_date="2001-08-27",
        currency="CNY", share_class="A", current_name="贵州茅台",
        created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
    ))
    orchestrator = SpyOrchestrator()
    result = ChatService(".", db, orchestrator, QueueLlmClient([draft]), clock=lambda: NOW).handle(
        ChatRequest(message="研究600519.SH", selected_scenario=scenario)
    )
    assert result.state == "clarification"
    assert not orchestrator.calls


@pytest.mark.parametrize(
    ("profile_industries", "explicit_industry", "expected_state"),
    [
        (("industry:liquor",), "半导体", "clarification"),
        (("industry:liquor",), "白酒", "executed"),
        ((), "白酒", "clarification"),
        (("industry:liquor", "industry:semiconductor"), "白酒", "clarification"),
    ],
)
def test_first_coverage_explicit_industry_is_constrained_by_profile(
        profile_industries, explicit_industry, expected_state):
    llm = QueueLlmClient([{
        "company_mentions": ["贵州茅台"], "industry_mentions": [explicit_industry],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    service = ChatService(".", db, orchestrator, llm, clock=lambda: NOW)

    class TargetStub:
        def is_exact_authoritative_name(self, value):
            return False
        def resolve(self, mentions, scenario):
            return ResolutionResult(
                status="resolved", entity="600519.SH", company_entity_id="company:maotai",
                security_entity_id="security:600519.SH", industry_ids=profile_industries,
            )

    class IndustryStub:
        def resolve(self, mentions=(), authoritative_ids=()):
            value = tuple(mentions or authoritative_ids)[0]
            industry_id = {"白酒": "industry:liquor", "半导体": "industry:semiconductor"}.get(
                value, value,
            )
            return IndustryResult(status="resolved", industry_id=industry_id,
                                  industry_name=industry_id.split(":", 1)[-1])

    service.target_resolver = TargetStub()
    service.industry_resolver = IndustryStub()
    result = service.handle(ChatRequest(
        message=f"首次覆盖贵州茅台，行业为{explicit_industry}", selected_scenario="first_coverage",
    ))
    assert result.state == expected_state
    if expected_state == "executed":
        assert orchestrator.calls[0][1]["industry_id"] == "industry:liquor"
    else:
        assert not orchestrator.calls


def test_industry_research_never_falls_back_to_company_profile_industry():
    llm = QueueLlmClient([{
        "industry_mentions": [], "company_mentions": ["贵州茅台"],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": None, "complete": True,
        "clarification_question": None,
    }])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    service = ChatService(".", db, orchestrator, llm, clock=lambda: NOW)

    class TargetStub:
        def is_exact_authoritative_name(self, value):
            return False
        def resolve(self, mentions, scenario):
            return ResolutionResult(status="resolved", entity="600519.SH",
                                    industry_ids=("industry:liquor",))

    class IndustryMustNotRun:
        def resolve(self, mentions=(), authoritative_ids=()):
            raise AssertionError("profile industry fallback is forbidden")

    service.target_resolver = TargetStub()
    service.industry_resolver = IndustryMustNotRun()
    result = service.handle(ChatRequest(
        message="研究贵州茅台所属行业", selected_scenario="industry_research"
    ))
    assert result.state == "clarification"
    assert not orchestrator.calls
