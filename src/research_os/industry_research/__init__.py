"""Phase 6A industry research data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── 21 canonical industry research dimensions (S2-1: single authority) ──
INDUSTRY_DIMENSIONS = [
    {
        "id": "scope_and_boundary",
        "label": "研究范围与边界",
        "desc": "行业定义、边界、核心产品/服务、产业链位置",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "industry_classification",
        "label": "产业分类",
        "desc": "官方分类标准（GICS/申万/中信）、细分行业归属与对照",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "value_chain",
        "label": "产业链全景",
        "desc": "上中下游结构、价值分布、各环节利润池",
        "hint_node_types": ["Industry", "IndustrySegment", "Material", "Equipment", "Application"],
        "hint_relations": ["UPSTREAM_OF", "DOWNSTREAM_OF", "SUPPLIES", "PURCHASES_FROM", "PRODUCES"],
    },
    {
        "id": "key_segments",
        "label": "关键细分赛道",
        "desc": "高增长/高价值细分领域识别与对比",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "supply",
        "label": "供给侧分析",
        "desc": "产能、产量、供给结构、进入壁垒",
        "hint_node_types": ["Industry", "Material", "Equipment"],
        "hint_relations": ["UPSTREAM_OF", "SUPPLIES"],
    },
    {
        "id": "demand",
        "label": "需求侧分析",
        "desc": "需求驱动因素、市场空间、渗透率、增速",
        "hint_node_types": ["Industry", "Application"],
        "hint_relations": ["DOWNSTREAM_OF", "PURCHASES_FROM"],
    },
    {
        "id": "competitive_landscape",
        "label": "竞争格局",
        "desc": "市场集中度（CRn/HHI）、竞争态势、替代威胁",
        "hint_node_types": ["Industry", "Company"],
        "hint_relations": ["COMPETES_WITH", "BELONGS_TO", "SUBSTITUTES"],
    },
    {
        "id": "technology_path",
        "label": "技术路线对比",
        "desc": "主流与新兴技术路径比较、技术成熟度",
        "hint_node_types": ["Technology", "Equipment", "Industry"],
        "hint_relations": ["USES_TECHNOLOGY", "APPLIED_IN", "SUBSTITUTES"],
    },
    {
        "id": "materials",
        "label": "关键原材料",
        "desc": "原材料来源、价格趋势、供应链安全性",
        "hint_node_types": ["Material", "Industry"],
        "hint_relations": ["UPSTREAM_OF", "SUPPLIES"],
    },
    {
        "id": "equipment",
        "label": "关键设备与工艺",
        "desc": "核心生产设备、制造工艺、国产化率",
        "hint_node_types": ["Equipment", "Industry"],
        "hint_relations": ["PRODUCES", "DOWNSTREAM_OF"],
    },
    {
        "id": "applications",
        "label": "应用场景",
        "desc": "下游应用领域分布、各场景渗透情况",
        "hint_node_types": ["Application", "Industry"],
        "hint_relations": ["APPLIED_IN", "DOWNSTREAM_OF"],
    },
    {
        "id": "policy_and_events",
        "label": "政策与重大事件",
        "desc": "产业政策、监管动向、重大历史事件影响",
        "hint_node_types": ["Policy", "Event", "Industry"],
        "hint_relations": ["AFFECTS", "BENEFITS_FROM", "HARMED_BY", "SUPPORTED_BY"],
    },
    {
        "id": "key_metrics",
        "label": "关键跟踪指标",
        "desc": "行业核心量化指标（量、价、利、库存等）",
        "hint_node_types": ["Metric", "Industry"],
        "hint_relations": ["HAS_METRIC"],
    },
    {
        "id": "key_companies",
        "label": "核心公司映射",
        "desc": "代表性上市公司、业务关联、行业地位",
        "hint_node_types": ["Company", "Industry"],
        "hint_relations": ["BELONGS_TO", "COMPETES_WITH"],
    },
    {
        "id": "catalysts",
        "label": "近期催化剂",
        "desc": "近期可能驱动行业/股价变动的潜在事件",
        "hint_node_types": ["Event", "Policy"],
        "hint_relations": ["HAS_CATALYST", "AFFECTS"],
    },
    {
        "id": "risks",
        "label": "关键风险",
        "desc": "行业面临的主要风险因素及影响评估",
        "hint_node_types": ["Event", "Policy", "Industry"],
        "hint_relations": ["HARMED_BY", "AFFECTS"],
    },
    {
        "id": "core_controversies",
        "label": "核心争议点",
        "desc": "市场主要分歧、多空双方核心论点",
        "hint_node_types": ["Event", "Industry"],
        "hint_relations": ["CONTRADICTED_BY", "AFFECTS"],
    },
    {
        "id": "supporting_evidence",
        "label": "支撑证据",
        "desc": "支持主流/多方观点的关键事实与数据",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "counter_evidence",
        "label": "反向证据",
        "desc": "与主流/多方观点相悖的事实与数据",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "unknowns",
        "label": "已知未知",
        "desc": "已知但不确定性高的领域与关键变量",
        "hint_node_types": [],
        "hint_relations": [],
    },
    {
        "id": "open_questions",
        "label": "待回答的问题",
        "desc": "尚未有定论、需要进一步研究的关键问题",
        "hint_node_types": [],
        "hint_relations": [],
    },
]

RESEARCH_DIMENSIONS_ALL = [d["id"] for d in INDUSTRY_DIMENSIONS]
DIMENSION_FAST = RESEARCH_DIMENSIONS_ALL
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
