"""异动分析数据模型（Phase 3 任务 5 节）。

与 schemas/*.schema.json 一一对应。所有对象遵循：
- JSON Schema 为完整权威契约（全部字段 required、additionalProperties:false）
- Pydantic 仅提供构造便利（默认值），model_dump() 后必须通过对应 Schema
- extra="forbid" 与 Schema additionalProperties:false 一致

PeerMove 不单独建顶层 Schema，作为 AbnormalMoveObservation 的嵌套模型。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------- 枚举字面量 ----------

EntityTypeAM = Literal["company", "industry", "concept"]
Granularity = Literal["daily", "minute"]
Depth = Literal["fast", "standard", "deep"]
AdjustmentMethod = Literal["none", "qfq", "hfq"]
MetricStatus = Literal["valid", "insufficient_sample", "missing_input", "not_applicable"]
Direction = Literal["positive", "negative", "neutral", "unknown"]
BenchmarkType = Literal["market", "industry", "concept", "peer_basket"]
CauseCategory = Literal[
    "direct_trigger", "secondary_catalyst", "industry_or_theme_resonance",
    "market_style_background", "funding_and_trading_structure",
    "expectation_revision", "old_news_recirc", "after_the_fact_explanation",
    "unverified_rumor", "multi_cause_component", "unexplained",
]
TimingRelation = Literal["BEFORE_MOVE", "DURING_MOVE", "AFTER_MOVE", "UNKNOWN_ORDER"]
LinkRelation = Literal["supports", "contradicts", "context", "timing_only"]
LinkDirectness = Literal["direct", "indirect", "inferred"]
LinkTiming = Literal["before", "during", "after", "unknown"]
AttributionStatus = Literal[
    "EXPLAINED", "MULTI_CAUSE", "UNEXPLAINED_MOVE",
    "INSUFFICIENT_EVIDENCE", "SOURCE_CONFLICT", "DATA_DEGRADED",
]
MarketStateFlag = Literal[
    "SUSPENDED", "RESUMPTION", "NEW_LISTING", "ST", "PRICE_LIMIT_UP",
    "PRICE_LIMIT_DOWN", "EX_RIGHTS", "EX_DIVIDEND", "NON_TRADING_DAY",
    "CURRENT_SESSION_NOT_CLOSED", "MISSING_BENCHMARK", "MIXED_ADJUSTMENT",
]
TimingPrecision = Literal["minute", "session", "day", "unknown"]

METRIC_TYPES = [
    "absolute_return", "market_excess_return", "industry_excess_return",
    "concept_excess_return", "beta_adjusted_residual", "volume_anomaly",
    "amount_anomaly", "turnover_anomaly", "amplitude_anomaly",
    "volatility_anomaly", "return_streak", "gap", "peer_breadth",
    "peer_median_return", "idiosyncratic_move",
]
MetricType = Literal[tuple(METRIC_TYPES)]  # type: ignore[valid-type]


def _check_uuid(value: str, field: str) -> str:
    if not UUID_RE.match(value):
        raise ValueError(f"{field} 必须是 UUID 字符串: {value!r}")
    return value


def _check_date(value: str, field: str) -> str:
    if not DATE_RE.match(value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD: {value!r}")
    return value


def _check_iso(value: str, field: str) -> str:
    if not validate_iso(value):
        raise ValueError(f"{field} 必须是 ISO-8601: {value!r}")
    return value


class ModelRoute(StrictModel):
    """模型路由如实记录（DECISIONS #9 / 任务 12.5）。业务升级与 provider 故障回退分离。"""

    mode: Literal["deterministic_fallback", "llm"] = "deterministic_fallback"
    llm_called: bool = False
    intended_default_model: str = "deepseek-v4-flash"
    selected_model: Optional[str] = None
    failure_stage: Optional[str] = None
    limitation: str = "semantic_llm_modules_not_connected"
    escalated: bool = False
    escalation_reasons: List[str] = Field(default_factory=list)
    business_escalation_reason: Optional[str] = None
    provider_fallback_used: bool = False
    provider_fallback_reason: Optional[str] = None


class PeerMove(StrictModel):
    """同类公司（同行）异动表现，嵌套于 AbnormalMoveObservation。"""

    peer_entity_id: str = Field(..., min_length=1)
    peer_name: str = ""
    return_value: Optional[float] = None
    robust_z: Optional[float] = None
    severity: int = Field(0, ge=0, le=5)
    same_direction: bool = False
    abnormal: bool = False
    note: str = ""


