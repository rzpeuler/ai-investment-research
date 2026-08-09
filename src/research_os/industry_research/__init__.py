"""Phase 6A industry research data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── 21 canonical industry research dimensions (S2-1: single authority) ──
INDUSTRY_DIMENSIONS = [
    {"id": "scope_and_boundary",     "label": "研究范围与边界"},
    {"id": "industry_classification", "label": "产业分类"},
    {"id": "value_chain",            "label": "产业链全景"},
    {"id": "key_segments",           "label": "关键细分赛道"},
    {"id": "supply",                 "label": "供给侧分析"},
    {"id": "demand",                 "label": "需求侧分析"},
    {"id": "competitive_landscape",  "label": "竞争格局"},
    {"id": "technology_path",        "label": "技术路线对比"},
    {"id": "materials",              "label": "关键原材料"},
    {"id": "equipment",              "label": "关键设备与工艺"},
    {"id": "applications",           "label": "应用场景"},
    {"id": "policy_and_events",      "label": "政策与重大事件"},
    {"id": "key_metrics",            "label": "关键跟踪指标"},
    {"id": "key_companies",          "label": "核心公司映射"},
    {"id": "catalysts",              "label": "近期催化剂"},
    {"id": "risks",                  "label": "关键风险"},
    {"id": "core_controversies",     "label": "核心争议点"},
    {"id": "supporting_evidence",    "label": "支撑证据"},
    {"id": "counter_evidence",       "label": "反向证据"},
    {"id": "unknowns",               "label": "已知未知"},
    {"id": "open_questions",         "label": "待回答的问题"},
]

RESEARCH_DIMENSIONS_ALL = [d["id"] for d in INDUSTRY_DIMENSIONS]
DIMENSION_FAST = RESEARCH_DIMENSIONS_ALL[:9]
DIMENSION_STANDARD = RESEARCH_DIMENSIONS_ALL

REPORT_SECTIONS = {d["id"]: d["label"] for d in INDUSTRY_DIMENSIONS}

VALID_STATUSES = {"success", "partial_success", "degraded", "insufficient_evidence", "failed"}
VALID_DEPTHS = {"fast", "standard", "deep"}


@dataclass
class IndustryResearchConfig:
    max_graph_depth: int = 2
    max_nodes: int = 200
    max_edges: int = 500
    max_evidence: int = 1000
    max_evidence_per_dimension: int = 50
    assertion_types: Optional[List[str]] = None
    relation_filters: Optional[List[str]] = None
    direction: str = "both"
    deterministic_only: bool = False


@dataclass
class ResearchContext:
    graph_available: bool = False
    root: Optional[Dict[str, Any]] = None
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    epistemic: Dict[str, List[str]] = field(default_factory=dict)
    limitations: List[Dict[str, str]] = field(default_factory=list)
    conflicts: List[Any] = field(default_factory=list)
    as_of: str = ""
    max_depth: int = 0
    query_parameters: Dict[str, Any] = field(default_factory=dict)
    build_error: Optional[str] = None

    @property
    def node_count(self) -> int: return len(self.nodes)
    @property
    def edge_count(self) -> int: return len(self.edges)
    @property
    def evidence_count(self) -> int: return len(self.evidence)


@dataclass
class IndustryFinding:
    finding_id: str = ""
    dimension: str = ""
    title: str = ""
    statement: str = ""
    claim_type: str = "FACT"
    evidence_ids: List[str] = field(default_factory=list)
    graph_node_ids: List[str] = field(default_factory=list)
    confidence: Optional[float] = None
    source_description: str = "deterministic_code"
    model_route: str = "deterministic_fallback"


@dataclass
class IndustryResearchResult:
    status: str = "planned"
    task_id: str = ""
    run_id: str = ""
    industry_id: str = ""
    industry_name: str = ""
    as_of: str = ""
    depth: str = "standard"
    dimensions_covered: List[str] = field(default_factory=list)
    dimensions_missing: List[str] = field(default_factory=list)
    findings: List[IndustryFinding] = field(default_factory=list)
    research_context: Optional[ResearchContext] = None
    markdown: str = ""
    report_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    model_route: Dict[str, Any] = field(default_factory=dict)
    evidence_quality: Dict[str, Any] = field(default_factory=dict)
    data_degraded: bool = False
    exit_code: int = 0
    message: str = ""
