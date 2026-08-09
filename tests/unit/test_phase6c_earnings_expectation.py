"""Phase 6C earnings expectation governance and deterministic forecast tests."""
from __future__ import annotations

from copy import deepcopy
import json
from uuid import NAMESPACE_DNS, uuid5

import pytest
from pydantic import ValidationError

from research_os.earnings_expectation.pipeline import (
    HistoricalInputResolver,
    idempotency_key,
    EarningsExpectationPipeline,
    _validated_assumptions,
)
from research_os.equity_research.forecast import FORECAST_RULES_VERSION
from research_os.models import (
    EarningsExpectationRequest,
    Evidence,
    FinancialFact,
    FinancialReport,
)
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance, validate_model


COMPANY = "company:600000.SH"
AS_OF = "2025-08-01T12:00:00+08:00"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"phase6c-test:{label}"))


def _db(tmp_path) -> Database:
    db = Database(tmp_path / "research.db")
    db.initialize()
    return db


def _evidence(
    eid: str, published: str, tier: str = "A",
    evidence_type: str = "official_disclosure",
    access_status: str = "ok",
) -> Evidence:
    return Evidence(
        evidence_id=_uuid(f"evidence:{eid}"),
        source_id="cninfo",
        raw_item_id=_uuid(f"raw:{eid}"),
        title="official financial evidence",
        publisher="listed company",
        published_at=published,
        retrieved_at=published,
        url=f"https://example.test/{eid}",
        excerpt="revenue disclosure",
        evidence_type=evidence_type,
        independence_group=f"report:{eid}",
        source_tier=tier,
        access_status=access_status,
    )


def _report(
    rid: str, period_end: str, published: str, *, company: str = COMPANY,
    fiscal_period: str = "FY", restatement: str = "original", version: int = 1,
) -> FinancialReport:
    year = int(period_end[:4])
    return FinancialReport(
        financial_report_id=rid,
        company_entity_id=company,
        document_id=f"doc-{rid}",
        manifest_id=None,
        report_type="annual" if fiscal_period == "FY" else "interim",
        period_start=f"{year}-01-01",
        period_end=period_end,
        fiscal_year=year,
        fiscal_period=fiscal_period,
        duration_months=12 if fiscal_period == "FY" else 6,
        statement_scope="consolidated",
        accounting_standard="CAS",
        currency="CNY",
        unit_scale=1,
        audit_status="audited" if fiscal_period == "FY" else "reviewed",
        audit_opinion="unmodified" if fiscal_period == "FY" else "unknown",
        restatement_status=restatement,
        supersedes_report_id=None,
        filing_version=f"v{version}",
        source_ids=["cninfo"],
        evidence_ids=[],
        data_status="complete",
        version=version,
        published_at=published,
        created_at=published,
    )


def _fact(
    fid: str, rid: str, period_end: str, published: str, value: str,
    evidence_id: str, *, company: str = COMPANY, restatement_version: int = 1,
    source_priority: int = 1, version: int = 1,
) -> FinancialFact:
    year = period_end[:4]
    return FinancialFact(
        fact_id=fid,
        fact_key=f"revenue|{period_end}|consolidated",
        financial_report_id=rid,
        company_entity_id=company,
        statement_type="income_statement",
        taxonomy_code="revenue",
        label_raw="revenue",
        period_start=f"{year}-01-01",
        period_end=period_end,
        instant_or_duration="duration",
        period_basis="reported_period",
        statement_scope="consolidated",
        currency="CNY",
        unit_scale=1,
        raw_value=value,
        normalized_value=value,
        normalized_unit="yuan",
        value_status="reported",
        sign_convention="reported",
        audit_status="audited",
        segment_id=None,
        source_document_id=f"doc-{rid}",
        source_block_ids=[f"block-{fid}"],
        evidence_ids=[_uuid(f"evidence:{evidence_id}")],
        source_priority=source_priority,
        restatement_version=restatement_version,
        valid_from=published,
        valid_to=None,
        conflict_group_id=None,
        warnings=[],
        version=version,
        created_at=published,
    )


def _seed_period(
    db: Database, rid: str, fid: str, eid: str, period_end: str,
    published: str, value: str, *, fiscal_period: str = "FY",
) -> None:
    evidence = _evidence(eid, published)
    report = _report(rid, period_end, published, fiscal_period=fiscal_period)
    fact = _fact(fid, rid, period_end, published, value, eid)
    assert validate_instance(evidence.model_dump(), "evidence") == []
    assert validate_instance(report.model_dump(), "financial_report") == []
    assert validate_instance(fact.model_dump(), "financial_fact") == []
    db.upsert(evidence)
    db.upsert(report)
    db.upsert(fact)


