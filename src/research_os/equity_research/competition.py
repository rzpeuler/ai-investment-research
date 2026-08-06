"""行业位置与竞争因素（Phase 4 任务书 3.14/Commit 10）。

竞争优势证据门槛（至少满足之一）：可验证市场份额 / 成本毛利单位经济性 / 专利认证技术指标 /
客户留存切换成本 / 渠道覆盖 / 规模效应 / 供给约束资源禀赋 / 监管许可 / 多期财务表现 /
独立第三方或客户证据。
仅管理层自述 → management_only=true、status=weakly_supported；不得写"已形成护城河"。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import List, Optional

from research_os.models.equity_research import CompetitiveFactor
from research_os.utils.time import now_iso

# 合格证据类型（任务书 3.14）
VALID_EVIDENCE_TYPES = {
    "market_share", "cost_unit_economics", "patent_certification",
    "customer_retention_switching", "channel_coverage", "scale_effect",
    "supply_constraint_resource", "regulatory_license", "multi_period_financials",
    "independent_third_party",
}

MANAGEMENT_STATEMENT_KEYWORDS = ["管理层", "董事长", "总经理", "公司表示", "公司认为", "公司称"]


@dataclass
class FactorInput:
    company_entity_id: str
    factor_type: str  # technology / brand / cost / channel / ...
    direction: str  # advantage / disadvantage / mixed / unknown
    statement: str
    mechanism: str = ""
    business_segment_ids: List[str] = field(default_factory=list)
    evidence_types: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    counter_evidence_ids: List[str] = field(default_factory=list)
    source_text: str = ""  # 证据来源原文（用于管理层自述判定）
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None


def is_management_only(source_text: str, evidence_types: List[str]) -> bool:
    """判断是否仅管理层自述：无合格证据类型且来源原文含管理层表述关键词。"""
    has_evidence = any(t in VALID_EVIDENCE_TYPES for t in evidence_types)
    if has_evidence:
        return False
    return any(kw in source_text for kw in MANAGEMENT_STATEMENT_KEYWORDS)


def build_factor(fi: FactorInput) -> CompetitiveFactor:
    """构造竞争因素；管理层自述 → weakly_supported。"""
    management_only = is_management_only(fi.source_text, fi.evidence_types)
    if management_only:
        status = "weakly_supported"
        confidence = 0.3
    elif any(t in VALID_EVIDENCE_TYPES for t in fi.evidence_types):
        status = "supported" if fi.evidence_ids else "weakly_supported"
        confidence = 0.7 if fi.evidence_ids else 0.4
    else:
        status = "unknown"
        confidence = 0.2
    # 存在反证 → contested
    if fi.counter_evidence_ids:
        status = "contested"
        confidence = min(confidence, 0.4)

    return CompetitiveFactor(
        factor_id=str(uuid.uuid4()),
        company_entity_id=fi.company_entity_id,
        factor_type=fi.factor_type,  # type: ignore[arg-type]
        direction=fi.direction,  # type: ignore[arg-type]
        statement=fi.statement,
        business_segment_ids=fi.business_segment_ids,
        mechanism=fi.mechanism,
        required_evidence_types=sorted(fi.evidence_types),
        evidence_ids=fi.evidence_ids,
        counter_evidence_ids=fi.counter_evidence_ids,
        management_only=management_only,
        confidence=confidence,
        status=status,  # type: ignore[arg-type]
        valid_from=fi.valid_from,
        valid_to=fi.valid_to,
        version=1,
        created_at=now_iso(),
    )


def check_moat_language(statement: str) -> List[str]:
    """检查"护城河"等过度结论表述（返回违规提示）。"""
    forbidden = ["已形成护城河", "护城河已形成", "具有强大护城河", "绝对壁垒"]
    return [f"禁止结论表述: {f}" for f in forbidden if f in statement]


def add_counter_evidence(factor: CompetitiveFactor, counter_evidence_ids: List[str]) -> CompetitiveFactor:
    """追加反证并重评状态为 contested（保留原状态历史由版本化处理）。"""
    new = factor.model_copy(deep=True)
    new.counter_evidence_ids = list(dict.fromkeys(factor.counter_evidence_ids + counter_evidence_ids))
    if new.counter_evidence_ids:
        new.status = "contested"
        new.confidence = min(new.confidence, 0.4)
    new.version = factor.version + 1
    return new
