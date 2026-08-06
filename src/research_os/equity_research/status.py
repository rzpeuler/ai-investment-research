"""集中、版本化的 Phase 4 研究状态判定。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

STATUS_RULES_VERSION = "2.0.0"


@dataclass
class ResearchCoverage:
    comparable_years: int
    financial_coverage: bool
    evidence_coverage: bool
    business_coverage: bool
    competition_coverage: bool
    risk_coverage: bool
    catalyst_coverage: bool
    counter_evidence_coverage: bool
    market_debate_coverage: bool
    valuation_applicable_or_explained: bool
    semantic_coverage: bool
    source_quality_adequate: bool
    as_of_known: bool
    validator_status: str = "pending"
    source_conflict: bool = False


@dataclass
class StatusDecision:
    status: str
    rules_version: str = STATUS_RULES_VERSION
    missing_core_modules: List[str] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


def evaluate_research_status(c: ResearchCoverage) -> StatusDecision:
    if c.validator_status == "fail":
        return StatusDecision("failed", reasons=["Validator 存在 error"])
    if c.source_conflict:
        return StatusDecision("source_conflict", reasons=["核心事实存在未解决来源冲突"])
    if c.comparable_years <= 0 or not c.financial_coverage or not c.evidence_coverage:
        return StatusDecision("insufficient_data", reasons=["最低财务或 Claim/Evidence 条件不满足"])
    if c.comparable_years == 1:
        return StatusDecision("partial_success", reasons=["只有一个可比年度"])

    checks: Dict[str, bool] = {
        "product_business": c.business_coverage,
        "industry_competition": c.competition_coverage,
        "risks": c.risk_coverage,
        "catalysts": c.catalyst_coverage,
        "counter_evidence": c.counter_evidence_coverage,
        "market_debate": c.market_debate_coverage,
        "valuation_applicability": c.valuation_applicable_or_explained,
        "semantic_capability": c.semantic_coverage,
        "source_quality": c.source_quality_adequate,
        "as_of": c.as_of_known,
    }
    missing = [name for name, covered in checks.items() if not covered]
    if missing:
        return StatusDecision(
            "degraded", missing_core_modules=missing,
            reasons=["一个或多个核心研究模块缺失或发生能力降级"],
        )
    return StatusDecision("success", reasons=["全部最低覆盖和证据条件满足"])
