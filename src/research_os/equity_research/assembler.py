"""研报结果合成（Phase 4 任务书 3.19 阶段 22/Commit 15）。

Result 只聚合已存在的结构化对象 ID；报告不新增结构化对象之外的关键事实。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models.equity_research import EquityResearchResult
from research_os.utils.time import now_iso

VALID_RESEARCH_STATUS = {
    "success", "partial_success", "degraded", "insufficient_data",
    "source_conflict", "validation_failed", "failed",
}


@dataclass
class ResultInput:
    run_id: str
    request_id: str
    company_entity_id: str
    security_entity_id: str
    as_of: str
    research_status: str
    coverage: Dict[str, Any] = field(default_factory=dict)
    key_finding_ids: List[str] = field(default_factory=list)
    financial_metric_ids: List[str] = field(default_factory=list)
    segment_ids: List[str] = field(default_factory=list)
    peer_selection_id: Optional[str] = None
    valuation_snapshot_id: Optional[str] = None
    forecast_scenario_ids: List[str] = field(default_factory=list)
    catalyst_ids: List[str] = field(default_factory=list)
    risk_ids: List[str] = field(default_factory=list)
    phase3_link_ids: List[str] = field(default_factory=list)
    claim_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    unknowns: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    report_path: Optional[str] = None
    validator_summary: Dict[str, Any] = field(default_factory=dict)
    model_route_summary: Dict[str, Any] = field(default_factory=dict)


def build_result(ri: ResultInput) -> EquityResearchResult:
    if ri.research_status not in VALID_RESEARCH_STATUS:
        raise ValueError(f"非法 research_status: {ri.research_status!r}")
    return EquityResearchResult(
        result_id=str(uuid.uuid4()),
        run_id=ri.run_id,
        request_id=ri.request_id,
        company_entity_id=ri.company_entity_id,
        security_entity_id=ri.security_entity_id,
        as_of=ri.as_of,
        research_status=ri.research_status,  # type: ignore[arg-type]
        coverage=ri.coverage,
        key_finding_ids=ri.key_finding_ids,
        financial_metric_ids=ri.financial_metric_ids,
        segment_ids=ri.segment_ids,
        peer_selection_id=ri.peer_selection_id,
        valuation_snapshot_id=ri.valuation_snapshot_id,
        forecast_scenario_ids=ri.forecast_scenario_ids,
        catalyst_ids=ri.catalyst_ids,
        risk_ids=ri.risk_ids,
        phase3_link_ids=ri.phase3_link_ids,
        claim_ids=ri.claim_ids,
        evidence_ids=ri.evidence_ids,
        unknowns=ri.unknowns,
        conflicts=ri.conflicts,
        warnings=ri.warnings,
        report_path=ri.report_path,
        validator_summary=ri.validator_summary,
        model_route_summary=ri.model_route_summary,
        version=1,
        created_at=now_iso(),
    )
