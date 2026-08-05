"""晨报流水线数据模型（Phase 2）。

CandidateItem / EventCluster / InformationScore / MorningBriefRun，
与 schemas/candidate_item|event_cluster|information_score|morning_brief_run 一致。

分类树（任务 8.1-8.4）与 monitoring_channel（任务 5.1）作为常量。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

MonitoringChannel = Literal[
    "fast_news", "deep_financial_media", "community_sentiment",
    "institutional_activity", "official_disclosure",
    "government_and_regulator", "company_official", "market_data",
    "manual_submission", "unknown",
]
ContentType = Literal["fact_report", "opinion", "analysis", "market_data", "unknown"]
CandidateStatus = Literal[
    "collected", "classified", "scored", "selected", "vetoed",
    "quarantined", "deduplicated",
]

# 用户定义的四类主分类树（8.1-8.4），不得自行改动
CLASSIFICATION_TREE: Dict[str, List[str]] = {
    "macro": ["policy", "liquidity", "economic_data", "geopolitics", "emergency"],
    "industry": ["event", "trend", "data", "policy", "technology_breakthrough"],
    "market": ["a_share", "hong_kong", "us_market", "commodity", "rates", "foreign_exchange"],
    "company": ["announcement", "operation", "interaction_and_research", "financing", "risk"],
}

# 四个并列监测方向（不得改造成上下级关系）
MONITORING_CHANNELS: List[str] = [
    "fast_news", "deep_financial_media", "community_sentiment", "institutional_activity",
]


def _iso_opt(value: Optional[str]) -> Optional[str]:
    if value is not None:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


class CandidateItem(StrictModel):
    """候选信息（进入筛选流水线）。"""

    candidate_id: str
    raw_item_ids: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    monitoring_channel: MonitoringChannel = "unknown"
    title: str = Field(..., min_length=1)
    summary: str = ""
    published_at: str
    retrieved_at: str
    event_time: Optional[str] = None
    entities: List[str] = Field(default_factory=list)
    classification_path: List[str] = Field(default_factory=list)
    content_type: ContentType = "unknown"
    language: str = "zh-CN"
    status: CandidateStatus = "collected"
    warnings: List[str] = Field(default_factory=list)

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
        return value

    @field_validator("event_time")
    @classmethod
    def _iso_e(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)

    @field_validator("classification_path")
    @classmethod
    def _path(cls, value: List[str]) -> List[str]:
        if value:
            if value[0] not in CLASSIFICATION_TREE:
                raise ValueError(f"主分类必须属于 {list(CLASSIFICATION_TREE)}: {value[0]!r}")
            if len(value) > 1 and value[1] not in CLASSIFICATION_TREE.get(value[0], []):
                raise ValueError(f"子分类 {value[1]!r} 不属于 {value[0]}")
        return value


class EventCluster(StrictModel):
    """语义事件簇。"""

    cluster_id: str
    canonical_title: str = Field(..., min_length=1)
    event_type: str = Field(..., min_length=1)
    event_time: Optional[str] = None
    first_published_at: str
    last_updated_at: str
    subject_entities: List[str] = Field(default_factory=list)
    member_candidate_ids: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    independence_groups: List[str] = Field(default_factory=list)
    official_confirmation: bool = False
    primary_evidence_ids: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    status: Literal["active", "resolved", "superseded", "rejected"] = "active"

    @field_validator("first_published_at", "last_updated_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
        return value

    @field_validator("event_time")
    @classmethod
    def _iso_e(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)


class InformationScore(StrictModel):
    """信息价值评分（0-5 原始分，final_score 0-100）。"""

    candidate_id: str
    novelty: int = Field(0, ge=0, le=5)
    impact_strength: int = Field(0, ge=0, le=5)
    authority: int = Field(0, ge=0, le=5)
    certainty: int = Field(0, ge=0, le=5)
    impact_scope: int = Field(0, ge=0, le=5)
    expectation_gap: int = Field(0, ge=0, le=5)
    verifiability: int = Field(0, ge=0, le=5)
    market_relevance: int = Field(0, ge=0, le=5)
    base_score: float = Field(0.0, ge=0, le=100)
    penalties: List[str] = Field(default_factory=list)
    bonuses: List[str] = Field(default_factory=list)
    final_score: float = Field(0.0, ge=0, le=100)
    hard_veto: bool = False
    veto_reasons: List[str] = Field(default_factory=list)
    score_reasons: List[str] = Field(default_factory=list)
    forced_include: bool = False
    forced_include_reason: Optional[str] = None


class MorningBriefRun(StrictModel):
    """晨报运行记录。"""

    report_id: str
    task_id: str
    as_of: str
    window_start: str
    window_end: str
    actual_started_at: str
    actual_finished_at: str
    scheduled_for: str
    delayed: bool = False
    delay_seconds: int = 0
    coverage: List[Dict[str, Any]] = Field(default_factory=list)
    selected_cluster_ids: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status: Literal["success", "partial_success", "insufficient_data", "failed"] = "success"

    @field_validator("as_of", "window_start", "window_end",
                     "actual_started_at", "actual_finished_at", "scheduled_for")
    @classmethod
    def _iso(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
        return value
