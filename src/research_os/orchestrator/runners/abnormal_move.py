"""异动分析场景适配器。"""
from __future__ import annotations

from typing import Any, Dict

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class AbnormalMoveScenarioRunner:
    scenario = "abnormal_move_analysis"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not request.get("entity_id"):
            raise ValueError("异动分析缺少 entity_id")
        if request.get("granularity", "daily") != "daily":
            raise ValueError("minute 粒度暂无可用数据源")
        return dict(request)

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "resolve_window", "load_market_data", "detect_anomaly", "select_benchmark",
                "retrieve_events", "score_causes", "synthesize_attribution", "render", "validate",
            ],
            "data_requirements": ["market_daily_ohlcv", "entity_mapping", "event_evidence"],
            "model_policy": "flash_default_with_pro_escalation",
            "fallback_policy": ["manual_import", "deterministic_fallback", "UNEXPLAINED_MOVE"],
            "output_paths": ["reports/abnormal_moves", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.abnormal_move.pipeline import AbnormalMovePipeline
        from research_os.storage import Database

        ephemeral_db = None
        db = context.get("db")
        if db is None:
            db_path = context["project_root"] / "data" / "sqlite" / "research.db"
            if db_path.is_file():
                ephemeral_db = Database.open_read_only(db_path)
            else:
                ephemeral_db = Database(":memory:")
                ephemeral_db.initialize()
            db = ephemeral_db
        try:
            outcome = AbnormalMovePipeline(context["project_root"], db).run(
                entity_id=request["entity_id"], entity_type=request.get("entity_type", "company"),
                analysis_date=request.get("analysis_date"), depth=request.get("depth", "standard"),
                granularity=request.get("granularity", "daily"), force=bool(request.get("force")),
                dry_run=bool(request.get("dry_run")), task_id=context["task"].task_id,
                as_of=request.get("as_of"),
                window_start=request.get("window_start"), window_end=request.get("window_end"),
                peers=list(request.get("peers") or []), entity_name=request.get("entity_name", ""),
            )
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()
        validation = "fail" if outcome.status == "failed" and outcome.exit_code == 4 else (
            "not_run" if request.get("dry_run") else "pass")
        return ScenarioExecutionResult(
            status=outcome.status, exit_code=outcome.exit_code, task_id=context["task"].task_id,
            run_id=outcome.run.run_id if outcome.run else None,
            run_dir=str(outcome.run_dir) if outcome.run_dir else None,
            report_path=str(outcome.report_path) if outcome.report_path else None,
            validation_status=validation,
            warnings=list(outcome.run.warnings) if outcome.run else [],
            missing_data=[outcome.message] if outcome.status == "insufficient_data" else [],
            model_route=(outcome.run.model_route.model_dump() if outcome.run else {
                "mode": "deterministic_fallback", "llm_called": False,
            }),
            message=outcome.message,
        )
