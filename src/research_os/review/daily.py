"""每日复盘流水线（Phase 6B B2）。

结构（工程指南 69.8 / DECISIONS #43.4）：
observed_fact / previous_research_view / new_evidence / updated_interpretation /
remaining_unknown。回答：今天实际发生了什么、此前记录了什么判断、新增了什么
Evidence、哪些假设得到支持、哪些被削弱/证伪、哪些仍未知。

daily_review != 次日交易计划（输出安全校验覆盖）。
previous_research_view 无来源时明确降级，不虚构历史判断。

as_of 语义：observed_fact 截止 = min(day_end, as_of)；所有观察/新增/解读
不得使用 published_at > as_of 的 Evidence（BLOCKER B2-1 修复）。
previous_cutoff 优先显式值；否则从 previous_run_ids 的 artifact metadata
推导；无法确定时降级为 unavailable，不做伪精确分类（BLOCKER B2-2 修复）。
"""
from __future__ import annotations

import json
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
from research_os.utils.time import now_iso, parse_iso

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass
class DailyReviewArtifacts:
    task_id: str
    review_business_date: str
    as_of: str
    previous_cutoff: Optional[str]
    effective_end: str = ""
    observed_facts: List[dict] = field(default_factory=list)
    previous_views: List[dict] = field(default_factory=list)
    new_evidence: List[dict] = field(default_factory=list)
    interpretations: List[dict] = field(default_factory=list)
    remaining_unknown: List[str] = field(default_factory=list)
    markdown: str = ""
    report_path: Optional[str] = None
    missing_data: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _day_range(review_business_date: date) -> tuple[str, str]:
    start = datetime.combine(review_business_date, time(0, 0), tzinfo=_SHANGHAI)
    end = datetime.combine(review_business_date + timedelta(days=1), time(0, 0), tzinfo=_SHANGHAI)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def _effective_end(day_end: str, as_of: str) -> str:
    """observed_fact 截止 = min(day_end, as_of)（BLOCKER B2-1）。"""
    try:
        de = parse_iso(day_end)
        ao = parse_iso(as_of)
        return (day_end if de <= ao else as_of)
    except ValueError:
        return day_end


