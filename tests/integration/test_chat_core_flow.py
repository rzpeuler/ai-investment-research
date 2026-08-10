from __future__ import annotations

from datetime import datetime

from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.models import ChatRequest
from research_os.orchestrator import Orchestrator, ScenarioRegistry
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.storage import Database


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
