"""Real isolated-Orchestrator integration for Phase 6C First Coverage."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

from research_os.models import (
    Catalyst, CompanyProfile, EquityResearchRequest, EquityResearchResult,
    EquityResearchRun, Evidence, FinancialFact, FinancialReport, PeerSelection,
    ResearchFinding, RiskFactor, SecurityProfile, ValuationSnapshot,
)
from research_os.orchestrator.orchestrator import Orchestrator
from research_os.orchestrator.runners.first_coverage import FirstCoverageScenarioRunner
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.reports import validate_report
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance
from tests.integration.test_phase6a_s2 import _seed_valid_governed_theme_graph


COMPANY = "company:600000.SH"
SECURITY = "security:600000.SH"
INDUSTRY = "sw1:semi"
AS_OF = "2025-08-01T12:00:00+08:00"
P4_AS_OF = "2025-07-01T12:00:00+08:00"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"first-coverage-integration:{label}"))


EVIDENCE_ID = _uuid("evidence")
COUNTER_ID = _uuid("counter")


def _setup(tmp_path):
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()
    registry = ScenarioRegistry()
    registry.register(FirstCoverageScenarioRunner())
    return db, Orchestrator(tmp_path, db=db, registry=registry)


def _store(db, obj, schema):
    assert validate_instance(obj.model_dump(), schema) == []
    db.upsert(obj)


def _seed(db, *, company_name: str = "Test Bank"):
    _store(db, CompanyProfile(
        company_profile_id="cp1", entity_id=COMPANY, canonical_name=company_name,
        industry_ids=[INDUSTRY], fiscal_year_end="12-31",
        reporting_currency="CNY", ownership_type="state_owned",
        valid_from="2020-01-01", status="active", version=1,
        created_at="2020-01-01T00:00:00+08:00",
        updated_at="2020-01-01T00:00:00+08:00",
    ), "company_profile")
    _store(db, SecurityProfile(
        security_profile_id="sp1", security_entity_id=SECURITY,
        company_entity_id=COMPANY, symbol="600000.SH", exchange="SH",
        board="main", security_type="common_share", listing_date="1999-11-10",
        currency="CNY", share_class="A", current_name="Test Bank",
        status="listed", version=1,
        created_at="2020-01-01T00:00:00+08:00",
        updated_at="2020-01-01T00:00:00+08:00",
    ), "security_profile")

    for eid, title, excerpt, group in (
        (EVIDENCE_ID, "Annual report", "Revenue was 100.", "annual-report"),
        (COUNTER_ID, "Counter source", "A premise remains disputed.", "counter"),
    ):
        _store(db, Evidence(
            evidence_id=eid, source_id="cninfo", raw_item_id=_uuid(f"raw-{eid}"),
            title=title, publisher="listed company", published_at="2025-03-30T10:00:00+08:00",
            retrieved_at="2025-03-30T10:00:00+08:00",
            url=f"https://example.test/{eid}", excerpt=excerpt,
            evidence_type="official_disclosure", independence_group=group,
            source_tier="A", access_status="ok",
        ), "evidence")

    request = EquityResearchRequest(
        request_id="p4-request", task_id="p4-task", company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of=P4_AS_OF,
        report_date=P4_AS_OF[:10], requested_at=P4_AS_OF,
    )
    run = EquityResearchRun(
        run_id="p4-run", request_id=request.request_id, task_id=request.task_id,
        idempotency_key="p4-key", status="success", validation_status="pass",
        started_at=P4_AS_OF, finished_at=P4_AS_OF,
    )
    finding = ResearchFinding(
        finding_id="finding-1", request_id=request.request_id,
        company_entity_id=COMPANY, finding_type="fact_summary",
        title="Revenue baseline", statement="Reported revenue baseline is available.",
        claim_type="FACT", predicate="has_revenue_baseline", object={"value": "100"},
        as_of=P4_AS_OF, evidence_ids=[EVIDENCE_ID],
        counter_evidence_ids=[COUNTER_ID], confidence=0.9, support_level="direct",
        status="supported", invalidation_conditions=["A restatement is filed."],
        materiality="high", section_id="financials", created_at=P4_AS_OF,
    )
    peer = PeerSelection(
        peer_selection_id="peer-1", request_id=request.request_id,
        subject_company_id=COMPANY, information_cutoff=P4_AS_OF,
        universe_version="v1", scoring_version="v1",
        candidate_ids=["company:600001.SH"], selected_company_ids=["company:600001.SH"],
        sample_size=1, minimum_required=1, status="full",
        selection_rationale=["Comparable business model"], outlier_policy="none",
        evidence_ids=[EVIDENCE_ID], created_at=P4_AS_OF,
    )
    valuation = ValuationSnapshot(
        valuation_snapshot_id="valuation-1", company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of=P4_AS_OF,
        financial_basis="FY", metrics=[], history_sample_size=0,
        peer_selection_id=peer.peer_selection_id, peer_sample_size=1,
        applicability_notes=["Only method applicability is presented."],
        status="complete", evidence_ids=[EVIDENCE_ID], calculated_at=P4_AS_OF,
    )
    catalyst = Catalyst(
        catalyst_id="catalyst-1", company_entity_id=COMPANY, source_phase="phase4",
        catalyst_type="earnings", description="A scheduled disclosure may update the premise.",
        claim_type="HYPOTHESIS", announcement_status="announced",
        impact_mechanism="New reported inputs may change the baseline.",
        invalidation_conditions=["The disclosure is cancelled."],
        evidence_ids=[EVIDENCE_ID], confidence=0.7, created_at=P4_AS_OF,
        updated_at=P4_AS_OF,
    )
    risk = RiskFactor(
        risk_id="risk-1", company_entity_id=COMPANY, source_phase="phase4",
        risk_type="market", description="Demand may differ from the base assumption.",
        claim_type="HYPOTHESIS", impact_mechanism="Lower demand would weaken revenue.",
        triggers=["Demand data weakens"], counter_evidence_ids=[COUNTER_ID],
        evidence_ids=[EVIDENCE_ID], confidence=0.7, created_at=P4_AS_OF,
        updated_at=P4_AS_OF,
    )
    result = EquityResearchResult(
        result_id="p4-result", run_id=run.run_id, request_id=request.request_id,
        company_entity_id=COMPANY, security_entity_id=SECURITY, as_of=P4_AS_OF,
        research_status="success", key_finding_ids=[finding.finding_id],
        peer_selection_id=peer.peer_selection_id,
        valuation_snapshot_id=valuation.valuation_snapshot_id,
        catalyst_ids=[catalyst.catalyst_id], risk_ids=[risk.risk_id],
        evidence_ids=[EVIDENCE_ID], unknowns=["What changes the earnings premise?"],
        conflicts=["Demand evidence remains mixed."], created_at=P4_AS_OF,
    )
    for obj, schema in (
        (request, "equity_research_request"), (run, "equity_research_run"),
        (finding, "research_finding"), (peer, "peer_selection"),
        (valuation, "valuation_snapshot"), (catalyst, "catalyst"),
        (risk, "risk_factor"), (result, "equity_research_result"),
    ):
        _store(db, obj, schema)

    report = FinancialReport(
        financial_report_id="fr24", company_entity_id=COMPANY, document_id="doc24",
        report_type="annual", period_start="2024-01-01", period_end="2024-12-31",
        fiscal_year=2024, fiscal_period="FY", duration_months=12,
        statement_scope="consolidated", accounting_standard="CAS", currency="CNY",
        unit_scale=1, audit_status="audited", audit_opinion="unmodified",
        restatement_status="original", filing_version="v1", evidence_ids=[EVIDENCE_ID],
        data_status="complete", published_at="2025-03-30T10:00:00+08:00",
        created_at="2025-03-30T10:00:00+08:00",
    )
    fact = FinancialFact(
        fact_id="ff24", fact_key="revenue|2024FY|consolidated",
        financial_report_id=report.financial_report_id, company_entity_id=COMPANY,
        statement_type="income_statement", taxonomy_code="revenue", label_raw="revenue",
        period_start="2024-01-01", period_end="2024-12-31",
        instant_or_duration="duration", period_basis="reported_period",
        statement_scope="consolidated", currency="CNY", unit_scale=1,
        raw_value="100", normalized_value="100", normalized_unit="yuan",
        value_status="reported", sign_convention="reported", audit_status="audited",
        source_document_id="doc24", source_block_ids=["block24"],
        evidence_ids=[EVIDENCE_ID], source_priority=1, restatement_version=1,
        valid_from="2025-03-30T10:00:00+08:00",
        created_at="2025-03-30T10:00:00+08:00",
    )
    _store(db, report, "financial_report")
    _store(db, fact, "financial_fact")
    _seed_valid_governed_theme_graph(db)


def _request(**overrides):
    request = {
        "company_entity_id": COMPANY, "security_entity_id": SECURITY,
        "industry_id": INDUSTRY, "industry_name": "Semiconductors", "as_of": AS_OF,
        "earnings_expectation": {
            "forecast_period": {"start": "2025-01-01", "end": "2026-12-31",
                                "periods": ["FY2025", "FY2026"]},
            "assumptions": [{
                "driver": "revenue_growth", "value": "0.10", "unit": "ratio",
                "period": "annual", "source_type": "user_input",
                "source_ref_ids": ["user"], "evidence_ids": [], "confidence": 0.7,
                "invalidates_when": "new disclosure", "known_at": P4_AS_OF,
            }],
            "metric_code": "revenue", "scenario_name": "base",
        },
    }
    request.update(overrides)
    return request


def test_real_orchestrator_reuses_phase4_6a_and_s3(tmp_path, monkeypatch):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db)
        from research_os.equity_research.pipeline import EquityResearchPipeline

        monkeypatch.setattr(
            EquityResearchPipeline, "run",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("Phase4 full rerun prohibited")),
        )
        result = orchestrator.execute("first_coverage", _request())
        # Accepted 6A currently has unmapped dimensions and therefore degrades by design.
        assert result.status == "degraded", result.message
        assert result.exit_code == 0
        run_dir = Path(result.run_dir)
        expected = {
            "task.json", "plan.json", "first_coverage_request.json",
            "first_coverage_run.json", "scenario_execution_result.json",
            "validation.json", "final.md",
        }
        assert expected.issubset({path.name for path in run_dir.iterdir()})
        prohibited = {
            "earnings_expectation_request.json", "earnings_expectation_run.json",
            "industry_research_request.json", "industry_research_run.json",
            "equity_research_request.json", "equity_research_run.json", "run.json",
        }
        assert prohibited.isdisjoint({path.name for path in run_dir.iterdir()})
        request = json.loads((run_dir / "first_coverage_request.json").read_text("utf-8"))
        run = json.loads((run_dir / "first_coverage_run.json").read_text("utf-8"))
        execution = json.loads((run_dir / "scenario_execution_result.json").read_text("utf-8"))
        task = json.loads((run_dir / "task.json").read_text("utf-8"))
        plan = json.loads((run_dir / "plan.json").read_text("utf-8"))
        assert task["task_id"] == plan["task_id"] == request["task_id"] == run["task_id"]
        assert run["task_id"] == execution["task_id"] == result.task_id
        assert run["phase4_result_id"] == "p4-result"
        assert run["phase4_as_of"] == P4_AS_OF
        assert run["industry_component_run_id"] == result.task_id
        assert run["industry_component_status"] == "degraded"
        assert run["peer_selection_id"] == "peer-1"
        assert run["peer_company_ids"] == ["company:600001.SH"]
        assert run["valuation_snapshot_id"] == "valuation-1"
        assert run["catalyst_ids"] == ["catalyst-1"]
        assert run["risk_ids"] == ["risk-1"]
        assert run["counter_evidence_ids"] == [COUNTER_ID]
        assert [item["value"] for item in run["earnings_scenarios"][0]["outputs"]] == ["110", "121"]
        assert all(a["claim_type"] != "FACT" for a in run["earnings_scenarios"][0]["assumptions"])
        assert run["earnings_projection_lineage"][0]["baseline_financial_fact_id"] == "ff24"
        assert run["model_route"]["llm_called"] is False
        assert validate_instance(request, "first_coverage_request") == []
        assert validate_instance(run, "first_coverage_run") == []
        assert validate_report(run_dir / "final.md").ok
        assert db.count("forecast_scenarios") == 0
    finally:
        orchestrator.close()


def test_invalid_request_fails_before_artifacts(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        result = orchestrator.execute("first_coverage", _request(as_of="bad"))
        assert result.status == "failed"
        assert result.exit_code == 2
        assert result.run_dir is None
        assert not list((tmp_path / "reports" / "runs").glob("*/first_coverage_request.json"))
    finally:
        orchestrator.close()


def test_unknown_request_field_fails_before_artifacts(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        result = orchestrator.execute(
            "first_coverage", _request(future_component_shape={"x": 1}))
        assert result.status == "failed"
        assert result.exit_code == 2
        assert result.run_dir is None
        assert not list((tmp_path / "reports" / "runs").glob("*/first_coverage_request.json"))
    finally:
        orchestrator.close()


def test_future_finding_and_valuation_are_excluded(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db)
        finding = db.get("research_findings", "finding-1")
        finding["as_of"] = "2025-08-02T00:00:00+08:00"
        db._conn.execute(
            "UPDATE research_findings SET payload=? WHERE finding_id=?",
            (json.dumps(finding), "finding-1"),
        )
        valuation = db.get("valuation_snapshots", "valuation-1")
        valuation["as_of"] = "2025-08-02T00:00:00+08:00"
        db._conn.execute(
            "UPDATE valuation_snapshots SET payload=? WHERE valuation_snapshot_id=?",
            (json.dumps(valuation), "valuation-1"),
        )
        db._conn.commit()
        result = orchestrator.execute("first_coverage", _request())
        run = json.loads(
            (Path(result.run_dir) / "first_coverage_run.json").read_text("utf-8"))
        report = (Path(result.run_dir) / "final.md").read_text("utf-8")
        assert run["valuation_snapshot_id"] is None
        assert "ResearchFinding IDs: none" in report
        assert "## Key Findings\n\n- INSUFFICIENT_EVIDENCE" in report
        assert any("future research_finding" in item for item in run["warnings"])
        assert any("future valuation_snapshot" in item for item in run["warnings"])
    finally:
        orchestrator.close()


def test_counter_evidence_is_authoritative_and_fail_closed(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db)
        future_id = _uuid("future-counter")
        invalid_id = _uuid("invalid-counter")
        for eid, published in (
            (future_id, "2025-08-02T10:00:00+08:00"),
            (invalid_id, "2025-03-30T10:00:00+08:00"),
        ):
            _store(db, Evidence(
                evidence_id=eid, source_id="cninfo", raw_item_id=_uuid(f"raw-{eid}"),
                title="Counter", publisher="listed company", published_at=published,
                retrieved_at=published, url=f"https://example.test/{eid}",
                excerpt="Counter evidence", evidence_type="official_disclosure",
                independence_group=eid, source_tier="A", access_status="ok",
            ), "evidence")
        invalid = db.get("evidence", invalid_id)
        del invalid["access_status"]
        db._conn.execute(
            "UPDATE evidence SET payload=? WHERE evidence_id=?",
            (json.dumps(invalid), invalid_id),
        )
        finding = db.get("research_findings", "finding-1")
        finding["counter_evidence_ids"] = [
            COUNTER_ID, "missing-evidence", future_id, invalid_id,
        ]
        db._conn.execute(
            "UPDATE research_findings SET payload=? WHERE finding_id=?",
            (json.dumps(finding), "finding-1"),
        )
        db._conn.commit()
        result = orchestrator.execute("first_coverage", _request())
        run = json.loads(
            (Path(result.run_dir) / "first_coverage_run.json").read_text("utf-8"))
        assert run["counter_evidence_ids"] == [COUNTER_ID]
        assert "Demand evidence remains mixed." not in run["counter_evidence_ids"]
    finally:
        orchestrator.close()


def test_raw_evidence_default_masking_excludes_references(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db)
        evidence = db.get("evidence", EVIDENCE_ID)
        del evidence["access_status"]
        db._conn.execute(
            "UPDATE evidence SET payload=? WHERE evidence_id=?",
            (json.dumps(evidence), EVIDENCE_ID),
        )
        db._conn.commit()
        result = orchestrator.execute("first_coverage", _request())
        run = json.loads(
            (Path(result.run_dir) / "first_coverage_run.json").read_text("utf-8"))
        assert EVIDENCE_ID not in run["evidence_ids"]
        assert run["catalyst_ids"] == []
        assert run["risk_ids"] == []
        assert any("raw Schema validation failed (evidence)" in item for item in run["warnings"])
    finally:
        orchestrator.close()


def test_run_schema_failure_is_fail_closed(tmp_path, monkeypatch):
    db, orchestrator = _setup(tmp_path)
    _seed(db)
    from research_os.orchestrator.runners import first_coverage as runner_module

    original = runner_module._validated_payload

    def fail_run(model, schema_name):
        if schema_name == "first_coverage_run":
            raise ValueError("injected run schema failure")
        return original(model, schema_name)

    monkeypatch.setattr(runner_module, "_validated_payload", fail_run)
    try:
        task_id = "00000000-0000-4000-8000-000000000094"
        result = orchestrator.execute("first_coverage", _request(task_id=task_id))
        run_dir = tmp_path / "reports" / "runs" / task_id
        assert result.status == "failed"
        assert (run_dir / "first_coverage_request.json").exists()
        assert not (run_dir / "first_coverage_run.json").exists()
        assert (run_dir / "final.md").read_text("utf-8").startswith("#")
        assert db.count("forecast_scenarios") == 0
    finally:
        orchestrator.close()


def test_request_schema_failure_prevents_pipeline_and_artifacts(tmp_path, monkeypatch):
    db, orchestrator = _setup(tmp_path)
    from research_os.first_coverage.pipeline import FirstCoveragePipeline
    from research_os.orchestrator.runners import first_coverage as runner_module

    original = runner_module._validated_payload

    def fail_request(model, schema_name):
        if schema_name == "first_coverage_request":
            raise ValueError("injected request schema failure")
        return original(model, schema_name)

    monkeypatch.setattr(runner_module, "_validated_payload", fail_request)
    monkeypatch.setattr(
        FirstCoveragePipeline, "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("pipeline must not run")),
    )
    try:
        task_id = "00000000-0000-4000-8000-000000000092"
        result = orchestrator.execute("first_coverage", _request(task_id=task_id))
        run_dir = tmp_path / "reports" / "runs" / task_id
        assert result.status == "failed"
        assert result.exit_code == 5
        assert not (run_dir / "first_coverage_request.json").exists()
        assert not (run_dir / "first_coverage_run.json").exists()
    finally:
        orchestrator.close()


def test_report_safety_failure_is_fail_closed(tmp_path):
    db, orchestrator = _setup(tmp_path)
    try:
        _seed(db, company_name="建议买入")
        task_id = "00000000-0000-4000-8000-000000000093"
        result = orchestrator.execute("first_coverage", _request(task_id=task_id))
        run_dir = tmp_path / "reports" / "runs" / task_id
        assert result.status == "failed"
        assert result.exit_code == 5
        assert (run_dir / "first_coverage_request.json").exists()
        assert not (run_dir / "first_coverage_run.json").exists()
        assert "建议买入" not in (run_dir / "final.md").read_text("utf-8")
        assert db.count("forecast_scenarios") == 0
    finally:
        orchestrator.close()
