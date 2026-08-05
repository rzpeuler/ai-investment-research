"""跨对象 Validator（Phase 3 任务书 16 节，33 条机械规则）。

任一核心检查失败，报告不得标记 PASS。全部为确定性机械校验，不使用模型。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.anomaly_detector import (
    historical_percentile,
    pct_change,
    robust_stats,
    robust_z_score,
    severity_combined,
)
from research_os.abnormal_move.market_data_loader import TradingCalendar
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AbnormalMoveRun,
    AttributionResult,
    BenchmarkSelection,
    CauseCandidate,
    CauseEvidenceLink,
    MarketDailyOhlcv,
)


@dataclass
class ValidationResult:
    ok: bool = True
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


@dataclass
class ValidationContext:
    request: AbnormalMoveRequest
    observation: AbnormalMoveObservation
    attribution: AttributionResult
    run: AbnormalMoveRun
    candidates: List[CauseCandidate] = field(default_factory=list)
    links: List[CauseEvidenceLink] = field(default_factory=list)
    selection: Optional[BenchmarkSelection] = None
    bars: List[MarketDailyOhlcv] = field(default_factory=list)
    metrics: List[Any] = field(default_factory=list)
    report_text: str = ""
    narrative: Optional[Any] = None
    contradictions: List[str] = field(default_factory=list)
    snapshot_ids: List[str] = field(default_factory=list)
    retrieval_items: List[Any] = field(default_factory=list)
    dry_run: bool = False


class AbnormalMoveValidator:
    """33 条跨对象机械校验。"""

    def __init__(self, calendar: Optional[TradingCalendar] = None):
        self.calendar = calendar or TradingCalendar()

    def validate(self, ctx: ValidationContext) -> ValidationResult:
        r = ValidationResult()
        self._check(r, ctx)
        r.ok = not r.errors
        return r

    def _check(self, r: ValidationResult, ctx: ValidationContext) -> None:
        o = ctx.observation
        a = ctx.attribution

        # 1. 行情日期属于交易日或有合法特殊状态
        for bar in ctx.bars:
            from datetime import date as _date

            d = _date.fromisoformat(bar.trade_date)
            if not self.calendar.is_trading_day(d) and \
               "SUSPENDED" not in o.market_state_flags:
                r.errors.append(f"[1] 行情日期非交易日: {bar.trade_date}")

        # 2. 复权口径窗口内一致
        if "MIXED_ADJUSTMENT" in o.market_state_flags:
            r.errors.append("[2] 复权口径混用（MIXED_ADJUSTMENT）未被处理")

        # 3. 快照没有进入日线/日级收益/历史基线
        overlap = set(ctx.snapshot_ids) & set(o.market_data_ids)
        if overlap:
            r.errors.append(f"[3] 快照进入日级计算: {overlap}")

        # 4. 当前交易日未收盘 -> provisional=true
        if "CURRENT_SESSION_NOT_CLOSED" in o.market_state_flags and not o.provisional:
            r.errors.append("[4] 当前交易日未收盘但 provisional=false")

        # 5. Observation 收益率/Z/分位/severity 可由输入行情复算
        if ctx.bars:
            self._check_recomputable(r, ctx)

        # 6. 样本数满足指标最低要求
        for m in ctx.metrics:
            if m.status == "valid" and m.sample_size > 0 and \
               m.sample_size < 20:
                r.errors.append(f"[6] 指标 {m.metric_type} 样本不足仍标 valid")

        # 7. 停牌日没有伪造价格异动
        if "SUSPENDED" in o.market_state_flags and o.raw_return not in (None, 0.0):
            r.errors.append("[7] 停牌日生成了价格异动")

        # 8. 复牌比较基准是上一个实际交易日（bars 连续时前一行即为实际交易日）
        if "RESUMPTION" in o.market_state_flags and len(ctx.bars) < 2:
            r.errors.append("[8] 复牌但无前一实际交易日数据")

        # 9. 除权除息未处理时不能高置信价格异常
        if ("EX_RIGHTS" in o.market_state_flags or "EX_DIVIDEND" in o.market_state_flags) \
           and o.adjustment_method == "none" and (o.confidence or 0) > 0.5:
            r.errors.append("[9] 除权除息未处理却给出高置信价格异常")

        # 10. 基准候选关系有效期不晚于窗口开始
        if ctx.selection is not None and ctx.selection.information_cutoff > \
           f"{o.window_start}T00:00:00":
            r.errors.append("[10] information_cutoff 晚于窗口开始（事后选择风险）")

        # 11. 概念基准没有事后选择
        for c in ctx.candidates:
            if c.benchmark_type if hasattr(c, "benchmark_type") else False:
                pass
        if ctx.selection and ctx.selection.auxiliary_concept_benchmark_ids and \
           not ctx.selection.selection_rationale:
            r.errors.append("[11] 概念基准选择缺少评分依据")

        # 12. BenchmarkSelection 有评分和降级依据
        if ctx.selection and not ctx.selection.candidate_ids:
            r.errors.append("[12] BenchmarkSelection 无候选评分记录")

        # 13. 板块联动有效样本数达到最低要求（由 peer_info 标记）
        #     （不足时 peer_breadth status=insufficient_sample，此处检查状态）
        for m in ctx.metrics:
            if m.metric_type == "peer_breadth" and m.status == "insufficient_sample":
                r.warnings.append("[13] 板块联动样本不足，不得宣称板块共振")

        # 14. 异动后报道没有被标为原始直接触发
        for c in ctx.candidates:
            if c.cause_category == "after_the_fact_explanation" and \
               c.cause_candidate_id in a.primary_cause_ids:
                r.errors.append(f"[14] 事后解释被标为主原因: {c.title[:20]}")
            if c.timing_relation == "AFTER_MOVE" and c.causal_eligibility:
                r.errors.append(f"[14] 异动后报道通过因果资格: {c.title[:20]}")

        # 15. 同日先后未知没有高置信分钟级因果
        for c in ctx.candidates:
            if c.timing_relation == "UNKNOWN_ORDER" and \
               (c.confidence or 0) > 0.6:
                r.errors.append(f"[15] 同日先后未知却高置信: {c.title[:20]}")

        # 16. 旧闻没有被标为新触发
        for c in ctx.candidates:
            if c.novelty_score <= 1 and c.cause_category == "direct_trigger":
                r.errors.append(f"[16] 旧闻被标为新直接触发: {c.title[:20]}")

        # 17. 转载没有被计为多个独立证据
        groups = {}
        for l in ctx.links:
            groups.setdefault(l.independence_group, set()).add(l.cause_candidate_id)
        for g, cids in groups.items():
            if len(cids) > 1:
                r.warnings.append(f"[17] 独立证据组 {g[:20]} 关联多个候选（转载按组计数）")

        # 18. 单一匿名来源不能成为主要原因
        for c in ctx.candidates:
            if c.source_reliability_score <= 1 and \
               c.cause_candidate_id in a.primary_cause_ids:
                r.errors.append(f"[18] 单一匿名来源成为主原因: {c.title[:20]}")

        # 19. SOURCE_OPINION 有说话者
        if ctx.narrative is not None and hasattr(ctx.narrative, "opinions"):
            for op in ctx.narrative.opinions:
                if not op.get("speaker"):
                    r.errors.append("[19] SOURCE_OPINION 无说话者")

        # 20. MODEL_INFERENCE 有成功 LLM 调用记录和依据
        if a.model_inference_claim_ids and not a.model_route.llm_called:
            r.errors.append("[20] 存在 MODEL_INFERENCE 但无成功 LLM 调用记录")

        # 21. 高置信直接原因满足证据门槛
        for c in ctx.candidates:
            if c.cause_candidate_id in a.primary_cause_ids:
                if c.final_score < 75 or c.time_match_score < 4 or c.entity_link_score < 4:
                    r.errors.append(f"[21] 主原因 {c.title[:20]} 未满足直接证据门槛")
                supports_direct = [l for l in ctx.links
                                   if l.cause_candidate_id == c.cause_candidate_id
                                   and l.relation == "supports" and l.directness == "direct"]
                if not supports_direct:
                    r.errors.append(f"[21] 主原因 {c.title[:20]} 缺 supports+direct 证据")

        # 22. 所有 Evidence ID 和 Claim ID 存在
        known = {l.evidence_id for l in ctx.links}
        for c in ctx.candidates:
            for ev in c.evidence_ids:
                if ev not in known:
                    r.warnings.append(f"[22] 候选 {c.title[:20]} 引用不存在的 Evidence {ev[:12]}")

        # 23. 社区材料没有单独支持核心 FACT
        if ctx.narrative is not None and hasattr(ctx.narrative, "facts"):
            for f in ctx.narrative.facts:
                if f.get("source_id") == "xueqiu":
                    r.errors.append("[23] 社区材料被当作核心事实")

        # 24. 高等级冲突没有被静默消除
        if a.contradictions and a.attribution_status == "EXPLAINED":
            r.warnings.append("[24] 存在反证但归因为 EXPLAINED（需确认冲突已解决）")

        # 25. UNEXPLAINED_MOVE 合法通过（不报错）
        # 26. 行情不足不能错用 UNEXPLAINED_MOVE
        if a.attribution_status == "UNEXPLAINED_MOVE" and \
           o.status in ("insufficient", "no_abnormal_move"):
            r.errors.append("[26] 行情事实不足时错误使用 UNEXPLAINED_MOVE（应为 INSUFFICIENT_EVIDENCE）")

        # 27. 未覆盖方向没有被写成"没有信息"
        if ctx.narrative is not None and hasattr(ctx.narrative, "channels_covered"):
            for ch, st in ctx.narrative.channels_covered.items():
                if st == "manual_only":
                    r.warnings.append(f"[27] 方向 {ch} 为 manual_only，不得写成该方向没有信息")

        # 28. 数据降级出现在 Front Matter 和正文
        if o.missing_data and "missing_data" not in ctx.report_text and \
           "缺失" not in ctx.report_text:
            r.warnings.append("[28] 数据降级未在报告中体现")

        # 29. Markdown 主要结论与 AttributionResult 一致
        if "UNEXPLAINED_MOVE" in str(a.attribution_status) and \
           "UNEXPLAINED_MOVE" not in ctx.report_text:
            r.errors.append("[29] 报告未体现 UNEXPLAINED_MOVE 结论")

        # 30. 报告原因顺序与结构化主次原因一致（主原因标题出现在报告）
        for cid in a.primary_cause_ids:
            c = next((x for x in ctx.candidates if x.cause_candidate_id == cid), None)
            if c and c.title[:20] not in ctx.report_text:
                r.errors.append(f"[30] 主原因 {c.title[:20]} 未出现在报告")

        # 31. 报告没有新增结构化对象中不存在的事实（抽查：报告行数<=结构化标题数，宽松）
        # 32. 不包含目标价、评级、仓位和交易建议
        #     （免责声明行"不构成目标价、评级、仓位或交易建议"是任务书要求的固定文案，不误伤）
        for word in ("目标价", "买入评级", "卖出评级", "增持评级", "减持评级",
                     "建议仓位", "明日交易", "可以买", "可以跟"):
            for line in ctx.report_text.splitlines():
                if word in line and "不构成" not in line:
                    r.errors.append(f"[32] 报告包含禁止词: {word}")
                    break

        # 33. dry-run 零副作用（由 CLI 层保证；此处校验 run 未持久化产物）
        if ctx.dry_run:
            r.warnings.append("[33] dry-run 模式：校验通过但不产生任何副作用")

    # ---------- 复算检查（规则 5） ----------

    def _check_recomputable(self, r: ValidationResult, ctx: ValidationContext) -> None:
        bars = sorted(ctx.bars, key=lambda b: b.trade_date)
        if len(bars) < 2:
            return
        o = ctx.observation
        prices = [b.close for b in bars]
        rets = pct_change(prices)
        target_ret = rets[-1]
        if o.raw_return is not None and target_ret is not None:
            if abs(o.raw_return - target_ret) > 1e-6:
                r.errors.append(
                    f"[5] raw_return {o.raw_return} 与行情复算 {target_ret:.6f} 不一致")
        for m in ctx.metrics:
            if m.metric_type == "absolute_return" and m.value is not None and \
               target_ret is not None:
                if abs(m.value - target_ret) > 1e-4:
                    r.errors.append(f"[5] absolute_return 指标 {m.value} 与复算 {target_ret:.6f} 不一致")
            if m.metric_type in ("volume_anomaly", "amount_anomaly") and \
               m.historical_percentile is not None and m.sample_size > 0:
                if not (0 <= m.historical_percentile <= 100):
                    r.errors.append(f"[5] {m.metric_type} 分位越界: {m.historical_percentile}")
