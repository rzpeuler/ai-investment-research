"""Deterministic composition of accepted Phase 4, Phase 6A, and S3 outputs."""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import ValidationError

from research_os.earnings_expectation.pipeline import EarningsExpectationPipeline
from research_os.industry_research.pipeline import IndustryResearchPipeline
from research_os.models import (
    Catalyst, CompanyProfile, EarningsExpectationRequest, EquityResearchRequest,
    EquityResearchResult, EquityResearchRun, Evidence, FirstCoverageComponentStatus,
    FirstCoverageRequest, ForecastScenario, PeerSelection, ProjectionLineage,
    ResearchFinding, RiskFactor, SecurityProfile, ValuationSnapshot,
)
from research_os.storage import Database
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_instance

PIPELINE_VERSION = "1.0.0"
ACCEPTED_PHASE4 = {"success", "partial_success", "degraded"}
COMPONENTS = (
    "profile", "phase4_baseline", "industry_research", "peer_context",
    "earnings_expectation", "valuation", "catalysts", "risks",
    "counter_evidence", "open_questions",
)


@dataclass
class FirstCoverageOutcome:
    run_id: str
    status: str
    company_profile: Optional[dict] = None
    security_profile: Optional[dict] = None
    phase4_result: Optional[dict] = None
    phase4_request: Optional[dict] = None
    phase4_run: Optional[dict] = None
    findings: List[dict] = field(default_factory=list)
    peer_selection: Optional[dict] = None
    valuation_snapshot: Optional[dict] = None
    catalysts: List[dict] = field(default_factory=list)
    risks: List[dict] = field(default_factory=list)
    industry_outcome: Any = None
    earnings_request_id: Optional[str] = None
    earnings_outcome: Any = None
    counter_evidence_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    component_statuses: List[FirstCoverageComponentStatus] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    idempotency_key: str = ""
    markdown: str = ""


def _strict_payload(raw: Any, model: Type[Any], schema: str) -> Tuple[Optional[dict], Optional[str]]:
    errors = validate_instance(raw, schema)
    if errors:
        return None, f"raw Schema validation failed ({schema}): {errors}"
    try:
        obj = model(**raw)
    except (TypeError, ValidationError, ValueError) as exc:
        return None, f"Pydantic validation failed ({schema}): {exc}"
    payload = obj.model_dump()
    errors = validate_instance(payload, schema)
    if errors:
        return None, f"roundtrip Schema validation failed ({schema}): {errors}"
    return payload, None


def _strict_get(db: Database, table: str, object_id: Optional[str], model: Type[Any], schema: str):
    if not object_id:
        return None, f"missing {schema} reference"
    raw = db.get(table, object_id)
    if raw is None:
        return None, f"missing {schema}: {object_id}"
    return _strict_payload(raw, model, schema)


def _rows(db: Database, table: str, column: str, value: str) -> List[dict]:
    allowed = {
        ("company_profiles", "entity_id"),
        ("security_profiles", "security_entity_id"),
        ("equity_research_results", "company_entity_id"),
    }
    if (table, column) not in allowed:
        raise ValueError("unsupported structured authority query")
    return db.query(f"SELECT payload FROM {table} WHERE {column} = ?", (value,))


def _active_profiles(db: Database, request: FirstCoverageRequest):
    cutoff = request.as_of[:10]
    warnings: List[str] = []
    companies = []
    for row in _rows(db, "company_profiles", "entity_id", request.company_entity_id):
        try:
            raw = json.loads(row["payload"])
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"company profile invalid JSON: {exc}")
            continue
        value, error = _strict_payload(raw, CompanyProfile, "company_profile")
        if error:
            warnings.append(error); continue
        if value["entity_id"] == request.company_entity_id and value["status"] == "active" and value["valid_from"] <= cutoff and (value["valid_to"] is None or cutoff < value["valid_to"]):
            companies.append(value)
    securities = []
    for row in _rows(db, "security_profiles", "security_entity_id", request.security_entity_id):
        try:
            raw = json.loads(row["payload"])
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            warnings.append(f"security profile invalid JSON: {exc}")
            continue
        value, error = _strict_payload(raw, SecurityProfile, "security_profile")
        if error:
            warnings.append(error); continue
        if value["security_entity_id"] == request.security_entity_id and value["company_entity_id"] == request.company_entity_id and value["listing_date"] <= cutoff and (value["delisting_date"] is None or cutoff <= value["delisting_date"]):
            securities.append(value)
    if len(companies) != 1:
        warnings.append(f"active company profile count must be one: {len(companies)}")
    if len(securities) != 1:
        warnings.append(f"active security profile count must be one: {len(securities)}")
    return (companies[0] if len(companies) == 1 else None,
            securities[0] if len(securities) == 1 else None, warnings)


