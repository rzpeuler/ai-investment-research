"""Phase 6C first-coverage composition and authority tests."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_DNS, uuid5

import pytest
from pydantic import ValidationError

from research_os.first_coverage.pipeline import FirstCoveragePipeline
from research_os.models import (
    CompanyProfile, EquityResearchRequest, EquityResearchResult, EquityResearchRun,
    Evidence, FinancialFact, FinancialReport, FirstCoverageRequest, SecurityProfile,
)
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance, validate_model

COMPANY = "company:600000.SH"
SECURITY = "security:600000.SH"
AS_OF = "2025-08-01T12:00:00+08:00"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"first-coverage:{label}"))


def _db(tmp_path) -> Database:
    db = Database(tmp_path / "research.db"); db.initialize(); return db


def _request(**overrides) -> FirstCoverageRequest:
    data = {"request_id": "fc-request", "task_id": "fc-task", "company_entity_id": COMPANY,
            "security_entity_id": SECURITY, "as_of": AS_OF, "industry_id": "industry:bank",
            "industry_name": "Banking", "earnings_expectation": None, "requested_at": AS_OF}
    data.update(overrides)
    return FirstCoverageRequest(**data)


def _seed_profiles(db: Database) -> None:
    cp = CompanyProfile(company_profile_id="cp1", entity_id=COMPANY, canonical_name="Test Bank",
        industry_ids=["industry:bank"], fiscal_year_end="12-31", reporting_currency="CNY",
        ownership_type="state_owned", valid_from="2020-01-01", status="active", version=1,
        created_at="2020-01-01T00:00:00+08:00", updated_at="2020-01-01T00:00:00+08:00")
    sp = SecurityProfile(security_profile_id="sp1", security_entity_id=SECURITY,
        company_entity_id=COMPANY, symbol="600000.SH", exchange="SH", board="main",
        security_type="common_share", listing_date="1999-11-10", currency="CNY",
        share_class="A", current_name="Test Bank", status="listed", version=1,
        created_at="2020-01-01T00:00:00+08:00", updated_at="2020-01-01T00:00:00+08:00")
    assert validate_instance(cp.model_dump(), "company_profile") == []
    assert validate_instance(sp.model_dump(), "security_profile") == []
    db.upsert(cp); db.upsert(sp)


def _seed_phase4(db: Database, *, as_of: str = "2025-07-01T00:00:00+08:00") -> None:
    req = EquityResearchRequest(request_id="p4-request", task_id="p4-task", company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of=as_of, report_date=as_of[:10], requested_at=as_of)
    run = EquityResearchRun(run_id="p4-run", request_id=req.request_id, task_id=req.task_id,
        idempotency_key="p4-key", status="success", validation_status="pass", started_at=as_of,
        finished_at=as_of)
    result = EquityResearchResult(result_id="p4-result", run_id=run.run_id,
        request_id=req.request_id, company_entity_id=COMPANY, security_entity_id=SECURITY,
        as_of=as_of, research_status="success", unknowns=["What changes the earnings premise?"],
        created_at=as_of)
    for obj, schema in ((req, "equity_research_request"), (run, "equity_research_run"),
                        (result, "equity_research_result")):
        assert validate_instance(obj.model_dump(), schema) == []; db.upsert(obj)


def _seed_financial(db: Database) -> None:
    eid = _uuid("e24")
    ev = Evidence(evidence_id=eid, source_id="cninfo", raw_item_id=_uuid("raw-e24"),
        title="2024 annual report", publisher="company", published_at="2025-03-30T10:00:00+08:00",
        retrieved_at="2025-03-30T10:00:00+08:00", url="https://example.test/e24",
        excerpt="revenue 100", evidence_type="official_disclosure", independence_group="fy2024",
        source_tier="A", access_status="ok")
    report = FinancialReport(financial_report_id="fr24", company_entity_id=COMPANY,
        document_id="doc24", report_type="annual", period_start="2024-01-01",
        period_end="2024-12-31", fiscal_year=2024, fiscal_period="FY", duration_months=12,
        statement_scope="consolidated", accounting_standard="CAS", currency="CNY", unit_scale=1,
        audit_status="audited", audit_opinion="unmodified", restatement_status="original",
        filing_version="v1", evidence_ids=[eid], published_at="2025-03-30T10:00:00+08:00",
        created_at="2025-03-30T10:00:00+08:00")
    fact = FinancialFact(fact_id="ff24", fact_key="revenue|2024FY|consolidated",
        financial_report_id="fr24", company_entity_id=COMPANY, statement_type="income_statement",
        taxonomy_code="revenue", label_raw="revenue", period_start="2024-01-01",
        period_end="2024-12-31", instant_or_duration="duration", period_basis="reported_period",
        statement_scope="consolidated", currency="CNY", unit_scale=1, raw_value="100",
        normalized_value="100", normalized_unit="yuan", value_status="reported",
        sign_convention="reported", audit_status="audited", source_document_id="doc24",
        source_block_ids=["block24"], evidence_ids=[eid], source_priority=1,
        restatement_version=1, valid_from="2025-03-30T10:00:00+08:00",
        created_at="2025-03-30T10:00:00+08:00")
    for obj, schema in ((ev, "evidence"), (report, "financial_report"), (fact, "financial_fact")):
        assert validate_instance(obj.model_dump(), schema) == []; db.upsert(obj)


def _earnings_input():
    return {"forecast_period": {"start": "2025-01-01", "end": "2026-12-31",
            "periods": ["FY2025", "FY2026"]}, "assumptions": [{"driver": "revenue_growth",
            "value": "0.10", "unit": "ratio", "period": "annual", "source_type": "user_input",
            "source_ref_ids": ["user"], "evidence_ids": [], "confidence": 0.7,
            "invalidates_when": "new disclosure", "known_at": "2025-07-01T00:00:00+08:00"}],
            "metric_code": "revenue", "scenario_name": "base"}


def test_request_schema_roundtrip_and_optional_earnings():
    request = _request()
    assert validate_model(request) == []
    assert validate_instance(request.model_dump(), "first_coverage_request") == []


@pytest.mark.parametrize(("field", "value"), [("timezone", "UTC"),
    ("phase4_selection_policy", "latest"), ("source_policy", "public_first")])
def test_request_rejects_unsupported_controls(field, value):
    with pytest.raises(ValidationError): _request(**{field: value})


def test_missing_phase4_is_insufficient_without_rerun(tmp_path):
    db = _db(tmp_path); _seed_profiles(db)
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    assert outcome.status == "insufficient_evidence"
    assert outcome.phase4_result is None
    assert len(outcome.idempotency_key) == 64
    db.close()


def test_future_phase4_is_rejected(tmp_path):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db, as_of="2025-08-02T00:00:00+08:00")
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    assert outcome.status == "insufficient_evidence"
    assert "accepted_phase4_baseline" in outcome.missing_data
    db.close()


def test_raw_profile_default_masking_is_prohibited(tmp_path):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    raw = db.get("company_profiles", "cp1"); del raw["status"]
    assert CompanyProfile(**raw).status == "active"
    assert validate_instance(raw, "company_profile")
    db._conn.execute("UPDATE company_profiles SET payload=? WHERE company_profile_id=?",
                     (json.dumps(raw), "cp1")); db._conn.commit()
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    assert outcome.status == "insufficient_evidence"
    assert any("raw Schema validation failed" in w for w in outcome.warnings)
    db.close()


def test_real_s3_pipeline_reused_and_forecast_never_fact(tmp_path):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db); _seed_financial(db)
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request(earnings_expectation=_earnings_input()))
    assert outcome.status == "partial_success"
    assert [o.value for o in outcome.earnings_outcome.scenarios[0].outputs] == ["110", "121"]
    assert all(a.claim_type != "FACT" for a in outcome.earnings_outcome.scenarios[0].assumptions)
    assert outcome.earnings_outcome.projection_lineage[0].baseline_financial_fact_id == "ff24"
    assert "FORECAST / HYPOTHESIS" in outcome.markdown
    db.close()


def test_optional_earnings_maps_to_partial_success(tmp_path):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    assert outcome.status == "partial_success"
    status = {x.component: x.status for x in outcome.component_statuses}
    assert status["earnings_expectation"] == "insufficient_evidence"
    assert "No Catalyst object is referenced by the accepted Phase4 baseline." in outcome.markdown
    assert "No Risk object is referenced by the accepted Phase4 baseline." in outcome.markdown
    assert "None in accepted Phase4 baseline." not in outcome.markdown
    db.close()


def test_idempotency_canonicalizes_assumption_reference_order(tmp_path):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db); _seed_financial(db)
    first_input = _earnings_input(); first_input["assumptions"][0]["source_ref_ids"] = ["b", "a"]
    second_input = deepcopy(first_input); second_input["assumptions"][0]["source_ref_ids"] = ["a", "b"]
    a = FirstCoveragePipeline(tmp_path, db).run(_request(earnings_expectation=first_input))
    b = FirstCoveragePipeline(tmp_path, db).run(_request(earnings_expectation=second_input))
    assert a.idempotency_key == b.idempotency_key
    semantic_change = deepcopy(second_input)
    semantic_change["assumptions"][0]["value"] = "0.11"
    c = FirstCoveragePipeline(tmp_path, db).run(
        _request(earnings_expectation=semantic_change))
    assert c.idempotency_key != a.idempotency_key
    changed = FirstCoveragePipeline(tmp_path, db).run(_request(industry_id="industry:other", earnings_expectation=second_input))
    assert changed.idempotency_key != a.idempotency_key
    db.close()


def test_pipeline_has_no_phase4_markdown_or_full_pipeline_dependency():
    root = Path(__file__).parents[2]
    pipeline_text = (root / "src/research_os/first_coverage/pipeline.py").read_text("utf-8")
    text = pipeline_text + "\n" + (
        root / "src/research_os/orchestrator/runners/first_coverage.py"
    ).read_text("utf-8")
    assert "EquityResearchPipeline" not in text
    assert "report_path" not in pipeline_text
    assert "GraphQueryService" not in text
    assert "IndustryResearchScenarioRunner" not in text
    assert "EarningsExpectationScenarioRunner" not in text
    assert "Orchestrator(" not in text


def _mock_industry(monkeypatch, *, status, missing_data, covered, missing):
    def fake_industry(*args, **kwargs):
        return SimpleNamespace(
            status=status, run_id="industry-component", findings=[], warnings=[],
            missing_data=missing_data, dimensions_covered=covered,
            dimensions_missing=missing, evidence_quality={},
        )

    monkeypatch.setattr(
        "research_os.first_coverage.pipeline.IndustryResearchPipeline.run",
        fake_industry,
    )


def test_industry_dimension_coverage_gap_maps_to_partial_success(
    tmp_path, monkeypatch,
):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    _mock_industry(
        monkeypatch, status="degraded", missing_data=[],
        covered=["key_metrics"], missing=["open_questions"],
    )
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    statuses = {item.component: item.status for item in outcome.component_statuses}
    assert outcome.industry_outcome.status == "degraded"
    assert statuses["industry_research"] == "partial_success"
    assert outcome.status == "partial_success"
    db.close()


def test_industry_infrastructure_degradation_maps_to_degraded(
    tmp_path, monkeypatch,
):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    _mock_industry(
        monkeypatch, status="degraded",
        missing_data=["knowledge_graph_unavailable"],
        covered=["key_metrics"], missing=["open_questions"],
    )
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    statuses = {item.component: item.status for item in outcome.component_statuses}
    assert statuses["industry_research"] == "degraded"
    assert outcome.status == "degraded"
    db.close()


def test_industry_insufficient_maps_parent_to_partial_success(tmp_path, monkeypatch):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    _mock_industry(
        monkeypatch, status="insufficient_evidence", missing_data=[],
        covered=[], missing=["key_metrics"],
    )
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    statuses = {item.component: item.status for item in outcome.component_statuses}
    assert statuses["industry_research"] == "insufficient_evidence"
    assert outcome.status == "partial_success"
    db.close()


def test_industry_failed_preserves_raw_status_and_maps_to_degraded(
    tmp_path, monkeypatch,
):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)
    _mock_industry(
        monkeypatch, status="failed", missing_data=["industry_failure"],
        covered=[], missing=[],
    )
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    component = next(
        item for item in outcome.component_statuses
        if item.component == "industry_research")
    assert outcome.industry_outcome.status == "failed"
    assert component.status == "degraded"
    assert any("raw status=failed" in warning for warning in component.warnings)
    assert any("raw status=failed" in warning for warning in outcome.warnings)
    assert outcome.status == "degraded"
    db.close()


def test_component_as_of_propagation(tmp_path, monkeypatch):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db); _seed_financial(db)
    captured = {}

    def fake_industry(_self, payload):
        captured["industry"] = payload["as_of"]
        return SimpleNamespace(
            status="success", run_id="industry-component", findings=[], warnings=[],
            missing_data=[], dimensions_covered=[], dimensions_missing=[],
            evidence_quality={},
        )

    def fake_earnings(_self, request):
        captured["earnings"] = request.as_of
        return SimpleNamespace(
            status="success", run_id="earnings-component", scenarios=[],
            projection_lineage=[], evidence_ids=[], warnings=[], missing_data=[],
            idempotency_key="earnings-key",
        )

    monkeypatch.setattr(
        "research_os.first_coverage.pipeline.IndustryResearchPipeline.run",
        fake_industry,
    )
    monkeypatch.setattr(
        "research_os.first_coverage.pipeline.EarningsExpectationPipeline.run",
        fake_earnings,
    )
    FirstCoveragePipeline(tmp_path, db).run(
        _request(earnings_expectation=_earnings_input()))
    assert captured == {"industry": AS_OF, "earnings": AS_OF}
    db.close()


def test_industry_fact_is_downgraded_when_authoritative_evidence_fails(
    tmp_path, monkeypatch,
):
    db = _db(tmp_path); _seed_profiles(db); _seed_phase4(db)

    def fake_industry(_self, payload):
        return SimpleNamespace(
            status="success", run_id="industry-component",
            findings=[{
                "dimension_id": "key_metrics", "judgment": "FACT",
                "summary": "Future-only metric", "evidence_ids": ["missing-evidence"],
            }],
            warnings=[], missing_data=[], dimensions_covered=["key_metrics"],
            dimensions_missing=[], evidence_quality={},
        )

    monkeypatch.setattr(
        "research_os.first_coverage.pipeline.IndustryResearchPipeline.run",
        fake_industry,
    )
    outcome = FirstCoveragePipeline(tmp_path, db).run(_request())
    assert outcome.industry_outcome.status == "success"
    assert outcome.industry_outcome.findings[0]["judgment"] == "INSUFFICIENT_EVIDENCE"
    assert "Future-only metric" not in outcome.markdown
    assert "missing-evidence" not in outcome.evidence_ids
    db.close()
