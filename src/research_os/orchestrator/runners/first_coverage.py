"""Isolated ScenarioRunner for Phase 6C first coverage."""
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


class FirstCoverageScenarioRunner:
    scenario = "first_coverage"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.models.phase6c import FirstCoverageEarningsInput
        from research_os.utils.time import validate_iso
        allowed = {
            "task_id", "company_entity_id", "security_entity_id", "as_of",
            "as_of_basis", "timezone", "industry_id", "industry_name",
            "phase4_result_id", "phase4_selection_policy", "depth",
            "earnings_expectation", "live", "dry_run", "force",
            "source_policy", "warnings", "rule_versions", "version",
        }
        unknown = sorted(set(request) - allowed)
        if unknown:
            raise ValueError(f"unsupported first_coverage request fields: {unknown}")
        if not request.get("as_of") or not validate_iso(request["as_of"]):
            raise ValueError("first_coverage requires a valid explicit as_of")
        company = request.get("company_entity_id")
        security = request.get("security_entity_id")
        if not isinstance(company, str) or not company.startswith("company:"):
            raise ValueError("first_coverage requires company_entity_id")
        if not isinstance(security, str) or not security.startswith("security:"):
            raise ValueError("first_coverage requires security_entity_id")
        if not request.get("industry_id"):
            raise ValueError("first_coverage requires industry_id")
        earnings = request.get("earnings_expectation")
        if earnings is not None:
            try: earnings = FirstCoverageEarningsInput(**earnings).model_dump()
            except (TypeError, ValidationError, ValueError) as exc:
                raise ValueError(f"invalid earnings_expectation input: {exc}") from exc
        controls = {"timezone": "Asia/Shanghai", "as_of_basis": "user_provided", "phase4_selection_policy": "latest_accepted_at_or_before_as_of", "source_policy": "authoritative_db_only"}
        for name, supported in controls.items():
            if name in request and request[name] != supported:
                raise ValueError(f"unsupported {name}: {request[name]!r}")
        for name in ("live", "dry_run", "force"):
            if name in request and not isinstance(request[name], bool):
                raise ValueError(f"{name} must be a boolean")
        if "warnings" in request and not isinstance(request["warnings"], list):
            raise ValueError("warnings must be a list")
        if "rule_versions" in request and not isinstance(request["rule_versions"], dict):
            raise ValueError("rule_versions must be an object")
        normalized = dict(request)
        normalized["earnings_expectation"] = earnings
        normalized.setdefault("industry_name", "")
        normalized.setdefault("phase4_result_id", None)
        normalized.setdefault("depth", "standard")
        normalized.setdefault("live", False); normalized.setdefault("dry_run", False); normalized.setdefault("force", False)
        normalized.setdefault("warnings", []); normalized.setdefault("rule_versions", {}); normalized.setdefault("version", 1)
        normalized.update({k: normalized.get(k, v) for k, v in controls.items()})
        normalized["entities"] = [company, security]
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {"steps": ["validate_contract", "resolve_profiles", "resolve_phase4_baseline", "invoke_industry_component", "invoke_earnings_component", "compose_structured_context", "validate_report_and_run"], "data_requirements": ["valid company/security profiles", "accepted Phase4 structured result", "Phase6A industry context", "optional S3 earnings inputs"], "model_policy": "deterministic_only", "fallback_policy": ["partial_success", "degraded", "insufficient_evidence"], "output_paths": ["reports/runs/{task_id}"]}

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.first_coverage.pipeline import FirstCoveragePipeline, PIPELINE_VERSION
        from research_os.models import FirstCoverageRequest, FirstCoverageRun
        from research_os.reports import validate_report
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso
        task, run_dir = context["task"], context["run_dir"]
        if request.get("dry_run"):
            return ScenarioExecutionResult(status="planned", exit_code=0, task_id=task.task_id, validation_status="not_run", model_route={"mode": "deterministic_only", "llm_called": False}, message="[dry-run] first_coverage; no side effects")
        started = now_iso()
        request_model = FirstCoverageRequest(request_id=new_uuid(), task_id=task.task_id, company_entity_id=request["company_entity_id"], security_entity_id=request["security_entity_id"], as_of=request["as_of"], industry_id=request["industry_id"], industry_name=request["industry_name"], phase4_result_id=request["phase4_result_id"], depth=request["depth"], earnings_expectation=request["earnings_expectation"], live=bool(request["live"]), force=bool(request["force"]), requested_at=started, warnings=request["warnings"], rule_versions={**request["rule_versions"], "first_coverage": PIPELINE_VERSION})
        run_dir.write_json("first_coverage_request.json", _validated_payload(request_model, "first_coverage_request"))
        outcome = FirstCoveragePipeline(context["project_root"], context["db"], context.get("llm_client")).run(request_model)
        candidate = run_dir.root / ".first_coverage_candidate.md"
        candidate.write_text(outcome.markdown, encoding="utf-8")
        try: report_check = validate_report(candidate)
        finally: candidate.unlink(missing_ok=True)
        if not report_check.ok:
            raise ValueError(f"first coverage report validation failed: {report_check.errors}")
        final_markdown = outcome.markdown.replace("validator_status: pending", "validator_status: pass", 1)
        final_candidate = run_dir.root / ".first_coverage_final_candidate.md"
        final_candidate.write_text(final_markdown, encoding="utf-8")
        try: final_check = validate_report(final_candidate)
        finally: final_candidate.unlink(missing_ok=True)
        if not final_check.ok: raise ValueError(f"final first coverage report validation failed: {final_check.errors}")
        industry = outcome.industry_outcome
        earnings = outcome.earnings_outcome
        artifacts = [str(run_dir.root / "first_coverage_request.json"), str(run_dir.root / "first_coverage_run.json"), str(run_dir.root / "scenario_execution_result.json"), str(run_dir.final_md)]
        model_route = {"mode": "deterministic_only", "llm_called": False, "provider": None, "model": None, "fallback_used": False}
        run_model = FirstCoverageRun(run_id=outcome.run_id, request_id=request_model.request_id, task_id=task.task_id, company_entity_id=request_model.company_entity_id, security_entity_id=request_model.security_entity_id, as_of=request_model.as_of, company_profile_id=outcome.company_profile and outcome.company_profile["company_profile_id"], security_profile_id=outcome.security_profile and outcome.security_profile["security_profile_id"], phase4_result_id=outcome.phase4_result and outcome.phase4_result["result_id"], phase4_request_id=outcome.phase4_result and outcome.phase4_result["request_id"], phase4_run_id=outcome.phase4_result and outcome.phase4_result["run_id"], phase4_as_of=outcome.phase4_result and outcome.phase4_result["as_of"], industry_id=request_model.industry_id, industry_component_run_id=getattr(industry, "run_id", None), industry_component_status=getattr(industry, "status", "insufficient_evidence"), industry_dimensions_covered=getattr(industry, "dimensions_covered", []), industry_dimensions_missing=getattr(industry, "dimensions_missing", []), industry_evidence_quality=getattr(industry, "evidence_quality", {}), peer_selection_id=outcome.peer_selection and outcome.peer_selection["peer_selection_id"], peer_status=outcome.peer_selection["status"] if outcome.peer_selection else "insufficient", peer_company_ids=outcome.peer_selection["selected_company_ids"] if outcome.peer_selection else [], earnings_component_request_id=outcome.earnings_request_id, earnings_component_run_id=getattr(earnings, "run_id", None), earnings_component_status=getattr(earnings, "status", "insufficient_evidence"), earnings_scenarios=getattr(earnings, "scenarios", []), earnings_projection_lineage=getattr(earnings, "projection_lineage", []), valuation_snapshot_id=outcome.valuation_snapshot and outcome.valuation_snapshot["valuation_snapshot_id"], valuation_status=outcome.valuation_snapshot["status"] if outcome.valuation_snapshot else "insufficient_data", valuation_applicability_notes=outcome.valuation_snapshot["applicability_notes"] if outcome.valuation_snapshot else [], catalyst_ids=[x["catalyst_id"] for x in outcome.catalysts], risk_ids=[x["risk_id"] for x in outcome.risks], counter_evidence_ids=outcome.counter_evidence_ids, open_questions=outcome.open_questions, evidence_ids=outcome.evidence_ids, component_statuses=outcome.component_statuses, idempotency_key=outcome.idempotency_key, started_at=started, finished_at=now_iso(), status=outcome.status, artifact_paths=artifacts, input_versions={"first_coverage": PIPELINE_VERSION}, model_route=model_route, validation_status="pass", warnings=outcome.warnings, missing_data=outcome.missing_data)
        run_dir.write_json("first_coverage_run.json", _validated_payload(run_model, "first_coverage_run"))
        run_dir.write_final(final_markdown)
        run_dir.write_validation({"status": "ok" if outcome.status == "success" else outcome.status, "task_id": task.task_id, "checks": [x.model_dump() for x in outcome.component_statuses], "errors": []})
        return ScenarioExecutionResult(status=outcome.status, exit_code=0, task_id=task.task_id, run_id=outcome.run_id, run_dir=str(run_dir.root), report_path=str(run_dir.final_md), validation_status="pass", warnings=outcome.warnings, missing_data=outcome.missing_data, model_route=model_route, message=f"first coverage completed: status={outcome.status}")
