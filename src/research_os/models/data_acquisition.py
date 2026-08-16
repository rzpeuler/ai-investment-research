"""P7-D0 Unified Data Layer 契约模型（ScenarioDataRequirement / DataReadiness / DataGap / AcquisitionPlan / BriefAttentionSnapshot）。

每个模型与 schemas/*.schema.json 一一对应；JSON Schema 是权威契约，
Pydantic 只是构造器。model_dump() 后必须通过对应 Schema 校验。
本里程碑只定义契约与 Registry，不实现采集、GapClassifier 或 AcquisitionExecutor。
"""
from __future__ import annotations

from typing import Annotated, Any, List, Literal, Optional, Union
from uuid import UUID

from pydantic import Field, StrictInt, StringConstraints, field_validator, model_validator

from research_os.models.core import StrictModel
from research_os.models.sources import DataRoute
from research_os.utils.time import parse_iso, validate_iso

# ---------- 枚举字面量（与 JSON Schema 保持一致） ----------

ScenarioId = Literal[
    "morning_brief", "evening_brief", "daily_review",
    "abnormal_move_analysis", "stock_research_report", "first_coverage",
    "stock_review", "industry_research", "theme_discovery",
    "earnings_expectation",
]

RequirementPurpose = Literal[
    "research_input", "brief_event_discovery", "brief_attention_monitoring",
]

ScopeType = Literal[
    "global", "subject", "benchmark", "peers", "industry", "watchlist", "scenario",
]

TimePolicy = Literal[
    "scenario_window", "explicit_request_window", "as_of_snapshot",
    "latest_available", "lookback_trading_days",
]

PointInTimePolicy = Literal[
    "strict_as_of", "window_bounded", "current_snapshot", "not_applicable",
]

ReadinessStatus = Literal[
    "READY", "PARTIAL", "MISSING", "STALE",
    "SOURCE_UNHEALTHY", "MANUAL_REQUIRED", "NOT_ACQUIRABLE",
]

GapClassification = Literal[
    "AVAILABLE", "AUTO_ACQUIRABLE", "AUTO_DERIVABLE",
    "STALE_REFRESHABLE", "MANUAL_INPUT_REQUIRED", "HUMAN_REVIEW_REQUIRED",
    "GOVERNED_WORKFLOW_REQUIRED", "UNAVAILABLE",
]

AcquisitionAction = Literal[
    "route_existing_sources", "derive_existing", "request_manual_input",
    "request_human_review", "governed_workflow", "unavailable",
]

PlanStepStatus = Literal["pending", "in_progress", "completed", "blocked", "failed"]

AcquisitionExecutionStatus = Literal[
    "not_executable", "completed", "partial_success", "failed",
]

AcquisitionExecutionStepStatus = Literal[
    "not_executable", "skipped", "completed", "partial_success", "failed",
]

AcquisitionExecutionReason = Literal[
    "EXECUTION_DISABLED", "LIVE_GATE_DISABLED", "DRY_RUN_PROHIBITS_EXECUTION",
    "PLAN_CONTEXT_MISMATCH", "ACTION_SKIPPED", "REQUIREMENT_NOT_FOUND",
    "DATA_TYPE_MISMATCH", "CAPABILITY_NOT_BUSINESS_SUFFICIENT", "ROUTE_UNAVAILABLE",
    "FETCH_FAILED", "NORMALIZATION_FAILED", "RAW_ITEM_SCHEMA_INVALID",
    "FUTURE_ITEM_REJECTED", "EMPTY_RESULT", "PERSIST_FAILED", "RECHECK_FAILED",
    "CONTROL_PLANE_CONFIGURATION_ERROR",
]

StrictText = Annotated[str, StringConstraints(strict=True)]
NonEmptyStrictText = Annotated[str, StringConstraints(strict=True, min_length=1)]
Sha256Text = Annotated[str, StringConstraints(strict=True, pattern=r"^[0-9a-f]{64}$")]

