"""归因合成（Phase 3 任务书 13 节 attribution_synthesizer、11.6、14 节）。

状态机：
1. 行情事实本身不能成立（样本不足/无日线）-> INSUFFICIENT_EVIDENCE
   （不是 UNEXPLAINED_MOVE）
2. 未解决高等级来源冲突 -> SOURCE_CONFLICT
3. unexplained_conditions 命中 -> UNEXPLAINED_MOVE（合法输出，不生成
   "可能是资金推动"等兜底话术）
4. primary 存在 -> EXPLAINED；multi -> MULTI_CAUSE
5. 只有 secondary/hypothesis -> INSUFFICIENT_EVIDENCE
6. 数据降级（复权缺失等）-> DATA_DEGRADED

Claim 分类：行情计算 FACT（带 calculation_version/input_bar_ids/formula）、
SOURCE_OPINION（必须有说话者）、MODEL_INFERENCE（仅 llm_called 且成功）、
HYPOTHESIS、UNKNOWN、CONFLICT（保留双方）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.cause_candidate_scorer import (
    ScoreResult,
    unexplained_conditions,
)
from research_os.abnormal_move.contradiction_checker import ContradictionResult
from research_os.abnormal_move.narrative_analyzer import NarrativeResult
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AttributionResult,
    BenchmarkSelection,
    ModelRoute,
)
from research_os.utils.id import new_uuid


@dataclass
class SynthesizeResult:
    attribution: AttributionResult
    claim_ids_by_type: Dict[str, List[str]] = field(default_factory=dict)
    status_reason: str = ""


class AttributionSynthesizer:
    """归因合成器。"""

    def __init__(self, rules_version: str = "attribution.v1"):
        self.rules_version = rules_version

    def synthesize(
        self,
        request: AbnormalMoveRequest,
        observation: AbnormalMoveObservation,
        score_result: ScoreResult,
        selection: Optional[BenchmarkSelection],
        contradictions: ContradictionResult,
        narrative: NarrativeResult,
        model_route: ModelRoute,
        fact_claim_ids: Optional[List[str]] = None,
        sample_insufficient: bool = False,
    ) -> SynthesizeResult:
        status, reason = self._decide_status(
            observation, score_result, contradictions, sample_insufficient)
        fact_claim_ids = fact_claim_ids or []

        # Claim 分类（确定性）
        claim_ids = {
            "fact_claim_ids": list(fact_claim_ids),
            "source_opinion_claim_ids": [
                f"opinion:{o['item_id']}" for o in narrative.opinions if o.get("speaker")],
            "model_inference_claim_ids": (
                [f"inference:{new_uuid()}"] if model_route.llm_called
                and model_route.mode == "llm" else []),
            "hypothesis_claim_ids": list(score_result.hypothesis_ids),
            "unknown_claim_ids": [],
        }
        primary = score_result.primary_ids + score_result.multi_ids
        confidence = self._confidence(status, score_result, observation)

        attribution = AttributionResult(
            attribution_result_id=new_uuid(),
            request_id=request.request_id,
            observation_id=observation.observation_id,
            benchmark_selection_id=selection.benchmark_selection_id if selection else None,
            attribution_status=status,  # type: ignore[arg-type]
            primary_cause_ids=primary,
            secondary_cause_ids=score_result.secondary_ids,
            background_cause_ids=[],
            hypothesis_cause_ids=score_result.hypothesis_ids,
            excluded_cause_ids=score_result.excluded_ids,
            contradictions=[c.description for c in contradictions.contradictions],
            fact_claim_ids=claim_ids["fact_claim_ids"],
            source_opinion_claim_ids=claim_ids["source_opinion_claim_ids"],
            model_inference_claim_ids=claim_ids["model_inference_claim_ids"],
            hypothesis_claim_ids=claim_ids["hypothesis_claim_ids"],
            unknown_claim_ids=claim_ids["unknown_claim_ids"],
            overall_confidence=confidence,
            explanation_coverage=self._coverage(status, score_result),
            evidence_ids=[c.cause_candidate_id for c in score_result.candidates],
            model_route=model_route,
            rules_version=self.rules_version,
            warnings=[f"归因状态: {reason}"] + list(contradictions.warnings),
            missing_data=observation.missing_data,
        )
        return SynthesizeResult(attribution=attribution,
                                claim_ids_by_type=claim_ids,
                                status_reason=reason)

    # ---------- 状态机 ----------

    def _decide_status(self, observation, score_result, contradictions,
                       sample_insufficient: bool) -> tuple:
        # 1. 行情事实不足 -> INSUFFICIENT_EVIDENCE（不是 UNEXPLAINED_MOVE）
        if sample_insufficient or observation.status == "no_abnormal_move":
            return "INSUFFICIENT_EVIDENCE", "异动事实未成立或样本不足"
        if "NEW_LISTING" in observation.market_state_flags and \
           observation.confidence is not None and observation.confidence <= 0.4:
            return "INSUFFICIENT_EVIDENCE", "新股样本不足，不输出正式归因"
        # 2. 高等级来源冲突未解决 -> SOURCE_CONFLICT
        if contradictions.high_authority_conflict:
            return "SOURCE_CONFLICT", "高等级来源冲突未解决"
        # 3. UNEXPLAINED_MOVE 条件
        reasons = unexplained_conditions(score_result.candidates)
        if reasons and not score_result.primary_ids:
            return "UNEXPLAINED_MOVE", "; ".join(reasons)
        # 4. EXPLAINED / MULTI_CAUSE
        if score_result.multi_ids:
            return "MULTI_CAUSE", "多原因共同作用"
        if score_result.primary_ids:
            return "EXPLAINED", "主原因成立"
        # 5. 只有次级/假设
        if score_result.secondary_ids or score_result.hypothesis_ids:
            return "INSUFFICIENT_EVIDENCE", "仅有次级催化或假设，证据不足"
        # 6. 数据降级
        if observation.missing_data or observation.warnings:
            return "DATA_DEGRADED", "数据降级"
        return "UNEXPLAINED_MOVE", "无候选满足解释门槛"

    def _confidence(self, status, score_result, observation) -> float:
        base = {
            "EXPLAINED": 0.8, "MULTI_CAUSE": 0.7, "UNEXPLAINED_MOVE": 0.5,
            "INSUFFICIENT_EVIDENCE": 0.3, "SOURCE_CONFLICT": 0.3,
            "DATA_DEGRADED": 0.4,
        }[status]
        if observation.confidence is not None:
            base = min(base, observation.confidence)
        return round(base, 2)

    def _coverage(self, status, score_result) -> Optional[float]:
        if not score_result.candidates:
            return None
        top = score_result.candidates[0]
        return round(min(1.0, top.final_score / 100.0), 2)