def _phase4_baseline(db: Database, request: FirstCoverageRequest):
    warnings: List[str] = []
    candidates: List[dict] = []
    if request.phase4_result_id:
        value, error = _strict_get(db, "equity_research_results", request.phase4_result_id, EquityResearchResult, "equity_research_result")
        if error: warnings.append(error)
        elif value: candidates = [value]
    else:
        for row in _rows(db, "equity_research_results", "company_entity_id", request.company_entity_id):
            try: raw = json.loads(row["payload"])
            except (TypeError, KeyError, json.JSONDecodeError) as exc:
                warnings.append(f"Phase4 result invalid JSON: {exc}"); continue
            value, error = _strict_payload(raw, EquityResearchResult, "equity_research_result")
            if error: warnings.append(error); continue
            candidates.append(value)
    eligible = [v for v in candidates if v["company_entity_id"] == request.company_entity_id and v["security_entity_id"] == request.security_entity_id and v["research_status"] in ACCEPTED_PHASE4 and parse_iso(v["as_of"]) <= parse_iso(request.as_of)]
    if not eligible:
        return None, None, None, warnings + ["no accepted Phase4 baseline"]
    eligible.sort(key=lambda v: (v["as_of"], int(v["version"]), v["result_id"]), reverse=True)
    best_rank = (eligible[0]["as_of"], int(eligible[0]["version"]))
    best = [v for v in eligible if (v["as_of"], int(v["version"])) == best_rank]
    if len(best) != 1:
        return None, None, None, warnings + ["ambiguous accepted Phase4 baseline"]
    result = best[0]
    phase4_request, req_error = _strict_get(db, "equity_research_requests", result["request_id"], EquityResearchRequest, "equity_research_request")
    phase4_run, run_error = _strict_get(db, "equity_research_runs", result["run_id"], EquityResearchRun, "equity_research_run")
    if req_error or run_error:
        return None, None, None, warnings + [e for e in (req_error, run_error) if e]
    if (
        phase4_request["company_entity_id"] != request.company_entity_id
        or phase4_request["security_entity_id"] != request.security_entity_id
        or phase4_request["request_id"] != result["request_id"]
        or phase4_request["as_of"] != result["as_of"]
        or phase4_run["request_id"] != result["request_id"]
        or phase4_run["run_id"] != result["run_id"]
        or phase4_run["task_id"] != phase4_request["task_id"]
        or phase4_run["status"] not in ACCEPTED_PHASE4
        or phase4_run["validation_status"] not in {"pass", "pass_with_warnings"}
    ):
        return None, None, None, warnings + ["Phase4 request/run/result lineage mismatch"]
    return result, phase4_request, phase4_run, warnings


def _load_refs(
    db: Database,
    ids: List[str],
    table: str,
    model: Type[Any],
    schema: str,
    request: FirstCoverageRequest,
    time_field: Optional[str] = None,
    expected: Optional[Dict[str, Any]] = None,
):
    values, warnings = [], []
    for oid in sorted(set(ids)):
        value, error = _strict_get(db, table, oid, model, schema)
        if error: warnings.append(error); continue
        checks = {"company_entity_id": request.company_entity_id, **(expected or {})}
        mismatch = next(
            (name for name, wanted in checks.items()
             if name in value and value[name] != wanted),
            None,
        )
        if mismatch:
            warnings.append(f"wrong {mismatch} {schema}: {oid}"); continue
        if time_field and value.get(time_field) and parse_iso(value[time_field]) > parse_iso(request.as_of):
            warnings.append(f"future {schema}: {oid}"); continue
        values.append(value)
    return values, warnings