def _request(**overrides) -> EarningsExpectationRequest:
    data = {
        "request_id": "req-1",
        "task_id": "task-1",
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
            "invalidates_when": "new disclosure changes the growth premise",
            "known_at": "2025-08-01T10:00:00+08:00",
        }],
        "requested_at": AS_OF,
    }
    data.update(overrides)
    return EarningsExpectationRequest(**data)


def test_request_and_run_schema_registry_roundtrip(tmp_path):
    request = _request()
    assert validate_model(request) == []
    assert validate_instance(request.model_dump(), "earnings_expectation_request") == []


def test_request_rejects_future_known_assumption():
    assumptions = deepcopy(_request().model_dump()["assumptions"])
    assumptions[0]["known_at"] = "2025-08-02T00:00:00+08:00"
    with pytest.raises(ValidationError, match="known_at"):
        _request(assumptions=assumptions)


def test_user_input_requires_explicit_known_at():
    assumptions = deepcopy(_request().model_dump()["assumptions"])
    assumptions[0]["known_at"] = None
    with pytest.raises(ValidationError, match="requires explicit known_at"):
        _request(assumptions=assumptions)


@pytest.mark.parametrize("periods", [
    ["2025FY", "FY2026"],
    ["FY2025", "FY2027"],
    ["FY2026", "FY2025"],
])
def test_request_rejects_invalid_or_nonconsecutive_fy_labels(periods):
    with pytest.raises(ValidationError):
        _request(forecast_period={
            "start": "2025-01-01", "end": "2026-12-31", "periods": periods,
        })


@pytest.mark.parametrize(("field", "value"), [
    ("timezone", "UTC"),
    ("historical_selection_policy", "latest_report"),
    ("source_policy", "anything_available"),
])
def test_request_rejects_policy_override(field, value):
    with pytest.raises(ValidationError):
        _request(**{field: value})


@pytest.mark.parametrize(
    "mutation",
    [
        {"forecast_period": {
            "start": "2025-01-01", "end": "2026-12-31",
            "periods": ["2025H1", "FY2026"],
        }},
        {"timezone": "UTC"},
        {"historical_selection_policy": "use_future_data"},
        {"source_policy": "uncontrolled"},
        {"unexpected_property": True},
    ],
)
def test_request_pydantic_and_json_schema_negative_parity(mutation):
    payload = _request().model_dump()
    payload.update(mutation)
    with pytest.raises(ValidationError):
        EarningsExpectationRequest(**payload)
    assert validate_instance(payload, "earnings_expectation_request")


def test_request_rejects_inverted_forecast_period():
    with pytest.raises(ValidationError, match="start"):
        _request(forecast_period={
            "start": "2026-01-01", "end": "2025-12-31", "periods": ["FY2025"],
        })


def test_request_rejects_non_numeric_assumption_value():
    assumptions = deepcopy(_request().model_dump()["assumptions"])
    assumptions[0]["value"] = "not-a-number"
    with pytest.raises(ValidationError, match="value"):
        _request(assumptions=assumptions)


