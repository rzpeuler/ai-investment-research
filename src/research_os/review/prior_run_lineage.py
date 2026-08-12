"""Prior Run Lineage 共享 helper（P7-D1-R3）。

从 review/daily.py 抽取的纯只读 lineage 逻辑，供 DailyReviewPipeline 与
Data Layer RunArtifactChecker 共同调用（§40-42）。NO BUSINESS SEMANTIC CHANGE。

acceptance gate（任一不通过 → reject）：
1. run directory name == previous_run_id == task.json.task_id
2. task.json.status == "completed"
3. task.json.scenario in {morning_brief, evening_brief}
4. validation.json exists, status in {ok, pass, pass_with_warnings}
5. if validation.json has task_id, it must match previous_run_id

business cutoff extraction priority：
P1 — scenario Run artifact window_end（schema-valid 后）
P2 — task.json.time_window.end
P3 — task.json.as_of（morning legacy fallback）

永久禁止：finished_at, created_at, updated_at, requested_at, filesystem mtime/ctime。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from research_os.utils.time import parse_iso

_PASS_EQUIVALENT = {"ok", "pass", "pass_with_warnings"}
_ELIGIBLE_SCENARIOS = {"morning_brief", "evening_brief"}


def validate_prior_run(run_dir: Path, run_id: str) -> Optional[dict]:
    """校验单个 prior run 的 lineage；通过返回 task.json dict，否则 None。

    等价于 DailyReview._derive_prior_cutoff 中 gate 1-5 的单 run 判定。
    """
    tp = run_dir / "task.json"
    if not tp.exists():
        return None
    try:
        tdata = json.loads(tp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    if str(tdata.get("task_id") or "") != run_id:
        return None  # directory/task.json mismatch → reject
    if str(tdata.get("status") or "").strip() != "completed":
        return None
    if str(tdata.get("scenario") or "").strip() not in _ELIGIBLE_SCENARIOS:
        return None
    vp = run_dir / "validation.json"
    if not vp.exists():
        return None
    try:
        vdata = json.loads(vp.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None
    vstatus = str(vdata.get("status") or vdata.get("validation_status") or "").strip()
    if vstatus not in _PASS_EQUIVALENT:
        return None
    v_task_id = vdata.get("task_id")
    if v_task_id and str(v_task_id) != run_id:
        return None
    return tdata


def extract_business_cutoff(tdata: dict, run_dir: Path, scenario: str,
                            as_of_dt: datetime) -> Optional[datetime]:
    """P1: scenario Run artifact window_end → P2: task time_window.end → P3: task as_of。"""
    # P1 — scenario Run artifact
    if scenario == "evening_brief":
        ep = run_dir / "evening_brief_run.json"
        if ep.exists():
            try:
                edata = json.loads(ep.read_text(encoding="utf-8"))
                from research_os.validators.schema_validator import validate_instance
                schema_errors = validate_instance(edata, "evening_brief_run")
                if not schema_errors and str(edata.get("task_id") or "") == tdata.get("task_id"):
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


def derive_prior_cutoff(project_root: Path, previous_run_ids: List[str],
                        as_of: str) -> Optional[str]:
    """从 previous_run_ids 的 artifact metadata 推导真实 business cutoff。

    仅检查 requested run_ids；未通过 acceptance gate 的 prior run 不产生有效 cutoff。
    """
    try:
        as_of_dt = parse_iso(as_of)
    except ValueError:
        return None
    best: Optional[datetime] = None
    for run_id in previous_run_ids:
        run_dir = project_root / "reports" / "runs" / run_id
        tdata = validate_prior_run(run_dir, run_id)
        if tdata is None:
            continue
        t_scenario = str(tdata.get("scenario") or "").strip()
        cutoff_dt = extract_business_cutoff(tdata, run_dir, t_scenario, as_of_dt)
        if cutoff_dt and (best is None or cutoff_dt > best):
            best = cutoff_dt
    return best.isoformat(timespec="seconds") if best else None


def pass_equivalent_statuses() -> set:
    return set(_PASS_EQUIVALENT)


def eligible_scenarios() -> set:
    return set(_ELIGIBLE_SCENARIOS)
