from __future__ import annotations

from datetime import datetime

from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.models import ChatRequest
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


def test_safety_guard_calls_neither_llm_nor_orchestrator():
    llm = QueueLlmClient([])
    orchestrator = SpyOrchestrator()
    db = Database(":memory:"); db.initialize()
    result = ChatService(".", db, orchestrator, llm, clock=lambda: NOW).handle(
        ChatRequest(message="推荐股票并给出明日买入信号", selected_scenario="AUTO")
    )
    assert result.state == "failed"
    assert not llm.calls and not orchestrator.calls


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
