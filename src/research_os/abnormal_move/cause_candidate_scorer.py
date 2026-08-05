"""原因候选确定性评分（Phase 3 任务书 11.1-11.5 节）。

base_score = Σ(raw/5 * weight)，final_score = clamp(base - penalties, 0, 100)。
权重、惩罚、门槛为确定性规则，不得由模型决定；模型可提供评分理由草案，
但不得改变最终分。

主次划分（11.4）：
- primary:   final>=75 且 causal_eligibility 且 top1-top2>=8 且满足直接证据门槛
- multi:     top1 与 top2 均 >=70，差值<8，机制不同，各有独立证据
- secondary: 60<=score<75，或明确次级催化/背景强化
- hypothesis: 45<=score<60 或证据不完整
- excluded:  <45（不得为报告完整而抬高分数）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.config import CAUSE_SCORE_VERSION
from research_os.models import CauseCandidate, CauseEvidenceLink

# 权重（任务书 11.1 表）
CAUSE_WEIGHTS: Dict[str, float] = {
    "time_match_score": 25,
    "entity_link_score": 20,
    "novelty_score": 15,
    "peer_linkage_score": 15,
    "source_reliability_score": 10,
    "explanation_coverage_score": 10,
    "verifiability_score": 5,
}

# 阈值（任务书 11.4）
PRIMARY_MIN = 75.0
PRIMARY_TOP_GAP = 8.0
MULTI_MIN = 70.0
SECONDARY_MIN = 60.0
HYPOTHESIS_MIN = 45.0

# 直接原因证据门槛（11.5）
DIRECT_FINAL_MIN = 75.0
DIRECT_TIME_MIN = 4
DIRECT_ENTITY_MIN = 4

# 惩罚（11.3）
PENALTY_OLD_NEWS_2_5D = -10.0
PENALTY_OLD_NEWS_GT_5D = -20.0
PENALTY_AFTER_FACT = -25.0
PENALTY_ANONYMOUS = -30.0
PENALTY_REPOST_ONLY = -10.0
PENALTY_MISSING_TIME = -10.0


@dataclass
class ScoreResult:
    candidates: List[CauseCandidate]
    links: List[CauseEvidenceLink]
    primary_ids: List[str] = field(default_factory=list)
    multi_ids: List[str] = field(default_factory=list)
    secondary_ids: List[str] = field(default_factory=list)
    hypothesis_ids: List[str] = field(default_factory=list)
    excluded_ids: List[str] = field(default_factory=list)
    rationale: List[str] = field(default_factory=list)


class CauseCandidateScorer:
    """确定性评分器。"""

    def __init__(self):
        self.version = CAUSE_SCORE_VERSION

    # ---------- 评分 ----------

    def _base_score(self, c: CauseCandidate) -> float:
        raw = {
            "time_match_score": c.time_match_score,
            "entity_link_score": c.entity_link_score,
            "novelty_score": c.novelty_score,
            "peer_linkage_score": c.peer_linkage_score,
            "source_reliability_score": c.source_reliability_score,
            "explanation_coverage_score": c.explanation_coverage_score,
            "verifiability_score": c.verifiability_score,
        }
        return sum(raw[k] / 5.0 * CAUSE_WEIGHTS[k] for k in CAUSE_WEIGHTS)

    def _penalties(self, c: CauseCandidate,
                   evidence_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> float:
        """惩罚（任务书 11.3）。"""
        p = 0.0
        penalties: List[str] = []
        # 旧闻惩罚：novelty<=1 且非窗口内新披露
        if c.novelty_score <= 1:
            p += PENALTY_OLD_NEWS_GT_5D
            penalties.append("旧闻超过5个交易日且无新增:-20")
        # 异动后解释性报道：-25 且不得 direct
        if c.cause_category == "after_the_fact_explanation":
            p += PENALTY_AFTER_FACT
            penalties.append("异动后解释性报道:-25")
        # 单一匿名来源（来源分<=1 且无独立组）
        if c.source_reliability_score <= 1 and len(c.independence_groups) <= 1:
            p += PENALTY_ANONYMOUS
            penalties.append("单一匿名来源:-30")
        # 只有转载无原始出处：标题以[转载]开头或来源为转载类
        if c.title.startswith("["):
            p += PENALTY_REPOST_ONLY
            penalties.append("只有转载无原始出处:-10")
        # 证据时间缺失
        if c.published_at is None:
            p += PENALTY_MISSING_TIME
            penalties.append("证据时间缺失:-10")
        # 高等级来源冲突 -> 不得 high confidence（在 eligibility 处理）
        c.warnings.extend(penalties)
        return p

    def _direct_evidence_ok(self, c: CauseCandidate,
                            links: List[CauseEvidenceLink]) -> bool:
        """直接原因证据门槛（11.5）。"""
        if c.final_score < DIRECT_FINAL_MIN:
            return False
        if c.time_match_score < DIRECT_TIME_MIN:
            return False
        if c.entity_link_score < DIRECT_ENTITY_MIN:
            return False
        supports_direct = [l for l in links
                           if l.cause_candidate_id == c.cause_candidate_id
                           and l.relation == "supports" and l.directness == "direct"]
        if not supports_direct:
            return False
        # 至少一个 S/A 原始证据组 或 两个独立 A/B 组（确定性近似：来源分>=4 为 S/A）
        if c.source_reliability_score >= 4:
            return True
        if len(c.independence_groups) >= 2 and c.source_reliability_score >= 3:
            return True
        return False

    # ---------- 主入口 ----------

    def score(self, candidates: List[CauseCandidate],
              links: Optional[List[CauseEvidenceLink]] = None,
              evidence_meta: Optional[Dict[str, Dict[str, Any]]] = None) -> ScoreResult:
        links = links or []
        scored: List[CauseCandidate] = []
        for c in candidates:
            base = self._base_score(c)
            penalties = self._penalties(c, evidence_meta)
            final = max(0.0, min(100.0, base + penalties))
            c.base_score = round(base, 1)
            c.penalties = round(abs(penalties), 1)
            c.final_score = round(final, 1)
            # 异动后报道不得标 direct_trigger（11.3）
            if c.cause_category == "after_the_fact_explanation":
                c.causal_eligibility = False
            # 高等级来源冲突：source_reliability 高但存在 contradicts 链接 -> 不得 high confidence
            has_contradiction = any(
                l.relation == "contradicts" and l.cause_candidate_id == c.cause_candidate_id
                for l in links)
            if has_contradiction:
                c.confidence = min(c.confidence or 0.5, 0.4)
            if c.causal_eligibility:
                c.causal_eligibility = self._direct_evidence_ok(c, links)
            scored.append(c)

        ranked = sorted(scored, key=lambda c: c.final_score, reverse=True)
        primary, multi, secondary, hypothesis, excluded = self._classify(ranked, links)
        result = ScoreResult(
            candidates=scored, links=links,
            primary_ids=primary, multi_ids=multi,
            secondary_ids=secondary, hypothesis_ids=hypothesis,
            excluded_ids=excluded,
            rationale=self._rationale(ranked),
        )
        return result

    def _classify(self, ranked: List[CauseCandidate],
                  links: List[CauseEvidenceLink]) -> tuple:
        primary: List[str] = []
        multi: List[str] = []
        secondary: List[str] = []
        hypothesis: List[str] = []
        excluded: List[str] = []
        if not ranked:
            return primary, multi, secondary, hypothesis, excluded

        top1 = ranked[0]
        top2 = ranked[1] if len(ranked) > 1 else None

        # 多原因：top1 与 top2 均 >=70，差值<8
        if top2 and top1.final_score >= MULTI_MIN and top2.final_score >= MULTI_MIN and \
           abs(top1.final_score - top2.final_score) < PRIMARY_TOP_GAP:
            multi = [top1.cause_candidate_id, top2.cause_candidate_id]
        elif top1.final_score >= PRIMARY_MIN and top1.causal_eligibility and \
             (top2 is None or top1.final_score - top2.final_score >= PRIMARY_TOP_GAP):
            primary = [top1.cause_candidate_id]

        for c in ranked:
            cid = c.cause_candidate_id
            if cid in primary or cid in multi:
                continue
            if c.final_score >= SECONDARY_MIN:
                secondary.append(cid)
            elif c.final_score >= HYPOTHESIS_MIN:
                hypothesis.append(cid)
            else:
                excluded.append(cid)
        return primary, multi, secondary, hypothesis, excluded

    def _rationale(self, ranked: List[CauseCandidate]) -> List[str]:
        out = []
        for c in ranked[:5]:
            out.append(
                f"{c.title[:30]}: base={c.base_score:.1f} 惩罚={c.penalties:.1f} "
                f"final={c.final_score:.1f} eligible={c.causal_eligibility}")
        return out


def unexplained_conditions(candidates: List[CauseCandidate]) -> List[str]:
    """UNEXPLAINED_MOVE 触发条件（任务书 11.6）。由合成器调用。"""
    reasons: List[str] = []
    eligible = [c for c in candidates if c.causal_eligibility]
    if not eligible:
        reasons.append("没有候选达到 60 分并通过因果资格")
    if candidates and all(c.cause_category == "after_the_fact_explanation" for c in candidates):
        reasons.append("所有候选都是事后解释")
    if candidates and all(c.novelty_score <= 1 for c in candidates):
        reasons.append("所有候选都是旧闻且没有新增变量")
    if candidates and all(c.source_reliability_score <= 1 for c in candidates):
        reasons.append("只有匿名传闻")
    # 多个高分候选冲突
    high = [c for c in candidates if c.final_score >= 60]
    if len(high) >= 2:
        top = sorted(high, key=lambda c: c.final_score, reverse=True)
        if top[0].final_score - top[1].final_score < 8:
            reasons.append("多个候选得分接近且无法确定主次")
    return reasons
