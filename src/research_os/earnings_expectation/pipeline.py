"""Earnings expectation orchestration over Phase 4 forecast primitives.

This module owns time governance and lineage assembly.  It intentionally owns
no forecast arithmetic: all numeric projections use the Phase 4 primitive.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from research_os.equity_research.forecast import (
    FORECAST_RULES_VERSION,
    AssumptionInput,
    ScenarioInput,
    build_scenario,
    deterministic_projection,
)
from research_os.models import (
    EarningsExpectationRequest,
    ForecastPeriod,
    ForecastScenario,
    HistoricalInputPeriod,
)
from research_os.storage import Database
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_instance


PIPELINE_VERSION = "1.0.0"
ELIGIBLE_GUIDANCE_TIERS = {"S", "A"}
ELIGIBLE_OPINION_TIERS = {"S", "A", "B"}


@dataclass
class EarningsExpectationOutcome:
    run_id: str
    status: str
    historical_input_periods: List[HistoricalInputPeriod] = field(default_factory=list)
    scenarios: List[ForecastScenario] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    error_codes: List[str] = field(default_factory=list)
    stage_statuses: List[Dict[str, Any]] = field(default_factory=list)
    idempotency_key: str = ""
    markdown: str = ""


def _payloads(db: Database, table: str, needle: str) -> Iterable[dict]:
    for row in db.query(f"SELECT payload FROM {table} WHERE payload LIKE ?", (f"%{needle}%",)):
        try:
            value = json.loads(row["payload"])
        except (KeyError, TypeError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            yield value


def _not_after(timestamp: Optional[str], as_of: str) -> bool:
    if not timestamp:
        return False
    try:
        return parse_iso(timestamp) <= parse_iso(as_of)
    except ValueError:
        return False


def _after(timestamp: Optional[str], as_of: str) -> bool:
    if not timestamp:
        return False
    try:
        return parse_iso(timestamp) > parse_iso(as_of)
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
    db: Database, evidence_ids: List[str], as_of: str, eligible_tiers: set[str],
) -> Tuple[List[str], List[str]]:
    eligible: List[str] = []
    warnings: List[str] = []
    for evidence_id in dict.fromkeys(evidence_ids):
        evidence = db.get("evidence", evidence_id)
        if evidence is None:
            warnings.append(f"missing evidence: {evidence_id}")
            continue
        if evidence.get("access_status") != "ok":
            warnings.append(f"ineligible evidence access: {evidence_id}")
            continue
        if evidence.get("source_tier") not in eligible_tiers:
            warnings.append(f"ineligible evidence tier: {evidence_id}")
            continue
        if not _not_after(evidence.get("published_at"), as_of):
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
        reports = [
            report for report in _payloads(self.db, "financial_reports", company_entity_id)
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

        facts = [
            fact for fact in _payloads(self.db, "financial_facts", company_entity_id)
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
        warnings: List[str] = []
        for fact in facts:
            requested_ids = list(fact.get("evidence_ids") or [])
            evidence_ids, evidence_warnings = _evidence_eligible(
                self.db, requested_ids, as_of, {"S", "A", "B"},
            )
            if not requested_ids or len(evidence_ids) != len(set(requested_ids)):
                warnings.extend(
                    [f"fact {fact.get('fact_id')}: {item}" for item in evidence_warnings]
                    or [f"fact {fact.get('fact_id')}: no evidence lineage"]
                )
                continue
            fact = dict(fact)
            fact["evidence_ids"] = evidence_ids
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
            valid_ids, evidence_warnings = _evidence_eligible(
                db, evidence_ids, request.as_of, tiers,
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
        result.append(AssumptionInput(
            driver=assumption.driver,
            value=assumption.value,
            unit=assumption.unit,
            period=assumption.period,
            source_type=assumption.source_type,
            source_ref_ids=source_ref_ids,
            evidence_ids=evidence_ids,
            confidence=assumption.confidence,
            invalidates_when=assumption.invalidates_when,
        ))
    return result, warnings


def idempotency_key(
    request: EarningsExpectationRequest,
    periods: List[HistoricalInputPeriod],
    assumptions: List[AssumptionInput],
) -> str:
    material = {
        "company_entity_id": request.company_entity_id,
        "as_of": request.as_of,
        "historical_inputs": [p.model_dump() for p in periods],
        "forecast_period": request.forecast_period.model_dump(),
        "metric_code": request.metric_code,
        "assumptions": [vars(a) for a in assumptions],
        "calculation_version": FORECAST_RULES_VERSION,
        "model_state": {"mode": "deterministic_only", "llm_called": False},
    }
    canonical = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _render(
    request: EarningsExpectationRequest,
    periods: List[HistoricalInputPeriod],
    scenarios: List[ForecastScenario],
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
        "validator_status: pass",
        "knowledge_coordinates:",
        f"  as_of: '{request.as_of}'",
        "  assertion_type: HYPOTHESIS",
        "---",
        "",
        "# Earnings Expectation",
        "",
        "> 本报告中的 earnings expectation 均为显式预测假设，不属于事实陈述、投资评级或交易建议。",
        "",
        f"- 公司实体：{request.company_entity_id}",
        f"- 知识截止时间：{request.as_of}",
        f"- 预测区间：{request.forecast_period.start} 至 {request.forecast_period.end}",
        f"- 计算规则：{FORECAST_RULES_VERSION}",
        f"- 生成方式：deterministic_code（llm_called=false）",
        "",
        "## 历史输入",
        "",
    ]
    if periods:
        for period in periods:
            lines.append(
                f"- {period.period_label}（截至 {period.latest_published_at} 已披露；"
                f"facts={len(period.financial_fact_ids)}；evidence={len(period.evidence_ids)}）"
            )
    else:
        lines.append("- INSUFFICIENT_EVIDENCE：截止时间前无合格历史财务输入。")
    lines.extend(["", "## 预测情景", ""])
    if scenarios:
        for scenario in scenarios:
            lines.append(f"### {scenario.name}")
            lines.append("")
            for output in scenario.outputs:
                lines.append(
                    f"- {output.period} {output.metric_code}: {output.value} {output.unit} "
                    f"（HYPOTHESIS；formula={output.formula_version}）"
                )
            lines.append("")
            lines.append("不确定性：结果取决于显式增长假设；假设失效时应重新计算。")
            lines.append("")
    else:
        lines.append("- INSUFFICIENT_EVIDENCE：未形成有效预测情景。")
    if warnings:
        lines.extend(["", "## 数据与假设警告", ""])
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
        if periods and assumptions:
            # A final numeric output is only driven by an explicit growth assumption.
            growth = next((a for a in assumptions if a.driver in {
                "growth_rate", f"{request.metric_code}_growth", "revenue_growth",
            }), None)
            baseline = next((
                fact for fact in sorted(facts, key=lambda f: str(f.get("period_end")), reverse=True)
                if fact.get("taxonomy_code") == request.metric_code
            ), None)
            if growth is None:
                missing.append("growth_assumption")
            if baseline is None:
                missing.append(f"historical_{request.metric_code}_baseline")
            if growth is not None and baseline is not None:
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
                    self.db.upsert(scenario)
                    scenarios.append(scenario)
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
            evidence_ids=evidence_ids,
            warnings=warnings,
            missing_data=sorted(set(missing)),
            error_codes=[],
            stage_statuses=stages,
            idempotency_key=key,
            markdown=_render(request, periods, scenarios, warnings),
        )
