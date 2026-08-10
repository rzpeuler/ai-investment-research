from __future__ import annotations

from datetime import datetime
import json

from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.app import DashboardApplication
from research_os.dashboard.models import ChatRequest
from research_os.dashboard.session import SessionStore
from research_os.llm.models import LlmResponse
from research_os.orchestrator import Orchestrator, ScenarioRegistry
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.storage import Database
from research_os.models import CompanyProfile, SecurityProfile


class CapturingRunner:
    scenario = "stock_research_report"
    version = "test"

    def __init__(self):
        self.request = None

    def validate_request(self, request):
        assert request == {"entity": "600519.SH"}
        return dict(request)

    def build_plan(self, request, context):
        return {"steps": ["capture"], "data_requirements": ["entity_mapping"]}

    def execute(self, request, context):
        self.request = dict(request)
        return ScenarioExecutionResult(
            status="insufficient_evidence", exit_code=0,
            task_id=context["task"].task_id, validation_status="pass",
        )


def test_chat_hands_only_minimal_request_to_real_orchestrator(tmp_path):
    db = Database(":memory:"); db.initialize()
    runner = CapturingRunner()
    registry = ScenarioRegistry(); registry.register(runner)
    orchestrator = Orchestrator(tmp_path, db=db, registry=registry)
    service = ChatService(
        tmp_path, db, orchestrator, llm_client=None,
        clock=lambda: datetime(2026, 8, 10, 9, 30),
    )
    result = service.handle(ChatRequest(
        message="600519.SH", selected_scenario="stock_research_report", llm_enabled=False,
    ))
    assert result.state == "executed"
    assert result.minimal_request == {"entity": "600519.SH"}
    assert runner.request == result.minimal_request
    # Business/control artifacts are owned by Orchestrator, never written beside Chat state.
    assert not list(tmp_path.glob("*chat*"))
    orchestrator.close()


class ConversationLlm:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.prompts = []

    def generate_json(self, request, output_schema, budget=None):
        self.prompts.append(request.prompt)
        if budget is not None:
            budget.record("flash")
        return LlmResponse(
            call_id=request.call_id, called=True, status="success", schema_valid=True,
            output=self.outputs.pop(0), attempt_count=1,
        )


class EarningsOrchestrator:
    def __init__(self): self.calls = []
    def execute(self, scenario, request):
        self.calls.append((scenario, request))
        return ScenarioExecutionResult(
            status="partial_success", exit_code=0, task_id="task-conversation",
            validation_status="pass",
        )


def _conversation_db():
    db = Database(":memory:"); db.initialize()
    common = {"created_at": "2026-01-01T00:00:00", "updated_at": "2026-01-01T00:00:00"}
    db.upsert(CompanyProfile(
        company_profile_id="cp1", entity_id="company:maotai", canonical_name="贵州茅台",
        industry_ids=["industry:liquor"], fiscal_year_end="12-31",
        reporting_currency="CNY", ownership_type="state_owned", valid_from="2001-01-01",
        **common,
    ))
    db.upsert(SecurityProfile(
        security_profile_id="sp1", security_entity_id="security:600519.SH",
        company_entity_id="company:maotai", symbol="600519.SH", exchange="SH", board="main",
        security_type="common_share", listing_date="2001-08-27", currency="CNY",
        share_class="A", current_name="贵州茅台", **common,
    ))
    return db


