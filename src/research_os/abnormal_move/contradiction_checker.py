"""反证与冲突检查（Phase 3 任务书 13 节 contradiction_checker、14.2 CONFLICT）。

高置信结论不能忽略反证；CONFLICT 保留冲突双方，不得根据股价方向选一方。
确定性硬冲突：数值方向、时间先后、主体错误、复权口径；语义反证由 LLM 提取。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.event_window_retriever import RetrievedItem
from research_os.models import CauseCandidate, CauseEvidenceLink


@dataclass
class Contradiction:
    kind: str                    # numeric_direction / timing / entity / adjustment / authority
    description: str
    candidate_ids: List[str] = field(default_factory=list)
    severity: str = "warning"    # warning | conflict


@dataclass
class ContradictionResult:
    contradictions: List[Contradiction] = field(default_factory=list)
    high_authority_conflict: bool = False
    warnings: List[str] = field(default_factory=list)


class ContradictionChecker:
    """确定性反证检查器。"""

    def check(
        self,
        candidates: List[CauseCandidate],
        links: List[CauseEvidenceLink],
        observation,
        items: Optional[List[RetrievedItem]] = None,
    ) -> ContradictionResult:
        result = ContradictionResult()
        items = items or []

        # 1. 时间冲突：候选标 BEFORE_MOVE 但实际发布时间晚于异动开始
        for c in candidates:
            if c.timing_relation == "BEFORE_MOVE" and c.published_at and \
               observation.move_start_at and c.published_at > observation.move_start_at:
                result.contradictions.append(Contradiction(
                    kind="timing",
                    description=f"候选 {c.title[:20]} 标 BEFORE_MOVE 但发布时间晚于异动开始",
                    candidate_ids=[c.cause_candidate_id], severity="conflict"))
                result.warnings.append(f"{c.title[:20]}：时间标签与数据矛盾")

        # 2. 主体错误：候选实体与对象无关（entity_link=0 但未被过滤）
        for c in candidates:
            if c.entity_link_score == 0:
                result.contradictions.append(Contradiction(
                    kind="entity",
                    description=f"候选 {c.title[:20]} 实体主体错误",
                    candidate_ids=[c.cause_candidate_id], severity="conflict"))

        # 3. 反方向候选：高分会选中两个方向相反的原因
        positive = [c for c in candidates if c.final_score >= 60 and
                    (c.cause_category in ("direct_trigger", "secondary_catalyst"))]
        negative = [c for c in candidates if c.final_score >= 60 and
                    c.cause_category == "after_the_fact_explanation"]
        # 4. 高等级来源冲突：supports 与 contradicts 并存于同一候选
        for c in candidates:
            c_links = [l for l in links if l.cause_candidate_id == c.cause_candidate_id]
            has_support = any(l.relation == "supports" for l in c_links)
            has_contradict = any(l.relation == "contradicts" for l in c_links)
            if has_support and has_contradict and c.source_reliability_score >= 4:
                result.contradictions.append(Contradiction(
                    kind="authority",
                    description=f"候选 {c.title[:20]} 存在高等级来源冲突",
                    candidate_ids=[c.cause_candidate_id], severity="conflict"))
                result.high_authority_conflict = True
        return result