def test_three_time_happy_path_uses_phase4_projection(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r23", "f23", "e23", "2023-12-31", "2024-03-30T10:00:00+08:00", "80")
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    outcome = EarningsExpectationPipeline(db).run(_request())
    assert outcome.status == "success"
    assert [p.period_label for p in outcome.historical_input_periods] == ["2023FY", "2024FY"]
    assert [o.value for o in outcome.scenarios[0].outputs] == ["110", "121"]
    assert [o.period for o in outcome.scenarios[0].outputs] == ["FY2025", "FY2026"]
    assert all(o.formula_version == FORECAST_RULES_VERSION for o in outcome.scenarios[0].outputs)
    assert all(a.claim_type == "HYPOTHESIS" for a in outcome.scenarios[0].assumptions)
    lineage = outcome.projection_lineage[0]
    assert lineage.baseline_financial_report_id == "r24"
    assert lineage.baseline_financial_fact_id == "f24"
    assert lineage.output_periods == ["FY2025", "FY2026"]
    db.close()


def test_interim_report_cannot_replace_comparable_annual_baseline(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    _seed_period(
        db, "r25h1", "f25h1", "e25h1", "2025-06-30",
        "2025-07-30T10:00:00+08:00", "60", fiscal_period="H1",
    )
    outcome = EarningsExpectationPipeline(db).run(_request())
    assert outcome.status == "success"
    assert [o.value for o in outcome.scenarios[0].outputs] == ["110", "121"]
    assert outcome.projection_lineage[0].baseline_financial_fact_id == "f24"
    assert outcome.projection_lineage[0].baseline_fiscal_period == "FY"
    db.close()


def test_forecast_must_start_after_latest_comparable_fy_baseline(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r25", "f25", "e25", "2025-12-31", "2026-03-30T10:00:00+08:00", "120")
    outcome = EarningsExpectationPipeline(db).run(
        _request(as_of="2026-08-01T12:00:00+08:00")
    )
    assert outcome.status == "insufficient_evidence"
    assert outcome.scenarios == []
    assert "forecast_period_not_after_comparable_baseline" in outcome.missing_data
    db.close()


def test_future_report_never_leaks_into_historical_inputs(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    _seed_period(db, "r25", "f25", "e25", "2025-12-31", "2026-03-30T10:00:00+08:00", "120")
    periods, facts, _ = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assert [p.financial_report_ids for p in periods] == [["r24"]]
    assert [f["fact_id"] for f in facts] == ["f24"]
    db.close()


def test_same_db_different_as_of_changes_eligible_set(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r23", "f23", "e23", "2023-12-31", "2024-03-30T10:00:00+08:00", "80")
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    early, _, _ = HistoricalInputResolver(db).resolve(COMPANY, "2025-02-01T00:00:00+08:00")
    late, _, _ = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assert len(early) == 1
    assert len(late) == 2
    db.close()


def test_wrong_company_and_broken_evidence_are_excluded(tmp_path):
    db = _db(tmp_path)
    db.upsert(_report("wrong", "2024-12-31", "2025-03-01T00:00:00+08:00", company="company:other"))
    db.upsert(_fact("wrong-f", "wrong", "2024-12-31", "2025-03-01T00:00:00+08:00", "9", "none", company="company:other"))
    db.upsert(_report("broken", "2024-12-31", "2025-03-01T00:00:00+08:00"))
    db.upsert(_fact("broken-f", "broken", "2024-12-31", "2025-03-01T00:00:00+08:00", "100", "missing"))
    periods, _, warnings = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assert periods == []
    assert any("missing evidence" in warning for warning in warnings)
    db.close()


@pytest.mark.parametrize(
    ("table", "primary_key", "primary_value"),
    [
        ("financial_reports", "financial_report_id", "r24"),
        ("financial_facts", "fact_id", "f24"),
    ],
)
def test_corrupt_financial_payloads_fail_closed_on_strict_reload(
    tmp_path, table, primary_key, primary_value,
):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    payload = db.get(table, primary_value)
    payload["unexpected_field"] = "attack"
    db._conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {primary_key} = ?",
        (json.dumps(payload), primary_value),
    )
    db._conn.commit()
    periods, facts, warnings = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assert periods == [] and facts == []
    assert any("raw Schema validation failed" in warning for warning in warnings)
    db.close()


@pytest.mark.parametrize(
    ("table", "primary_key", "primary_value", "field", "model_type", "schema_name", "default"),
    [
        (
            "evidence", "evidence_id", _uuid("evidence:e24"), "source_tier",
            Evidence, "evidence", "B",
        ),
        (
            "evidence", "evidence_id", _uuid("evidence:e24"), "access_status",
            Evidence, "evidence", "ok",
        ),
        (
            "financial_reports", "financial_report_id", "r24", "data_status",
            FinancialReport, "financial_report", "complete",
        ),
        (
            "financial_facts", "fact_id", "f24", "value_status",
            FinancialFact, "financial_fact", "reported",
        ),
    ],
)
def test_default_maskable_raw_corruption_fails_closed_in_pipeline(
    tmp_path, table, primary_key, primary_value, field, model_type, schema_name, default,
):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    payload = db.get(table, primary_value)
    del payload[field]
    assert validate_instance(payload, schema_name)
    assert model_type(**payload).model_dump()[field] == default
    db._conn.execute(
        f"UPDATE {table} SET payload = ? WHERE {primary_key} = ?",
        (json.dumps(payload), primary_value),
    )
    db._conn.commit()

    outcome = EarningsExpectationPipeline(db).run(_request())

    assert outcome.status == "insufficient_evidence"
    assert outcome.scenarios == []
    assert outcome.projection_lineage == []
    assert any("raw Schema validation failed" in warning for warning in outcome.warnings)
    db.close()


def test_schema_invalid_evidence_is_rejected_after_database_reload(tmp_path):
    db = _db(tmp_path)
    evidence = _evidence("corrupt", "2025-07-01T00:00:00+08:00")
    db.upsert(evidence)
    payload = db.get("evidence", evidence.evidence_id)
    payload["raw_item_id"] = "not-a-schema-uuid"
    db._conn.execute(
        "UPDATE evidence SET payload = ? WHERE evidence_id = ?",
        (json.dumps(payload), evidence.evidence_id),
    )
    db._conn.commit()
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": "company_guidance",
        "source_ref_ids": ["guidance-1"], "evidence_ids": [evidence.evidence_id],
        "confidence": 0.6, "invalidates_when": "guidance changes", "known_at": None,
    }])
    assumptions, warnings = _validated_assumptions(request, db, [])
    assert assumptions == []
    assert any("schema-invalid evidence" in warning for warning in warnings)
    db.close()


@pytest.mark.parametrize(
    ("evidence_type", "tier", "access_status", "published"),
    [
        ("unknown", "A", "ok", "2025-03-30T10:00:00+08:00"),
        ("official_disclosure", "C", "ok", "2025-03-30T10:00:00+08:00"),
        ("official_disclosure", "A", "partial", "2025-03-30T10:00:00+08:00"),
        ("official_disclosure", "A", "ok", "2025-08-02T10:00:00+08:00"),
    ],
)
def test_ineligible_financial_evidence_cannot_support_baseline(
    tmp_path, evidence_type, tier, access_status, published,
):
    db = _db(tmp_path)
    evidence = _evidence(
        "financial-gate", published, tier=tier,
        evidence_type=evidence_type, access_status=access_status,
    )
    report = _report("r24", "2024-12-31", "2025-03-30T10:00:00+08:00")
    fact = _fact(
        "f24", "r24", "2024-12-31", "2025-03-30T10:00:00+08:00",
        "100", "financial-gate",
    )
    db.upsert(evidence)
    db.upsert(report)
    db.upsert(fact)
    outcome = EarningsExpectationPipeline(db).run(_request())
    assert outcome.status == "insufficient_evidence"
    assert outcome.scenarios == []
    assert any("fact f24" in warning for warning in outcome.warnings)
    db.close()


def test_equal_rank_conflicting_facts_cannot_be_baseline(tmp_path):
    db = _db(tmp_path)
    db.upsert(_evidence("e1", "2025-03-01T00:00:00+08:00"))
    db.upsert(_evidence("e2", "2025-03-01T00:00:00+08:00"))
    db.upsert(_report("r", "2024-12-31", "2025-03-01T00:00:00+08:00"))
    db.upsert(_fact("f1", "r", "2024-12-31", "2025-03-01T00:00:00+08:00", "100", "e1"))
    second = _fact("f2", "r", "2024-12-31", "2025-03-01T00:00:00+08:00", "101", "e2")
    second.source_document_id = "doc-r-alternate"
    db.upsert(second)
    periods, facts, warnings = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assert periods == [] and facts == []
    assert any("conflict" in warning for warning in warnings)
    db.close()


@pytest.mark.parametrize("source_type", ["company_guidance", "external_opinion"])
def test_future_assumption_evidence_is_rejected(tmp_path, source_type):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    evidence_type = "official_disclosure" if source_type == "company_guidance" else "news_report"
    db.upsert(_evidence("future", "2025-08-02T00:00:00+08:00", evidence_type=evidence_type))
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": source_type, "source_ref_ids": ["op-1"],
        "evidence_ids": [_uuid("evidence:future")], "confidence": 0.5,
        "invalidates_when": "guidance changes", "known_at": None,
    }])
    periods, _, _ = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assumptions, warnings = _validated_assumptions(request, db, periods)
    assert assumptions == []
    assert any("after as_of" in warning for warning in warnings)
    db.close()


