"""Phase 6A 主题发现数据模型（权威来源）。"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

THEME_LIFECYCLE_STATES = ["forming", "supported", "weakening", "invalidated", "uncertain"]
DISCOVERY_MODES = ["graph_based", "evidence_driven", "keyword_sweep", "peer_diffusion"]
FORBIDDEN_METRIC_NAMES = {"buy_score", "stock_score", "investment_score", "recommended_stock", "trade_signal", "position_signal"}


@dataclass
class ThemeTrigger:
    trigger_id: str = ""
    trigger_type: str = ""
    keyword: Optional[str] = None
    industry_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    graph_node_ids: List[str] = field(default_factory=list)
    description: str = ""
    strength: float = 0.5
    first_seen_at: Optional[str] = None
    last_seen_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger_id": self.trigger_id, "trigger_type": self.trigger_type,
            "keyword": self.keyword, "industry_ids": self.industry_ids,
            "evidence_ids": self.evidence_ids, "graph_node_ids": self.graph_node_ids,
            "description": self.description, "strength": self.strength,
            "first_seen_at": self.first_seen_at, "last_seen_at": self.last_seen_at,
        }


@dataclass
class ThemeHypothesis:
    hypothesis_id: str = ""
    theme_name: str = ""
    statement: str = ""
    claim_type: str = "HYPOTHESIS"
    lifecycle_state: str = "forming"
    triggers: List[ThemeTrigger] = field(default_factory=list)
    cross_industry_count: int = 0
    supporting_evidence_ids: List[str] = field(default_factory=list)
    counter_evidence_ids: List[str] = field(default_factory=list)
    supporting_factors: List[str] = field(default_factory=list)
    counter_evidence: List[str] = field(default_factory=list)
    industry_mapping: List[str] = field(default_factory=list)
    related_entity_ids: List[str] = field(default_factory=list)
    invalidating_conditions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    company_ids: List[str] = field(default_factory=list)
    confidence: float = 0.0
    first_observed_at: Optional[str] = None
    updated_at: Optional[str] = None
    generated_by: str = "deterministic_code"
    model_route: str = "deterministic_code"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "hypothesis_id": self.hypothesis_id, "theme_name": self.theme_name,
            "statement": self.statement, "claim_type": self.claim_type,
            "lifecycle_state": self.lifecycle_state,
            "triggers": [t.to_dict() for t in self.triggers],
            "cross_industry_count": self.cross_industry_count,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "counter_evidence_ids": self.counter_evidence_ids,
            "supporting_factors": self.supporting_factors,
            "counter_evidence": self.counter_evidence,
            "industry_mapping": self.industry_mapping,
            "related_entity_ids": self.related_entity_ids,
            "invalidating_conditions": self.invalidating_conditions,
            "open_questions": self.open_questions,
            "company_ids": self.company_ids, "confidence": self.confidence,
            "first_observed_at": self.first_observed_at, "updated_at": self.updated_at,
            "generated_by": self.generated_by, "model_route": self.model_route,
        }


@dataclass
class ResearchSortMetrics:
    evidence_volume: int = 0
    evidence_trend: str = "stable"
    cross_industry_count: int = 0
    company_adoption: int = 0
    policy_support: str = "neutral"
    market_attention: str = "low"
    controversy_level: str = "low"
    research_priority: float = 0.0
    novelty: float = 0.0
    evidence_density: float = 0.0
    theme_relevance: float = 0.0
    uncertainty: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "evidence_volume": self.evidence_volume, "evidence_trend": self.evidence_trend,
            "cross_industry_count": self.cross_industry_count, "company_adoption": self.company_adoption,
            "policy_support": self.policy_support, "market_attention": self.market_attention,
            "controversy_level": self.controversy_level, "research_priority": self.research_priority,
            "novelty": self.novelty, "evidence_density": self.evidence_density,
            "theme_relevance": self.theme_relevance, "uncertainty": self.uncertainty,
        }
        for fb in FORBIDDEN_METRIC_NAMES:
            assert fb not in d, f"Forbidden metric: {fb}"
        return d


@dataclass
class ThemeDiscoveryResult:
    status: str = "planned"
    task_id: str = ""
    run_id: str = ""
    as_of: str = ""
    discovery_mode: str = ""
    themes: List[ThemeHypothesis] = field(default_factory=list)
    sort_metrics: Dict[str, ResearchSortMetrics] = field(default_factory=dict)
    triggers: List[ThemeTrigger] = field(default_factory=list)
    research_context: Optional[Dict[str, Any]] = None
    markdown: str = ""
    report_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)
    model_route: Dict[str, Any] = field(default_factory=dict)
    evidence_quality: Dict[str, Any] = field(default_factory=dict)
    data_degraded: bool = False
    exit_code: int = 0
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status, "task_id": self.task_id, "run_id": self.run_id,
            "as_of": self.as_of, "discovery_mode": self.discovery_mode,
            "themes": [t.to_dict() for t in self.themes],
            "sort_metrics": {k: v.to_dict() for k, v in self.sort_metrics.items()},
            "triggers": [t.to_dict() for t in self.triggers],
            "research_context": self.research_context, "markdown": self.markdown,
            "report_path": self.report_path, "warnings": self.warnings,
            "missing_data": self.missing_data, "model_route": self.model_route,
            "evidence_quality": self.evidence_quality, "data_degraded": self.data_degraded,
            "exit_code": self.exit_code, "message": self.message,
        }