def test_earnings_clarification_can_complete_on_second_turn_without_hidden_context_leak(tmp_path):
    first_draft = {
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "2027年",
        "metric_expressions": [], "scenario_expressions": [],
        "explicit_assumptions": [], "complete": True, "clarification_question": None,
    }
    second_draft = {
        **first_draft,
        "explicit_assumptions": [{
            "statement": "收入增长10%", "metric_expression": "收入增长",
            "value_expression": "10%", "period_expression": "2027年",
        }],
    }
    llm = ConversationLlm([
        {"scenario": "earnings_expectation", "confidence": 0.95,
         "needs_clarification": False, "clarification_question": None},
        first_draft,
        {"scenario": None, "confidence": 0.2,
         "needs_clarification": True, "clarification_question": "请补充研究场景。"},
        second_draft,
    ])
    db = _conversation_db()
    orchestrator = EarningsOrchestrator()
    service = ChatService(tmp_path, db, orchestrator, llm_client=llm,
                          clock=lambda: datetime(2026, 8, 10, 9, 30))
    app = DashboardApplication(tmp_path, service, SessionStore(), llm_configured=True)
    headers = {"Content-Type": "application/json"}

    def post(message, *, llm_enabled=True):
        payload = json.dumps({
            "session_id": "earnings", "message": message,
            "selected_scenario": "AUTO", "llm_enabled": llm_enabled,
            "research_live": False,
        }, ensure_ascii=False).encode("utf-8")
        status, _, body = app.dispatch("POST", "/api/chat", headers, payload)
        return status, json.loads(body)

    first_status, first = post("贵州茅台 2027年财报预期")
    assert first_status == 200 and first["status"] == "clarification"
    assert not orchestrator.calls
    context = app.sessions.context("earnings", "AUTO")
    assert context["awaiting_clarification"] is True
    assert context["user_messages"] == ["贵州茅台 2027年财报预期"]
    second_status, second = post("补充假设：收入增长10%")
    assert second_status == 200 and second["status"] == "executed", second
    assert first["recognized"]["llm_calls"] == 2
    assert second["recognized"]["llm_calls"] == 2
    assert len(orchestrator.calls) == 1
    assert "贵州茅台 2027年财报预期" in llm.prompts[3]
    assert "补充假设：收入增长10%" in llm.prompts[3]
    assert len(llm.prompts) == 4  # each AUTO turn: route once + extract once
    recent = app.dispatch("GET", "/api/recent?session_id=earnings", {})[2].decode("utf-8")
    assert "user_messages" not in recent
    assert "贵州茅台 2027年财报预期\n补充假设" not in recent
    db.close()


def test_auto_explicit_new_scenario_overrides_awaiting_context(tmp_path):
    first_draft = {
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "2027年",
        "metric_expressions": [], "scenario_expressions": [],
        "explicit_assumptions": [], "complete": True, "clarification_question": None,
    }
    llm = ConversationLlm([
        {"scenario": "earnings_expectation", "confidence": 0.95,
         "needs_clarification": False, "clarification_question": None},
        first_draft,
    ])
    db = _conversation_db()
    orchestrator = EarningsOrchestrator()
    service = ChatService(tmp_path, db, orchestrator, llm_client=llm,
                          clock=lambda: datetime(2026, 8, 10, 9, 30))
    app = DashboardApplication(tmp_path, service, SessionStore(), llm_configured=True)

    def post(message, llm_enabled):
        payload = json.dumps({
            "session_id": "switch", "message": message, "selected_scenario": "AUTO",
            "llm_enabled": llm_enabled, "research_live": False,
        }, ensure_ascii=False).encode("utf-8")
        return json.loads(app.dispatch(
            "POST", "/api/chat", {"Content-Type": "application/json"}, payload,
        )[2])

    assert post("贵州茅台 2027年财报预期", True)["status"] == "clarification"
    switched = post("今天晨报", False)
    assert switched["status"] == "executed"
    assert switched["recognized"]["scenario"] == "morning_brief"
    context = app.sessions.context("switch", "AUTO")
    assert context["scenario"] == "morning_brief"
    assert context["awaiting_clarification"] is False
    assert context["user_messages"] == []
    assert orchestrator.calls[-1][0] == "morning_brief"
    db.close()


def test_completed_stock_request_does_not_contaminate_next_symbol(tmp_path):
    db = Database(":memory:"); db.initialize()
    orchestrator = EarningsOrchestrator()
    service = ChatService(tmp_path, db, orchestrator, llm_client=None,
                          clock=lambda: datetime(2026, 8, 10, 9, 30))
    app = DashboardApplication(tmp_path, service, SessionStore(), llm_configured=False)

    def post(symbol):
        payload = json.dumps({
            "session_id": "stocks", "message": symbol,
            "selected_scenario": "stock_research_report", "llm_enabled": False,
            "research_live": False,
        }).encode()
        return json.loads(app.dispatch(
            "POST", "/api/chat", {"Content-Type": "application/json"}, payload,
        )[2])

    assert post("600519.SH")["status"] == "executed"
    assert post("000001.SZ")["status"] == "executed"
    assert [call[1]["entity"] for call in orchestrator.calls] == ["600519.SH", "000001.SZ"]
    assert app.sessions.context("stocks", "stock_research_report")["user_messages"] == []
    db.close()
