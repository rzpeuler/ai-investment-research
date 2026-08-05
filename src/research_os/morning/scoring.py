"""信息价值评分（Phase 2 任务 13-14 节）。

代码负责：权重计算、总分、阈值、强制纳入、硬性否决、转载惩罚、缺字段惩罚。
LLM 负责：新颖性/影响路径/预期差的候选评分（Phase 2 提供确定性回退，
LLM 接口见 InformationScorer 子类 TODO）。

维度得分 = 原始评分 ÷ 5 × 权重；总分 0-100。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from research_os.models import CandidateItem, InformationScore
from research_os.models.morning import CLASSIFICATION_TREE
from research_os.utils.time import parse_iso
from research_os.validators.schema_validator import validate_instance

# 维度权重（任务 13.1）
WEIGHTS: Dict[str, float] = {
    "novelty": 20.0,
    "impact_strength": 20.0,
    "authority": 15.0,
    "certainty": 15.0,
    "impact_scope": 10.0,
    "expectation_gap": 10.0,
    "verifiability": 5.0,
    "market_relevance": 5.0,
}

# 分数区间（任务 13.7）
BANDS = [
    (75, "重大必读"),
    (65, "晨报正文"),
    (55, "附录或候选观察"),
    (40, "事件库候选（不进入正文）"),
]


def band_for(score: float) -> str:
    """分数 -> 区间标签。"""
    for threshold, label in BANDS:
        if score >= threshold:
            return label
    return "索引、隔离或丢弃"


# 确定性基础评分（LLM 评分接口的规则回退）
class InformationScorer:
    """信息价值评分器。"""

    def __init__(self, source_tiers: Optional[Dict[str, str]] = None,
                 source_status: Optional[Dict[str, str]] = None):
        self.source_tiers = source_tiers or {}      # source_id -> S/A/B/C/D
        self.source_status = source_status or {}    # source_id -> status

    # ---------- 各维度（规则回退；可被子类覆盖为 LLM 评分） ----------

    def score_novelty(self, candidate: CandidateItem, cluster_size: int = 1) -> int:
        """新颖性：确定性近似。重复簇成员多 -> 低分；首次披露 -> 高分。"""
        if cluster_size >= 5:
            return 1  # 大量转载
        if cluster_size >= 2:
            return 2  # 旧趋势的新评论/转载
        return 4      # 首次进入流水线

    def score_impact_strength(self, candidate: CandidateItem) -> int:
        """影响强度：按分类路径的确定性近似（不得把'重大/重磅'直接转高分）。"""
        path = candidate.classification_path or ["unknown"]
        if path[0] == "company" and path[1] in ("risk", "financing"):
            return 4
        if path[0] == "macro" and path[1] in ("policy", "emergency"):
            return 4
        if path[0] == "industry" and path[1] in ("event", "technology_breakthrough"):
            return 3
        return 2

    def score_authority(self, candidate: CandidateItem) -> int:
        """权威与证据质量：来源等级映射；多转载不提升。"""
        best = 0
        for sid in candidate.source_ids:
            tier = self.source_tiers.get(sid, "B")
            best = max(best, {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1}.get(tier, 2))
        return best

    def score_certainty(self, candidate: CandidateItem) -> int:
        """确定性：已公告/已发生 > 计划 > 传闻。"""
        text = f"{candidate.title} {candidate.summary}"
        if any(k in text for k in ["公告", "披露", "发布", "签署", "已"]):
            return 5
        if any(k in text for k in ["计划", "预计", "拟", "目标"]):
            return 3
        if any(k in text for k in ["传闻", "据称", "或", "可能"]):
            return 1
        return 4

    def score_impact_scope(self, candidate: CandidateItem) -> int:
        """影响范围：宏观 > 行业 > 公司。"""
        path = candidate.classification_path or ["unknown"]
        return {"macro": 4, "industry": 3, "market": 2, "company": 2}.get(path[0], 1)

    def score_expectation_gap(self, candidate: CandidateItem) -> int:
        """预期差：确定性近似——首次披露/修正数据高，无依据时保守（任务 13.6）。"""
        text = f"{candidate.title} {candidate.summary}"
        if any(k in text for k in ["首次", "修正", "超预期", "不及预期", "上调", "下调"]):
            return 4
        return 2  # 证据不足时降低，不臆测市场预期

    def score_verifiability(self, candidate: CandidateItem) -> int:
        """可验证性：有原始证据（官方来源）高；无 URL 低。"""
        has_official = any(
            self.source_tiers.get(sid, "D") in ("S", "A") for sid in candidate.source_ids
        )
        if has_official:
            return 5
        return 3

    def score_market_relevance(self, candidate: CandidateItem) -> int:
        """市场相关性：分类路径 market/company 相关度更高。"""
        path = candidate.classification_path or ["unknown"]
        if candidate.entities:
            return 4
        if path[0] in ("market", "company"):
            return 3
        return 2

    # ---------- 汇总 ----------

    def score(self, candidate: CandidateItem, cluster_size: int = 1,
              vetoed: bool = False, veto_reasons: Optional[List[str]] = None) -> InformationScore:
        dims = {
            "novelty": self.score_novelty(candidate, cluster_size),
            "impact_strength": self.score_impact_strength(candidate),
            "authority": self.score_authority(candidate),
            "certainty": self.score_certainty(candidate),
            "impact_scope": self.score_impact_scope(candidate),
            "expectation_gap": self.score_expectation_gap(candidate),
            "verifiability": self.score_verifiability(candidate),
            "market_relevance": self.score_market_relevance(candidate),
        }
        base = sum(dims[k] / 5.0 * w for k, w in WEIGHTS.items())
        penalties: List[str] = []
        bonuses: List[str] = []

        # 转载惩罚：同一事件簇多个成员（十篇转载不显著提升权威）
        if cluster_size >= 5:
            penalties.append(f"转载过多（簇内 {cluster_size} 条）")
            base -= 8.0
        elif cluster_size >= 2:
            penalties.append(f"多来源转载（簇内 {cluster_size} 条）")
            base -= 3.0
        # 缺字段惩罚
        missing = [f for f in ("title", "summary", "entities") if not getattr(candidate, f)]
        if missing:
            penalties.append(f"缺字段: {missing}")
            base -= 2.0 * len(missing)
        # 强制纳入（任务 13.8）：重大监管/法定公告/重大政策
        forced, forced_reason = self._forced_include(candidate)
        if forced:
            bonuses.append("强制纳入（重大事件）")
            base = max(base, 80.0)

        final = max(0.0, min(100.0, base))
        result = InformationScore(
            candidate_id=candidate.candidate_id,
            **dims,
            base_score=round(base, 2),
            penalties=penalties,
            bonuses=bonuses,
            final_score=round(final, 2),
            hard_veto=vetoed,
            veto_reasons=veto_reasons or [],
            score_reasons=self._reasons(dims, penalties, bonuses, forced),
            forced_include=forced,
            forced_include_reason=forced_reason,
        )
        errs = validate_instance(result.model_dump(), "information_score")
        if errs:
            raise ValueError(f"InformationScore 未通过 Schema 校验: {errs}")
        return result

    @staticmethod
    def _forced_include(candidate: CandidateItem):
        """强制纳入判定：重大监管风险/重大公司法定公告/重大政策（记录原因，不得滥用）。"""
        text = f"{candidate.title} {candidate.summary}"
        path = candidate.classification_path or []
        if "风险提示" in text or "处罚" in text or "立案" in text:
            return True, "major_regulatory_event"
        if path[:1] == ["company"] and "公告" in text:
            return True, "major_company_disclosure"
        if path[:2] == ["macro", "policy"]:
            return True, "major_policy"
        return False, None

    @staticmethod
    def _reasons(dims, penalties, bonuses, forced) -> List[str]:
        reasons = [f"{k}={v}" for k, v in sorted(dims.items())]
        reasons += penalties + bonuses
        if forced:
            reasons.append("forced_include")
        return reasons
