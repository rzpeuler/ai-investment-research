"""个股增量复盘流水线（Phase 6B B3）。

增量复盘（工程指南 69.8 / DECISIONS #43.4）：what_changed / new_evidence /
thesis strengthened|weakened / risk changed / catalyst changed /
valuation assumption changed / remaining questions。

复用 Phase3（abnormal_move）与 Phase4（equity_research）已验收产物，
不重跑完整 Phase4 研报。确定性近似实现，语义归纳留 LLM 扩展接口。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.review.evidence import (
    cutoff_after,
    entity_overlap,
    load_evidence_in_range,
    load_research_findings,
    opposite_signal,
)
from research_os.utils.time import now_iso

# Phase 4 finding_type 与复盘维度的映射（复用已验收产物分类）
_FINDING_DIMENSION = {
    "risk_factor": "risk",
    "catalyst": "catalyst",
    "valuation": "valuation_assumption",
    "business": "thesis",
    "financial": "thesis",
    "competitive": "thesis",
    "forecast": "valuation_assumption",
}


@dataclass
class StockReviewArtifacts:
    task_id: str
    entity: str
    review_start: str
    review_end: str
    as_of: str
    previous_cutoff: Optional[str]
    findings: List[dict] = field(default_factory=list)
    window_evidence: List[dict] = field(default_factory=list)
    what_changed: List[str] = field(default_factory=list)
    thesis_supported: List[str] = field(default_factory=list)
    thesis_weakened: List[str] = field(default_factory=list)
    risk_changed: List[str] = field(default_factory=list)
    catalyst_changed: List[str] = field(default_factory=list)
    valuation_assumption_changed: List[str] = field(default_factory=list)
    remaining_questions: List[str] = field(default_factory=list)
    markdown: str = ""
    report_path: Optional[str] = None
    missing_data: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class StockReviewPipeline:
    """个股增量复盘（确定性第一版）。"""

    def __init__(self, project_root: str | Path, db: Any):
        self.project_root = Path(project_root)
        self.db = db

    def run(
        self,
        entity: str,
        review_start: date,
        review_end: date,
        as_of: str,
        *,
        task_id: str,
        previous_cutoff: Optional[str] = None,
    ) -> StockReviewArtifacts:
        day_start = f"{review_start.isoformat()}T00:00:00+08:00"
        day_end = f"{review_end.isoformat()}T23:59:59+08:00"
        artifacts = StockReviewArtifacts(
            task_id=task_id, entity=entity,
            review_start=review_start.isoformat(), review_end=review_end.isoformat(),
            as_of=as_of, previous_cutoff=previous_cutoff,
        )

        # 1. 窗口内 Evidence（新增信息；previous_cutoff 之后才算 new）
        artifacts.window_evidence = load_evidence_in_range(self.db, day_start, day_end)
        for ev in artifacts.window_evidence:
            artifacts.what_changed.append(
                f"{ev.get('published_at', '')} | {ev.get('title', '')} "
                f"（Evidence ID: `{ev.get('evidence_id', '')}`）")

        # 2. Phase 4 已验收产物（research_findings）
        artifacts.findings = load_research_findings(self.db, entity)
        if not artifacts.findings:
            artifacts.missing_data.append(
                f"Phase4 research_findings: 实体 {entity} 无已验收研报产物；"
                "thesis/risk/catalyst/valuation 复盘无法对照（不虚构）")

        # 3. 增量对照（确定性近似）
        self._evaluate(artifacts)

        # 4. remaining questions
        artifacts.remaining_questions = _remaining_questions(artifacts)

        # 5. 渲染
        artifacts.markdown = render_stock_review(artifacts)
        artifacts.report_path = report_path_for(entity, review_end, self.project_root)
        return artifacts

    def _evaluate(self, artifacts: StockReviewArtifacts) -> None:
        for finding in artifacts.findings:
            dimension = _FINDING_DIMENSION.get(str(finding.get("finding_type", "")), "thesis")
            statement = str(finding.get("statement") or finding.get("title") or "")
            f_entities = _finding_entities(finding)
            related = []
            for ev in artifacts.window_evidence:
                ev_text = f"{ev.get('title', '')} {ev.get('excerpt', '')}"
                ev_entities = ev.get("entities") or []
                if entity_overlap(f_entities, ev_entities):
                    related.append(ev_text)
                elif any(tok in ev_text for tok in statement.split() if len(tok) >= 4):
                    related.append(ev_text)
            if not related:
                # 无相关新增证据：维持原判断（明确标注非"没有变化"）
                continue
            weakened = any(opposite_signal(statement, r) for r in related)
            line = (f"{statement[:80]}"
                    f"（{'出现相反信号，判断被削弱' if weakened else '获新增证据支持'}；"
                    f"相关 Evidence {len(related)} 条）")
            if dimension == "risk":
                artifacts.risk_changed.append(line)
            elif dimension == "catalyst":
                artifacts.catalyst_changed.append(line)
            elif dimension == "valuation_assumption":
                artifacts.valuation_assumption_changed.append(line)
            elif weakened:
                artifacts.thesis_weakened.append(line)
            else:
                artifacts.thesis_supported.append(line)


def _finding_entities(finding: dict) -> List[str]:
    obj = finding.get("object") or {}
    entities = obj.get("entities") or obj.get("subject_entities") or []
    if not entities and finding.get("company_entity_id"):
        entities = [finding["company_entity_id"]]
    return list(entities)


def _remaining_questions(artifacts: StockReviewArtifacts) -> List[str]:
    out: List[str] = []
    if not artifacts.window_evidence:
        out.append(f"窗口 {artifacts.review_start} 至 {artifacts.review_end} 内未检索到新增 Evidence；"
                   "不得将此解释为'没有变化'")
    if not artifacts.findings:
        out.append(f"实体 {artifacts.entity} 缺 Phase4 研报基线，无法评估 thesis/risk/catalyst 变化")
    for finding in artifacts.findings:
        invalidation = finding.get("invalidation_conditions") or []
        for cond in invalidation[:3]:
            if cond:
                out.append(f"待验证（研报基线）：{str(cond)[:100]}")
    return out[:10]


def report_path_for(entity: str, review_end: date, root: str | Path) -> str:
    safe = entity.replace(":", "_").replace("/", "_")
    p = (Path(root) / "reports" / "stock_review" / safe
         / f"{review_end.isoformat()}_stock_review.md")
    return str(p)


def render_stock_review(artifacts: StockReviewArtifacts) -> str:
    """渲染个股增量复盘 Markdown。"""
    finished = now_iso()
    out = [
        "---",
        f"report_id: {artifacts.task_id}",
        "scenario: stock_review",
        f"title: 个股复盘 {artifacts.entity}（{artifacts.review_start} 至 {artifacts.review_end}）",
        f"created_at: {finished}",
        f"as_of: {artifacts.as_of}",
        "timezone: Asia/Shanghai",
        "entities: []",
        f"time_window: {{start: {artifacts.review_start}T00:00:00+08:00, end: {artifacts.review_end}T23:59:59+08:00}}",
        f"entity: {artifacts.entity}",
        f"review_start: {artifacts.review_start}",
        f"review_end: {artifacts.review_end}",
        f"previous_cutoff: {artifacts.previous_cutoff or 'null'}",
        f"data_status: {'partial' if artifacts.missing_data else 'ok'}",
        "source_coverage: {}",
        "model_route:",
        "  mode: deterministic_fallback",
        "  llm_called: false",
        "  limitation: semantic_review_modules_not_connected",
        "runtime_seconds: 0",
        "validator_status: pending",
        "knowledge_coordinates: []",
        "---",
        "",
        f"# 个股复盘 {artifacts.entity}",
        "",
        "## 执行说明", "",
        f"- 复盘实体：{artifacts.entity}",
        f"- 增量窗口：{artifacts.review_start} 至 {artifacts.review_end}",
        f"- 上次研究截止 previous_cutoff：{artifacts.previous_cutoff or '未提供'}",
        f"- 数据覆盖状态：{'部分缺失' if artifacts.missing_data else '正常'}",
        "- 降级与缺失：" + ("；".join(artifacts.missing_data) or "无"),
        "- 本报告为增量复盘，不重跑完整 Phase4 研报；判断变化为确定性近似",
        "",
        "## 一、what_changed（窗口内发生了什么）", "",
    ]
    if artifacts.what_changed:
        out.extend(f"- {w}" for w in artifacts.what_changed[:30])
        if len(artifacts.what_changed) > 30:
            out.append(f"- …（共 {len(artifacts.what_changed)} 条）")
    else:
        out.append("- 窗口内未检索到新增 Evidence（不得解释为'没有变化'）")
    out += ["", "## 二、new_evidence（新增 Evidence）", ""]
    if artifacts.window_evidence:
        new = [ev for ev in artifacts.window_evidence
               if cutoff_after(artifacts.previous_cutoff, ev.get("published_at", ""))]
        if new:
            out.extend(f"- {ev.get('published_at', '')} | {ev.get('title', '')} "
                       f"（Evidence ID: `{ev.get('evidence_id', '')}`）" for ev in new[:30])
            if len(new) > 30:
                out.append(f"- …（共 {len(new)} 条）")
        else:
            out.append("- previous_cutoff 之后无新增 Evidence（不得解释为'没有变化'）")
    else:
        out.append("- 无（窗口内无 Evidence）")
    out += ["", "## 三、thesis（核心判断 strengthened / weakened）", ""]
    if artifacts.thesis_supported:
        out.append("- **strengthened（获支持）**：")
        out.extend(f"  - {line}" for line in artifacts.thesis_supported)
    if artifacts.thesis_weakened:
        out.append("- **weakened（被削弱）**：")
        out.extend(f"  - {line}" for line in artifacts.thesis_weakened)
    if not artifacts.thesis_supported and not artifacts.thesis_weakened:
        out.append("- 无相关新增证据；维持既有判断（不代表没有变化）")
    out += ["", "## 四、risk changed（风险变化）", ""]
    if artifacts.risk_changed:
        out.extend(f"- {line}" for line in artifacts.risk_changed)
    else:
        out.append("- 窗口内无与已记录风险相关的证据")
    out += ["", "## 五、catalyst changed（催化剂变化）", ""]
    if artifacts.catalyst_changed:
        out.extend(f"- {line}" for line in artifacts.catalyst_changed)
    else:
        out.append("- 窗口内无与已记录催化剂相关的证据")
    out += ["", "## 六、valuation assumption changed（估值假设变化）", ""]
    if artifacts.valuation_assumption_changed:
        out.extend(f"- {line}" for line in artifacts.valuation_assumption_changed)
    else:
        out.append("- 窗口内无与已记录估值假设相关的证据")
    out += ["", "## 七、remaining questions（仍待验证）", ""]
    if artifacts.remaining_questions:
        out.extend(f"- {q}" for q in artifacts.remaining_questions)
    else:
        out.append("- 无（本期无明确待验证项）")
    out.append("")
    return "\n".join(out)
