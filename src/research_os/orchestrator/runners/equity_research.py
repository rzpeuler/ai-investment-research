"""个股研报场景适配器。"""
from __future__ import annotations

from typing import Any, Dict

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class EquityResearchScenarioRunner:
    scenario = "stock_research_report"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if not request.get("entity"):
            raise ValueError("个股研报缺少 entity")
        from datetime import date

        from research_os.utils.time import now_iso, shanghai_now, validate_iso

        normalized = dict(request)
        report_date = request.get("date") or shanghai_now().date().isoformat()
        try:
            date.fromisoformat(report_date)
        except ValueError:
            raise ValueError(f"--date 非法: {report_date!r}（需要 YYYY-MM-DD）") from None
        if request.get("as_of") and not validate_iso(request["as_of"]):
            raise ValueError(f"--as-of 非法: {request['as_of']!r}（需要 ISO-8601）")
        normalized["date"] = report_date
        normalized["as_of"] = request.get("as_of") or now_iso()
        normalized["as_of_basis"] = "user_provided" if request.get("as_of") else "query_cutoff"
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "resolve_entity", "check_capability", "register_documents", "import_financials",
                "normalize_financials", "calculate_metrics", "analyze_business", "select_peers",
                "analyze_competition", "observe_valuation", "link_events", "run_semantic_tasks",
                "assemble_findings", "build_claim_evidence", "professional_review", "render", "validate",
            ],
            "data_requirements": [
                "company_profile", "security_profile", "financial_statement_data", "company_document",
                "industry_membership", "peer_financial_data", "market_valuation_snapshot", "event_evidence",
            ],
            "model_policy": "task_budget_flash_default_with_pro_escalation",
            "fallback_policy": ["manual_financial_import", "deterministic_fallback", "DATA_DEGRADED"],
            "output_paths": ["reports/stocks/{ticker}", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.equity_research.pipeline import EquityResearchPipeline
        from research_os.storage import Database

        payload = dict(request)
        payload.setdefault("task_id", context["task"].task_id)
        ephemeral_db = None
        db = context.get("db")
        if db is None:
            ephemeral_db = Database(":memory:")
            ephemeral_db.initialize()
            db = ephemeral_db
        try:
            outcome = EquityResearchPipeline(context["project_root"], db).run(payload)
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()
        validation = "fail" if outcome.exit_code == 4 else ("not_run" if payload.get("dry_run") else "pass")
        return ScenarioExecutionResult(
            status=outcome.status, exit_code=outcome.exit_code or 0,
            task_id=context["task"].task_id, run_id=outcome.run_id,
            run_dir=outcome.run_dir, report_path=outcome.report_path,
            validation_status=validation,
            missing_data=[outcome.message] if outcome.status == "insufficient_data" else [],
            model_route=outcome.model_route or {"mode": "deterministic_fallback", "llm_called": False},
            message=outcome.message,
        )
