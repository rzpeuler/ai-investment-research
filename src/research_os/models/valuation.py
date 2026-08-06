"""估值与同行模型（Phase 4 任务书 3.9.3-9/10/11/12/13）。

同行冻结与防事后选择：候选宇宙版本 + 评分权重进幂等键，估值前冻结。
估值仅作观察：不含目标价、合理价值、买卖区间。
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

DECIMAL_RE = re.compile(r"^-?\d+(\.\d+)?$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

SegmentType = Literal["product", "geography", "customer", "channel", "other"]
MappingMethod = Literal["rule", "llm_assisted", "manual"]
SegmentStatus = Literal["active", "superseded", "conflict"]

PeerSelectionStatus = Literal["full", "limited", "insufficient"]
ValuationStatus = Literal["complete", "partial", "not_applicable", "insufficient_data"]
FinancialBasis = Literal["TTM", "FY", "latest", "none"]

ScenarioType = Literal["company_guidance", "external_view", "user_assumption", "deterministic_projection", "model_assisted"]
AssumptionSourceType = Literal["company_guidance", "external_opinion", "user_input", "deterministic_extrapolation", "model_generated"]
ScenarioStatus = Literal["valid", "partial", "invalid", "disabled"]
ForecastClaimType = Literal["SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS"]


def _check_time(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"{field} 必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


def _check_date(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD 日期: {value!r}")
    return value


def _check_decimal(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not DECIMAL_RE.match(value):
        raise ValueError(f"{field} 必须是十进制定点字符串: {value!r}")
    return value


def _check_company(value: str) -> str:
    if not value.startswith("company:"):
        raise ValueError(f"必须以 company: 开头: {value!r}")
    return value


class BusinessSegment(StrictModel):
    """报告期内业务/产品/地区分部。"""

    segment_id: str
    company_entity_id: str
    financial_report_id: str
    parent_segment_id: Optional[str] = None
    segment_type: SegmentType
    raw_name: str
    canonical_name: str
    mapping_method: MappingMethod
    mapping_confidence: float = Field(..., ge=0, le=1)
    valid_from: str
    valid_to: Optional[str] = None
    revenue: Optional[str] = None
    revenue_share: Optional[str] = None
    profit: Optional[str] = None
    profit_margin: Optional[str] = None
    volume: Optional[str] = None
    average_price: Optional[str] = None
    currency: Optional[str] = None
    unit_scale: Optional[int] = None
    metric_fact_ids: List[str] = Field(default_factory=list)
    source_block_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    reclassification_group_id: Optional[str] = None
    status: SegmentStatus = "active"
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("valid_from")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "valid_from")

    @field_validator("revenue", "revenue_share", "profit", "profit_margin", "volume", "average_price")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "分部数值")

    @field_validator("created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "created_at")


class PeerCandidate(StrictModel):
    """冻结同行宇宙中的一个候选及其评分。"""

    peer_candidate_id: str
    subject_company_id: str
    candidate_company_id: str
    information_cutoff: str
    universe_version: str
    relationship_valid_from: str
    relationship_valid_to: Optional[str] = None
    industry_score: int = Field(..., ge=0, le=5)
    business_model_score: int = Field(..., ge=0, le=5)
    revenue_mix_score: int = Field(..., ge=0, le=5)
    supply_chain_score: int = Field(..., ge=0, le=5)
    size_score: int = Field(..., ge=0, le=5)
    listing_tenure_score: int = Field(..., ge=0, le=5)
    accounting_comparability_score: int = Field(..., ge=0, le=5)
    region_score: int = Field(..., ge=0, le=5)
    data_completeness_score: int = Field(..., ge=0, le=5)
    core_subtotal: float = Field(..., ge=0, le=100)
    total_score: float = Field(..., ge=0, le=100)
    eligible: bool
    exclusion_reasons: List[str] = Field(default_factory=list)
    llm_assisted_dimensions: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str

    @field_validator("subject_company_id", "candidate_company_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("information_cutoff", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")

    @field_validator("relationship_valid_from")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "relationship_valid_from")


class PeerSelection(StrictModel):
    """本次研究冻结的同行选择。"""

    peer_selection_id: str
    request_id: str
    subject_company_id: str
    information_cutoff: str
    universe_version: str
    scoring_version: str
    candidate_ids: List[str] = Field(default_factory=list)
    selected_company_ids: List[str] = Field(default_factory=list)
    sample_size: int = Field(0, ge=0)
    minimum_required: int = Field(5, ge=0)
    status: PeerSelectionStatus
    selection_rationale: List[str] = Field(default_factory=list)
    outlier_policy: str
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str

    @field_validator("subject_company_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("information_cutoff", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")


class ValuationMetric(StrictModel):
    metric_code: str
    numerator: Optional[str] = None
    denominator: Optional[str] = None
    value: Optional[str] = None
    unit: str
    status: str
    formula_version: str
    warnings: List[str] = Field(default_factory=list)

    @field_validator("numerator", "denominator", "value")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "估值值")


class ValuationSnapshot(StrictModel):
    """特定时点的估值输入、指标和分位（无目标价）。"""

    valuation_snapshot_id: str
    company_entity_id: str
    security_entity_id: str
    as_of: str
    market_data_manifest_id: Optional[str] = None
    price: Optional[str] = None
    shares_outstanding: Optional[str] = None
    market_cap: Optional[str] = None
    enterprise_value: Optional[str] = None
    financial_period_end: Optional[str] = None
    financial_basis: FinancialBasis = "latest"
    metrics: List[ValuationMetric] = Field(default_factory=list)
    history_window_start: Optional[str] = None
    history_window_end: Optional[str] = None
    history_sample_size: int = Field(0, ge=0)
    peer_selection_id: Optional[str] = None
    peer_sample_size: int = Field(0, ge=0)
    percentile_method: str = "average_rank"
    applicability_notes: List[str] = Field(default_factory=list)
    status: ValuationStatus = "partial"
    source_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    version: int = 1
    calculated_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("security_entity_id")
    @classmethod
    def _v_security(cls, value: str) -> str:
        if not value.startswith("security:"):
            raise ValueError(f"security_entity_id 必须以 security: 开头: {value!r}")
        return value

    @field_validator("as_of", "calculated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")

    @field_validator("price", "shares_outstanding", "market_cap", "enterprise_value")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "估值输入")


class ForecastAssumption(StrictModel):
    assumption_id: str
    driver: str
    value: Any = None
    unit: str
    period: str
    source_type: AssumptionSourceType
    source_ref_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    claim_type: ForecastClaimType
    confidence: float = Field(..., ge=0, le=1)
    invalidates_when: str


class ForecastOutput(StrictModel):
    metric_code: str
    period: str
    value: Optional[str] = None
    unit: str
    formula_version: str
    status: str

    @field_validator("value")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "预测值")


class ForecastScenario(StrictModel):
    """显式、非 FACT 的情景预测（默认关闭）。"""

    scenario_id: str
    request_id: str
    company_entity_id: str
    name: str
    scenario_type: ScenarioType
    enabled: bool
    forecast_start: str
    forecast_end: str
    periods: List[str] = Field(default_factory=list)
    assumptions: List[ForecastAssumption] = Field(default_factory=list)
    outputs: List[ForecastOutput] = Field(default_factory=list)
    sensitivity_axes: List[dict] = Field(default_factory=list)
    confidence: float = Field(..., ge=0, le=1)
    status: ScenarioStatus = "valid"
    llm_called: bool = False
    model_route: Optional[dict] = None
    warnings: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        return _check_company(value)

    @field_validator("forecast_start", "forecast_end")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "预测期间")

    @field_validator("created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "created_at")
