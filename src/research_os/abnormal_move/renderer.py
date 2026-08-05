"""异动分析 Markdown 报告渲染（Phase 3 任务书 15 节）。

Front Matter 字段与正文 18 章节按任务书模板；空章节不得用套话填满。
报告与结构化结果逐项一致；不新增结构化对象中不存在的事实。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRun,
    AttributionResult,
    BenchmarkSelection,
    CauseCandidate,
)

FORBIDDEN_WORDS = ["目标价", "买入评级", "卖出评级", "增持评级", "减持评级", "建议仓位", "明日交易"]


@dataclass
class RenderContext:
    run: AbnormalMoveRun
    attribution: AttributionResult
    observation: AbnormalMoveObservation
    selection: Optional[BenchmarkSelection]
    candidates: List[CauseCandidate]
    metrics: List[Any] = field(default_factory=list)
    peer_info: Optional[Dict[str, Any]] = None
    narrative: Optional[Any] = None
    contradictions: Optional[List[str]] = field(default_factory=list)
    entity_name: str = ""


class AbnormalMoveRenderer:
    """Markdown 渲染器。"""

    def render(self, ctx: RenderContext) -> str:
        a = ctx.attribution
        o = ctx.observation
        lines: List[str] = []
        lines.extend(self._frontmatter(ctx))
        name = ctx.entity_name or o.entity_id
        lines.append(f"# A股异动分析：{name}")
        lines.append("")
        lines.extend(self._section1(ctx))
        lines.extend(self._section2(ctx))
        lines.extend(self._section3(ctx))
        lines.extend(self._section4(ctx))
        lines.extend(self._section5(ctx))
        lines.extend(self._section6(ctx))
        lines.extend(self._section7(ctx))
        lines.extend(self._section8(ctx))
        lines.extend(self._section9(ctx))
        lines.extend(self._section10(ctx))
        lines.extend(self._section11(ctx))
        lines.extend(self._section12(ctx))
        lines.extend(self._section13(ctx))
        lines.extend(self._section14(ctx))
        lines.extend(self._section15(ctx))
        lines.extend(self._section16(ctx))
        lines.extend(self._section17(ctx))
        lines.extend(self._section18(ctx))
        return "\n".join(lines) + "\n"

    # ---------- Front Matter（任务书 15 节） ----------

    def _frontmatter(self, ctx: RenderContext) -> List[str]:
        a = ctx.attribution
        o = ctx.observation
        mr = a.model_route
        lines = [
            "---",
            "scenario: abnormal_move_analysis",
            f"run_id: {ctx.run.run_id}",
            f"request_id: {a.request_id}",
            f"entity_id: {o.entity_id}",
            f"entity_type: {o.entity_type}",
            f"analysis_date: {o.trade_date}",
            f"window_start: {o.window_start}",
            f"window_end: {o.window_end}",
            f"granularity: {o.granularity}",
            f"as_of: {ctx.run.finished_at}",
            f"provisional: {str(o.provisional).lower()}",
            f"data_status: {'partial' if o.missing_data else 'ok'}",
            f"attribution_status: {a.attribution_status}",
            f"overall_confidence: {a.overall_confidence}",
            f"market_data_version: {ctx.run.rules_versions.get('market_data', 'unknown')}",
            f"rules_versions: {ctx.run.rules_versions}",
            f"benchmark_selection_id: {a.benchmark_selection_id or 'null'}",
            f"missing_data: {o.missing_data}",
            f"warnings: {a.warnings}",
            "model_route:",
            f"  mode: {mr.mode}",
            f"  llm_called: {str(mr.llm_called).lower()}",
            f"  intended_default_model: {mr.intended_default_model}",
            f"  selected_model: {mr.selected_model or 'null'}",
            f"  escalated: {str(mr.escalated).lower()}",
            f"  escalation_reasons: {mr.escalation_reasons}",
            f"  provider_fallback_used: {str(mr.provider_fallback_used).lower()}",
            "---",
            "",
        ]
        return lines

    # ---------- 章节 ----------

    def _section1(self, ctx) -> List[str]:
        return [
            "## 一、执行说明",
            "- 本报告用于事实、事件和叙事分析，不构成目标价、评级、仓位或交易建议。",
            f"- 运行版本：{ctx.run.rules_versions}",
            f"- 数据截止时间：{ctx.run.finished_at}",
            f"- 模型路由：mode={ctx.attribution.model_route.mode}, "
            f"llm_called={ctx.attribution.model_route.llm_called}",
            "",
        ]

    def _section2(self, ctx) -> List[str]:
        o = ctx.observation
        return [
            "## 二、对象和分析窗口",
            f"- 对象：{ctx.entity_name or o.entity_id}",
            f"- 对象类型：{o.entity_type}",
            f"- 分析日期：{o.trade_date}",
            f"- 窗口：{o.window_start} 至 {o.window_end}",
            f"- 异常粒度：{o.granularity}",
            f"- 研究深度：{ctx.run.rules_versions.get('depth', 'standard')}",
            "",
        ]

    def _section3(self, ctx) -> List[str]:
        o = ctx.observation
        sel = ctx.selection
        lines = [
            "## 三、数据覆盖和降级",
            f"- 历史行情来源与版本：{ctx.run.rules_versions.get('market_data', 'manual_import')}",
            f"- 复权口径：{o.adjustment_method}",
            f"- 市场基准：{sel.market_benchmark_id if sel else '（缺失）'}",
            f"- 行业基准：{sel.primary_industry_benchmark_id if sel else '（缺失）'}",
            f"- 概念基准：{(sel.auxiliary_concept_benchmark_ids if sel else []) or '（缺失）'}",
            f"- 缺失字段：{o.missing_data or '（无）'}",
            f"- 降级项：{sel.fallback_status if sel else 'benchmark_insufficient'}",
        ]
        if ctx.narrative is not None and hasattr(ctx.narrative, "channels_covered"):
            lines.append(f"- 四个监测方向覆盖状态：{ctx.narrative.channels_covered}")
        lines.append("")
        return lines

    def _section4(self, ctx) -> List[str]:
        o = ctx.observation
        lines = [
            "## 四、异动事实",
            f"- 绝对收益：{o.raw_return if o.raw_return is not None else 'N/A'}",
            f"- 特殊市场状态：{o.market_state_flags or '（无）'}",
            "- 每项指标的历史分位、Z-score 和样本数：",
        ]
        for m in ctx.metrics:
            lines.append(
                f"  - {m.metric_type}: value={m.value} "
                f"percentile={m.historical_percentile} z={m.robust_z} "
                f"severity={m.severity} sample={m.sample_size} status={m.status}")
        lines.append("")
        return lines

    def _section5(self, ctx) -> List[str]:
        o = ctx.observation
        lines = [
            "## 五、市场、行业和概念相对表现",
            f"- 相对市场：{o.market_relative_return if o.market_relative_return is not None else 'N/A'}",
            f"- 相对行业：{o.industry_relative_return if o.industry_relative_return is not None else 'N/A'}",
            f"- 相对概念：{o.concept_relative_returns or 'N/A'}",
            f"- Beta 调整残差：{'见指标表' if any(m.metric_type == 'beta_adjusted_residual' for m in ctx.metrics) else '样本不足未输出'}",
        ]
        sel = ctx.selection
        if sel:
            lines.append(f"- 基准选择依据与限制：{sel.selection_rationale or '（见候选评分）'}")
        lines.append("")
        return lines

    def _section6(self, ctx) -> List[str]:
        a = ctx.attribution
        abnormal = ctx.observation.status != "no_abnormal_move"
        lines = [
            "## 六、结论摘要",
            f"- 异动是否成立：{'是' if abnormal else '否'}",
            f"- 归因状态：{a.attribution_status}",
            f"- 总体置信度：{a.overall_confidence}",
        ]
        if a.attribution_status == "UNEXPLAINED_MOVE":
            lines.append("- 一句话结论：**UNEXPLAINED_MOVE**（异动事实成立但无法归因）")
        elif a.primary_cause_ids:
            lines.append("- 一句话结论：主原因成立（见第七章）")
        else:
            lines.append("- 一句话结论：证据不足，未形成主原因")
        lines.append("")
        return lines

    def _section7(self, ctx) -> List[str]:
        return self._causes_block(ctx, ctx.attribution.primary_cause_ids,
                                  "七、主要原因")

    def _section8(self, ctx) -> List[str]:
        return self._causes_block(ctx, ctx.attribution.secondary_cause_ids,
                                  "八、次要原因")

    def _section9(self, ctx) -> List[str]:
        lines = ["## 九、背景因素"]
        bg = [c for c in ctx.candidates if c.cause_candidate_id in
              ctx.attribution.background_cause_ids]
        if not bg:
            lines.append("（本报告无该项内容）")
        for c in bg:
            lines.append(f"- {c.title}（{c.cause_category}，final={c.final_score}）")
        lines.append("")
        return lines

    def _causes_block(self, ctx, ids: List[str], title: str) -> List[str]:
        lines = [f"## {title}"]
        if not ids:
            lines.append("（本报告无该项内容）")
            lines.append("")
            return lines
        for cid in ids:
            c = next((c for c in ctx.candidates if c.cause_candidate_id == cid), None)
            if c is None:
                continue
            lines.extend([
                f"### {c.title}",
                f"- 分类：{c.cause_category}",
                f"- 分数：{c.final_score}（base={c.base_score}，惩罚={c.penalties}）",
                f"- 时间关系：{c.timing_relation}（发布于 {c.published_at or '未知'}）",
                f"- 机制：{c.mechanism_summary or '（无）'}",
                f"- 支持证据：{len(c.evidence_ids)} 条",
                f"- 反证：{len(c.opposing_evidence_ids)} 条",
                f"- 置信度：{c.confidence or '未定'}",
                "",
            ])
        return lines

    def _section10(self, ctx) -> List[str]:
        lines = [
            "## 十、候选原因证据表",
            "| 候选 | 时间 | 实体关联 | 新颖性 | 联动 | 来源 | 覆盖 | 可验证 | 惩罚 | 最终分 | 状态 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
        for c in sorted(ctx.candidates, key=lambda x: x.final_score, reverse=True):
            lines.append(
                f"| {c.title[:24]} | {c.time_match_score} | {c.entity_link_score} | "
                f"{c.novelty_score} | {c.peer_linkage_score} | {c.source_reliability_score} | "
                f"{c.explanation_coverage_score} | {c.verifiability_score} | "
                f"{c.penalties} | {c.final_score} | {c.status} |")
        lines.append("")
        return lines

    def _section11(self, ctx) -> List[str]:
        lines = ["## 十一、板块和同类公司联动"]
        peer = ctx.peer_info or {}
        if not peer:
            lines.append("（无有效同行数据或未计算）")
        else:
            lines.append(f"- 有效同行数：{peer.get('effective_peers', 0)}")
            lines.append(f"- 上涨家数比例：{peer.get('advancing_ratio')}")
            lines.append(f"- 下跌家数比例：{peer.get('declining_ratio')}")
            lines.append(f"- 同类公司中位收益：{peer.get('peer_median_return')}")
            lines.append(f"- 对象横截面位置：{peer.get('subject_cross_sectional_percentile')}")
            lines.append(f"- 个股特异性：{'是' if peer.get('idiosyncratic') else '否'}")
            lines.append(f"- 同方向异常计数：{peer.get('same_direction_abnormal_count', 0)}")
        lines.append("")
        return lines

    def _section12(self, ctx) -> List[str]:
        lines = ["## 十二、媒体与市场叙事"]
        n = ctx.narrative
        if n is None:
            lines.append("（本报告无该项内容）")
        else:
            if getattr(n, "facts", None):
                lines.append("- **事实线索**：")
                for f in n.facts[:10]:
                    lines.append(f"  - {f['title'][:60]}（{f.get('published_at', '')}）")
            if getattr(n, "opinions", None):
                lines.append("- **来源观点**：")
                for o in n.opinions[:10]:
                    lines.append(f"  - {o['title'][:60]}（说话者：{o.get('speaker', '未知')}）")
            if getattr(n, "narratives", None):
                lines.append("- **传播叙事**：")
                for x in n.narratives[:10]:
                    lines.append(f"  - {x['title'][:60]}（{x.get('speaker', '匿名')}）")
            if getattr(n, "unverified", None):
                lines.append("- **未验证消息**：")
                for x in n.unverified[:5]:
                    lines.append(f"  - {x['title'][:60]}（匿名，不能单独支持核心事实）")
            lines.append("- 注：社区热度不得解释为机构买卖行为。")
        lines.append("")
        return lines

    def _section13(self, ctx) -> List[str]:
        lines = ["## 十三、反证"]
        if not ctx.contradictions:
            lines.append("（未发现未解决反证）")
        for c in ctx.contradictions:
            lines.append(f"- {c}")
        lines.append("")
        return lines

    def _section14(self, ctx) -> List[str]:
        lines = ["## 十四、排除项"]
        excluded = [c for c in ctx.candidates if c.cause_candidate_id in
                    ctx.attribution.excluded_cause_ids]
        if not excluded:
            lines.append("（本报告无该项内容）")
        for c in excluded:
            lines.append(
                f"- {c.title}（{c.cause_category}，final={c.final_score}，低于 45 分排除）")
        lines.append("")
        return lines

    def _section15(self, ctx) -> List[str]:
        a = ctx.attribution
        lines = [
            "## 十五、无法确认事项",
            f"- UNKNOWN：{a.unknown_claim_ids or '（无）'}",
            f"- INSUFFICIENT_EVIDENCE：{a.hypothesis_claim_ids or '（无）'}",
            f"- SOURCE_CONFLICT：{a.contradictions or '（无）'}",
            f"- DATA_DEGRADED：{a.missing_data or '（无）'}",
            "",
        ]
        return lines

    def _section16(self, ctx) -> List[str]:
        lines = [
            "## 十六、后续验证问题",
            "- （本报告无该项内容；由验证问题生成模块补充）",
            "",
        ]
        return lines

    def _section17(self, ctx) -> List[str]:
        lines = ["## 十七、来源与证据"]
        seen = set()
        for c in ctx.candidates:
            for ev in c.evidence_ids:
                if ev in seen:
                    continue
                seen.add(ev)
                lines.append(f"- Evidence ID: {ev}（候选：{c.title[:30]}）")
        if not seen:
            lines.append("（无证据记录）")
        lines.append("")
        return lines

    def _section18(self, ctx) -> List[str]:
        mr = ctx.attribution.model_route
        lines = [
            "## 十八、模型路由和限制",
            f"- 是否实际调用模型：{'是' if mr.llm_called else '否'}",
            f"- Flash/Pro：{mr.intended_default_model}（selected={mr.selected_model or '无'}）",
            f"- 升级原因：{mr.escalation_reasons or '（无）'}",
            f"- Provider 故障回退：{mr.provider_fallback_used}（{mr.provider_fallback_reason or '无'}）",
            f"- 规则回退：{mr.failure_stage or '无'}"
            f"{'（确定性规则近似，非模型推理）' if not mr.llm_called else ''}",
            f"- 时间精度和数据限制：{ctx.observation.timing_precision} / "
            f"missing_data={ctx.observation.missing_data or '无'}",
            "",
        ]
        return lines
