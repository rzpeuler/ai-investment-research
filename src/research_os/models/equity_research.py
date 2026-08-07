"""个股研报模型（Phase 4 任务书 3.9.3-14/15/16/17/18/19/20）。

研报只能引用已进入结构化对象的内容；报告由结构化对象生成，不先于对象。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from datetime import timedelta

from pydantic import Field, field_validator, model_validator

from research_os.models.core import StrictModel
from research_os.utils.time import parse_iso, validate_iso

MAX_AS_OF_CLOCK_SKEW_SECONDS = 5

FactorType = Literal[
    "technology", "brand", "cost", "channel", "customer_switching",
    "network_effects", "scale", "regulation", "resource", "governance", "other",
]
FactorDirection = Literal["advantage", "disadvantage", "mixed", "unknown"]
FactorStatus = Literal["supported", "weakly_supported", "contested", "unknown"]

SourcePhase = Literal["phase2", "phase3", "phase4", "manual"]
CatalystType = Literal["earnings", "project", "capacity", "product", "price", "policy", "financing", "restructuring", "governance", "other"]
AnnouncementStatus = Literal["occurred", "announced", "in_progress", "completed", "cancelled", "unknown"]
CatalystStatus = Literal["active", "realized", "expired", "cancelled", "unknown"]
WidelyKnown = Literal["yes", "no", "unknown"]

RiskType = Literal["operational", "financial", "governance", "regulatory", "market", "technology", "accounting", "project", "supply_chain", "customer", "concentration", "other"]
RiskStatus = Literal["active", "realized", "mitigated", "expired", "unknown"]

FindingType = Literal["fact_summary", "business_analysis", "financial_quality", "industry_position", "peer_comparison", "valuation_observation", "governance", "controversy", "research_question", "conclusion"]
FindingStatus = Literal["supported", "contested", "unknown"]
Materiality = Literal["high", "medium", "low"]

RequestStatus = Literal["planned", "validated", "rejected"]
Depth = Literal["fast", "standard", "deep"]
SourcePolicy = Literal["public_first", "official_first", "manual_only"]

RunStatus = Literal["planned", "running", "success", "partial_success", "degraded", "insufficient_data", "validation_failed", "failed"]
ValidationStatus = Literal["pending", "pass", "pass_with_warnings", "fail"]

ResearchStatus = Literal["success", "partial_success", "degraded", "insufficient_data", "source_conflict", "validation_failed", "failed"]

ClaimType = Literal["FACT", "SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS", "UNKNOWN", "CONFLICT"]
SupportLevel = Literal["direct", "indirect", "inferred"]


def _check_time(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"{field} 必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


def _check_date(value: Any, field: str) -> Any:
    import re
    if value is None:
        return value
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD 日期: {value!r}")
    return value


def _check_company(value: str) -> str:
    if not value.startswith("company:"):
        raise ValueError(f"company_entity_id 必须以 company: 开头: {value!r}")
    return value


def _check_security(value: str) -> str:
    if not value.startswith("security:"):
        raise ValueError(f"security_entity_id 必须以 security: 开头: {value!r}")
    return value


class CompetitiveFactor(StrictModel):
    """竞争优势/劣势因素。"""

    factor_id: str
    company_entity_id: str
    factor_type: FactorType
    direction: FactorDirection
    statement: str
    business_segment_ids: List[str] = Field(default_factory=list)
    mechanism: str
    required_evidence_types: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    counter_evidence_ids: List[str] = Field(default_factory=list)
    management_only: bool
    confidence: float = Field(..., ge=0, le=1)
    status: FactorStatus
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "created_at")


class Catalyst(StrictModel):
    """催化剂。"""

    catalyst_id: str
    company_entity_id: str
    event_id: Optional[str] = None
    source_phase: SourcePhase
    catalyst_type: CatalystType
    description: str
    claim_type: ClaimType
    announcement_status: AnnouncementStatus
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    impact_mechanism: str
    business_segment_ids: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    status: CatalystStatus = "active"
    widely_known: WidelyKnown = "unknown"
    phase3_attribution_result_id: Optional[str] = None
    version: int = 1
    created_at: str
    updated_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")


class RiskFactor(StrictModel):
    """风险因素。"""

    risk_id: str
    company_entity_id: str
    event_id: Optional[str] = None
    source_phase: SourcePhase
    risk_type: RiskType
    description: str
    claim_type: ClaimType
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    impact_mechanism: str
    business_segment_ids: List[str] = Field(default_factory=list)
    triggers: List[str] = Field(default_factory=list)
    mitigants: List[str] = Field(default_factory=list)
    invalidation_conditions: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    counter_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    status: RiskStatus = "active"
    widely_known: WidelyKnown = "unknown"
    phase3_attribution_result_id: Optional[str] = None
    version: int = 1
    created_at: str
    updated_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("created_at", "updated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")


class ResearchFinding(StrictModel):
    """研究发现。"""

    finding_id: str
    request_id: str
    company_entity_id: str
    finding_type: FindingType
    title: str
    statement: str
    claim_type: ClaimType
    predicate: str
    object: dict = Field(default_factory=dict)
    as_of: str
    evidence_ids: List[str] = Field(default_factory=list)
    supporting_object_ids: List[str] = Field(default_factory=list)
    counter_evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    support_level: SupportLevel = "indirect"
    status: FindingStatus = "unknown"
    invalidation_conditions: List[str] = Field(default_factory=list)
    materiality: Materiality = "medium"
    section_id: str
    model_route: Optional[dict] = None
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("as_of", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")


class EquityResearchRequest(StrictModel):
    """个股研报请求。"""

    request_id: str
    task_id: str
    company_entity_id: str
    security_entity_id: str
    as_of: str
    as_of_basis: Literal["user_provided", "query_cutoff", "data_derived", "unknown"] = "unknown"
    report_date: str
    timezone: str = "Asia/Shanghai"
    depth: Depth = "standard"
    periods: int = Field(5, ge=2, le=10)
    peer_overrides: List[str] = Field(default_factory=list)
    scenario_ids: List[str] = Field(default_factory=list)
    include_valuation: bool = True
    include_forecast: bool = False
    live: bool = False
    dry_run: bool = False
    force: bool = False
    input_document_ids: List[str] = Field(default_factory=list)
    financial_manifest_ids: List[str] = Field(default_factory=list)
    market_manifest_ids: List[str] = Field(default_factory=list)
    source_policy: SourcePolicy = "manual_only"
    status: RequestStatus = "planned"
    warnings: List[str] = Field(default_factory=list)
    rule_versions: Dict[str, str] = Field(default_factory=dict)
    requested_at: str
    version: int = 1

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("security_entity_id")
    @classmethod
    def _v_security(cls, value: str) -> str:
        return _check_security(value)

    @field_validator("as_of", "requested_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")

    @field_validator("report_date")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "report_date")

    @model_validator(mode="after")
    def _v_as_of_not_materially_future(self) -> "EquityResearchRequest":
        if parse_iso(self.as_of) > parse_iso(self.requested_at) + timedelta(
            seconds=MAX_AS_OF_CLOCK_SKEW_SECONDS
        ):
            raise ValueError(
                f"as_of 不得晚于 requested_at 超过 {MAX_AS_OF_CLOCK_SKEW_SECONDS} 秒"
            )
        return self


class StageStatus(StrictModel):
    stage: str
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)


class EquityResearchRun(StrictModel):
    """个股研报运行（幂等键 + run_version 唯一）。"""

    run_id: str
    request_id: str
    task_id: str
    idempotency_key: str
    run_version: int = Field(1, ge=1)
    started_at: str
    finished_at: Optional[str] = None
    status: RunStatus = "planned"
    stage_statuses: List[StageStatus] = Field(default_factory=list)
    artifact_paths: List[str] = Field(default_factory=list)
    input_versions: Dict[str, str] = Field(default_factory=dict)
    model_route_summary: Dict[str, Any] = Field(default_factory=dict)
    validation_status: ValidationStatus = "pending"
    error_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    version: int = 1

    @field_validator("started_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "started_at")


class EquityResearchResult(StrictModel):
    """个股研报结果。"""

    result_id: str
    run_id: str
    request_id: str
    company_entity_id: str
    security_entity_id: str
    as_of: str
    research_status: ResearchStatus
    coverage: dict = Field(default_factory=dict)
    key_finding_ids: List[str] = Field(default_factory=list)
    financial_metric_ids: List[str] = Field(default_factory=list)
    segment_ids: List[str] = Field(default_factory=list)
    peer_selection_id: Optional[str] = None
    valuation_snapshot_id: Optional[str] = None
    forecast_scenario_ids: List[str] = Field(default_factory=list)
    catalyst_ids: List[str] = Field(default_factory=list)
    risk_ids: List[str] = Field(default_factory=list)
    phase3_link_ids: List[str] = Field(default_factory=list)
    claim_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    unknowns: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    report_path: Optional[str] = None
    validator_summary: Dict[str, Any] = Field(default_factory=dict)
    model_route_summary: Dict[str, Any] = Field(default_factory=dict)
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("security_entity_id")
    @classmethod
    def _v_security(cls, value: str) -> str:
        return _check_security(value)

    @field_validator("as_of", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")
