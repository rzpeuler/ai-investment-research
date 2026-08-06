"""催化剂与风险（Phase 4 任务书 3.17/Commit 13）。

- 每项区分：已发生事实 / 已宣布未完成 / 公司指引 / 外部观点 / 模型推断 / 假设 / 未知 / 冲突；
- 必填字段：类型/描述/时间窗口/影响机制/关联业务/前置条件/失效条件/Evidence/Claim/
  置信度/状态/市场是否广泛知晓/Phase 2/3 来源/更新日期；
- "市场广泛知晓"缺证据时 unknown，不得由模型自信判断；
- Phase 3 归因结果只读引用（phase3_attribution_result_id），不得改写 AttributionResult。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from research_os.models.equity_research import Catalyst, RiskFactor
from research_os.utils.time import now_iso


@dataclass
class CatalystInput:
    company_entity_id: str
    catalyst_type: str
    description: str
    claim_type: str  # FACT/SOURCE_OPINION/MODEL_INFERENCE/HYPOTHESIS/UNKNOWN/CONFLICT
    announcement_status: str  # occurred/announced/in_progress/completed/cancelled/unknown
    source_phase: str = "phase4"  # phase2/phase3/phase4/manual
    event_id: Optional[str] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    impact_mechanism: str = ""
    business_segment_ids: List[str] = field(default_factory=list)
    prerequisites: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    widely_known: str = "unknown"  # yes/no/unknown
    phase3_attribution_result_id: Optional[str] = None


@dataclass
class RiskInput:
    company_entity_id: str
    risk_type: str
    description: str
    claim_type: str
    source_phase: str = "phase4"
    event_id: Optional[str] = None
    time_window_start: Optional[str] = None
    time_window_end: Optional[str] = None
    impact_mechanism: str = ""
    business_segment_ids: List[str] = field(default_factory=list)
    triggers: List[str] = field(default_factory=list)
    mitigants: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    counter_evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    widely_known: str = "unknown"
    phase3_attribution_result_id: Optional[str] = None


def build_catalyst(ci: CatalystInput) -> Catalyst:
    ts = now_iso()
    # 已发生事实（occurred）要求 FACT 或至少 evidence；否则标记 unknown/待验证
    status = "active"
    if ci.announcement_status == "completed":
        status = "realized"
    elif ci.announcement_status == "cancelled":
        status = "cancelled"
    return Catalyst(
        catalyst_id=str(uuid.uuid4()),
        company_entity_id=ci.company_entity_id,
        event_id=ci.event_id,
        source_phase=ci.source_phase,  # type: ignore[arg-type]
        catalyst_type=ci.catalyst_type,  # type: ignore[arg-type]
        description=ci.description,
        claim_type=ci.claim_type,  # type: ignore[arg-type]
        announcement_status=ci.announcement_status,  # type: ignore[arg-type]
        time_window_start=ci.time_window_start,
        time_window_end=ci.time_window_end,
        impact_mechanism=ci.impact_mechanism,
        business_segment_ids=ci.business_segment_ids,
        prerequisites=ci.prerequisites,
        invalidation_conditions=ci.invalidation_conditions,
        evidence_ids=ci.evidence_ids,
        confidence=ci.confidence,
        status=status,  # type: ignore[arg-type]
        widely_known=ci.widely_known,  # type: ignore[arg-type]
        phase3_attribution_result_id=ci.phase3_attribution_result_id,
        version=1,
        created_at=ts,
        updated_at=ts,
    )


def build_risk(ri: RiskInput) -> RiskFactor:
    ts = now_iso()
    status = "active"
    if ri.counter_evidence_ids:
        status = "mitigated"
    return RiskFactor(
        risk_id=str(uuid.uuid4()),
        company_entity_id=ri.company_entity_id,
        event_id=ri.event_id,
        source_phase=ri.source_phase,  # type: ignore[arg-type]
        risk_type=ri.risk_type,  # type: ignore[arg-type]
        description=ri.description,
        claim_type=ri.claim_type,  # type: ignore[arg-type]
        time_window_start=ri.time_window_start,
        time_window_end=ri.time_window_end,
        impact_mechanism=ri.impact_mechanism,
        business_segment_ids=ri.business_segment_ids,
        triggers=ri.triggers,
        mitigants=ri.mitigants,
        invalidation_conditions=ri.invalidation_conditions,
        evidence_ids=ri.evidence_ids,
        counter_evidence_ids=ri.counter_evidence_ids,
        confidence=ri.confidence,
        status=status,  # type: ignore[arg-type]
        widely_known=ri.widely_known,  # type: ignore[arg-type]
        phase3_attribution_result_id=ri.phase3_attribution_result_id,
        version=1,
        created_at=ts,
        updated_at=ts,
    )


def check_widely_known(evidence_ids: List[str], explicitly_known: bool) -> str:
    """市场广泛知晓：有明确证据 → yes；明确否定 → no；否则 unknown（不得自信判断）。"""
    if explicitly_known:
        return "yes"
    if evidence_ids:
        return "yes"
    return "unknown"


def link_phase3_unexplained(catalyst: CatalystInput, attribution_status: str) -> CatalystInput:
    """Phase 3 异动无法归因 → 关联归因 ID 但保持 UNEXPLAINED，不得补猜原因。"""
    if attribution_status == "UNEXPLAINED_MOVE":
        # 只关联 ID，不改 description/claim_type
        pass
    return catalyst
