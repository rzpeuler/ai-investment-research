"""Earnings expectation orchestration over Phase 4 forecast primitives.

This module owns time governance and lineage assembly.  It intentionally owns
no forecast arithmetic: all numeric projections use the Phase 4 primitive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import ValidationError

from research_os.equity_research.forecast import (
    FORECAST_RULES_VERSION,
    AssumptionInput,
    ScenarioInput,
    build_scenario,
    deterministic_projection,
)
from research_os.models import (
    Evidence,
    EarningsExpectationRequest,
    FinancialFact,
    FinancialReport,
    ForecastScenario,
    HistoricalInputPeriod,
)
from research_os.models.phase6c import ProjectionLineage
from research_os.storage import Database
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_instance


PIPELINE_VERSION = "1.0.0"
ELIGIBLE_GUIDANCE_TIERS = {"S", "A"}
ELIGIBLE_OPINION_TIERS = {"S", "A", "B"}
GUIDANCE_EVIDENCE_TYPES = {"official_disclosure", "company_official"}
OPINION_EVIDENCE_TYPES = {"institution_material", "news_report", "media_report"}
FINANCIAL_EVIDENCE_TYPES = {
    "official_disclosure", "company_official", "institution_material", "manual_input",
}


@dataclass
class GovernedAssumptionInput(AssumptionInput):
    """Phase 4 assumption input plus S3 knowledge-time audit metadata."""

    known_at: Optional[str] = None


@dataclass
class EarningsExpectationOutcome:
    run_id: str
    status: str
    historical_input_periods: List[HistoricalInputPeriod] = field(default_factory=list)
    scenarios: List[ForecastScenario] = field(default_factory=list)
    projection_lineage: List[ProjectionLineage] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    error_codes: List[str] = field(default_factory=list)
    stage_statuses: List[Dict[str, Any]] = field(default_factory=list)
    idempotency_key: str = ""
    markdown: str = ""


def _strict_reload_payload(
    raw: Any,
    model_type: Type[Any],
    schema_name: str,
) -> Tuple[Optional[dict], Optional[str]]:
    """Validate persisted authority before construction can supply defaults."""
    raw_errors = validate_instance(raw, schema_name)
    if raw_errors:
        return None, f"raw Schema validation failed: {raw_errors}"
    try:
        model = model_type(**raw)
    except (TypeError, ValidationError, ValueError) as exc:
        return None, f"Pydantic validation failed: {exc}"
    payload = model.model_dump()
    roundtrip_errors = validate_instance(payload, schema_name)
    if roundtrip_errors:
        return None, f"roundtrip Schema validation failed: {roundtrip_errors}"
    return payload, None


def _strict_company_payloads(
    db: Database,
    table: str,
    company_entity_id: str,
    model_type: Type[Any],
    schema_name: str,
) -> Tuple[List[dict], List[str]]:
    """Reload structured company rows through raw Schema and model roundtrip."""
    if table not in {"financial_reports", "financial_facts"}:
        raise ValueError(f"unsupported financial authority table: {table}")
    payloads: List[dict] = []
    warnings: List[str] = []
    rows = db.query(
        f"SELECT payload FROM {table} WHERE company_entity_id = ?",
        (company_entity_id,),
    )
    for index, row in enumerate(rows):
        try:
            value = json.loads(row["payload"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            warnings.append(f"{table} row {index}: invalid JSON payload: {exc}")
            continue
        payload, error = _strict_reload_payload(value, model_type, schema_name)
        if error:
            warnings.append(f"{table} row {index}: {error}")
            continue
        assert payload is not None
        payloads.append(payload)
    return payloads, warnings


def _not_after(timestamp: Optional[str], as_of: str) -> bool:
    if not timestamp:
        return False
    try:
        return parse_iso(timestamp) <= parse_iso(as_of)
    except ValueError:
        return False


def _period_label(report: dict) -> str:
    year = report.get("fiscal_year")
    period = report.get("fiscal_period") or report.get("report_type") or "OTHER"
    return f"{year}{period}" if year else str(report.get("period_end") or period)


def _report_rank(report: dict) -> Tuple[int, int, int, str]:
    restatement = {"restated": 3, "original": 2, "superseded": 1}.get(
        report.get("restatement_status"), 0
    )
    return (
        restatement,
        int(report.get("version") or 1),
        1 if report.get("audit_status") == "audited" else 0,
        str(report.get("published_at") or ""),
    )


def _evidence_eligible(
    db: Database,
    evidence_ids: List[str],
    as_of: str,
    eligible_tiers: set[str],
    eligible_types: set[str],
) -> Tuple[List[str], List[str]]:
    eligible: List[str] = []
    warnings: List[str] = []
    for evidence_id in dict.fromkeys(evidence_ids):
        evidence = db.get("evidence", evidence_id)
        if evidence is None:
            warnings.append(f"missing evidence: {evidence_id}")
            continue
        evidence, error = _strict_reload_payload(evidence, Evidence, "evidence")
        if error:
            warnings.append(f"schema-invalid evidence {evidence_id}: {error}")
            continue
        assert evidence is not None
        if evidence["access_status"] != "ok":
            warnings.append(f"ineligible evidence access: {evidence_id}")
            continue
        if evidence["source_tier"] not in eligible_tiers:
            warnings.append(f"ineligible evidence tier: {evidence_id}")
            continue
        if evidence["evidence_type"] not in eligible_types:
            warnings.append(f"ineligible evidence type: {evidence_id}")
            continue
        if not _not_after(evidence["published_at"], as_of):
            warnings.append(f"evidence after as_of: {evidence_id}")
            continue
        eligible.append(evidence_id)
    return eligible, warnings


class HistoricalInputResolver:
    """Select the financial knowledge that was available at an explicit cutoff."""

    def __init__(self, db: Database):
        self.db = db

    def resolve(
        self, company_entity_id: str, as_of: str,
    ) -> Tuple[List[HistoricalInputPeriod], List[dict], List[str]]:
        report_payloads, report_warnings = _strict_company_payloads(
            self.db, "financial_reports", company_entity_id,
            FinancialReport, "financial_report",
        )
        reports = [
            report for report in report_payloads
            if report.get("company_entity_id") == company_entity_id
            and report.get("data_status") in {"complete", "partial"}
            and _not_after(report.get("published_at"), as_of)
            and str(report.get("period_end") or "9999-99-99") <= as_of[:10]
        ]

        # One authoritative report version per economic period and statement scope.
        grouped_reports: Dict[Tuple[str, str, str], List[dict]] = {}
        for report in reports:
            key = (
                str(report.get("period_end")), str(report.get("statement_scope")),
                str(report.get("report_type")),
            )
            grouped_reports.setdefault(key, []).append(report)
        selected_reports = [
            max(group, key=_report_rank) for group in grouped_reports.values()
        ]
        report_by_id = {r["financial_report_id"]: r for r in selected_reports}

        fact_payloads, fact_warnings = _strict_company_payloads(
            self.db, "financial_facts", company_entity_id,
            FinancialFact, "financial_fact",
        )
        facts = [
            fact for fact in fact_payloads
            if fact.get("company_entity_id") == company_entity_id
            and fact.get("financial_report_id") in report_by_id
            and str(fact.get("period_end") or "9999-99-99") <= as_of[:10]
            and _not_after(fact.get("valid_from"), as_of)
            and not _not_after(fact.get("valid_to"), as_of)
            and fact.get("value_status") in {"reported", "derived_from_report"}
            and fact.get("normalized_value") is not None
        ]

        # Keep only facts whose Evidence can be authoritatively reloaded at as_of.
        eligible_facts: List[dict] = []
        warnings: List[str] = [*report_warnings, *fact_warnings]
        for fact in facts:
            requested_ids = list(fact.get("evidence_ids") or [])
            evidence_ids, evidence_warnings = _evidence_eligible(
                self.db, requested_ids, as_of, {"S", "A", "B"},
                FINANCIAL_EVIDENCE_TYPES,
            )
            if not requested_ids or len(evidence_ids) != len(set(requested_ids)):
                warnings.extend(
                    [f"fact {fact.get('fact_id')}: {item}" for item in evidence_warnings]
                    or [f"fact {fact.get('fact_id')}: no evidence lineage"]
                )
                continue
            fact = dict(fact)
            fact["evidence_ids"] = evidence_ids
            report = report_by_id[fact["financial_report_id"]]
            fact["_report_metadata"] = {
                "financial_report_id": report["financial_report_id"],
                "fiscal_year": report["fiscal_year"],
                "fiscal_period": report["fiscal_period"],
                "duration_months": report["duration_months"],
                "published_at": report["published_at"],
            }
            eligible_facts.append(fact)

        # Select a single current fact per period/scope/taxonomy.  An exact rank tie
        # with different values is unresolved and cannot become a forecast input.
        grouped_facts: Dict[Tuple[str, str, str], List[dict]] = {}
        for fact in eligible_facts:
            key = (
                str(fact.get("period_end")), str(fact.get("statement_scope")),
                str(fact.get("taxonomy_code")),
            )
            grouped_facts.setdefault(key, []).append(fact)
        selected_facts: List[dict] = []
        for group in grouped_facts.values():
            rank = lambda f: (  # noqa: E731
                int(f.get("restatement_version") or 1),
                -int(f.get("source_priority") or 6),
                int(f.get("version") or 1),
            )
            best_rank = max(rank(f) for f in group)
            best = [f for f in group if rank(f) == best_rank]
            if len({f.get("normalized_value") for f in best}) > 1:
                warnings.append(
                    f"unresolved financial fact conflict: {best[0].get('taxonomy_code')} "
                    f"{best[0].get('period_end')}"
                )
                continue
            selected_facts.append(sorted(best, key=lambda f: str(f.get("fact_id")))[0])

        facts_by_report: Dict[str, List[dict]] = {}
        for fact in selected_facts:
            facts_by_report.setdefault(str(fact.get("financial_report_id")), []).append(fact)

        periods: List[HistoricalInputPeriod] = []
        for report in sorted(selected_reports, key=lambda r: str(r.get("period_end"))):
            report_facts = facts_by_report.get(report["financial_report_id"], [])
            if not report_facts:
                continue
            periods.append(HistoricalInputPeriod(
                period_label=_period_label(report),
                period_start=report.get("period_start"),
                period_end=report["period_end"],
                financial_report_ids=[report["financial_report_id"]],
                financial_fact_ids=sorted(f["fact_id"] for f in report_facts),
                financial_metric_ids=[],
                evidence_ids=sorted({eid for f in report_facts for eid in f["evidence_ids"]}),
                latest_published_at=report["published_at"],
                eligibility_status="eligible",
                warnings=[],
                input_versions={
                    report["financial_report_id"]: int(report.get("version") or 1),
                    **{f["fact_id"]: int(f.get("version") or 1) for f in report_facts},
                },
            ))
        return periods, selected_facts, warnings


def _validated_assumptions(
    request: EarningsExpectationRequest,
    db: Database,
    periods: List[HistoricalInputPeriod],
) -> Tuple[List[AssumptionInput], List[str]]:
    result: List[AssumptionInput] = []
    warnings: List[str] = []
    historical_evidence = sorted({eid for p in periods for eid in p.evidence_ids})
    historical_refs = sorted({fid for p in periods for fid in p.financial_fact_ids})
    for assumption in request.assumptions:
        if assumption.source_type == "model_generated":
            warnings.append("model_generated assumption rejected: llm_called=false")
            continue
        evidence_ids = list(assumption.evidence_ids)
        source_ref_ids = list(assumption.source_ref_ids)
        if assumption.source_type in {"company_guidance", "external_opinion"}:
            if not source_ref_ids:
                warnings.append(f"{assumption.source_type} assumption requires source_ref_ids")
                continue
            tiers = (ELIGIBLE_GUIDANCE_TIERS if assumption.source_type == "company_guidance"
                     else ELIGIBLE_OPINION_TIERS)
            types = (GUIDANCE_EVIDENCE_TYPES if assumption.source_type == "company_guidance"
                     else OPINION_EVIDENCE_TYPES)
            valid_ids, evidence_warnings = _evidence_eligible(
                db, evidence_ids, request.as_of, tiers, types,
            )
            if not evidence_ids or len(valid_ids) != len(set(evidence_ids)):
                warnings.extend(evidence_warnings or [
                    f"{assumption.source_type} assumption requires evidence",
                ])
                continue
            evidence_ids = valid_ids
        elif assumption.source_type == "deterministic_extrapolation":
            if not periods:
                warnings.append("deterministic extrapolation requires historical inputs")
                continue
            evidence_ids = historical_evidence
            source_ref_ids = sorted(set(source_ref_ids) | set(historical_refs))
        result.append(GovernedAssumptionInput(
            driver=assumption.driver,
            value=assumption.value,
            unit=assumption.unit,
            period=assumption.period,
            source_type=assumption.source_type,
            source_ref_ids=sorted(set(source_ref_ids)),
            evidence_ids=sorted(set(evidence_ids)),
            confidence=assumption.confidence,
            invalidates_when=assumption.invalidates_when,
            known_at=assumption.known_at,
        ))
    return result, warnings


def idempotency_key(
    request: EarningsExpectationRequest,
    periods: List[HistoricalInputPeriod],
    assumptions: List[AssumptionInput],
) -> str:
    canonical_assumptions: List[Dict[str, Any]] = []
    for assumption in assumptions:
        item = dict(vars(assumption))
        item["source_ref_ids"] = sorted(set(item.get("source_ref_ids") or []))
        item["evidence_ids"] = sorted(set(item.get("evidence_ids") or []))
        canonical_assumptions.append(item)
    canonical_assumptions.sort(
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )
    material = {
        "company_entity_id": request.company_entity_id,
        "as_of": request.as_of,
        "historical_inputs": [
            p.model_dump() for p in sorted(periods, key=lambda item: item.period_label)
        ],
        "forecast_period": request.forecast_period.model_dump(),
        "metric_code": request.metric_code,
        "scenario_name": request.scenario_name,
        "assumptions": canonical_assumptions,
        "calculation_version": FORECAST_RULES_VERSION,
        "model_state": {"mode": "deterministic_only", "llm_called": False},
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _render(
    request: EarningsExpectationRequest,
    periods: List[HistoricalInputPeriod],
    scenarios: List[ForecastScenario],
    projection_lineage: List[ProjectionLineage],
    warnings: List[str],
) -> str:
    created_at = now_iso()
    lines = [
        "---",
        f"report_id: earnings-expectation-{request.request_id}",
        "scenario: earnings_expectation",
        "title: Earnings Expectation",
        f"created_at: '{created_at}'",
        f"as_of: '{request.as_of}'",
        "timezone: Asia/Shanghai",
        "entities:",
        f"  - '{request.company_entity_id}'",
        "time_window:",
        f"  start: '{request.forecast_period.start}'",
        f"  end: '{request.forecast_period.end}'",
        f"data_status: {'complete' if scenarios else 'insufficient_evidence'}",
        "source_coverage:",
        f"  historical_periods: {len(periods)}",
        "model_route:",
        "  mode: deterministic_only",
        "  llm_called: false",
        "runtime_seconds: 0.0",
        "validator_status: pending",
        "knowledge_coordinates:",
        f"  as_of: '{request.as_of}'",
        "  assertion_type: HYPOTHESIS",
        "---",
        "",
        "# Earnings Expectation",
        "",
        "> Every numeric expectation is a conditional HYPOTHESIS, not a FACT, rating, or trading instruction.",
        "",
        f"- Company entity: {request.company_entity_id}",
        f"- Knowledge cutoff: {request.as_of}",
        f"- Forecast window: {request.forecast_period.start} to {request.forecast_period.end}",
        f"- Calculation rules: {FORECAST_RULES_VERSION}",
        f"- Generated by: deterministic_code (llm_called=false)",
        "",
        "## Historical Inputs",
        "",
    ]
    if periods:
        for period in periods:
            lines.append(
                f"- {period.period_label}: published_by={period.latest_published_at}; "
                f"facts={len(period.financial_fact_ids)}; evidence={len(period.evidence_ids)}"
            )
    else:
        lines.append("- INSUFFICIENT_EVIDENCE: no eligible historical financial inputs.")

    lines.extend(["", "## Historical Projection Baseline", ""])
    if projection_lineage:
        for lineage in projection_lineage:
            lines.extend([
                f"### Scenario {lineage.scenario_id}",
                "",
                f"- Baseline period: {lineage.baseline_fiscal_period}{lineage.baseline_period_end[:4]}",
                f"- Baseline report: {lineage.baseline_financial_report_id}",
                f"- Baseline fact: {lineage.baseline_financial_fact_id}",
                f"- Baseline value: {lineage.baseline_normalized_value} {lineage.baseline_normalized_unit}",
                f"- Formula version: {lineage.formula_version}",
                "",
            ])
    else:
        lines.append("- INSUFFICIENT_EVIDENCE: no eligible annual FY projection baseline.")

    lines.extend(["", "## Assumptions & Sources", ""])
    if scenarios:
        for scenario in scenarios:
            lines.append(f"### {scenario.name}")
            lines.append("")
            for assumption in scenario.assumptions:
                lines.extend([
                    f"- Assumption ID: {assumption.assumption_id}",
                    f"  - Driver: {assumption.driver} = {assumption.value} {assumption.unit} ({assumption.period})",
                    f"  - Source type: {assumption.source_type}",
                    f"  - Claim type: {assumption.claim_type}",
                    f"  - Source references: {', '.join(assumption.source_ref_ids) or 'none'}",
                    f"  - Evidence IDs: {', '.join(assumption.evidence_ids) or 'none'}",
                    f"  - Invalidation condition: {assumption.invalidates_when}",
                ])
    else:
        lines.append("- No validated assumptions produced a numeric scenario.")

    lines.extend(["", "## Forecast Outputs", ""])
    if scenarios:
        for scenario in scenarios:
            lines.append(f"### {scenario.name}")
            lines.append("")
            for output in scenario.outputs:
                lines.append(
                    f"- {output.period} {output.metric_code}: {output.value} {output.unit} "
                    f"(HYPOTHESIS; formula={output.formula_version})"
                )
    else:
        lines.append("- INSUFFICIENT_EVIDENCE: no valid forecast scenario.")

    lines.extend(["", "## Evidence Lineage", ""])
    if projection_lineage:
        for lineage in projection_lineage:
            lines.append(
                f"- {lineage.scenario_id}: {', '.join(lineage.evidence_ids) or 'none'}"
            )
    else:
        lines.append("- No accepted projection lineage.")

    lines.extend([
        "", "## Uncertainty", "",
        "- Outputs remain conditional on the explicit annual ratio assumption and comparable FY baseline.",
        "- New authoritative disclosures require deterministic recomputation.",
        "", "## Invalidation Conditions", "",
    ])
    invalidations = [
        assumption.invalidates_when
        for scenario in scenarios for assumption in scenario.assumptions
    ]
    lines.extend(
        [f"- {condition}" for condition in invalidations]
        or ["- No accepted scenario; invalidation conditions are not applicable."]
    )
    if warnings:
        lines.extend(["", "## Data and Assumption Warnings", ""])
        lines.extend(f"- {warning}" for warning in warnings)
    return "\n".join(lines).rstrip() + "\n"


class EarningsExpectationPipeline:
    def __init__(self, db: Database):
        self.db = db

    def run(self, request: EarningsExpectationRequest) -> EarningsExpectationOutcome:
        run_id = hashlib.sha256(
            f"{request.request_id}:{request.company_entity_id}:{request.as_of}".encode()
        ).hexdigest()[:32]
        stages: List[Dict[str, Any]] = []
        periods, facts, warnings = HistoricalInputResolver(self.db).resolve(
            request.company_entity_id, request.as_of,
        )
        stages.append({
            "stage": "resolve_historical_inputs",
            "status": "success" if periods else "insufficient_evidence",
            "count": len(periods),
        })
        assumptions, assumption_warnings = _validated_assumptions(
            request, self.db, periods,
        )
        warnings.extend(assumption_warnings)
        stages.append({
            "stage": "validate_assumptions",
            "status": "success" if assumptions else "insufficient_evidence",
            "count": len(assumptions),
        })
        key = idempotency_key(request, periods, assumptions)
        missing: List[str] = []
        if not periods:
            missing.append("eligible_historical_financial_inputs")
        if not assumptions:
            missing.append("valid_forecast_assumptions")

        scenarios: List[ForecastScenario] = []
        projection_lineage: List[ProjectionLineage] = []
        if periods and assumptions:
            growth_candidates = [a for a in assumptions if a.driver in {
                "growth_rate", f"{request.metric_code}_growth", "revenue_growth",
            }]
            for candidate in growth_candidates:
                if candidate.period != "annual":
                    missing.append("growth_period_not_annual")
                if candidate.unit != "ratio":
                    missing.append("growth_unit_not_ratio")
            eligible_growth = [
                candidate for candidate in growth_candidates
                if candidate.period == "annual" and candidate.unit == "ratio"
            ]
            growth = eligible_growth[0] if len(eligible_growth) == 1 else None
            if len(eligible_growth) > 1:
                missing.append("ambiguous_growth_assumptions")
            elif growth is None:
                missing.append("growth_assumption")

            annual_facts = [
                fact for fact in facts
                if fact.get("taxonomy_code") == request.metric_code
                and fact.get("_report_metadata", {}).get("fiscal_period") == "FY"
                and fact.get("_report_metadata", {}).get("duration_months") == 12
            ]
            baseline = next(iter(sorted(
                annual_facts, key=lambda fact: str(fact.get("period_end")), reverse=True,
            )), None)
            if baseline is None:
                missing.append(f"historical_{request.metric_code}_baseline")

            period_aligned = False
            if baseline is not None:
                baseline_year = int(baseline["_report_metadata"]["fiscal_year"])
                first_forecast_year = int(request.forecast_period.periods[0][2:])
                period_aligned = first_forecast_year == baseline_year + 1
                if not period_aligned:
                    missing.append("forecast_period_not_after_comparable_baseline")
            if growth is not None and baseline is not None and period_aligned:
                scenario_type = {
                    "company_guidance": "company_guidance",
                    "external_opinion": "external_view",
                    "user_input": "user_assumption",
                    "deterministic_extrapolation": "deterministic_projection",
                }[growth.source_type]
                scenario = build_scenario(ScenarioInput(
                    request_id=request.request_id,
                    company_entity_id=request.company_entity_id,
                    name=request.scenario_name,
                    scenario_type=scenario_type,
                    forecast_start=request.forecast_period.start,
                    forecast_end=request.forecast_period.end,
                    periods=list(request.forecast_period.periods),
                    assumptions=assumptions,
                    llm_called=False,
                    model_route={
                        "mode": "deterministic_only", "llm_called": False,
                        "provider": None, "model": None, "fallback_used": False,
                    },
                ))
                outputs = deterministic_projection(
                    str(baseline["normalized_value"]), str(growth.value),
                    len(request.forecast_period.periods),
                    unit=str(baseline.get("normalized_unit") or "yuan"),
                    metric_code=request.metric_code,
                )
                for output, label in zip(outputs, request.forecast_period.periods):
                    output.period = label
                scenario.outputs = outputs
                if not outputs:
                    scenario.status = "invalid"
                    scenario.warnings.append("deterministic projection rejected its numeric inputs")
                    missing.append("valid_projection_outputs")
                else:
                    errors = validate_instance(scenario.model_dump(), "forecast_scenario")
                    if errors:
                        raise ValueError(f"ForecastScenario schema validation failed: {errors}")
                    scenarios.append(scenario)
                    forecast_growth = next(
                        assumption for assumption in scenario.assumptions
                        if assumption.driver == growth.driver
                        and str(assumption.value) == str(growth.value)
                        and assumption.unit == growth.unit
                        and assumption.period == growth.period
                        and assumption.source_type == growth.source_type
                    )
                    report_metadata = baseline["_report_metadata"]
                    projection_lineage.append(ProjectionLineage(
                        scenario_id=scenario.scenario_id,
                        metric_code=request.metric_code,
                        baseline_financial_report_id=report_metadata["financial_report_id"],
                        baseline_financial_fact_id=baseline["fact_id"],
                        baseline_period_end=baseline["period_end"],
                        baseline_fiscal_period="FY",
                        baseline_duration_months=12,
                        baseline_normalized_value=str(baseline["normalized_value"]),
                        baseline_normalized_unit=str(baseline["normalized_unit"]),
                        assumption_ids=[forecast_growth.assumption_id],
                        output_periods=[output.period for output in scenario.outputs],
                        formula_version=FORECAST_RULES_VERSION,
                        evidence_ids=sorted(set(
                            list(baseline.get("evidence_ids") or [])
                            + list(forecast_growth.evidence_ids)
                        )),
                    ))
        stages.append({
            "stage": "build_forecast_scenario",
            "status": "success" if scenarios else "insufficient_evidence",
            "count": len(scenarios),
        })

        status = "success" if scenarios else "insufficient_evidence"
        evidence_ids = sorted({
            eid for period in periods for eid in period.evidence_ids
        } | {
            eid for scenario in scenarios for assumption in scenario.assumptions
            for eid in assumption.evidence_ids
        })
        return EarningsExpectationOutcome(
            run_id=run_id,
            status=status,
            historical_input_periods=periods,
            scenarios=scenarios,
            projection_lineage=projection_lineage,
            evidence_ids=evidence_ids,
            warnings=warnings,
            missing_data=sorted(set(missing)),
            error_codes=[],
            stage_statuses=stages,
            idempotency_key=key,
            markdown=_render(request, periods, scenarios, projection_lineage, warnings),
        )
