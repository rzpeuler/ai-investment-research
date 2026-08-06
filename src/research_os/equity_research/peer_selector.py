"""同行选择（Phase 4 任务书 3.15/Commit 9）。

- 候选只来自：截止日前有效的稳定行业分类 / 版本化同行注册表 / 可验证主营业务关系 /
  产业链可比 / 用户显式提供候选（--peer 只增加候选，不自动合格）；
- 评分权重（合计 100）：行业关系 20 / 主营业务 20 / 收入结构 20 / 产业链 10 / 规模 10 /
  上市时间 5 / 会计口径 7 / 地区 3 / 数据完整度 5；dimension_score = raw/5 × weight；
- 资格：total>=65、core_subtotal>=35、relationship_valid_from<=cutoff、会计>=3、数据完整>=3；
- 防事后选择：宇宙版本与权重进幂等键；估值前冻结；不得按结果删同行；
- 样本门槛：>=5 完整 / 3—4 有限 / <3 insufficient_peer_sample。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from research_os.models.valuation import PeerCandidate, PeerSelection
from research_os.utils.time import now_iso

SCORING_VERSION = "1.0.0"

# 权重（与 registry/equity_peer_universe.yaml 保持一致）
WEIGHTS: Dict[str, float] = {
    "industry_relation": 20,
    "business_model_similarity": 20,
    "revenue_mix_similarity": 20,
    "supply_chain_relation": 10,
    "size": 10,
    "listing_tenure": 5,
    "accounting_comparability": 7,
    "region": 3,
    "data_completeness": 5,
}

CORE_DIMENSIONS = {
    "industry_relation", "business_model_similarity", "revenue_mix_similarity",
}

ELIGIBILITY = {
    "total_score_min": 65,
    "core_subtotal_min": 35,
    "accounting_comparability_min": 3,
    "data_completeness_min": 3,
}

SAMPLE_THRESHOLDS = {"full": 5, "limited_min": 3, "insufficient_max": 2}


@dataclass
class PeerInput:
    """同行候选输入（冻结宇宙中的一行）。"""
    candidate_company_id: str
    relationship_valid_from: str
    relationship_valid_to: Optional[str] = None
    information_cutoff: str = "9999-12-31T00:00:00"
    universe_version: str = "1.0.0"
    # 0-5 原始分
    industry_score: int = 0
    business_model_score: int = 0
    revenue_mix_score: int = 0
    supply_chain_score: int = 0
    size_score: int = 0
    listing_tenure_score: int = 0
    accounting_comparability_score: int = 0
    region_score: int = 0
    data_completeness_score: int = 0
    user_override: bool = False  # --peer 提供的候选
    evidence_ids: List[str] = field(default_factory=list)


def dimension_score(raw: int, weight: float) -> float:
    return raw / 5 * weight


def evaluate_peer_eligibility(pi: PeerInput) -> tuple[float, float, List[str]]:
    """唯一的同行评分/资格实现，供选择器和 Validator 复用。"""
    scores = {
        "industry_relation": pi.industry_score, "business_model_similarity": pi.business_model_score,
        "revenue_mix_similarity": pi.revenue_mix_score, "supply_chain_relation": pi.supply_chain_score,
        "size": pi.size_score, "listing_tenure": pi.listing_tenure_score,
        "accounting_comparability": pi.accounting_comparability_score, "region": pi.region_score,
        "data_completeness": pi.data_completeness_score,
    }
    core_subtotal = round(sum(dimension_score(scores[d], WEIGHTS[d]) for d in CORE_DIMENSIONS), 2)
    total_score = round(sum(dimension_score(scores[k], weight) for k, weight in WEIGHTS.items()), 2)
    reasons: List[str] = []
    if pi.relationship_valid_from > pi.information_cutoff[:10]:
        reasons.append("relationship_valid_from 晚于 information_cutoff")
    if total_score < ELIGIBILITY["total_score_min"]:
        reasons.append(f"total_score {total_score} < {ELIGIBILITY['total_score_min']}")
    if core_subtotal < ELIGIBILITY["core_subtotal_min"]:
        reasons.append(f"core_subtotal {core_subtotal} < {ELIGIBILITY['core_subtotal_min']}")
    if scores["accounting_comparability"] < ELIGIBILITY["accounting_comparability_min"]:
        reasons.append("会计口径可比分 < 3")
    if scores["data_completeness"] < ELIGIBILITY["data_completeness_min"]:
        reasons.append("数据完整度 < 3")
    return total_score, core_subtotal, reasons


def score_peer(pi: PeerInput, subject_company_id: str = "company:unknown") -> PeerCandidate:
    """评分并判定资格（确定性；LLM 不决定最终资格）。"""
    total_score, core_subtotal, exclusion_reasons = evaluate_peer_eligibility(pi)
    # 新上市公司（上市不足 2 个完整财年）由 listing_tenure_score 体现，不在此硬性排除

    eligible = not exclusion_reasons
    return PeerCandidate(
        peer_candidate_id=str(uuid.uuid4()),
        subject_company_id=subject_company_id,
        candidate_company_id=pi.candidate_company_id,
        information_cutoff=pi.information_cutoff,
        universe_version=pi.universe_version,
        relationship_valid_from=pi.relationship_valid_from,
        relationship_valid_to=pi.relationship_valid_to,
        industry_score=pi.industry_score,
        business_model_score=pi.business_model_score,
        revenue_mix_score=pi.revenue_mix_score,
        supply_chain_score=pi.supply_chain_score,
        size_score=pi.size_score,
        listing_tenure_score=pi.listing_tenure_score,
        accounting_comparability_score=pi.accounting_comparability_score,
        region_score=pi.region_score,
        data_completeness_score=pi.data_completeness_score,
        core_subtotal=core_subtotal,
        total_score=total_score,
        eligible=eligible,
        exclusion_reasons=exclusion_reasons,
        llm_assisted_dimensions=[],
        evidence_ids=pi.evidence_ids,
        warnings=[],
        version=1,
        created_at=now_iso(),
    )


def select_peers(
    subject_company_id: str,
    request_id: str,
    inputs: List[PeerInput],
    information_cutoff: str,
    universe_version: str,
) -> tuple[PeerSelection, List[PeerCandidate]]:
    """生成候选评分 → 冻结选择。返回 (PeerSelection, 全部候选)。

    防事后选择：选择只基于输入时点的评分，估值计算前冻结；被排除候选与原因保留。
    """
    candidates = [score_peer(pi) for pi in inputs]
    for c in candidates:
        c.subject_company_id = subject_company_id
    eligible = sorted(
        [c for c in candidates if c.eligible],
        key=lambda c: c.total_score, reverse=True,
    )
    selected = [c.candidate_company_id for c in eligible]
    sample_size = len(selected)
    if sample_size >= SAMPLE_THRESHOLDS["full"]:
        status = "full"
    elif sample_size >= SAMPLE_THRESHOLDS["limited_min"]:
        status = "limited"
    else:
        status = "insufficient"

    selection = PeerSelection(
        peer_selection_id=str(uuid.uuid4()),
        request_id=request_id,
        subject_company_id=subject_company_id,
        information_cutoff=information_cutoff,
        universe_version=universe_version,
        scoring_version=SCORING_VERSION,
        candidate_ids=[c.peer_candidate_id for c in candidates],
        selected_company_ids=selected,
        sample_size=sample_size,
        minimum_required=SAMPLE_THRESHOLDS["full"],
        status=status,  # type: ignore[arg-type]
        selection_rationale=[
            f"样本 {sample_size}（完整>=5 / 有限3-4 / 不足<3）",
            f"评分版本 {SCORING_VERSION}，宇宙版本 {universe_version}",
            "候选集在估值前冻结，不按结果调整",
        ],
        outlier_policy="winsorize",
        evidence_ids=[],
        warnings=[],
        version=1,
        created_at=now_iso(),
    )
    return selection, candidates
