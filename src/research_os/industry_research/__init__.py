"""Phase 6A industry research data model."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

RESEARCH_DIMENSIONS_ALL = [
    "scope_and_boundary", "industry_classification", "value_chain",
    "key_segments", "supply", "demand", "competitive_landscape",
    "technology_path", "materials", "equipment", "applications",
    "policy_and_events", "key_metrics", "key_companies",
    "catalysts", "risks", "core_controversies",
    "supporting_evidence", "counter_evidence", "unknowns",
    "open_questions",
]

DIMENSION_FAST = RESEARCH_DIMENSIONS_ALL[:9]
DIMENSION_STANDARD = RESEARCH_DIMENSIONS_ALL

REPORT_SECTIONS = {
    "scope_and_boundary": "Research Scope & Boundary",
    "industry_classification": "Industry Classification",
    "value_chain": "Value Chain", "key_segments": "Key Segments",
    "supply": "Supply", "demand": "Demand",
    "competitive_landscape": "Competitive Landscape",
    "technology_path": "Technology Path", "materials": "Materials",
    "equipment": "Equipment", "applications": "Applications",
    "policy_and_events": "Policy & Events", "key_metrics": "Key Metrics",
    "key_companies": "Key Companies", "catalysts": "Catalysts",
    "risks": "Risks", "core_controversies": "Core Controversies",
    "supporting_evidence": "Supporting Evidence",
    "counter_evidence": "Counter Evidence", "unknowns": "Unknowns",
    "open_questions": "Open Questions",
}

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
    model_route: str = "deterministic_code"


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