CoverageStatus = Literal["covered", "partial", "manual_only", "not_covered", "source_failure"]


def _iso_validator(value: str) -> str:
    if not validate_iso(value):
        raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


# ---------- ScenarioDataRequirement（§12-15） ----------

class RequirementScope(StrictModel):
    scope_type: ScopeType
    reference: Optional[str] = None
    watchlist_group: Optional[str] = None


class ScenarioDataRequirement(StrictModel):
    requirement_id: str = Field(..., min_length=1)
    scenario: ScenarioId
    purpose: RequirementPurpose
    data_type: str = Field(..., min_length=1)
    scope: RequirementScope
    time_policy: TimePolicy
    required: bool
    minimum_fields: List[str] = Field(default_factory=list)
    minimum_coverage: float = Field(0.0, ge=0.0, le=1.0)
    minimum_source_tier: Literal["S", "A", "B", "C", "D"] = "D"
    freshness_seconds: int = Field(0, ge=0)
    point_in_time_policy: PointInTimePolicy
    acceptable_fallback_modes: List[str] = Field(default_factory=list)
    degradation_policy: str = Field(..., min_length=1)
    notes: str = ""


# ---------- DataReadiness（§16） ----------

class DataReadiness(StrictModel):
    requirement_id: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1)
    checked_at: str
    as_of: str
    status: ReadinessStatus
    available_fields: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    coverage_ratio: Optional[float] = Field(None, ge=0.0, le=1.0)
    freshness_age_seconds: Optional[int] = Field(None, ge=0)
    eligible_record_count: int = Field(0, ge=0)
    ineligible_record_count: int = Field(0, ge=0)
    source_tiers_present: List[Literal["S", "A", "B", "C", "D"]] = Field(default_factory=list)
    record_refs: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("checked_at", "as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- DataGap（§17） ----------

class DataGap(StrictModel):
    requirement_id: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1)
    classification: GapClassification
    reason_codes: List[str] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    recommended_action: str = Field(..., min_length=1)
    requires_network: bool = False
    requires_user_input: bool = False
    requires_human_review: bool = False
    warnings: List[str] = Field(default_factory=list)


# ---------- AcquisitionPlan（§18-19） ----------

class AcquisitionStep(StrictModel):
    step_id: str = Field(..., min_length=1)
    requirement_id: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1)
    action: AcquisitionAction
    dependencies: List[str] = Field(default_factory=list)
    status: PlanStepStatus = "pending"
    warnings: List[str] = Field(default_factory=list)


class AcquisitionPlan(StrictModel):
    task_id: str = Field(..., min_length=1)
    scenario: ScenarioId
    as_of: str
    steps: List[AcquisitionStep] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- AcquisitionExecutionResult（P7-D2 Foundation） ----------

class AcquisitionExecutionError(StrictModel):
    code: NonEmptyStrictText
    message: NonEmptyStrictText
    component: NonEmptyStrictText


class AcquisitionExecutionStepResult(StrictModel):
    step_id: NonEmptyStrictText
    requirement_id: NonEmptyStrictText
    data_type: NonEmptyStrictText
    action: AcquisitionAction
    status: AcquisitionExecutionStepStatus
    reason_codes: List[AcquisitionExecutionReason] = Field(..., strict=True)
    route: Optional[DataRoute]
    inserted_raw_item_ids: List[NonEmptyStrictText] = Field(..., strict=True)
    reused_raw_item_ids: List[NonEmptyStrictText] = Field(..., strict=True)
    inserted_count: StrictInt = Field(..., ge=0)
    reused_count: StrictInt = Field(..., ge=0)
    rejected_future_item_count: StrictInt = Field(..., ge=0)
    warnings: List[StrictText] = Field(..., strict=True)
    errors: List[AcquisitionExecutionError] = Field(..., strict=True)

    @field_validator("route", mode="before")
    @classmethod
    def _strict_data_route(cls, value: object) -> object:
        if value is None:
            return value
        payload = value.model_dump() if isinstance(value, DataRoute) else value
        from research_os.validators.schema_validator import validate_instance

        errors = validate_instance(payload, "data_route")
        if errors:
            raise ValueError(f"route must match the authoritative DataRoute schema: {errors}")
        return value