def test_model_generated_assumption_without_call_is_rejected(tmp_path):
    db = _db(tmp_path)
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "999999", "unit": "ratio",
        "period": "annual", "source_type": "model_generated", "source_ref_ids": ["fake"],
        "evidence_ids": [], "confidence": 0.5, "invalidates_when": "never", "known_at": None,
    }])
    assumptions, warnings = _validated_assumptions(request, db, [])
    assert assumptions == []
    assert warnings == ["model_generated assumption rejected: llm_called=false"]
    db.close()


@pytest.mark.parametrize(
    ("source_type", "tier", "expected_claim"),
    [("company_guidance", "A", "SOURCE_OPINION"),
     ("external_opinion", "B", "SOURCE_OPINION")],
)
def test_source_assumption_with_authoritative_evidence_is_accepted(
    tmp_path, source_type, tier, expected_claim,
):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    evidence_type = "official_disclosure" if source_type == "company_guidance" else "institution_material"
    db.upsert(_evidence(
        "assumption-evidence", "2025-07-01T00:00:00+08:00",
        tier=tier, evidence_type=evidence_type,
    ))
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": source_type,
        "source_ref_ids": ["source-opinion-1"],
        "evidence_ids": [_uuid("evidence:assumption-evidence")],
        "confidence": 0.6, "invalidates_when": "source revises its expectation", "known_at": None,
    }])
    outcome = EarningsExpectationPipeline(db).run(request)
    assert outcome.status == "success"
    assumption = outcome.scenarios[0].assumptions[0]
    assert assumption.claim_type == expected_claim
    assert assumption.evidence_ids == [_uuid("evidence:assumption-evidence")]
    db.close()


