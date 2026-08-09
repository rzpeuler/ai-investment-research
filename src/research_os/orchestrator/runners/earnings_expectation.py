"""Isolated ScenarioRunner for Phase 6C earnings expectation."""
from __future__ import annotations

from typing import Any, Dict

from pydantic import ValidationError

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


def _validated_payload(model: Any, schema_name: str) -> dict:
    from research_os.validators.schema_validator import validate_instance

    payload = model.model_dump()
    errors = validate_instance(payload, schema_name)
    if errors:
        raise ValueError(f"Schema validation failed for {schema_name}: {errors}")
    return payload


class EarningsExpectationScenarioRunner:
    scenario = "earnings_expectation"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.models.phase6c import (
            EarningsExpectationAssumption,
            ForecastPeriod,
        )
        from research_os.utils.time import validate_iso
        from research_os.utils.time import parse_iso

        if not request.get("as_of") or not validate_iso(request["as_of"]):
            raise ValueError("earnings_expectation requires a valid explicit as_of")
        company = request.get("company_entity_id")
        if not isinstance(company, str) or not company.startswith("company:"):
            raise ValueError("earnings_expectation requires company_entity_id starting with company:")
        try:
            forecast_period = ForecastPeriod(**request.get("forecast_period", {}))
            assumptions = [
                EarningsExpectationAssumption(**item)
                for item in request.get("assumptions", [])
            ]
        except (TypeError, ValidationError, ValueError) as exc:
            raise ValueError(f"invalid earnings expectation request: {exc}") from exc
        if not assumptions:
            raise ValueError("earnings_expectation requires at least one explicit assumption")
        cutoff = parse_iso(request["as_of"])
        if any(item.source_type == "user_input" and item.known_at is None for item in assumptions):
            raise ValueError("user_input assumption requires explicit known_at")
        if any(item.known_at and parse_iso(item.known_at) > cutoff for item in assumptions):
            raise ValueError("assumption known_at must not be after as_of")

        controls = {
            "timezone": "Asia/Shanghai",
            "historical_selection_policy": "eligible_reports_published_by_as_of",
            "source_policy": "authoritative_db_only",
        }
        for field_name, supported in controls.items():
            if field_name in request and request[field_name] != supported:
                raise ValueError(f"unsupported {field_name}: {request[field_name]!r}")

        normalized = dict(request)
        normalized["forecast_period"] = forecast_period.model_dump()
        normalized["assumptions"] = [item.model_dump() for item in assumptions]
        normalized.setdefault("metric_code", "revenue")
        normalized.setdefault("scenario_name", "base")
        normalized.setdefault("as_of_basis", "user_provided")
        normalized.setdefault("timezone", "Asia/Shanghai")
        normalized.setdefault("historical_selection_policy", "eligible_reports_published_by_as_of")
        normalized.setdefault("depth", "standard")
        normalized.setdefault("live", False)
        normalized.setdefault("dry_run", False)
        normalized.setdefault("force", False)
        normalized.setdefault("source_policy", "authoritative_db_only")
        normalized.setdefault("warnings", [])
        normalized.setdefault("rule_versions", {})
        normalized.setdefault("version", 1)
        normalized["entities"] = [company]
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "validate_request_contract",
                "resolve_historical_financial_inputs_at_as_of",
                "validate_assumption_evidence",
                "build_phase4_forecast_scenario",
                "validate_and_persist_artifacts",
                "render_non_fact_report",
            ],
            "data_requirements": [
                "historical financial reports and facts",
                "assumptions and authoritative evidence",
                "explicit forecast periods",
            ],
            "model_policy": "deterministic_only",
            "fallback_policy": ["INSUFFICIENT_EVIDENCE", "DATA_DEGRADED"],
            "output_paths": ["reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.earnings_expectation.pipeline import (
            PIPELINE_VERSION,
            EarningsExpectationPipeline,
        )
        from research_os.equity_research.forecast import FORECAST_RULES_VERSION
        from research_os.models import EarningsExpectationRequest, EarningsExpectationRun
        from research_os.reports import validate_report
        from research_os.storage import Database
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso

        task = context["task"]
        if request.get("dry_run"):
            return ScenarioExecutionResult(
                status="planned",
                exit_code=0,
                task_id=task.task_id,
                validation_status="not_run",
                model_route={"mode": "deterministic_only", "llm_called": False},
                message=(f"[dry-run] earnings_expectation company={request['company_entity_id']} "
                         f"as_of={request['as_of']}; no side effects"),
            )

        run_dir = context["run_dir"]
        requested_at = now_iso()
        request_model = EarningsExpectationRequest(
            request_id=new_uuid(),
            task_id=task.task_id,
            company_entity_id=request["company_entity_id"],
            as_of=request["as_of"],
            as_of_basis=request["as_of_basis"],
            timezone=request["timezone"],
            historical_selection_policy=request["historical_selection_policy"],
            forecast_period=request["forecast_period"],
            assumptions=request["assumptions"],
            metric_code=request["metric_code"],
            scenario_name=request["scenario_name"],
            live=bool(request["live"]),
            dry_run=False,
            force=bool(request["force"]),
            source_policy=request["source_policy"],
            status="validated",
            warnings=list(request["warnings"]),
            rule_versions={
                **dict(request["rule_versions"]),
                "forecast": FORECAST_RULES_VERSION,
                "earnings_expectation": PIPELINE_VERSION,
            },
            requested_at=requested_at,
            version=int(request["version"]),
        )
        request_payload = _validated_payload(request_model, "earnings_expectation_request")
        run_dir.write_json("earnings_expectation_request.json", request_payload)

        ephemeral_db = None
        db = context.get("db")
        if db is None:
            ephemeral_db = Database(":memory:")
            ephemeral_db.initialize()
            db = ephemeral_db
        try:
            outcome = EarningsExpectationPipeline(db).run(request_model)
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()

        # Candidate report safety is a production acceptance gate.  The temporary
        # file is always removed and is never exposed as a successful artifact.
        candidate_path = run_dir.root / ".earnings_expectation_candidate.md"
        candidate_path.write_text(outcome.markdown, encoding="utf-8")
        try:
            report_validation = validate_report(candidate_path)
        finally:
            candidate_path.unlink(missing_ok=True)
        if not report_validation.ok:
            raise ValueError(
                f"earnings expectation report validation failed: {report_validation.errors}"
            )
        final_markdown = outcome.markdown.replace(
            "validator_status: pending", "validator_status: pass", 1,
        )
        final_candidate_path = run_dir.root / ".earnings_expectation_final_candidate.md"
        final_candidate_path.write_text(final_markdown, encoding="utf-8")
        try:
            final_report_validation = validate_report(final_candidate_path)
        finally:
            final_candidate_path.unlink(missing_ok=True)
        if not final_report_validation.ok:
            raise ValueError(
                f"final earnings expectation report validation failed: "
                f"{final_report_validation.errors}"
            )

        artifact_paths = [
            str(run_dir.root / "earnings_expectation_request.json"),
            str(run_dir.root / "earnings_expectation_run.json"),
            str(run_dir.root / "scenario_execution_result.json"),
            str(run_dir.final_md),
        ]
        model_route = {
            "mode": "deterministic_only",
            "llm_called": False,
            "provider": None,
            "model": None,
            "fallback_used": False,
            "reason": "P6-S3 deterministic forecast path",
        }
        run_model = EarningsExpectationRun(
            run_id=outcome.run_id,
            request_id=request_model.request_id,
            task_id=task.task_id,
            company_entity_id=request_model.company_entity_id,
            as_of=request_model.as_of,
            historical_input_periods=outcome.historical_input_periods,
            forecast_period=request_model.forecast_period,
            scenario_ids=[scenario.scenario_id for scenario in outcome.scenarios],
            scenarios=outcome.scenarios,
            projection_lineage=outcome.projection_lineage,
            evidence_ids=outcome.evidence_ids,
            method="Phase4 deterministic_projection over as_of-governed historical baseline",
            uncertainty=[
                "Forecast values are hypotheses conditional on explicit assumptions.",
                "New disclosures or invalidated assumptions require recomputation.",
            ],
            calculation_version=FORECAST_RULES_VERSION,
            generated_by="deterministic_code",
            model_route=model_route,
            idempotency_key=outcome.idempotency_key,
            run_version=1,
            started_at=requested_at,
            finished_at=now_iso(),
            status=outcome.status,
            stage_statuses=outcome.stage_statuses,
            artifact_paths=artifact_paths,
            input_versions={
                "pipeline_version": PIPELINE_VERSION,
                "forecast_rules_version": FORECAST_RULES_VERSION,
            },
            validation_status="pass",
            error_codes=outcome.error_codes,
            warnings=outcome.warnings,
            missing_data=outcome.missing_data,
            version=1,
        )
        # Run schema validation must happen before any successful run artifact is persisted.
        run_payload = _validated_payload(run_model, "earnings_expectation_run")
        # ForecastScenario persistence is allowed only after scenario Schema,
        # shared report validation, and Run Pydantic/Schema have all passed.
        for scenario in outcome.scenarios:
            db.upsert(scenario)
        run_dir.write_json("earnings_expectation_run.json", run_payload)
        run_dir.write_final(final_markdown)
        run_dir.write_validation({
            "status": "ok" if outcome.status == "success" else outcome.status,
            "task_id": task.task_id,
            "checks": outcome.stage_statuses,
            "errors": outcome.error_codes,
        })
        return ScenarioExecutionResult(
            status=outcome.status,
            exit_code=0,
            task_id=task.task_id,
            run_id=outcome.run_id,
            run_dir=str(run_dir.root),
            report_path=str(run_dir.final_md),
            validation_status="pass",
            warnings=outcome.warnings,
            missing_data=outcome.missing_data,
            model_route=model_route,
            message=(f"earnings expectation completed: company={request_model.company_entity_id}, "
                     f"status={outcome.status}, scenarios={len(outcome.scenarios)}"),
        )
