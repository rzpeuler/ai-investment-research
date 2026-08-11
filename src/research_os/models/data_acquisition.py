"""P7-D0 Unified Data Layer 契约模型（ScenarioDataRequirement / DataReadiness / DataGap / AcquisitionPlan / BriefAttentionSnapshot）。

每个模型与 schemas/*.schema.json 一一对应；JSON Schema 是权威契约，
Pydantic 只是构造器。model_dump() 后必须通过对应 Schema 校验。
本里程碑只定义契约与 Registry，不实现采集、GapClassifier 或 AcquisitionExecutor。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

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
    coverage_ratio: float = Field(0.0, ge=0.0, le=1.0)
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
