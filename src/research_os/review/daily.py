"""每日复盘流水线（Phase 6B B2）。

结构（工程指南 69.8 / DECISIONS #43.4）：
observed_fact / previous_research_view / new_evidence / updated_interpretation /
remaining_unknown。回答：今天实际发生了什么、此前记录了什么判断、新增了什么
Evidence、哪些假设得到支持、哪些被削弱/证伪、哪些仍未知。

daily_review != 次日交易计划（输出安全校验覆盖）。
previous_research_view 无来源时明确降级，不虚构历史判断。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.review.evidence import (
    cutoff_after,
    entity_overlap,
    load_evidence_in_range,
    load_previous_views,
    opposite_signal,
)
from research_os.utils.time import now_iso

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")
_DEFAULT_PREVIOUS_CUTOFF_HOUR = 20  # 默认上次研究截止 = 复盘日前一日 20:00（晨报窗口结束）


@dataclass
class DailyReviewArtifacts:
    task_id: str
    review_business_date: str
    as_of: str
    previous_cutoff: str
    observed_facts: List[dict] = field(default_factory=list)
    previous_views: List[dict] = field(default_factory=list)
    new_evidence: List[dict] = field(default_factory=list)
    interpretations: List[dict] = field(default_factory=list)
    remaining_unknown: List[str] = field(default_factory=list)
    markdown: str = ""
    report_path: Optional[str] = None
    missing_data: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def previous_cutoff_for(review_business_date: date) -> str:
    """默认上次研究截止：复盘日前一日 20:00:00（晨报信息窗口结束）。"""
    dt = datetime.combine(review_business_date - timedelta(days=1), time(20, 0), tzinfo=_SHANGHAI)
    return dt.isoformat(timespec="seconds")


def _day_range(review_business_date: date) -> tuple[str, str]:
    start = datetime.combine(review_business_date, time(0, 0), tzinfo=_SHANGHAI)
    end = datetime.combine(review_business_date + timedelta(days=1), time(0, 0), tzinfo=_SHANGHAI)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _claim_text(claim: Optional[dict]) -> str:
    if not claim:
        return ""
    return str(claim.get("title") or claim.get("statement")
               or (claim.get("object") or {}).get("summary") or "")


def _claim_entities(claim: Optional[dict]) -> List[str]:
    if not claim:
        return []
    obj = claim.get("object") or {}
    return list(obj.get("entities") or obj.get("subject_entities") or [])


def _interpret(claim: dict, new_evidence: List[dict]) -> str:
    """确定性近似判断：supported / weakened / falsified / unchanged / unknown。

    规则（明确为近似，不宣称语义判断）：
    - 无 claim 内容可解析 -> unknown
    - 与新增证据实体重叠且无相反信号 -> supported（获得新证据）
    - 与新增证据实体重叠且有相反信号 -> weakened（出现削弱信号；直接矛盾按
      opposite_signal 命中处理，确认为削弱而非证伪——证伪需要更强证据，此处
      不越权判定）
    - 无相关新增证据 -> unchanged（未见新证据，不代表没有变化）
    """
    text = _claim_text(claim)
    if not text:
        return "unknown"
    related = []
    for ev in new_evidence:
        ev_text = f"{ev.get('title', '')} {ev.get('excerpt', '')}"
        if entity_overlap(_claim_entities(claim), ev.get("entities") or []):
            related.append(ev_text)
        elif any(tok in text for tok in ev_text.split() if len(tok) >= 4):
            related.append(ev_text)
    if not related:
        return "unchanged"
    if any(opposite_signal(text, r) for r in related):
        return "weakened"
    return "supported"


class DailyReviewPipeline:
    """每日复盘（确定性第一版；语义归纳留 LLM 扩展接口）。"""

    def __init__(self, project_root: str | Path, db: Any):
        self.project_root = Path(project_root)
        self.db = db

    def run(
        self,
        review_business_date: date,
        as_of: str,
        *,
        task_id: str,
        previous_run_ids: Optional[List[str]] = None,
        previous_report_paths: Optional[List[str]] = None,
        previous_cutoff: Optional[str] = None,
        entities: Optional[List[str]] = None,
    ) -> DailyReviewArtifacts:
        day_start, day_end = _day_range(review_business_date)
        cutoff = previous_cutoff or previous_cutoff_for(review_business_date)
        artifacts = DailyReviewArtifacts(
            task_id=task_id,
            review_business_date=review_business_date.isoformat(),
            as_of=as_of,
            previous_cutoff=cutoff,
        )

        # 1. observed_fact：复盘日全天 Evidence（DB 只读复用）
        artifacts.observed_facts = load_evidence_in_range(self.db, day_start, day_end)
        for ev in artifacts.observed_facts:
            if cutoff_after(cutoff, ev.get("published_at", "")):
                artifacts.new_evidence.append(ev)

        # 2. previous_research_view：morning/evening 已验收产物（claims.json / 报告路径）
        artifacts.previous_views = load_previous_views(
            self.project_root, list(previous_run_ids or []), list(previous_report_paths or []))
        if not artifacts.previous_views:
            artifacts.missing_data.append(
                "previous_research_view: 无前序研究产物（previous_run_ids / previous_report_paths "
                "为空或不可读），updated_interpretation 无法执行，不虚构历史判断")

        # 3. updated_interpretation：确定性近似
        for view in artifacts.previous_views:
            claim = view.get("claim")
            verdict = _interpret(claim, artifacts.new_evidence)
            artifacts.interpretations.append({
                "source_run_id": view.get("source_run_id"),
                "source_report_path": view.get("source_report_path"),
                "claim_id": (claim or {}).get("claim_id"),
                "verdict": verdict,
                "note": _interpret_note(verdict),
            })

        # 4. remaining_unknown
        artifacts.remaining_unknown = _remaining_unknown(artifacts)

        # 5. 渲染
        artifacts.markdown = render_daily_review(artifacts)
        artifacts.report_path = report_path_for(review_business_date, self.project_root)
        return artifacts


def _interpret_note(verdict: str) -> str:
    return {
        "supported": "当日新增 Evidence 与既有判断主题相关且无相反信号（确定性近似）",
        "weakened": "当日新增 Evidence 出现相反信号，判断被削弱（确定性近似）",
        "falsified": "当日新增 Evidence 直接推翻（本版不越权判定，需更强证据）",
        "unchanged": "当日未见相关新增 Evidence；不代表没有变化",
        "unknown": "前序判断内容无法解析或缺少结构化 Claim",
    }[verdict]


def _remaining_unknown(artifacts: DailyReviewArtifacts) -> List[str]:
    out: List[str] = []
    if not artifacts.observed_facts:
        out.append("复盘日窗口内未检索到 Evidence；不得将此解释为'没有变化'")
    if not artifacts.previous_views:
        out.append("缺少前序研究产物，无法评估判断变化")
    if artifacts.new_evidence and not artifacts.interpretations:
        out.append("有新增 Evidence 但无前序判断可对照")
    return out


def report_path_for(review_business_date: date, root: str | Path) -> str:
    """工程指南报告路径：reports/daily_review/YYYY/YYYY-MM/YYYY-MM-DD_review.md。"""
    p = (Path(root) / "reports" / "daily_review" / str(review_business_date.year)
         / f"{review_business_date.year:04d}-{review_business_date.month:02d}"
         / f"{review_business_date.isoformat()}_review.md")
    return str(p)


def render_daily_review(artifacts: DailyReviewArtifacts) -> str:
    """渲染每日复盘 Markdown（五段结构 + 执行说明）。"""
    finished = now_iso()
    out = [
        "---",
        f"report_id: {artifacts.task_id}",
        "scenario: daily_review",
        f"title: 每日复盘 {artifacts.review_business_date}",
        f"created_at: {finished}",
        f"as_of: {artifacts.as_of}",
        "timezone: Asia/Shanghai",
        "entities: []",
        f"time_window: {{start: {artifacts.review_business_date}T00:00:00+08:00, end: {artifacts.review_business_date}T23:59:59+08:00}}",
        f"review_business_date: {artifacts.review_business_date}",
        f"previous_cutoff: {artifacts.previous_cutoff}",
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
        f"# 每日复盘 {artifacts.review_business_date}",
        "",
        "## 执行说明", "",
        f"- 复盘交易日：{artifacts.review_business_date}（不得与实际执行日期混为一体）",
        f"- 研究时点 as_of：{artifacts.as_of}",
        f"- 上次研究截止 previous_cutoff：{artifacts.previous_cutoff}",
        f"- 数据覆盖状态：{'部分缺失' if artifacts.missing_data else '正常'}",
        "- 降级与缺失：" + ("；".join(artifacts.missing_data) or "无"),
        "- 判断变化为确定性近似（实体重叠 + 相反信号），语义归纳未接入",
        "",
        "## 一、observed_fact（当日实际发生）", "",
    ]
    if artifacts.observed_facts:
        for ev in artifacts.observed_facts[:30]:
            out.append(f"- {ev.get('published_at', '')} | {ev.get('title', '')} "
                       f"（Evidence ID: `{ev.get('evidence_id', '')}`，来源 {ev.get('source_id', '')}）")
        if len(artifacts.observed_facts) > 30:
            out.append(f"- …（共 {len(artifacts.observed_facts)} 条）")
    else:
        out.append("- 复盘日窗口内未检索到 Evidence（不得解释为'没有变化'）")
    out += ["", "## 二、previous_research_view（此前记录了什么判断）", ""]
    if artifacts.previous_views:
        for view in artifacts.previous_views:
            claim = view.get("claim")
            src = view.get("source_run_id") or view.get("source_report_path") or "未知"
            if claim:
                out.append(f"- Claim `{claim.get('claim_id', '')}`（来源 run {src}）："
                           f"{_claim_text(claim)[:120]}")
            else:
                out.append(f"- 前序报告（无结构化 Claim）：{src}")
    else:
        out.append("- 无前序研究产物；本段不虚构历史判断（见执行说明降级）")
    out += ["", "## 三、new_evidence（新增 Evidence）", ""]
    if artifacts.new_evidence:
        for ev in artifacts.new_evidence[:30]:
            out.append(f"- {ev.get('published_at', '')} | {ev.get('title', '')} "
                       f"（Evidence ID: `{ev.get('evidence_id', '')}`）")
        if len(artifacts.new_evidence) > 30:
            out.append(f"- …（共 {len(artifacts.new_evidence)} 条）")
    else:
        out.append("- previous_cutoff 之后无新增 Evidence（不得解释为'没有变化'）")
    out += ["", "## 四、updated_interpretation（判断变化）", ""]
    if artifacts.interpretations:
        counts: Dict[str, int] = {}
        for interp in artifacts.interpretations:
            counts[interp["verdict"]] = counts.get(interp["verdict"], 0) + 1
            out.append(f"- {interp['verdict']}：{interp['note']}"
                       f"（Claim `{interp['claim_id'] or '—'}`）")
        out.append("")
        out.append(f"- 汇总：支持 {counts.get('supported', 0)} / 削弱 {counts.get('weakened', 0)} / "
                   f"证伪 {counts.get('falsified', 0)} / 未变 {counts.get('unchanged', 0)} / "
                   f"未知 {counts.get('unknown', 0)}")
    else:
        out.append("- 无前序判断可对照（不虚构）")
    out += ["", "## 五、remaining_unknown（仍未知）", ""]
    if artifacts.remaining_unknown:
        for item in artifacts.remaining_unknown:
            out.append(f"- {item}")
    else:
        out.append("- 无（本期无明确未知项）")
    out.append("")
    return "\n".join(out)
