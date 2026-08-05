"""核心数据模型（统一数据契约的 Python 实现）。

每个模型与 schemas/*.schema.json 一一对应：
Task / Entity / RawItem / Event / Opinion / Claim / Evidence / ModuleResult / GraphChange。

所有对象必须通过 Schema 校验（工程指南约束）；Pydantic 校验失败即拒绝实例化，
禁止静默失败。时间字段为 ISO-8601 字符串（Asia/Shanghai 口径）。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from research_os.utils.time import validate_iso

# ---------- 枚举字面量（与 JSON Schema 保持一致） ----------

TaskStatus = Literal["planned", "running", "completed", "failed", "cancelled"]
TaskDepth = Literal["fast", "standard", "deep"]
SourcePolicy = Literal["public_first", "official_first", "manual_only"]
ModelPolicy = Literal["flash_default", "pro_escalation", "no_model"]

EntityType = Literal[
    "industry", "industry_segment", "company", "product", "technology",
    "material", "equipment", "application", "policy", "event", "metric",
    "person_or_institution", "report", "investment_theme", "creator", "unknown",
]

AccessStatus = Literal["ok", "partial", "failed", "unauthorized", "unknown"]
ContentStorage = Literal["metadata_only", "metadata_and_excerpt", "full_text_allowed", "unknown"]

ImpactDirection = Literal["positive", "negative", "mixed", "neutral", "unknown"]
ImpactHorizon = Literal["intraday", "short", "medium", "long"]

Stance = Literal["bullish", "bearish", "mixed", "neutral"]

ClaimType = Literal["FACT", "SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS", "UNKNOWN", "CONFLICT"]
SupportLevel = Literal["direct", "indirect", "inferred"]
ReviewStatus = Literal["unreviewed", "approved", "rejected", "pending_revision", "superseded"]

ModuleStatus = Literal[
    "success", "partial_success", "degraded", "insufficient_evidence", "failed",
]

SourceTier = Literal["S", "A", "B", "C", "D"]

GraphChangeType = Literal["add_node", "add_edge", "modify_attribute", "retire_edge", "retire_node"]
GraphReviewStatus = Literal["candidate", "approved", "approved_with_changes", "deferred", "rejected"]


def _iso_validator(value: Any) -> str:
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


class StrictModel(BaseModel):
    """所有核心模型基类：禁止额外字段，与 JSON Schema additionalProperties:false 一致。"""

    model_config = ConfigDict(extra="forbid")


# ---------- Task（指南 11.1） ----------

class TimeWindow(StrictModel):
    start: Optional[str] = Field(None, description="ISO-8601 或 null")
    end: Optional[str] = Field(None, description="ISO-8601 或 null")

    @field_validator("start", "end")
    @classmethod
    def _v(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


class Task(StrictModel):
    task_id: str = Field(..., description="UUID")
    scenario: str
    status: TaskStatus = "planned"
    requested_at: str
    as_of: str
    finished_at: Optional[str] = Field(None, description="任务结束时间（completed/failed 时写入）")
    timezone: str = "Asia/Shanghai"
    entities: List[str] = Field(default_factory=list)
    time_window: TimeWindow = Field(default_factory=TimeWindow)
    depth: TaskDepth = "standard"
    max_runtime_seconds: int = Field(1200, ge=1)
    source_policy: SourcePolicy = "public_first"
    output_formats: List[str] = Field(default_factory=lambda: ["markdown"])
    model_policy: ModelPolicy = "flash_default"
    warnings: List[str] = Field(default_factory=list)

    @field_validator("task_id")
    @classmethod
    def _task_id(cls, value: str) -> str:
        if len(value) != 36:
            raise ValueError("task_id 必须是 UUID 字符串")
        return value

    @field_validator("requested_at", "as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)

    @field_validator("finished_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("timezone 必须为 Asia/Shanghai")
        return value


# ---------- Entity（指南 11.2） ----------

class Entity(StrictModel):
    entity_id: str
    entity_type: EntityType
    canonical_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    market: str = "unknown"
    industry_ids: List[str] = Field(default_factory=list)
    concept_ids: List[str] = Field(default_factory=list)
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    source_ids: List[str] = Field(default_factory=list)

    @field_validator("entity_id")
    @classmethod
    def _id_prefix(cls, value: str) -> str:
        if ":" not in value:
            raise ValueError("entity_id 必须形如 <type>:<id>")
        return value

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _validity(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


# ---------- RawItem（指南 11.3） ----------

class RawItem(StrictModel):
    raw_item_id: str
    source_id: str = Field(..., min_length=1)
    external_id: Optional[str] = None
    url: str
    title: str = Field(..., min_length=1)
    publisher: str = Field(..., min_length=1)
    author: Optional[str] = None
    published_at: str
    retrieved_at: str
    content_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    content_excerpt: str = Field(..., description="最小必要证据摘录，不保存全文")
    content_storage: ContentStorage = "metadata_and_excerpt"
    language: str = "zh-CN"
    access_status: AccessStatus = "ok"
    entities: List[str] = Field(default_factory=list)
    raw_category: Optional[str] = None

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- Event（指南 11.4） ----------

class Event(StrictModel):
    event_id: str
    event_type: str = Field(..., min_length=1)
    subject_entities: List[str] = Field(default_factory=list)
    object_entities: List[str] = Field(default_factory=list)
    event_time: str
    announced_at: str
    effective_at: Optional[str] = None
    status: str = "announced"
    summary: str = Field(..., min_length=1)
    quantitative_fields: dict = Field(default_factory=dict)
    industry_coordinates: List[str] = Field(default_factory=list)
    novelty: float = Field(0.0, ge=0.0, le=1.0)
    impact_direction: ImpactDirection = "unknown"
    impact_horizon: ImpactHorizon = "short"
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    conflicts: List[str] = Field(default_factory=list)

    @field_validator("event_time", "announced_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)

    @field_validator("effective_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


# ---------- Opinion（指南 11.5） ----------

class Opinion(StrictModel):
    opinion_id: str
    speaker_entity_id: str = Field(..., min_length=1)
    source_id: str = Field(..., min_length=1)
    published_at: str
    target_entities: List[str] = Field(default_factory=list)
    stance: Stance = "neutral"
    thesis: str = Field(..., min_length=1)
    arguments: List[str] = Field(default_factory=list)
    predictions: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    time_horizon: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    influence_score: Optional[float] = Field(None, ge=0.0, le=100.0)

    @field_validator("published_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- Claim（指南 11.6） ----------

class Claim(StrictModel):
    claim_id: str
    claim_type: ClaimType
    statement: str = Field(..., min_length=1)
    subject_entities: List[str] = Field(default_factory=list)
    predicate: str = Field(..., min_length=1)
    object: dict = Field(default_factory=dict)
    as_of: str
    evidence_ids: List[str] = Field(default_factory=list)
    support_level: SupportLevel = "inferred"
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    valid_until: Optional[str] = None
    review_status: ReviewStatus = "unreviewed"

    @field_validator("as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)

    @field_validator("valid_until")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


# ---------- Evidence（指南 11.7） ----------

class Evidence(StrictModel):
    evidence_id: str
    source_id: str = Field(..., min_length=1)
    raw_item_id: str
    title: str = Field(..., min_length=1)
    publisher: str = Field(..., min_length=1)
    published_at: str
    retrieved_at: str
    url: str
    excerpt: str = Field(..., description="支持该 Claim 的最小摘录")
    evidence_type: str = "unknown"
    independence_group: str = Field(..., description="原始事件组，识别转载")
    source_tier: SourceTier = "B"
    access_status: AccessStatus = "ok"

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- ModuleResult（指南 11.8） ----------

class ModuleResult(StrictModel):
    module: str = Field(..., min_length=1)
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+$")
    status: ModuleStatus = "failed"
    as_of: str
    inputs: dict = Field(default_factory=dict)
    facts: List[str] = Field(default_factory=list)
    source_opinions: List[str] = Field(default_factory=list)
    analyses: List[str] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)
    open_questions: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    artifacts: List[str] = Field(default_factory=list)

    @field_validator("as_of")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)


# ---------- GraphChange（指南 46 节） ----------

class GraphChange(StrictModel):
    graph_change_id: str
    change_type: GraphChangeType
    node: Optional[dict] = None
    edge: Optional[dict] = None
    current_knowledge: str = ""
    new_evidence_ids: List[str] = Field(default_factory=list)
    suggested_change: str = Field(..., min_length=1)
    impact_scope: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    verification_points: List[str] = Field(default_factory=list)
    review_status: GraphReviewStatus = "candidate"
    created_at: str
    reviewed_at: Optional[str] = None

    @field_validator("created_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)

    @field_validator("reviewed_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value