def _evidence_gated_objects(
    db: Database, values: List[dict], as_of: str, schema: str,
) -> Tuple[List[dict], List[str]]:
    """Exclude objects carrying any missing, future, or ineligible evidence ref."""
    accepted, warnings = [], []
    for value in values:
        evidence_ids = sorted(set(value.get("evidence_ids", [])))
        eligible, evidence_warnings = _eligible_evidence(db, evidence_ids, as_of)
        warnings.extend(evidence_warnings)
        if eligible != evidence_ids:
            object_id = (
                value.get("finding_id") or value.get("peer_selection_id")
                or value.get("valuation_snapshot_id") or value.get("catalyst_id")
                or value.get("risk_id") or "unknown"
            )
            warnings.append(f"excluded {schema} with ineligible evidence: {object_id}")
            continue
        if value.get("claim_type") == "FACT" and not eligible:
            object_id = (
                value.get("finding_id") or value.get("catalyst_id")
                or value.get("risk_id") or "unknown"
            )
            warnings.append(f"excluded unsupported FACT {schema}: {object_id}")
            continue
        accepted.append(value)
    return accepted, warnings


def _eligible_evidence(db: Database, ids: List[str], as_of: str):
    accepted, warnings = [], []
    for eid in sorted(set(ids)):
        value, error = _strict_get(db, "evidence", eid, Evidence, "evidence")
        if error: warnings.append(error); continue
        if value["access_status"] != "ok" or value["source_tier"] == "D" or parse_iso(value["published_at"]) > parse_iso(as_of):
            warnings.append(f"ineligible evidence: {eid}"); continue
        accepted.append(eid)
    return accepted, warnings


def _sanitize_industry_findings(
    db: Database, industry_outcome: Any, as_of: str,
) -> List[str]:
    """Re-gate every 6A factual finding before First Coverage renders it."""
    warnings: List[str] = []
    sanitized: List[dict] = []
    for original in getattr(industry_outcome, "findings", []):
        finding = dict(original)
        evidence_ids = sorted(set(finding.get("evidence_ids", [])))
        eligible, item_warnings = _eligible_evidence(db, evidence_ids, as_of)
        warnings.extend(item_warnings)
        if finding.get("judgment") == "FACT":
            if not eligible or eligible != evidence_ids:
                dimension = finding.get("dimension_id", "unknown")
                finding.update({
                    "judgment": "INSUFFICIENT_EVIDENCE", "summary": "",
                    "evidence_ids": [],
                    "reason": "First Coverage authoritative Evidence recheck failed.",
                })
                warnings.append(
                    f"downgraded industry FACT after Evidence recheck: {dimension}")
            else:
                finding["evidence_ids"] = eligible
        else:
            finding["evidence_ids"] = eligible
        sanitized.append(finding)
    industry_outcome.findings = sanitized
    if sanitized and getattr(industry_outcome, "status", None) not in {"failed"}:
        covered = [
            item.get("dimension_id", "") for item in sanitized
            if item.get("judgment") == "FACT" and item.get("dimension_id")
        ]
        missing = [
            item.get("dimension_id", "") for item in sanitized
            if item.get("judgment") != "FACT" and item.get("dimension_id")
        ]
        industry_outcome.dimensions_covered = covered
        industry_outcome.dimensions_missing = missing
        industry_outcome.status = (
            "insufficient_evidence" if not covered
            else "degraded" if missing else "success"
        )
    return warnings


