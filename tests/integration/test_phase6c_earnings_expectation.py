"""Real Orchestrator integration for isolated earnings_expectation registry."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

from research_os.models import Evidence, FinancialFact, FinancialReport
from research_os.orchestrator.orchestrator import Orchestrator
from research_os.orchestrator.runners.earnings_expectation import EarningsExpectationScenarioRunner
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.reports import validate_report
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance


COMPANY = "company:600000.SH"
PUBLISHED = "2025-03-30T10:00:00+08:00"
AS_OF = "2025-08-01T12:00:00+08:00"
E24 = str(uuid5(NAMESPACE_DNS, "phase6c-integration:e24"))
RAW_E24 = str(uuid5(NAMESPACE_DNS, "phase6c-integration:raw-e24"))


def _setup(tmp_path):
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()
    registry = ScenarioRegistry()
    registry.register(EarningsExpectationScenarioRunner())
    return db, Orchestrator(tmp_path, db=db, registry=registry)


def _seed(db):
    evidence = Evidence(
        evidence_id=E24, source_id="cninfo", raw_item_id=RAW_E24,
        title="2024 annual report", publisher="listed company",
        published_at=PUBLISHED, retrieved_at=PUBLISHED,
        url="https://example.test/e24", excerpt="revenue 100",
        evidence_type="official_disclosure", independence_group="report:2024",
        source_tier="A", access_status="ok",
    )
    report = FinancialReport(
        financial_report_id="r24", company_entity_id=COMPANY,
        document_id="doc-r24", manifest_id=None, report_type="annual",
        period_start="2024-01-01", period_end="2024-12-31", fiscal_year=2024,
        fiscal_period="FY", duration_months=12, statement_scope="consolidated",
        accounting_standard="CAS", currency="CNY", unit_scale=1,
        audit_status="audited", audit_opinion="unmodified",
        restatement_status="original", supersedes_report_id=None,
        filing_version="v1", source_ids=["cninfo"], evidence_ids=[E24],
        data_status="complete", version=1, published_at=PUBLISHED, created_at=PUBLISHED,
    )
    fact = FinancialFact(
        fact_id="f24", fact_key="revenue|2024|FY|consolidated",
        financial_report_id="r24", company_entity_id=COMPANY,
        statement_type="income_statement", taxonomy_code="revenue",
        label_raw="revenue", period_start="2024-01-01", period_end="2024-12-31",
        instant_or_duration="duration", period_basis="reported_period",
        statement_scope="consolidated", currency="CNY", unit_scale=1,
        raw_value="100", normalized_value="100", normalized_unit="yuan",
        value_status="reported", sign_convention="reported", audit_status="audited",
        segment_id=None, source_document_id="doc-r24", source_block_ids=["block-f24"],
        evidence_ids=[E24], source_priority=1, restatement_version=1,
        valid_from=PUBLISHED, valid_to=None, conflict_group_id=None,
        warnings=[], version=1, created_at=PUBLISHED,
    )
    assert validate_instance(evidence.model_dump(), "evidence") == []
    assert validate_instance(report.model_dump(), "financial_report") == []
    assert validate_instance(fact.model_dump(), "financial_fact") == []
    db.upsert(evidence)
    db.upsert(report)
    db.upsert(fact)


def _request(**extra):
    request = {
        "company_entity_id": COMPANY,
        "as_of": AS_OF,
        "forecast_period": {
            "start": "2025-01-01", "end": "2026-12-31",
            "periods": ["FY2025", "FY2026"],
        },
        "assumptions": [{
            "driver": "revenue_growth", "value": "0.10", "unit": "ratio",
            "period": "annual", "source_type": "user_input",
            "source_ref_ids": [], "evidence_ids": [], "confidence": 0.7,
            "invalidates_when": "new disclosure changes the premise", "known_at": AS_OF,
        }],
    }
    request.update(extra)
    return request


def test_orchestrator_happy_path_and_lineage(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db)
        result = orchestrator.execute("earnings_expectation", _request())
        assert result.status == "success", result.message
        assert result.exit_code == 0
        run_dir = Path(result.run_dir)
        expected = {
            "task.json", "plan.json", "earnings_expectation_request.json",
            "earnings_expectation_run.json", "scenario_execution_result.json", "final.md",
        }
        assert expected.issubset({p.name for p in run_dir.iterdir()})
        request = json.loads((run_dir / "earnings_expectation_request.json").read_text("utf-8"))
        run = json.loads((run_dir / "earnings_expectation_run.json").read_text("utf-8"))
        execution = json.loads((run_dir / "scenario_execution_result.json").read_text("utf-8"))
        assert request["task_id"] == run["task_id"] == execution["task_id"] == result.task_id
        assert validate_instance(request, "earnings_expectation_request") == []
        assert validate_instance(run, "earnings_expectation_run") == []
        assert run["as_of"] == AS_OF
        assert run["historical_input_periods"][0]["financial_report_ids"] == ["r24"]
        assert [o["value"] for o in run["scenarios"][0]["outputs"]] == ["110", "121"]
        assert run["projection_lineage"] == [{
            "scenario_id": run["scenarios"][0]["scenario_id"],
            "metric_code": "revenue",
            "baseline_financial_report_id": "r24",
            "baseline_financial_fact_id": "f24",
            "baseline_period_end": "2024-12-31",
            "baseline_fiscal_period": "FY",
            "baseline_duration_months": 12,
            "baseline_normalized_value": "100",
            "baseline_normalized_unit": "yuan",
            "assumption_ids": [run["scenarios"][0]["assumptions"][0]["assumption_id"]],
            "output_periods": ["FY2025", "FY2026"],
            "formula_version": run["calculation_version"],
            "evidence_ids": [E24],
        }]
        persisted = db.get("forecast_scenarios", run["scenario_ids"][0])
        assert persisted == run["scenarios"][0]
        assert run["model_route"]["llm_called"] is False
        assert validate_report(run_dir / "final.md").ok
    finally:
        orchestrator.close()


def test_invalid_request_fails_before_business_artifacts(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        result = orchestrator.execute("earnings_expectation", _request(as_of="bad"))
        assert result.status == "failed"
        assert result.exit_code == 2
        assert result.run_dir is None
        assert not list((tmp_path / "reports" / "runs").glob("*/earnings_expectation_request.json"))
    finally:
        orchestrator.close()


def test_no_eligible_history_is_insufficient_evidence(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        result = orchestrator.execute("earnings_expectation", _request())
        assert result.status == "insufficient_evidence"
        assert result.exit_code == 0
        run = json.loads(
            (Path(result.run_dir) / "earnings_expectation_run.json").read_text("utf-8")
        )
        assert run["status"] == "insufficient_evidence"
        assert run["scenarios"] == []
    finally:
        orchestrator.close()


def test_dry_run_has_no_side_effects(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        result = orchestrator.execute("earnings_expectation", _request(dry_run=True))
        assert result.status == "planned"
        assert result.run_dir is None
        assert not (tmp_path / "reports").exists()
    finally:
        orchestrator.close()


def test_run_schema_failure_cannot_persist_success_artifact(tmp_path, monkeypatch):
    db, orchestrator = _setup(tmp_path)
    _seed(db)
    from research_os.orchestrator.runners import earnings_expectation as runner_module

    original = runner_module._validated_payload

    def fail_run(model, schema_name):
        if schema_name == "earnings_expectation_run":
            raise ValueError("injected run schema failure")
        return original(model, schema_name)

    monkeypatch.setattr(runner_module, "_validated_payload", fail_run)
    try:
        task_id = "00000000-0000-4000-8000-000000000099"
        result = orchestrator.execute("earnings_expectation", _request(task_id=task_id))
        assert result.status == "failed"
        assert result.exit_code == 5
        run_dir = tmp_path / "reports" / "runs" / task_id
        assert (run_dir / "earnings_expectation_request.json").exists()
        assert not (run_dir / "earnings_expectation_run.json").exists()
        assert db.query("SELECT COUNT(*) AS count FROM forecast_scenarios")[0]["count"] == 0
    finally:
        orchestrator.close()


def test_report_safety_failure_cannot_persist_run_or_scenario(tmp_path):
    db, orchestrator = _setup(tmp_path)
    _seed(db)
    try:
        task_id = "00000000-0000-4000-8000-000000000098"
        result = orchestrator.execute(
            "earnings_expectation",
            _request(task_id=task_id, scenario_name="建议买入"),
        )
        assert result.status == "failed"
        assert result.exit_code == 5
        run_dir = tmp_path / "reports" / "runs" / task_id
        assert (run_dir / "earnings_expectation_request.json").exists()
        assert not (run_dir / "earnings_expectation_run.json").exists()
        assert (run_dir / "final.md").exists()
        assert (run_dir / "final.md").read_text("utf-8") == "# 待生成报告\n"
        assert db.query("SELECT COUNT(*) AS count FROM forecast_scenarios")[0]["count"] == 0
    finally:
        orchestrator.close()