@pytest.mark.parametrize(
    ("source_type", "evidence_type", "tier"),
    [
        ("company_guidance", "official_disclosure", "A"),
        ("company_guidance", "company_official", "A"),
        ("external_opinion", "institution_material", "B"),
        ("external_opinion", "news_report", "B"),
        ("external_opinion", "media_report", "B"),
    ],
)
def test_source_type_evidence_allowlists_accept_all_supported_types(
    tmp_path, source_type, evidence_type, tier,
):
    db = _db(tmp_path)
    evidence = _evidence(
        f"accepted-{evidence_type}", "2025-07-01T00:00:00+08:00",
        tier=tier, evidence_type=evidence_type,
    )
    db.upsert(evidence)
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": source_type,
        "source_ref_ids": ["source-1"], "evidence_ids": [evidence.evidence_id],
        "confidence": 0.6, "invalidates_when": "source changes", "known_at": None,
    }])
    assumptions, warnings = _validated_assumptions(request, db, [])
    assert len(assumptions) == 1
    assert warnings == []
    db.close()


@pytest.mark.parametrize(
    ("source_type", "evidence_type", "tier", "access_status"),
    [
        ("company_guidance", "news_report", "A", "ok"),
        ("company_guidance", "official_disclosure", "B", "ok"),
        ("company_guidance", "official_disclosure", "A", "partial"),
        ("external_opinion", "official_disclosure", "A", "ok"),
        ("external_opinion", "institution_material", "C", "ok"),
        ("external_opinion", "institution_material", "B", "failed"),
    ],
)
def test_source_assumption_rejects_wrong_type_tier_or_access(
    tmp_path, source_type, evidence_type, tier, access_status,
):
    db = _db(tmp_path)
    evidence = _evidence(
        "gated", "2025-07-01T00:00:00+08:00", tier=tier,
        evidence_type=evidence_type, access_status=access_status,
    )
    db.upsert(evidence)
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": source_type,
        "source_ref_ids": ["source-1"], "evidence_ids": [evidence.evidence_id],
        "confidence": 0.6, "invalidates_when": "source changes", "known_at": None,
    }])
    assumptions, warnings = _validated_assumptions(request, db, [])
    assert assumptions == []
    assert warnings
    db.close()


@pytest.mark.parametrize(("period", "unit", "code"), [
    ("half_year", "ratio", "growth_period_not_annual"),
    ("annual", "percent", "growth_unit_not_ratio"),
])
def test_growth_assumption_requires_annual_ratio(tmp_path, period, unit, code):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    assumptions = deepcopy(_request().model_dump()["assumptions"])
    assumptions[0]["period"] = period
    assumptions[0]["unit"] = unit
    outcome = EarningsExpectationPipeline(db).run(_request(assumptions=assumptions))
    assert outcome.status == "insufficient_evidence"
    assert outcome.scenarios == []
    assert code in outcome.missing_data
    db.close()