def _derive_prior_cutoff(project_root: Path, previous_run_ids: List[str],
                         as_of: str) -> Optional[str]:
    """从 previous_run_ids 的 artifact metadata 推导真实 business cutoff。

    acceptance gate（任一不通过 → reject）：
    1. run directory name == previous_run_id == task.json.task_id
    2. task.json.status == "completed"
    3. task.json.scenario in {morning_brief, evening_brief}
    4. validation.json exists, status in {ok, pass, pass_with_warnings}
    5. if validation.json has task_id, it must match previous_run_id

    cutoff extraction priority：
    P1 — scenario Run artifact (evening_brief_run.json.window_end)
    P2 — task.json.time_window.end
    P3 — task.json.as_of（morning legacy fallback）

    永久禁止：finished_at, created_at, updated_at, requested_at, runtime timestamp。
    未通过 acceptance gate 的 prior run 不产生有效 cutoff（返回 None）。
    """
    _PASS_EQUIVALENT = {"ok", "pass", "pass_with_warnings"}
    _ELIGIBLE_SCENARIOS = {"morning_brief", "evening_brief"}
    try:
        as_of_dt = parse_iso(as_of)
    except ValueError:
        return None

    best: Optional[datetime] = None
    for run_id in previous_run_ids:
        run_dir = project_root / "reports" / "runs" / run_id
        if not run_dir.exists():
            continue

        # ── gate 1: task.json exists + lineage ──
        tp = run_dir / "task.json"
        if not tp.exists():
            continue
        try:
            tdata = json.loads(tp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        t_task_id = str(tdata.get("task_id") or "")
        if t_task_id != run_id:
            continue  # directory/task.json mismatch → reject

        # ── gate 2: task completed ──
        t_status = str(tdata.get("status") or "").strip()
        if t_status != "completed":
            continue

        # ── gate 3: scenario eligible ──
        t_scenario = str(tdata.get("scenario") or "").strip()
        if t_scenario not in _ELIGIBLE_SCENARIOS:
            continue

        # ── gate 4: validation pass-equivalent ──
        vp = run_dir / "validation.json"
        if not vp.exists():
            continue
        try:
            vdata = json.loads(vp.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        vstatus = str(vdata.get("status") or vdata.get("validation_status") or "").strip()
        if vstatus not in _PASS_EQUIVALENT:
            continue

        # ── gate 5: validation task_id match (if present) ──
        v_task_id = vdata.get("task_id")
        if v_task_id and str(v_task_id) != run_id:
            continue

        # ── extract business cutoff ──
        cutoff_dt = _extract_business_cutoff(tdata, run_dir, t_scenario, as_of_dt)
        if cutoff_dt and (best is None or cutoff_dt > best):
            best = cutoff_dt

    return best.isoformat(timespec="seconds") if best else None


def _extract_business_cutoff(
    tdata: dict, run_dir: Path, scenario: str, as_of_dt: datetime,
) -> Optional[datetime]:
    """P1: scenario Run artifact window_end → P2: task time_window.end → P3: task as_of."""
    # P1 — scenario Run artifact
    if scenario == "evening_brief":
        ep = run_dir / "evening_brief_run.json"
        if ep.exists():
            try:
                edata = json.loads(ep.read_text(encoding="utf-8"))
                # authoritative schema validation before accepting
                from research_os.validators.schema_validator import validate_instance
                schema_errors = validate_instance(edata, "evening_brief_run")
                if schema_errors:
                    pass  # P1 rejected — schema invalid
                elif str(edata.get("task_id") or "") == tdata.get("task_id"):
                    we = edata.get("window_end")
                    if we:
                        dt = parse_iso(we)
                        if dt <= as_of_dt:
                            return dt
            except (ValueError, OSError, ImportError):
                pass
    # P2 — task time_window.end
    tw = tdata.get("time_window") or {}
    twe = tw.get("end") if isinstance(tw, dict) else None
    if twe:
        try:
            dt = parse_iso(twe)
            if dt <= as_of_dt:
                return dt
        except ValueError:
            pass
    # P3 — task as_of (legacy fallback)
    tao = tdata.get("as_of")
    if tao:
        try:
            dt = parse_iso(tao)
            if dt <= as_of_dt:
                return dt
        except ValueError:
            pass
    # P3.5 — legacy morning window_end at task top level
    we = tdata.get("window_end")
    if we:
        try:
            dt = parse_iso(we)
            if dt <= as_of_dt:
                return dt
        except ValueError:
            pass
    return None


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
    """确定性近似判断：supported / weakened / falsified / unchanged / unknown。"""
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
        effective_end = _effective_end(day_end, as_of)

        # previous_cutoff 三优先级（BLOCKER B2-2）
        if previous_cutoff:
            cutoff = previous_cutoff
        else:
            cutoff = _derive_prior_cutoff(
                self.project_root, list(previous_run_ids or []), as_of)
        if cutoff is None:
            # 无法确定 cutoff 时不标记 new_evidence（不伪造"新增"）
            artifacts = DailyReviewArtifacts(
                task_id=task_id,
                review_business_date=review_business_date.isoformat(),
                as_of=as_of,
                previous_cutoff=None,
                effective_end=effective_end,
            )
            artifacts.observed_facts = load_evidence_in_range(self.db, day_start, effective_end)
            artifacts.missing_data.append(
                "prior_cutoff_unavailable: 无法确定上次研究截止；"
                "new_evidence 不做伪精确分类；updated_interpretation 降级")
            artifacts.previous_views = load_previous_views(
                self.project_root, list(previous_run_ids or []), list(previous_report_paths or []))
            if not artifacts.previous_views:
                artifacts.missing_data.append(
                    "previous_research_view: 无前序研究产物（previous_run_ids / previous_report_paths "
                    "为空或不可读），updated_interpretation 无法执行，不虚构历史判断")
            for view in artifacts.previous_views:
                claim = view.get("claim")
                artifacts.interpretations.append({
                    "source_run_id": view.get("source_run_id"),
                    "source_report_path": view.get("source_report_path"),
                    "claim_id": (claim or {}).get("claim_id"),
                    "verdict": "unknown",
                    "note": "prior_cutoff 不可用，无法界定新增范围；不做伪精确判断",
                })
        else:
            artifacts = DailyReviewArtifacts(
                task_id=task_id,
                review_business_date=review_business_date.isoformat(),
                as_of=as_of,
                previous_cutoff=cutoff,
                effective_end=effective_end,
            )
            artifacts.observed_facts = load_evidence_in_range(self.db, day_start, effective_end)
            artifacts.previous_views = load_previous_views(
                self.project_root, list(previous_run_ids or []), list(previous_report_paths or []))
            if not artifacts.previous_views:
                artifacts.missing_data.append(
                    "previous_research_view: 无前序研究产物（previous_run_ids / previous_report_paths "
                    "为空或不可读），updated_interpretation 无法执行，不虚构历史判断")
            for ev in artifacts.observed_facts:
                if cutoff_after(cutoff, ev.get("published_at", "")):
                    artifacts.new_evidence.append(ev)
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
    }.get(verdict, verdict)


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
        f"time_window: {{start: {artifacts.review_business_date}T00:00:00+08:00, end: {artifacts.effective_end}}}",
        f"review_business_date: {artifacts.review_business_date}",
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
        f"# 每日复盘 {artifacts.review_business_date}",
        "",
        "## 执行说明", "",
        f"- 复盘交易日：{artifacts.review_business_date}（不得与实际执行日期混为一体）",
        f"- 研究时点 as_of：{artifacts.as_of}",
        f"- 上次研究截止 previous_cutoff：{artifacts.previous_cutoff or '不可用'}",
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
    elif artifacts.previous_cutoff is None:
        out.append("- prior_cutoff 不可用，不做伪精确新增标注")
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
        out.extend(f"- {item}" for item in artifacts.remaining_unknown)
    else:
        out.append("- 无（本期无明确未知项）")
    out.append("")
    return "\n".join(out)
