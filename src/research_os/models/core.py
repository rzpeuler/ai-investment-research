"""核心数据模型（统一数据契约的 Python 实现）。

每个模型与 schemas/*.schema.json 一一对应：
Task / Entity / RawItem / Event / Opinion / Claim / Evidence / ModuleResult / GraphChange。

所有对象必须通过 Schema 校验（工程指南约束）；Pydantic 校验失败即拒绝实例化，
禁止静默失败。时间字段为 ISO-8601 字符串（Asia/Shanghai 口径）。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from research_os.utils.time import validate_iso

# ---------- 枚举字面量（与 JSON Schema 保持一致） ----------

TaskStatus = Literal["planned", "running", "completed", "failed", "cancelled"]
TaskDepth = Literal["fast", "standard", "deep"]
SourcePolicy = Literal["public_first", "official_first", "manual_only"]
ModelPolicy = Literal["flash_default", "pro_escalation", "no_model"]

EntityType = Literal[
    "industry", "industry_segment", "company", "security", "product", "technology",
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


# ---------- Phase 5 图谱枚举 ----------

GraphNodeType = Literal[
    "Industry", "IndustrySegment", "Company", "Product", "Technology",
    "Material", "Equipment", "Application", "Policy", "Event",
    "Metric", "PersonOrInstitution", "Report", "InvestmentTheme",
]

GraphNodeStatus = Literal["active", "superseded", "expired", "retired"]

GraphRelation = Literal[
    "BELONGS_TO", "UPSTREAM_OF", "DOWNSTREAM_OF", "SUPPLIES",
    "PURCHASES_FROM", "PRODUCES", "USES_TECHNOLOGY", "APPLIED_IN",
    "COMPETES_WITH", "SUBSTITUTES", "BENEFITS_FROM", "HARMED_BY",
    "AFFECTS", "MENTIONED_IN", "SUPPORTED_BY", "CONTRADICTED_BY",
    "HAS_METRIC", "HAS_CATALYST",
]

GraphAssertionType = Literal["GOVERNANCE", "FACT", "MODEL_INFERENCE"]
GraphProposalAssertionType = Literal["FACT", "MODEL_INFERENCE"]

GraphObjectReviewStatus = Literal["candidate", "approved"]

GraphOriginKind = Literal["governance_seed", "graph_change"]

GraphReviewDecision = Literal["approved", "approved_with_changes", "deferred", "rejected"]

GraphPatchOp = Literal["add", "replace", "remove"]


# ---------- GraphNode（Phase 5 M1-R1） ----------

class GraphNode(StrictModel):
    node_id: str = Field(..., min_length=1)
    node_type: GraphNodeType
    name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    status: GraphNodeStatus = "active"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)
    version: int = Field(1, ge=1)
    last_reviewed_at: Optional[str] = None
    review_status: GraphObjectReviewStatus = "candidate"
    origin_kind: GraphOriginKind = "graph_change"
    originating_graph_change_id: Optional[str] = None
    created_at: str = Field(..., description="创建时间（必传合法 ISO）")

    @field_validator("created_at", "last_reviewed_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _validity_iso(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value

    @model_validator(mode="after")
    def _check_company_prefix(self) -> "GraphNode":
        if self.node_type == "Company" and not self.node_id.startswith("company:"):
            raise ValueError("Company node_id 必须以 'company:' 开头")
        return self


# ---------- GraphEdge（Phase 5 M1-R1） ----------

class GraphEdge(StrictModel):
    edge_id: str = Field(..., min_length=1)
    source_node_id: str = Field(..., min_length=1)
    relation: GraphRelation
    target_node_id: str = Field(..., min_length=1)
    attributes: dict = Field(default_factory=dict)
    assertion_type: GraphAssertionType = "FACT"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    evidence_ids: List[str] = Field(default_factory=list)
    review_status: GraphObjectReviewStatus = "candidate"
    version: int = Field(1, ge=1)
    originating_graph_change_id: Optional[str] = None
    created_at: str = Field(..., description="创建时间（必传合法 ISO）")
    last_reviewed_at: Optional[str] = None

    @field_validator("created_at", "last_reviewed_at")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _validity_iso(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


# ---------- GraphChange（M1-R1 typed node/edge） ----------

class GraphChange(StrictModel):
    """GraphChange with typed node/edge fields."""
    graph_change_id: str
    change_type: GraphChangeType
    node: Optional["GraphNode"] = None
    edge: Optional["GraphEdge"] = None
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

    @model_validator(mode="after")
    def _check_payload_consistency(self) -> "GraphChange":
        ct = self.change_type
        node = self.node
        edge = self.edge
        if ct in ("add_node", "retire_node"):
            if node is None:
                raise ValueError(f"{ct} 要求 node 非 null")
            if edge is not None:
                raise ValueError(f"{ct} 要求 edge 为 null")
        elif ct in ("add_edge", "retire_edge"):
            if edge is None:
                raise ValueError(f"{ct} 要求 edge 非 null")
            if node is not None:
                raise ValueError(f"{ct} 要求 node 为 null")
        elif ct == "modify_attribute":
            if (node is None and edge is None) or (node is not None and edge is not None):
                raise ValueError("modify_attribute 要求恰好 node / edge 其中一个非 null")
        return self


# ---------- GraphChangeProposal 辅助模型 ----------

class GraphProposalNode(StrictModel):
    existing_node_id: Optional[str] = None
    node_type: GraphNodeType
    name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    description: str = ""
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


class GraphProposalEdge(StrictModel):
    source_node_id: str = Field(..., min_length=1)
    relation: GraphRelation
    target_node_id: str = Field(..., min_length=1)
    attributes: dict = Field(default_factory=dict)
    assertion_type: GraphProposalAssertionType = "FACT"
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @field_validator("valid_from", "valid_to")
    @classmethod
    def _iso_opt(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            return _iso_validator(value)
        return value


# ---------- GraphChangeProposal（Phase 5 M1-R1） ----------

class GraphChangeProposal(StrictModel):
    proposal_type: GraphChangeType
    source_object_ids: List[str] = Field(..., min_length=1)
    candidate_node: Optional[GraphProposalNode] = None
    candidate_edge: Optional[GraphProposalEdge] = None
    new_evidence_ids: List[str] = Field(..., min_length=1)
    suggested_change: str = Field(..., min_length=1)
    impact_scope: List[str] = Field(default_factory=list)
    conflicts: List[str] = Field(default_factory=list)
    verification_points: List[str] = Field(default_factory=list)
    confidence: float = Field(0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def _check_payload_consistency(self) -> "GraphChangeProposal":
        pt = self.proposal_type
        cn = self.candidate_node
        ce = self.candidate_edge
        if pt == "add_node":
            if cn is None:
                raise ValueError("add_node 要求 candidate_node 非 null")
            if cn.existing_node_id is not None:
                raise ValueError("add_node 要求 existing_node_id 为 null")
            if ce is not None:
                raise ValueError("add_node 要求 candidate_edge 为 null")
        elif pt == "retire_node":
            if cn is None:
                raise ValueError("retire_node 要求 candidate_node 非 null")
            if cn.existing_node_id is None:
                raise ValueError("retire_node 要求 existing_node_id 非 null")
            if ce is not None:
                raise ValueError("retire_node 要求 candidate_edge 为 null")
        elif pt in ("add_edge", "retire_edge"):
            if ce is None:
                raise ValueError(f"{pt} 要求 candidate_edge 非 null")
            if cn is not None:
                raise ValueError(f"{pt} 要求 candidate_node 为 null")
        elif pt == "modify_attribute":
            if (cn is None and ce is None) or (cn is not None and ce is not None):
                raise ValueError("modify_attribute 要求恰好 candidate_node / candidate_edge 一个非 null")
            if cn is not None and cn.existing_node_id is None:
                raise ValueError("modify_attribute with node 要求 existing_node_id 非 null")
        return self


# ---------- GraphReview 辅助模型 ----------

class GraphReviewer(StrictModel):
    reviewer_type: Literal["human"] = "human"
    reviewer_id: str = Field(..., min_length=1)
    display_name: Optional[str] = None


class GraphPatchValueOperation(StrictModel):
    op: Literal["add", "replace"]
    path: str = Field(..., min_length=1)
    value: Any = None

    @field_validator("path")
    @classmethod
    def _allowed_path(cls, value: str) -> str:
        _check_patch_path(value)
        return value


class GraphPatchRemoveOperation(StrictModel):
    op: Literal["remove"]
    path: str = Field(..., min_length=1)

    @field_validator("path")
    @classmethod
    def _allowed_path(cls, value: str) -> str:
        _check_patch_path(value)
        return value


GraphPatchOperation = Union[GraphPatchValueOperation, GraphPatchRemoveOperation]


_ALLOWED_PATCH_PATHS = {
    "/suggested_change", "/impact_scope", "/conflicts", "/verification_points",
    "/new_evidence_ids",
    "/node/name", "/node/aliases", "/node/description", "/node/status",
    "/node/valid_from", "/node/valid_to", "/node/evidence_ids",
    "/edge/attributes", "/edge/valid_from", "/edge/valid_to",
    "/edge/confidence", "/edge/evidence_ids",
}


def _check_patch_path(path: str) -> None:
    """机械检查 patch path 是否在允许的业务路径白名单内（含子路径）。"""
    for allowed in _ALLOWED_PATCH_PATHS:
        if path == allowed or path.startswith(allowed + "/"):
            return
    raise ValueError(f"禁止的 patch 路径: {path}")


# ---------- GraphReview（Phase 5 M1-R1） ----------

class GraphReview(StrictModel):
    review_id: str
    graph_change_id: str
    decision: GraphReviewDecision
    reviewer: GraphReviewer
    reviewed_at: str
    candidate_hash: str = Field(..., pattern=r"^[0-9a-f]{64}$")
    review_patch: List[GraphPatchOperation] = Field(default_factory=list)
    notes: str = ""
    resulting_graph_change_id: Optional[str] = None

    @field_validator("reviewed_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        return _iso_validator(value)

    @model_validator(mode="after")
    def _check_decision_consistency(self) -> "GraphReview":
        d = self.decision
        patch = self.review_patch
        rid = self.resulting_graph_change_id
        if d == "approved":
            if patch:
                raise ValueError("approved 要求 review_patch 为空")
            if rid is not None:
                raise ValueError("approved 要求 resulting_graph_change_id 为 null")
        elif d == "approved_with_changes":
            if len(patch) < 1:
                raise ValueError("approved_with_changes 要求 review_patch 至少 1 项")
            if rid is None:
                raise ValueError("approved_with_changes 要求 resulting_graph_change_id 非 null")
        elif d == "deferred":
            if patch:
                raise ValueError("deferred 要求 review_patch 为空")
            if rid is not None:
                raise ValueError("deferred 要求 resulting_graph_change_id 为 null")
        elif d == "rejected":
            if patch:
                raise ValueError("rejected 要求 review_patch 为空")
            if rid is not None:
                raise ValueError("rejected 要求 resulting_graph_change_id 为 null")
        return self