@pytest.mark.parametrize("reverse", [False, True])
def test_multiple_growth_assumptions_fail_as_ambiguous_in_any_order(tmp_path, reverse):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    assumptions = deepcopy(_request().model_dump()["assumptions"])
    second = deepcopy(assumptions[0])
    second["value"] = "0.20"
    values = [assumptions[0], second]
    if reverse:
        values.reverse()
    outcome = EarningsExpectationPipeline(db).run(_request(assumptions=values))
    assert outcome.status == "insufficient_evidence"
    assert outcome.scenarios == []
    assert "ambiguous_growth_assumptions" in outcome.missing_data
    db.close()


def test_deterministic_extrapolation_is_hypothesis_with_historical_lineage(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    request = _request(assumptions=[{
        "driver": "revenue_growth", "value": "0.1", "unit": "ratio",
        "period": "annual", "source_type": "deterministic_extrapolation",
        "source_ref_ids": ["deterministic_projection_v1"], "evidence_ids": [],
        "confidence": 0.5, "invalidates_when": "historical relationship changes", "known_at": None,
    }])
    outcome = EarningsExpectationPipeline(db).run(request)
    assumption = outcome.scenarios[0].assumptions[0]
    assert assumption.claim_type == "HYPOTHESIS"
    assert "f24" in assumption.source_ref_ids
    assert assumption.evidence_ids == [_uuid("evidence:e24")]
    db.close()


def test_pipeline_validates_scenario_without_orphan_database_write(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    outcome = EarningsExpectationPipeline(db).run(_request())
    scenario = outcome.scenarios[0]
    assert validate_instance(scenario.model_dump(), "forecast_scenario") == []
    assert db.get("forecast_scenarios", scenario.scenario_id) is None
    db.close()


def test_report_body_has_no_forecast_as_fact_or_prohibited_output(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    outcome = EarningsExpectationPipeline(db).run(_request())
    text = outcome.markdown
    assert "HYPOTHESIS" in text
    for required in (
        "## Historical Projection Baseline", "Baseline report: r24",
        "Baseline fact: f24", "## Assumptions & Sources", "Formula version:",
        "## Evidence Lineage", "## Invalidation Conditions",
    ):
        assert required in text
    for forbidden in ("目标价", "买入评级", "卖出评级", "建议买入", "建议卖出", "仓位建议"):
        assert forbidden not in text
    db.close()


def test_no_history_is_insufficient_not_failed(tmp_path):
    db = _db(tmp_path)
    outcome = EarningsExpectationPipeline(db).run(_request())
    assert outcome.status == "insufficient_evidence"
    assert "eligible_historical_financial_inputs" in outcome.missing_data
    db.close()


def test_idempotency_changes_with_semantic_input(tmp_path):
    db = _db(tmp_path)
    _seed_period(db, "r24", "f24", "e24", "2024-12-31", "2025-03-30T10:00:00+08:00", "100")
    request = _request()
    periods, _, _ = HistoricalInputResolver(db).resolve(COMPANY, AS_OF)
    assumptions, _ = _validated_assumptions(request, db, periods)
    first = idempotency_key(request, periods, assumptions)
    assert first == idempotency_key(request, periods, assumptions)
    changed = _request(forecast_period={
        "start": "2025-01-01", "end": "2027-12-31", "periods": ["FY2025", "FY2026", "FY2027"],
    })
    assert first != idempotency_key(changed, periods, assumptions)
    assumption_payloads = deepcopy(request.model_dump()["assumptions"])
    other = deepcopy(assumption_payloads[0])
    other.update({
        "driver": "gross_margin", "value": "0.30",
        "source_ref_ids": ["b", "a", "a"],
    })
    assumption_payloads[0]["source_ref_ids"] = ["z", "y"]
    ordered = _request(assumptions=[assumption_payloads[0], other])
    reordered = _request(assumptions=[deepcopy(other), deepcopy(assumption_payloads[0])])
    ordered_valid, _ = _validated_assumptions(ordered, db, periods)
    reordered_valid, _ = _validated_assumptions(reordered, db, list(reversed(periods)))
    assert idempotency_key(ordered, periods, ordered_valid) == idempotency_key(
        reordered, list(reversed(periods)), reordered_valid,
    )
    renamed = _request(scenario_name="stress")
    assert first != idempotency_key(renamed, periods, assumptions)
    changed_known = deepcopy(request.model_dump()["assumptions"])
    changed_known[0]["known_at"] = "2025-07-31T10:00:00+08:00"
    known_request = _request(assumptions=changed_known)
    known_assumptions, _ = _validated_assumptions(known_request, db, periods)
    assert first != idempotency_key(known_request, periods, known_assumptions)
    db.close()
