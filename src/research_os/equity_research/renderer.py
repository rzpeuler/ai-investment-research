"""研报渲染器（Phase 4 任务书 3.21/Commit 15）。

38 章节 Markdown 模板；必须章节无论有无数据都显示，缺数据时写覆盖状态/缺失字段/
不能得出的结论/降级原因；禁止空章节套话；渲染四舍五入不回写结构化对象；
报告不新增结构化对象之外的关键事实（数据全部来自结构化对象输入）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.models.equity_research import EquityResearchResult
from research_os.equity_research.metric_display import (
    FINANCIAL_METRIC_DISPLAY,
    VALUATION_METRIC_DISPLAY,
    latest_financial_metrics,
    render_metric_line,
    valuation_metric_id,
)

# 38 章节（任务书 3.21）
SECTIONS = [
    "Front Matter", "研究对象", "研究范围、截止时间与版本", "执行摘要",
    "核心已知事实", "公司主体信息", "证券信息与股本变化", "业务结构与收入来源",
    "财务报告覆盖和审计状态", "收入趋势", "利润与利润率", "现金流质量",
    "资产负债质量", "营运资本与周转", "资本开支、在建工程与投资",
    "研发、销售与管理投入", "业务分部", "行业位置与产业链", "竞争格局",
    "竞争优势、劣势与反证", "同行候选和选择说明", "同行财务比较",
    "估值方法适用性", "历史估值观察", "同行估值观察", "情景与敏感性（可选）",
    "管理层、治理和资本配置", "重大项目、扩产、并购和资产变化",
    "Phase 3 历史事件和异动关联", "催化剂", "风险", "争议与来源冲突",
    "数据缺口", "待验证问题", "Claim 与 Evidence 摘要", "模型路由和降级",
    "方法和公式说明", "免责声明",
]

# 必须存在的章节（无论有无数据）
MANDATORY_SECTIONS = {1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 13, 18, 19, 20, 21, 22,
                      23, 24, 25, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38}

FORBIDDEN_FILLERS = ["公司未来可期", "行业前景广阔", "值得持续关注", "风险与机遇并存"]

DISCLAIMER = (
    "本报告由 AI＋A 股投研系统自动生成，仅供研究参考，不构成投资建议。"
    "不提供目标价、买卖评级、仓位建议或任何交易建议。"
)


@dataclass
class SectionContent:
    """单章节内容（来自结构化对象；缺数据时显式声明状态）。"""
    section_id: int
    title: str
    paragraphs: List[str] = field(default_factory=list)
    status: str = "covered"  # covered / not_applicable / missing_data / degraded


@dataclass
class RenderInput:
    """渲染输入（全部来自结构化对象，不得新增事实）。"""
    result: EquityResearchResult
    company_name: str = ""
    security_symbol: str = ""
    report_date: str = ""
    research_status: str = ""
    findings: List[Dict[str, Any]] = field(default_factory=list)
    metrics: List[Dict[str, Any]] = field(default_factory=list)
    segments: List[Dict[str, Any]] = field(default_factory=list)
    catalysts: List[Dict[str, Any]] = field(default_factory=list)
    risks: List[Dict[str, Any]] = field(default_factory=list)
    peers: Optional[Dict[str, Any]] = None
    valuation: Optional[Dict[str, Any]] = None
    scenarios: List[Dict[str, Any]] = field(default_factory=list)
    model_route: Dict[str, Any] = field(default_factory=dict)
    unknowns: List[str] = field(default_factory=list)
    data_gaps: List[str] = field(default_factory=list)


def _fmt_number(value: Any) -> str:
    """渲染数字（2 位百分比或 2-4 位倍数）；不回写结构化对象。"""
    if value is None:
        return "N/A"
    try:
        d = float(value)
    except (TypeError, ValueError):
        return str(value)
    if abs(d) < 1:
        return f"{d:.2%}" if abs(d) < 1 else f"{d:.2f}"
    return f"{d:.2f}"


def _financial_metric_lines(ri: RenderInput, section_id: int) -> List[str]:
    lines: List[str] = []
    for metric in latest_financial_metrics(ri.metrics):
        spec = FINANCIAL_METRIC_DISPLAY[metric["metric_code"]]
        if spec.section_id == section_id:
            lines.append(render_metric_line(metric, spec, metric["metric_id"]))
    return lines


def render_markdown(ri: RenderInput) -> str:
    """渲染完整研报 Markdown（38 章节）。"""
    lines: List[str] = []
    lines.append(f"# {ri.company_name or ri.result.company_entity_id} 个股深度研究报告")
    lines.append("")
    lines.append("---")
    lines.append("")

    for idx in range(1, 39):
        title = SECTIONS[idx - 1]
        if idx == 1:  # Front Matter
            lines.append(f"## {idx}. Front Matter")
            lines.append("")
            lines.append(f"- 报告日期：{ri.report_date}")
            lines.append(f"- 研究对象：{ri.company_name}（{ri.security_symbol}）")
            lines.append(f"- 研究状态：{ri.research_status}")
            lines.append(f"- 模型路由：{ri.model_route.get('mode', 'deterministic_fallback')}（llm_called={ri.model_route.get('llm_called', False)}）")
            lines.append("")
            continue

        lines.append(f"## {idx}. {title}")
        lines.append("")
        content = _render_section(ri, idx)
        if content.paragraphs:
            for p in content.paragraphs:
                lines.append(p)
                lines.append("")
        else:
            # 缺数据必须写覆盖状态/缺失字段/不能得出的结论/降级原因
            if idx in MANDATORY_SECTIONS:
                lines.append(f"**覆盖状态：{content.status}**")
                lines.append("")
                if content.status == "missing_data":
                    lines.append("本章节对应数据未导入或不足：无法得出该维度结论（不推断、不套话）。")
                    lines.append("")
            else:
                lines.append(f"*（可选章节：{content.status}，本报告未包含相关结构化对象）*")
                lines.append("")
        lines.append("---")
        lines.append("")

    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _render_section(ri: RenderInput, idx: int) -> SectionContent:
    """按章节 ID 渲染（数据只来自结构化对象输入）。"""
    if idx == 2:
        return SectionContent(idx, SECTIONS[idx - 1],
                              [f"- 公司实体：`{ri.result.company_entity_id}`", f"- 证券实体：`{ri.result.security_entity_id}`"])
    if idx == 3:
        return SectionContent(idx, SECTIONS[idx - 1], [
            f"- 数据截止时间（as_of）：`{ri.result.as_of}`",
            f"- 报告日期：`{ri.report_date}`",
            f"- 运行 ID：`{ri.result.run_id}`",
        ])
    if idx == 4:
        status_map = {"success": "研究完成", "partial_success": "部分完成",
                      "degraded": "降级完成", "insufficient_data": "数据不足",
                      "source_conflict": "来源冲突", "validation_failed": "校验失败",
                      "failed": "失败"}
        return SectionContent(idx, SECTIONS[idx - 1], [
            f"本报告研究状态为 **{status_map.get(ri.research_status, ri.research_status)}**。",
            f"关键发现 {len(ri.findings)} 条；财务指标 {len(ri.metrics)} 条；"
            f"催化剂 {len(ri.catalysts)} 条；风险 {len(ri.risks)} 条。",
        ])
    if idx == 5:
        facts = [f"- {f['title']}：{f['statement']}" for f in ri.findings if f.get("claim_type") == "FACT"]
        return SectionContent(idx, SECTIONS[idx - 1], facts[:20] or ["暂无已确认的核心事实（FACT）。"])
    if idx == 6:
        return SectionContent(idx, SECTIONS[idx - 1], [f"- 公司主体：`{ri.company_name or '未登记 CompanyProfile'}`"])
    if idx == 7:
        lines = [f"- 证券：`{ri.security_symbol or '未登记 SecurityProfile'}`"]
        lines.extend(_financial_metric_lines(ri, idx))
        return SectionContent(idx, SECTIONS[idx - 1], lines)
    if idx == 8:
        seg_lines = [f"- {s['canonical_name']}（{s.get('segment_type', 'other')}）" for s in ri.segments]
        return SectionContent(idx, SECTIONS[idx - 1], seg_lines or ["分部数据未导入。"])
    if idx == 9:
        return SectionContent(idx, SECTIONS[idx - 1], [
            f"财务报告/事实数量：{len(ri.metrics)} 条指标；覆盖状态见数据缺口章节。"])
    if idx == 10:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["收入趋势数据缺失。"])
    if idx == 11:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["利润率数据缺失。"])
    if idx == 12:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["现金流质量数据缺失。"])
    if idx == 13:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["资产负债数据缺失。"])
    if idx == 14:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["周转数据缺失。"])
    if idx == 15:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["资本开支数据缺失。"])
    if idx == 16:
        return SectionContent(idx, SECTIONS[idx - 1], _financial_metric_lines(ri, idx) or ["研发投入数据缺失。"])
    if idx == 17:
        seg_lines = [f"- {s['canonical_name']}：收入 {_fmt_number(s.get('revenue'))}" for s in ri.segments]
        return SectionContent(idx, SECTIONS[idx - 1], seg_lines or ["分部数据未导入。"])
    if idx in (18, 19):
        return SectionContent(idx, SECTIONS[idx - 1], ["行业与竞争数据未导入（可经 LLM 语义模块或人工补充）。"],
                              status="missing_data")
    if idx == 20:
        factors = [f"- {f['statement']}（{f.get('status', 'unknown')}）" for f in ri.findings
                   if f.get("finding_type") == "business_analysis"]
        return SectionContent(idx, SECTIONS[idx - 1], factors or ["竞争优势数据未导入。"])
    if idx == 21:
        if ri.peers:
            return SectionContent(idx, SECTIONS[idx - 1], [
                f"- 同行选择状态：{ri.peers.get('status')}；样本 {ri.peers.get('sample_size')}",
                f"- 选择同行：{', '.join(ri.peers.get('selected_company_ids', [])) or '无'}",
            ])
        return SectionContent(idx, SECTIONS[idx - 1], ["同行候选未构建。"], status="missing_data")
    if idx == 22:
        return SectionContent(idx, SECTIONS[idx - 1], ["同行财务比较数据未导入。"], status="missing_data")
    if idx == 23:
        if ri.valuation:
            notes = ri.valuation.get("applicability_notes", [])
            return SectionContent(idx, SECTIONS[idx - 1], [f"- {n}" for n in notes] or ["估值适用性说明缺失。"])
        return SectionContent(idx, SECTIONS[idx - 1], ["估值未计算。"], status="missing_data")
    if idx == 24:
        if ri.valuation:
            snapshot_id = ri.valuation.get("valuation_snapshot_id", "unknown")
            hist = [render_metric_line(m, VALUATION_METRIC_DISPLAY[m["metric_code"]],
                                       valuation_metric_id(snapshot_id, m["metric_code"]))
                    for m in ri.valuation.get("metrics", []) if m.get("metric_code") in VALUATION_METRIC_DISPLAY]
            return SectionContent(idx, SECTIONS[idx - 1], hist or ["历史估值观察数据缺失。"])
        return SectionContent(idx, SECTIONS[idx - 1], ["估值未计算。"], status="missing_data")
    if idx == 25:
        return SectionContent(idx, SECTIONS[idx - 1], ["同行估值观察数据缺失。"], status="missing_data")
    if idx == 26:
        if ri.scenarios:
            sc_lines = [f"- 情景「{s['name']}」：类型 {s.get('scenario_type')}，状态 {s.get('status')}" for s in ri.scenarios]
            return SectionContent(idx, SECTIONS[idx - 1], sc_lines)
        return SectionContent(idx, SECTIONS[idx - 1], ["本报告未启用情景预测（默认关闭）。"], status="not_applicable")
    if idx == 27:
        return SectionContent(idx, SECTIONS[idx - 1], ["管理层与治理数据未导入。"], status="missing_data")
    if idx == 28:
        return SectionContent(idx, SECTIONS[idx - 1], ["重大项目/扩产/并购数据未导入。"], status="missing_data")
    if idx == 29:
        links = ri.result.phase3_link_ids
        return SectionContent(idx, SECTIONS[idx - 1],
                              [f"- Phase 3 关联归因（只读）：{', '.join(links) if links else '无'}"])
    if idx == 30:
        cat_lines = [f"- {c['description']}（{c.get('status', 'active')}）" for c in ri.catalysts]
        return SectionContent(idx, SECTIONS[idx - 1], cat_lines or ["催化剂数据未导入。"])
    if idx == 31:
        risk_lines = [f"- {r['description']}（{r.get('status', 'active')}）" for r in ri.risks]
        return SectionContent(idx, SECTIONS[idx - 1], risk_lines or ["风险数据未导入。"])
    if idx == 32:
        return SectionContent(idx, SECTIONS[idx - 1],
                              ri.result.conflicts or ["未发现未解决的高等级来源冲突。"])
    if idx == 33:
        return SectionContent(idx, SECTIONS[idx - 1],
                              ri.data_gaps or ri.result.unknowns or ["暂无已识别数据缺口。"])
    if idx == 34:
        questions = [f"- {f['statement']}" for f in ri.findings if f.get("finding_type") == "research_question"]
        return SectionContent(idx, SECTIONS[idx - 1], questions or ["暂无待验证问题。"])
    if idx == 35:
        return SectionContent(idx, SECTIONS[idx - 1], [
            f"- Claim 数量：{len(ri.result.claim_ids)}；Evidence 数量：{len(ri.result.evidence_ids)}",
        ])
    if idx == 36:
        mode = ri.model_route.get("mode", "deterministic_fallback")
        called = ri.model_route.get("llm_called", False)
        return SectionContent(idx, SECTIONS[idx - 1], [
            f"- 模式：`{mode}`；llm_called=`{called}`",
            f"- 限制：`{ri.model_route.get('limitation', 'semantic_llm_modules_not_connected')}`",
        ])
    if idx == 37:
        return SectionContent(idx, SECTIONS[idx - 1], [
            "- 财务指标公式版本：见 FinancialMetric.formula_version",
            "- 估值规则版本：见 ValuationSnapshot.percentile_method",
            "- 同行评分版本：见 PeerSelection.scoring_version",
        ])
    if idx == 38:
        return SectionContent(idx, SECTIONS[idx - 1], [DISCLAIMER])
    return SectionContent(idx, SECTIONS[idx - 1], [], status="missing_data")


def check_no_filler(rendered: str) -> List[str]:
    """检查禁用的空章节套话。"""
    return [f for f in FORBIDDEN_FILLERS if f in rendered]
