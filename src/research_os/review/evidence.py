"""复盘场景共享数据访问（只读复用已验收产物）。

- Evidence：从 DB evidence 表按发布时间窗口读取（payload 为完整 Evidence）。
- Previous Views：从 run 目录 claims.json 读取（morning/evening 已验收产物）。
- Research Findings：从 DB research_findings 表读取（Phase 4 已验收产物）。

任何读取失败都显式记录，禁止静默把缺失当作"没有变化"。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.utils.time import parse_iso


def load_evidence_in_range(db: Any, start: str, end: str) -> List[dict]:
    """按发布时间 [start, end) 读取 Evidence（payload 完整对象）。

    start / end 为 ISO-8601 字符串；时间口径 Asia/Shanghai（naive ISO 字符串
    字典序比较与 parse_iso 语义一致）。
    """
    if db is None:
        return []
    rows = db.query(
        "SELECT payload FROM evidence "
        "WHERE json_extract(payload, '$.published_at') >= ? "
        "AND json_extract(payload, '$.published_at') < ? "
        "ORDER BY json_extract(payload, '$.published_at')",
        (start, end),
    )
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        except (TypeError, ValueError):
            continue
        out.append(payload)
    return out


def load_previous_views(project_root: Path, run_ids: List[str],
                        report_paths: List[str]) -> List[dict]:
    """读取 previous research views（claims 列表）。

    优先 run 目录（reports/runs/{run_id}/claims.json，morning/evening 已验收产物）；
    report_paths 提供时解析报告 Front Matter 作为来源记录（不含结构化 claim）。
    找不到任何前序判断时返回空列表（调用方负责 degraded 处理，不得虚构）。
    """
    views: List[dict] = []
    for run_id in run_ids:
        claims_path = Path(project_root) / "reports" / "runs" / run_id / "claims.json"
        if claims_path.exists():
            try:
                claims = json.loads(claims_path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            for c in claims:
                if isinstance(c, dict):
                    views.append({"source_run_id": run_id, "claim": c})
    for report_path in report_paths:
        p = Path(report_path)
        if p.exists():
            views.append({"source_report_path": str(p), "claim": None})
    return views


def load_research_findings(db: Any, company_entity_id: str) -> List[dict]:
    """读取 Phase 4 已验收产物（research_findings payload）。"""
    if db is None:
        return []
    rows = db.query(
        "SELECT payload FROM research_findings WHERE company_entity_id = ? ORDER BY version",
        (company_entity_id,),
    )
    out = []
    for row in rows:
        try:
            payload = json.loads(row["payload"]) if isinstance(row["payload"], str) else row["payload"]
        except (TypeError, ValueError):
            continue
        out.append(payload)
    return out


def entity_overlap(a: List[str], b: List[str]) -> bool:
    """实体集合是否有交集（用于判断新增证据与既有判断/主题的相关性）。"""
    if not a or not b:
        return False
    return bool(set(a) & set(b))


_OPPOSITE_PAIRS = [("今日", "昨日"), ("已", "未"), ("获批", "审批中"),
                   ("批准", "审批中"), ("上调", "下调"), ("完成", "延期"),
                   ("通过", "驳回")]


def opposite_signal(a: str, b: str) -> bool:
    """两条文本是否存在相反信号（确定性近似，供 weaken/falsify 判定）。"""
    for x, y in _OPPOSITE_PAIRS:
        if (x in a and y in b) or (y in a and x in b):
            return True
    return False


def cutoff_after(previous_cutoff: Optional[str], published_at: str) -> bool:
    """published_at 是否晚于 previous_cutoff（界定"新增 Evidence"）。"""
    if not previous_cutoff:
        return True
    try:
        return parse_iso(published_at) > parse_iso(previous_cutoff)
    except ValueError:
        return True
