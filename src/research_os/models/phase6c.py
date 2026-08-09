"""Phase 6C earnings-expectation request and run contracts."""
from __future__ import annotations

from datetime import date
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator, model_validator

from research_os.models.core import StrictModel
from research_os.models.valuation import ForecastScenario
from research_os.utils.time import parse_iso, validate_iso


def _iso(value: str) -> str:
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"must be a valid ISO-8601 timestamp: {value!r}")
    return value


class HistoricalInputPeriod(StrictModel):
    period_label: str = Field(..., min_length=1)
    period_start: Optional[str] = None
    period_end: str
    financial_report_ids: List[str] = Field(default_factory=list)
    financial_fact_ids: List[str] = Field(default_factory=list)
    financial_metric_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    latest_published_at: str
    eligibility_status: Literal["eligible", "conflict", "excluded"] = "eligible"
    warnings: List[str] = Field(default_factory=list)
    input_versions: Dict[str, int] = Field(default_factory=dict)


class ForecastPeriod(StrictModel):
    start: str
    end: str
    periods: List[str] = Field(..., min_length=1)

    @field_validator("start", "end")
    @classmethod
    def _dates(cls, value: str) -> str:
        try:
            date.fromisoformat(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"must be a valid YYYY-MM-DD date: {value!r}") from exc
        return value

    @model_validator(mode="after")
    def _ordered(self) -> "ForecastPeriod":
        if self.start > self.end:
            raise ValueError("forecast period start must not be after end")
        if len(set(self.periods)) != len(self.periods):
            raise ValueError("forecast periods must be unique")
        years: List[int] = []
        for label in self.periods:
            match = re.fullmatch(r"FY(\d{4})", label)
            if match is None:
                raise ValueError(f"forecast period label must match ^FY\\d{{4}}$: {label!r}")
            years.append(int(match.group(1)))
        if years != list(range(years[0], years[0] + len(years))):
            raise ValueError("forecast period years must be strictly increasing and consecutive")
        if years[0] != date.fromisoformat(self.start).year:
            raise ValueError("first forecast label year must equal forecast start year")
        if years[-1] != date.fromisoformat(self.end).year:
            raise ValueError("last forecast label year must equal forecast end year")
        return self


class EarningsExpectationAssumption(StrictModel):
    driver: str = Field(..., min_length=1)
    value: str = Field(..., pattern=r"^-?\d+(\.\d+)?$")
    unit: str = Field(..., min_length=1)
    period: str = Field(..., min_length=1)
    source_type: Literal[
        "company_guidance", "external_opinion", "user_input",
        "deterministic_extrapolation", "model_generated",
    ]
    source_ref_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.5, ge=0, le=1)
    invalidates_when: str = Field(..., min_length=1)
    known_at: Optional[str] = None

    @field_validator("known_at")
    @classmethod
    def _known_at(cls, value: Optional[str]) -> Optional[str]:
        return _iso(value) if value is not None else None


class EarningsExpectationRequest(StrictModel):
    request_id: str
    task_id: str
    company_entity_id: str
    as_of: str
    as_of_basis: Literal["user_provided"] = "user_provided"
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    historical_selection_policy: Literal[
        "eligible_reports_published_by_as_of"
    ] = "eligible_reports_published_by_as_of"
    forecast_period: ForecastPeriod
    assumptions: List[EarningsExpectationAssumption] = Field(..., min_length=1)
    metric_code: str = "revenue"
    scenario_name: str = "base"
    live: bool = False
    dry_run: bool = False
    force: bool = False
    source_policy: Literal["authoritative_db_only"] = "authoritative_db_only"
    status: Literal["validated"] = "validated"
    warnings: List[str] = Field(default_factory=list)
    rule_versions: Dict[str, Any] = Field(default_factory=dict)
    requested_at: str
    version: int = Field(1, ge=1)

    @field_validator("company_entity_id")
    @classmethod
    def _company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError("company_entity_id must start with company:")
        return value

    @field_validator("as_of", "requested_at")
    @classmethod
    def _timestamps(cls, value: str) -> str:
        return _iso(value)

    @model_validator(mode="after")
    def _knowledge_cutoff(self) -> "EarningsExpectationRequest":
        cutoff = parse_iso(self.as_of)
        for assumption in self.assumptions:
            if assumption.source_type == "user_input" and assumption.known_at is None:
                raise ValueError("user_input assumption requires explicit known_at")
            if assumption.known_at and parse_iso(assumption.known_at) > cutoff:
                raise ValueError("assumption known_at must not be after as_of")
        return self


class ProjectionLineage(StrictModel):
    scenario_id: str
    metric_code: str
    baseline_financial_report_id: str
    baseline_financial_fact_id: str
    baseline_period_end: str
    baseline_fiscal_period: Literal["FY"] = "FY"
    baseline_duration_months: Literal[12] = 12
    baseline_normalized_value: str = Field(..., pattern=r"^-?\d+(\.\d+)?$")
    baseline_normalized_unit: str
    assumption_ids: List[str] = Field(..., min_length=1)
    output_periods: List[str] = Field(..., min_length=1)
    formula_version: str
    evidence_ids: List[str] = Field(default_factory=list)


class EarningsExpectationRun(StrictModel):
    run_id: str
    request_id: str
    task_id: str
    company_entity_id: str
    as_of: str
    historical_input_periods: List[HistoricalInputPeriod] = Field(default_factory=list)
    forecast_period: ForecastPeriod
    scenario_ids: List[str] = Field(default_factory=list)
    scenarios: List[ForecastScenario] = Field(default_factory=list)
    projection_lineage: List[ProjectionLineage] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    method: str
    uncertainty: List[str] = Field(default_factory=list)
    calculation_version: str
    generated_by: Literal["deterministic_code"] = "deterministic_code"
    model_route: Dict[str, Any]
    idempotency_key: str
    run_version: int = Field(1, ge=1)
    started_at: str
    finished_at: Optional[str] = None
    status: Literal[
        "success", "partial_success", "degraded", "insufficient_evidence", "failed",
    ]
    stage_statuses: List[Dict[str, Any]] = Field(default_factory=list)
    artifact_paths: List[str] = Field(default_factory=list)
    input_versions: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = "pending"
    error_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    version: int = Field(1, ge=1)

    @field_validator("company_entity_id")
    @classmethod
    def _company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError("company_entity_id must start with company:")
        return value

    @field_validator("as_of", "started_at")
    @classmethod
    def _timestamps(cls, value: str) -> str:
        return _iso(value)

    @field_validator("finished_at")
    @classmethod
    def _finished(cls, value: Optional[str]) -> Optional[str]:
        return _iso(value) if value is not None else None
