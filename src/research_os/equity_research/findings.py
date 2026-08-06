"""研究发现（Phase 4 任务书 3.9.3-17/Commit 15）。

ResearchFinding 是报告章节数据的结构化来源；报告只能引用已进入结构化对象的内容。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models.equity_research import ResearchFinding
from research_os.utils.time import now_iso

VALID_CLAIM_TYPES = {"FACT", "SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS", "UNKNOWN", "CONFLICT"}


@dataclass
class FindingInput:
    request_id: str
    company_entity_id: str
    finding_type: str
    title: str
    statement: str
    claim_type: str
    predicate: str = ""
    object: Dict[str, Any] = field(default_factory=dict)
    evidence_ids: List[str] = field(default_factory=list)
    supporting_object_ids: List[str] = field(default_factory=list)
    counter_evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    support_level: str = "indirect"
    materiality: str = "medium"
    section_id: str = ""
    model_route: Optional[dict] = None
    invalidation_conditions: List[str] = field(default_factory=list)


def build_finding(fi: FindingInput) -> ResearchFinding:
    """构造 ResearchFinding；FACT 必须带 evidence_ids（Validator 兜底）。"""
    if fi.claim_type not in VALID_CLAIM_TYPES:
        raise ValueError(f"非法 claim_type: {fi.claim_type!r}")
    if fi.claim_type == "FACT" and not fi.evidence_ids:
        # 不拒绝构造，但标记 UNKNOWN 风险由 Validator（ERV-041）拦截
        pass
    status = "supported" if fi.evidence_ids else "unknown"
    if fi.counter_evidence_ids:
        status = "contested"
    return ResearchFinding(
        finding_id=str(uuid.uuid4()),
        request_id=fi.request_id,
        company_entity_id=fi.company_entity_id,
        finding_type=fi.finding_type,  # type: ignore[arg-type]
        title=fi.title,
        statement=fi.statement,
        claim_type=fi.claim_type,  # type: ignore[arg-type]
        predicate=fi.predicate,
        object=fi.object,
        as_of=now_iso(),
        evidence_ids=fi.evidence_ids,
        supporting_object_ids=fi.supporting_object_ids,
        counter_evidence_ids=fi.counter_evidence_ids,
        confidence=fi.confidence,
        support_level=fi.support_level,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        invalidation_conditions=fi.invalidation_conditions,
        materiality=fi.materiality,  # type: ignore[arg-type]
        section_id=fi.section_id,
        model_route=fi.model_route,
        version=1,
        created_at=now_iso(),
    )