class AbnormalMoveRequest(StrictModel):
    request_id: str
    task_id: str
    entity_id: str = Field(..., min_length=1)
    entity_type: EntityTypeAM
    analysis_date: str
    window_start: str
    window_end: str
    granularity: Granularity = "daily"
    depth: Depth = "standard"
    use_realtime: bool = False
    force: bool = False
    dry_run: bool = False
    as_of: str
    timezone: str = "Asia/Shanghai"
    data_policy: str = "primary_then_fallback"
    benchmark_policy: str = "market_industry_concept"
    requested_metrics: List[str] = Field(default_factory=list)
    status: str = "planned"
    warnings: List[str] = Field(default_factory=list)

    @field_validator("request_id", "task_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("analysis_date", "window_start", "window_end")
    @classmethod
    def _date(cls, value: str, info) -> str:
        return _check_date(value, info.field_name)

    @field_validator("as_of")
    @classmethod
    def _as_of(cls, value: str) -> str:
        return _check_iso(value, "as_of")

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("timezone 必须为 Asia/Shanghai")
        return value


class AnomalyMetric(StrictModel):
    metric_id: str
    observation_id: str
    metric_type: MetricType
    value: Optional[float] = None
    unit: str = ""
    direction: Direction = "unknown"
    benchmark_entity_id: Optional[str] = None
    baseline_window: Optional[int] = None
    baseline_method: Optional[str] = None
    baseline_median: Optional[float] = None
    baseline_mad: Optional[float] = None
    robust_z: Optional[float] = None
    historical_percentile: Optional[float] = Field(None, ge=0, le=100)
    cross_sectional_percentile: Optional[float] = Field(None, ge=0, le=100)
    severity: int = Field(0, ge=0, le=5)
    sample_size: int = Field(0, ge=0)
    minimum_sample_size: int = Field(0, ge=0)
    status: MetricStatus = "valid"
    calculation_version: str = "anomaly.v1"
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("metric_id", "observation_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)


class AbnormalMoveObservation(StrictModel):
    observation_id: str
    request_id: str
    entity_id: str = Field(..., min_length=1)
    entity_type: EntityTypeAM
    window_start: str
    window_end: str
    trade_date: str
    granularity: Granularity = "daily"
    provisional: bool = False
    market_data_ids: List[str] = Field(default_factory=list)
    data_manifest_ids: List[str] = Field(default_factory=list)
    adjustment_method: AdjustmentMethod = "none"
    raw_return: Optional[float] = None
    market_relative_return: Optional[float] = None
    industry_relative_return: Optional[float] = None
    concept_relative_returns: Dict[str, Optional[float]] = Field(default_factory=dict)
    metric_ids: List[str] = Field(default_factory=list)
    primary_anomaly_types: List[str] = Field(default_factory=list)
    peer_moves: List[PeerMove] = Field(default_factory=list)
    move_start_at: Optional[str] = None
    move_end_at: Optional[str] = None
    timing_precision: TimingPrecision = "day"
    market_state_flags: List[MarketStateFlag] = Field(default_factory=list)
    status: str = "ok"
    confidence: Optional[float] = Field(None, ge=0, le=1)
    evidence_ids: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("observation_id", "request_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("window_start", "window_end", "trade_date")
    @classmethod
    def _date(cls, value: str, info) -> str:
        return _check_date(value, info.field_name)

    @field_validator("move_start_at", "move_end_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str], info) -> Optional[str]:
        if value is not None:
            return _check_iso(value, info.field_name)
        return value


class BenchmarkCandidate(StrictModel):
    benchmark_candidate_id: str
    request_id: str
    subject_entity_id: str = Field(..., min_length=1)
    benchmark_entity_id: str = Field(..., min_length=1)
    benchmark_type: BenchmarkType
    relationship_valid_from: Optional[str] = None
    relationship_valid_to: Optional[str] = None
    stable_industry_score: int = Field(0, ge=0, le=5)
    main_business_score: int = Field(0, ge=0, le=5)
    supply_chain_score: int = Field(0, ge=0, le=5)
    preexisting_concept_score: int = Field(0, ge=0, le=5)
    historical_correlation_score: int = Field(0, ge=0, le=5)
    event_window_linkage_score: int = Field(0, ge=0, le=5)
    current_event_relevance_score: int = Field(0, ge=0, le=5)
    pre_window_subtotal: float = Field(0, ge=0)
    total_score: float = Field(0, ge=0, le=100)
    correlation_window: Optional[int] = None
    correlation_sample_size: Optional[int] = None
    event_window_breadth: Optional[int] = None
    eligible: bool = False
    exclusion_reasons: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("benchmark_candidate_id", "request_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("relationship_valid_from", "relationship_valid_to")
    @classmethod
    def _date_opt(cls, value: Optional[str], info) -> Optional[str]:
        if value is not None:
            return _check_date(value, info.field_name)
        return value


class BenchmarkSelection(StrictModel):
    benchmark_selection_id: str
    request_id: str
    observation_id: str
    market_benchmark_id: Optional[str] = None
    primary_industry_benchmark_id: Optional[str] = None
    auxiliary_concept_benchmark_ids: List[str] = Field(default_factory=list)
    peer_basket_id: Optional[str] = None
    selected_at: str
    information_cutoff: str
    scoring_version: str = "benchmark.v1"
    candidate_ids: List[str] = Field(default_factory=list)
    fallback_status: str = "full"
    selection_rationale: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("benchmark_selection_id", "request_id", "observation_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("selected_at", "information_cutoff")
    @classmethod
    def _iso(cls, value: str, info) -> str:
        return _check_iso(value, info.field_name)


class CauseCandidate(StrictModel):
    cause_candidate_id: str
    request_id: str
    observation_id: str
    event_id: Optional[str] = None
    claim_ids: List[str] = Field(default_factory=list)
    title: str = Field(..., min_length=1)
    cause_category: CauseCategory
    retrieval_layer: int = Field(1, ge=1, le=4)
    event_time: Optional[str] = None
    first_disclosed_at: Optional[str] = None
    published_at: Optional[str] = None
    retrieved_at: Optional[str] = None
    affected_entity_ids: List[str] = Field(default_factory=list)
    mechanism_summary: str = ""
    time_match_score: int = Field(0, ge=0, le=5)
    entity_link_score: int = Field(0, ge=0, le=5)
    novelty_score: int = Field(0, ge=0, le=5)
    peer_linkage_score: int = Field(0, ge=0, le=5)
    source_reliability_score: int = Field(0, ge=0, le=5)
    explanation_coverage_score: int = Field(0, ge=0, le=5)
    verifiability_score: int = Field(0, ge=0, le=5)
    base_score: float = Field(0, ge=0, le=100)
    penalties: float = Field(0, ge=0)
    final_score: float = Field(0, ge=0, le=100)
    causal_eligibility: bool = False
    timing_relation: TimingRelation = "UNKNOWN_ORDER"
    evidence_ids: List[str] = Field(default_factory=list)
    opposing_evidence_ids: List[str] = Field(default_factory=list)
    independence_groups: List[str] = Field(default_factory=list)
    confidence: Optional[float] = Field(None, ge=0, le=1)
    status: str = "candidate"
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("cause_candidate_id", "request_id", "observation_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("event_time", "first_disclosed_at", "published_at", "retrieved_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str], info) -> Optional[str]:
        if value is not None:
            return _check_iso(value, info.field_name)
        return value


class CauseEvidenceLink(StrictModel):
    link_id: str
    cause_candidate_id: str
    evidence_id: str = Field(..., min_length=1)
    relation: LinkRelation
    directness: LinkDirectness = "indirect"
    timing_relation: LinkTiming = "unknown"
    independence_group: str = Field(..., min_length=1)
    weight: float = 1.0
    notes: str = ""
    created_at: str
    warnings: List[str] = Field(default_factory=list)

    @field_validator("link_id", "cause_candidate_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("created_at")
    @classmethod
    def _created_at(cls, value: str) -> str:
        return _check_iso(value, "created_at")


class AttributionResult(StrictModel):
    attribution_result_id: str
    request_id: str
    observation_id: str
    benchmark_selection_id: Optional[str] = None
    attribution_status: AttributionStatus = "INSUFFICIENT_EVIDENCE"
    primary_cause_ids: List[str] = Field(default_factory=list)
    secondary_cause_ids: List[str] = Field(default_factory=list)
    background_cause_ids: List[str] = Field(default_factory=list)
    hypothesis_cause_ids: List[str] = Field(default_factory=list)
    excluded_cause_ids: List[str] = Field(default_factory=list)
    contradictions: List[str] = Field(default_factory=list)
    fact_claim_ids: List[str] = Field(default_factory=list)
    source_opinion_claim_ids: List[str] = Field(default_factory=list)
    model_inference_claim_ids: List[str] = Field(default_factory=list)
    hypothesis_claim_ids: List[str] = Field(default_factory=list)
    unknown_claim_ids: List[str] = Field(default_factory=list)
    overall_confidence: float = Field(0, ge=0, le=1)
    explanation_coverage: Optional[float] = Field(None, ge=0, le=1)
    evidence_ids: List[str] = Field(default_factory=list)
    model_route: ModelRoute = Field(default_factory=ModelRoute)
    rules_version: str = "attribution.v1"
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("attribution_result_id", "request_id", "observation_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)


class AbnormalMoveRun(StrictModel):
    run_id: str
    task_id: str
    request_id: str
    observation_id: str
    attribution_result_id: Optional[str] = None
    idempotency_key: str = Field(..., min_length=1)
    run_version: int = Field(1, ge=1)
    started_at: str
    finished_at: str
    module_results: List[str] = Field(default_factory=list)
    data_routes: List[str] = Field(default_factory=list)
    model_route: ModelRoute = Field(default_factory=ModelRoute)
    rules_versions: Dict[str, str] = Field(default_factory=dict)
    artifact_paths: List[str] = Field(default_factory=list)
    report_path: Optional[str] = None
    validation_status: str = "pending"
    status: str = "running"
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)

    @field_validator("run_id", "task_id", "request_id", "observation_id")
    @classmethod
    def _uuid(cls, value: str, info) -> str:
        return _check_uuid(value, info.field_name)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _iso(cls, value: str, info) -> str:
        return _check_iso(value, info.field_name)