def _canonical_key(request: FirstCoverageRequest, objects: Dict[str, Any]) -> str:
    earnings = request.earnings_expectation.model_dump() if request.earnings_expectation else None
    if earnings:
        for item in earnings["assumptions"]:
            item["source_ref_ids"] = sorted(set(item["source_ref_ids"]))
            item["evidence_ids"] = sorted(set(item["evidence_ids"]))
        earnings["assumptions"].sort(key=lambda x: json.dumps(x, sort_keys=True, ensure_ascii=False))
    material = {
        "company": request.company_entity_id, "security": request.security_entity_id,
        "as_of": request.as_of, "industry_id": request.industry_id, "depth": request.depth,
        "earnings": earnings, "objects": objects,
        "rule_versions": request.rule_versions, "version": PIPELINE_VERSION,
        "provider": {"mode": "deterministic_only", "llm_called": False},
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _finish_early(
    request: FirstCoverageRequest,
    outcome: FirstCoverageOutcome,
    stage: str,
    objects: Dict[str, Any],
) -> FirstCoverageOutcome:
    present = {item.component for item in outcome.component_statuses}
    for component in COMPONENTS:
        if component not in present:
            outcome.component_statuses.append(FirstCoverageComponentStatus(
                component=component, status="insufficient_evidence",
                missing_data=[stage],
            ))
    outcome.idempotency_key = _canonical_key(
        request, {"terminal_stage": stage, **objects})
    outcome.markdown = _render(request, outcome)
    return outcome


def _render(request: FirstCoverageRequest, outcome: FirstCoverageOutcome) -> str:
    cp, sp, p4 = outcome.company_profile, outcome.security_profile, outcome.phase4_result
    lines = ["---", f"report_id: first-coverage-{outcome.run_id}", "scenario: first_coverage", "title: First Coverage", f"created_at: '{now_iso()}'", f"as_of: '{request.as_of}'", "timezone: Asia/Shanghai", "entities:", f"  - '{request.company_entity_id}'", f"  - '{request.security_entity_id}'", "time_window:", f"  start: '{request.as_of[:10]}'", f"  end: '{request.as_of[:10]}'", f"data_status: {outcome.status}", "source_coverage:", f"  evidence_count: {len(outcome.evidence_ids)}", "model_route:", "  mode: deterministic_only", "  llm_called: false", "runtime_seconds: 0.0", "validator_status: pending", "knowledge_coordinates:", f"  as_of: '{request.as_of}'", "  assertion_type: MIXED", "---", "", "# First Coverage", "", "> Composition of accepted structured research; not a brokerage rating or trading instruction.", "", "## Company and Security", "", f"- Company profile: {cp['company_profile_id'] if cp else 'INSUFFICIENT_EVIDENCE'}", f"- Company: {cp['canonical_name'] if cp else request.company_entity_id}", f"- Security profile: {sp['security_profile_id'] if sp else 'INSUFFICIENT_EVIDENCE'}", "", "## Accepted Phase4 Baseline", "", f"- Result: {p4['result_id'] if p4 else 'INSUFFICIENT_EVIDENCE'}", f"- Status: {p4['research_status'] if p4 else 'INSUFFICIENT_EVIDENCE'}", ""]
    lines += ["## Key Findings", ""]
    lines += ([f"- {x['finding_id']} [{x['claim_type']}]: {x['statement']} | evidence={','.join(x['evidence_ids']) or 'none'}" for x in outcome.findings] or ["- INSUFFICIENT_EVIDENCE"])
    lines += ["", "## Industry Research", "", f"- Component status: {getattr(outcome.industry_outcome, 'status', 'insufficient_evidence')}"]
    for finding in getattr(outcome.industry_outcome, "findings", [])[:20]:
        claim_type = finding.get("claim_type", finding.get("judgment", "UNKNOWN"))
        lines.append(f"- {finding.get('dimension_id', finding.get('dimension', 'industry'))}: {finding.get('statement', finding.get('summary', ''))} [claim={claim_type}; evidence={','.join(finding.get('evidence_ids', [])) or 'none'}]")
    lines += ["", "## Peer Context", "", f"- PeerSelection: {outcome.peer_selection['peer_selection_id'] if outcome.peer_selection else 'INSUFFICIENT_EVIDENCE'}", f"- Status: {outcome.peer_selection['status'] if outcome.peer_selection else 'insufficient'}", f"- Selected companies: {', '.join(outcome.peer_selection['selected_company_ids']) if outcome.peer_selection else 'none'}"]
    if outcome.peer_selection:
        lines += [
            f"- Sample: {outcome.peer_selection['sample_size']} / minimum {outcome.peer_selection['minimum_required']}",
            f"- Rationale: {'; '.join(outcome.peer_selection['selection_rationale']) or 'none'}",
            f"- Warnings: {'; '.join(outcome.peer_selection['warnings']) or 'none'}",
        ]
    lines += ["", "## Earnings Expectation (FORECAST / HYPOTHESIS)", ""]
    if outcome.earnings_outcome and outcome.earnings_outcome.scenarios:
        for scenario in outcome.earnings_outcome.scenarios:
            lines.append(f"### Scenario {scenario.scenario_id}")
            for output in scenario.outputs: lines.append(f"- {output.period} {output.metric_code}: {output.value} {output.unit} (HYPOTHESIS; {output.formula_version})")
    else: lines.append("- INSUFFICIENT_EVIDENCE")
    lines += ["", "## Valuation Applicability", "", f"- Snapshot: {outcome.valuation_snapshot['valuation_snapshot_id'] if outcome.valuation_snapshot else 'none'}", f"- Status: {outcome.valuation_snapshot['status'] if outcome.valuation_snapshot else 'insufficient_data'}"]
    if outcome.valuation_snapshot:
        lines += [
            f"- Financial basis: {outcome.valuation_snapshot['financial_basis']}",
            f"- History sample size: {outcome.valuation_snapshot['history_sample_size']}",
            f"- Peer sample size: {outcome.valuation_snapshot['peer_sample_size']}",
        ]
        lines += [f"- Applicability: {note}" for note in outcome.valuation_snapshot["applicability_notes"]]
        for metric in outcome.valuation_snapshot["metrics"]: lines.append(f"- {metric['metric_code']}: {metric['value']} {metric['unit']} ({metric['status']})")
    lines += ["", "## Catalysts", ""]
    if outcome.catalysts:
        for item in outcome.catalysts:
            lines += [
                f"- {item['catalyst_id']} [{item['claim_type']} / {item['announcement_status']}]: {item['description']}",
                f"  - Type/status: {item['catalyst_type']} / {item['status']}",
                f"  - Time window: {item['time_window_start'] or 'unknown'} to {item['time_window_end'] or 'unknown'}",
                f"  - Impact mechanism: {item['impact_mechanism']}",
                f"  - Prerequisites: {'; '.join(item['prerequisites']) or 'none'}",
                f"  - Invalidation: {'; '.join(item['invalidation_conditions']) or 'none'}",
                f"  - Confidence: {item['confidence']}; evidence={','.join(item['evidence_ids']) or 'none'}",
            ]
    else:
        lines.append("- None in accepted Phase4 baseline.")
    lines += ["", "## Risks", ""]
    if outcome.risks:
        for item in outcome.risks:
            lines += [
                f"- {item['risk_id']} [{item['claim_type']} / {item['status']}]: {item['description']}",
                f"  - Type: {item['risk_type']}",
                f"  - Impact mechanism: {item['impact_mechanism']}",
                f"  - Triggers: {'; '.join(item['triggers']) or 'none'}",
                f"  - Mitigants: {'; '.join(item['mitigants']) or 'none'}",
                f"  - Invalidation: {'; '.join(item['invalidation_conditions']) or 'none'}",
                f"  - Confidence: {item['confidence']}; evidence={','.join(item['evidence_ids']) or 'none'}; counter={','.join(item['counter_evidence_ids']) or 'none'}",
            ]
    else:
        lines.append("- None in accepted Phase4 baseline.")
    lines += ["", "## Counter Evidence / Controversies", ""] + ([f"- Evidence ID: {eid}" for eid in outcome.counter_evidence_ids] or ["- No eligible counter Evidence."])
    lines += ["", "## Open Questions", ""] + ([f"- {q}" for q in outcome.open_questions] or ["- None recorded."])
    lines += ["", "## Evidence Audit", "", f"- Phase4 result ID: {p4['result_id'] if p4 else 'none'}", f"- ResearchFinding IDs: {', '.join(x['finding_id'] for x in outcome.findings) or 'none'}", f"- Industry component run ID: {getattr(outcome.industry_outcome, 'run_id', 'none')}", f"- Earnings scenario IDs: {', '.join(s.scenario_id for s in getattr(outcome.earnings_outcome, 'scenarios', [])) or 'none'}"]
    lines += [f"- Evidence ID: {eid}" for eid in outcome.evidence_ids]
    lines += ["", "## Limitations", ""] + ([f"- {w}" for w in outcome.warnings] or ["- None recorded."])
    return "\n".join(lines).rstrip() + "\n"


class FirstCoveragePipeline:
    def __init__(self, root: Path, db: Database, llm_client: Any = None):
        self.root, self.db, self.llm_client = Path(root), db, llm_client

    def run(self, request: FirstCoverageRequest) -> FirstCoverageOutcome:
        outcome = FirstCoverageOutcome(run_id=new_uuid(), status="insufficient_evidence")
        cp, sp, warnings = _active_profiles(self.db, request)
        outcome.company_profile, outcome.security_profile = cp, sp
        outcome.warnings.extend(warnings)
        outcome.component_statuses.append(FirstCoverageComponentStatus(component="profile", status="success" if cp and sp else "insufficient_evidence", source_object_ids=[x for x in [cp and cp["company_profile_id"], sp and sp["security_profile_id"]] if x], warnings=warnings, missing_data=[] if cp and sp else ["valid_profiles"]))
        if not cp or not sp:
            outcome.missing_data.append("valid_profiles")
            return _finish_early(request, outcome, "profiles", {})
        if cp["industry_ids"] and request.industry_id not in cp["industry_ids"]:
            outcome.warnings.append("requested industry_id not in CompanyProfile.industry_ids")
            outcome.missing_data.append("industry_profile_mapping")
            return _finish_early(
                request, outcome, "industry_profile_mapping",
                {"company_profile": [cp["company_profile_id"], cp["version"]],
                 "security_profile": [sp["security_profile_id"], sp["version"]]},
            )
        p4, p4req, p4run, warnings = _phase4_baseline(self.db, request)
        outcome.phase4_result, outcome.phase4_request, outcome.phase4_run = p4, p4req, p4run
        outcome.warnings.extend(warnings)
        phase4_component_status = (
            "insufficient_evidence" if not p4
            else "degraded" if p4["research_status"] == "degraded"
            else "partial_success" if p4["research_status"] == "partial_success"
            else "success"
        )
        outcome.component_statuses.append(FirstCoverageComponentStatus(component="phase4_baseline", status=phase4_component_status, source_object_ids=[p4["result_id"]] if p4 else [], warnings=warnings, missing_data=[] if p4 else ["accepted_phase4_baseline"]))
        if not p4:
            outcome.missing_data.append("accepted_phase4_baseline")
            return _finish_early(
                request, outcome, "phase4_baseline",
                {"company_profile": [cp["company_profile_id"], cp["version"]],
                 "security_profile": [sp["security_profile_id"], sp["version"]]},
            )
        outcome.findings, w = _load_refs(
            self.db, p4["key_finding_ids"], "research_findings", ResearchFinding,
            "research_finding", request, "as_of", {"request_id": p4["request_id"]})
        outcome.warnings += w
        outcome.findings, w = _evidence_gated_objects(
            self.db, outcome.findings, request.as_of, "research_finding")
        outcome.warnings += w
        peers, w = _load_refs(
            self.db, [p4["peer_selection_id"]] if p4["peer_selection_id"] else [],
            "peer_selections", PeerSelection, "peer_selection", request,
            "information_cutoff",
            {"subject_company_id": request.company_entity_id,
             "request_id": p4["request_id"]})
        outcome.warnings += w; outcome.peer_selection = peers[0] if peers else None
        if outcome.peer_selection:
            peers, w = _evidence_gated_objects(
                self.db, [outcome.peer_selection], request.as_of, "peer_selection")
            outcome.warnings += w
            outcome.peer_selection = peers[0] if peers else None
        vals, w = _load_refs(
            self.db, [p4["valuation_snapshot_id"]] if p4["valuation_snapshot_id"] else [],
            "valuation_snapshots", ValuationSnapshot, "valuation_snapshot", request,
            "as_of", {"security_entity_id": request.security_entity_id})
        outcome.warnings += w; outcome.valuation_snapshot = vals[0] if vals else None
        if outcome.valuation_snapshot:
            vals, w = _evidence_gated_objects(
                self.db, [outcome.valuation_snapshot], request.as_of,
                "valuation_snapshot")
            outcome.warnings += w
            outcome.valuation_snapshot = vals[0] if vals else None
        outcome.catalysts, w = _load_refs(self.db, p4["catalyst_ids"], "catalysts", Catalyst, "catalyst", request, "created_at"); outcome.warnings += w
        outcome.risks, w = _load_refs(self.db, p4["risk_ids"], "risk_factors", RiskFactor, "risk_factor", request, "created_at"); outcome.warnings += w
        outcome.catalysts, w = _evidence_gated_objects(
            self.db, outcome.catalysts, request.as_of, "catalyst")
        outcome.warnings += w
        outcome.risks, w = _evidence_gated_objects(
            self.db, outcome.risks, request.as_of, "risk_factor")
        outcome.warnings += w
        for risk in outcome.risks:
            risk["counter_evidence_ids"], w = _eligible_evidence(
                self.db, risk["counter_evidence_ids"], request.as_of)
            outcome.warnings += w
        outcome.industry_outcome = IndustryResearchPipeline(self.root, self.db, self.llm_client).run({"industry_id": request.industry_id, "industry_name": request.industry_name, "as_of": request.as_of, "depth": request.depth, "deterministic_only": True, "task_id": request.task_id})
        outcome.warnings += _sanitize_industry_findings(
            self.db, outcome.industry_outcome, request.as_of)
        outcome.warnings += list(getattr(outcome.industry_outcome, "warnings", []))
        outcome.missing_data += list(getattr(outcome.industry_outcome, "missing_data", []))
        if request.earnings_expectation:
            nested = request.earnings_expectation
            earnings_request = EarningsExpectationRequest(request_id=new_uuid(), task_id=request.task_id, company_entity_id=request.company_entity_id, as_of=request.as_of, forecast_period=nested.forecast_period, assumptions=nested.assumptions, metric_code=nested.metric_code, scenario_name=nested.scenario_name, requested_at=request.requested_at, rule_versions=request.rule_versions)
            errors = validate_instance(earnings_request.model_dump(), "earnings_expectation_request")
            if errors: raise ValueError(f"nested earnings request schema failed: {errors}")
            outcome.earnings_request_id = earnings_request.request_id
            outcome.earnings_outcome = EarningsExpectationPipeline(self.db).run(earnings_request)
            outcome.warnings += list(getattr(outcome.earnings_outcome, "warnings", []))
            outcome.missing_data += list(getattr(outcome.earnings_outcome, "missing_data", []))
        counter_ids = [eid for finding in outcome.findings for eid in finding["counter_evidence_ids"]] + [eid for risk in outcome.risks for eid in risk["counter_evidence_ids"]]
        for finding in getattr(outcome.industry_outcome, "findings", []):
            if (
                finding.get("claim_type") in {"CONFLICT", "UNKNOWN"}
                or finding.get("dimension_id") in {"core_controversies", "counter_evidence"}
            ):
                counter_ids += finding.get("evidence_ids", [])
        outcome.counter_evidence_ids, w = _eligible_evidence(self.db, counter_ids, request.as_of); outcome.warnings += w
        evidence = list(p4["evidence_ids"]) + [eid for x in outcome.findings + outcome.catalysts + outcome.risks for eid in x.get("evidence_ids", [])] + outcome.counter_evidence_ids
        if outcome.peer_selection:
            evidence += outcome.peer_selection["evidence_ids"]
        if outcome.valuation_snapshot:
            evidence += outcome.valuation_snapshot["evidence_ids"]
        evidence += [eid for x in getattr(outcome.industry_outcome, "findings", []) for eid in x.get("evidence_ids", [])]
        evidence += list(getattr(outcome.earnings_outcome, "evidence_ids", []))
        outcome.evidence_ids, w = _eligible_evidence(self.db, evidence, request.as_of); outcome.warnings += w
        questions = list(p4["unknowns"]) + list(p4["conflicts"]) + [q for x in outcome.findings for q in x["invalidation_conditions"]]
        questions += list(getattr(outcome.industry_outcome, "dimensions_missing", [])) + list(getattr(outcome.earnings_outcome, "missing_data", []))
        for scenario in getattr(outcome.earnings_outcome, "scenarios", []):
            questions += [
                assumption.invalidates_when for assumption in scenario.assumptions
                if assumption.invalidates_when
            ]
        if outcome.peer_selection and outcome.peer_selection["status"] != "full": questions += outcome.peer_selection["warnings"] or ["peer context insufficient"]
        if outcome.valuation_snapshot: questions += outcome.valuation_snapshot["applicability_notes"]
        outcome.open_questions = sorted(set(q for q in questions if q))
        ind_status = getattr(outcome.industry_outcome, "status", "insufficient_evidence")
        earn_status = getattr(outcome.earnings_outcome, "status", "insufficient_evidence")
        peer_component_status = (
            "insufficient_evidence" if not outcome.peer_selection
            or outcome.peer_selection["status"] == "insufficient" else "success"
        )
        valuation_component_status = (
            "insufficient_evidence" if not outcome.valuation_snapshot
            or outcome.valuation_snapshot["status"] == "insufficient_data"
            else "partial_success" if outcome.valuation_snapshot["status"] == "partial"
            else "success"
        )
        components = [
            ("industry_research", ind_status, [getattr(outcome.industry_outcome, "run_id", "")]),
            ("peer_context", peer_component_status, [outcome.peer_selection["peer_selection_id"]] if outcome.peer_selection else []),
            ("earnings_expectation", earn_status, [getattr(outcome.earnings_outcome, "run_id", "")] if outcome.earnings_outcome else []),
            ("valuation", valuation_component_status, [outcome.valuation_snapshot["valuation_snapshot_id"]] if outcome.valuation_snapshot else []),
            ("catalysts", "success" if len(outcome.catalysts) == len(set(p4["catalyst_ids"])) else "insufficient_evidence", [x["catalyst_id"] for x in outcome.catalysts]),
            ("risks", "success" if len(outcome.risks) == len(set(p4["risk_ids"])) else "insufficient_evidence", [x["risk_id"] for x in outcome.risks]),
            ("counter_evidence", "success", outcome.counter_evidence_ids), ("open_questions", "success", []),
        ]
        for name, status, ids in components: outcome.component_statuses.append(FirstCoverageComponentStatus(component=name, status=status, source_object_ids=[x for x in ids if x]))
        component_states = [item.status for item in outcome.component_statuses]
        if "failed" in component_states or "degraded" in component_states:
            outcome.status = "degraded"
        elif (
            any(status != "success" for status in component_states)
            or len(outcome.findings) != len(set(p4["key_finding_ids"]))
        ):
            outcome.status = "partial_success"
        else:
            outcome.status = "success"
        industry_findings = sorted(
            getattr(outcome.industry_outcome, "findings", []),
            key=lambda item: (item.get("dimension_id", ""), item.get("judgment", "")),
        )
        outcome.idempotency_key = _canonical_key(request, {
            "company_profile": [cp["company_profile_id"], cp["version"]],
            "security_profile": [sp["security_profile_id"], sp["version"]],
            "phase4": [p4["result_id"], p4["version"], p4["as_of"]],
            "findings": sorted([x["finding_id"], x["version"], x["as_of"]] for x in outcome.findings),
            "peer": [outcome.peer_selection["peer_selection_id"], outcome.peer_selection["version"]] if outcome.peer_selection else None,
            "valuation": [outcome.valuation_snapshot["valuation_snapshot_id"], outcome.valuation_snapshot["version"]] if outcome.valuation_snapshot else None,
            "catalysts": sorted([x["catalyst_id"], x["version"]] for x in outcome.catalysts),
            "risks": sorted([x["risk_id"], x["version"]] for x in outcome.risks),
            "counter_evidence": outcome.counter_evidence_ids,
            "evidence": outcome.evidence_ids,
            "industry": {
                "interface_version": "1.0.0", "status": ind_status,
                "dimensions_covered": sorted(getattr(outcome.industry_outcome, "dimensions_covered", [])),
                "dimensions_missing": sorted(getattr(outcome.industry_outcome, "dimensions_missing", [])),
                "findings": industry_findings,
                "evidence_quality": getattr(outcome.industry_outcome, "evidence_quality", {}),
            },
            "earnings": [
                earn_status, getattr(outcome.earnings_outcome, "idempotency_key", ""),
                getattr(outcome.earnings_outcome, "calculation_version", ""),
            ],
        })
        outcome.markdown = _render(request, outcome)
        return outcome