class AcquisitionExecutionResult(StrictModel):
    execution_id: StrictText
    task_id: NonEmptyStrictText
    scenario: ScenarioId
    as_of: StrictText
    plan_sha256: Sha256Text
    started_at: StrictText
    finished_at: StrictText
    status: AcquisitionExecutionStatus
    steps: List[AcquisitionExecutionStepResult] = Field(..., strict=True)
    readiness_before_requirement_ids: List[NonEmptyStrictText] = Field(..., strict=True)
    readiness_after_requirement_ids: List[NonEmptyStrictText] = Field(..., strict=True)
    warnings: List[StrictText] = Field(..., strict=True)
    errors: List[AcquisitionExecutionError] = Field(..., strict=True)

    @field_validator("execution_id")
    @classmethod
    def _uuid5(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except (TypeError, ValueError, AttributeError) as exc:
            raise ValueError("execution_id must be a UUID5") from exc
        if parsed.version != 5 or str(parsed) != value:
            raise ValueError("execution_id must be a canonical lowercase UUID5")
        return value

    @field_validator("as_of", "started_at", "finished_at")
    @classmethod
    def _execution_iso(cls, value: str) -> str:
        return _iso_validator(value)

    @model_validator(mode="after")
    def _time_order(self) -> "AcquisitionExecutionResult":
        if parse_iso(self.finished_at) < parse_iso(self.started_at):
            raise ValueError("finished_at must not precede started_at")
        return self


# ---------- BriefAttentionSnapshot（§20-23） ----------

class AttentionCoverage(StrictModel):
    watchlist_group: str = Field(..., min_length=1)
    configured_count: int = Field(0, ge=0)
    attempted_count: int = Field(0, ge=0)
    succeeded_count: int = Field(0, ge=0)
    failed_count: int = Field(0, ge=0)
    status: CoverageStatus
    warnings: List[str] = Field(default_factory=list)


class GroupCount(StrictModel):
    group: str = Field(..., min_length=1)
    count: int = Field(0, ge=0)


class PublicMetric(StrictModel):
    """平台直接公开提供的指标（R1-01：strict nested object，非自由键 dict）。

    value 只保存平台公开观察值；不得在此编码 trend / velocity / rank_change /
    historical_heat 等持续监控字段。
    """
    metric_name: str = Field(..., min_length=1)
    value: Optional[Union[float, int, str]] = None
    unit: Optional[str] = None
    source_reference: Optional[str] = None
    observed_at: Optional[str] = None

    @field_validator("observed_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


PublicMetric.model_rebuild()


class AttentionTopic(StrictModel):
    rank: int = Field(..., ge=1)
    topic_label: str = Field(..., min_length=1)
    heat_score: float = Field(0.0, ge=0.0)
    mention_count: int = Field(0, ge=0)
    unique_source_count: int = Field(0, ge=0)
    unique_author_count: int = Field(0, ge=0)
    group_counts: List[GroupCount] = Field(default_factory=list)
    representative_item_ids: List[str] = Field(default_factory=list)
    public_metrics: List[PublicMetric] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class BriefAttentionSnapshot(StrictModel):
    snapshot_id: str = Field(..., min_length=1)
    task_id: str = Field(..., min_length=1)
    scenario: Literal["morning_brief", "evening_brief"]
    window_start: str
    window_end: str
    as_of: str
    coverage: List[AttentionCoverage] = Field(default_factory=list)
    topics: List[AttentionTopic] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("window_start", "window_end", "as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)
