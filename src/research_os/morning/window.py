"""晨报时间窗口与延迟补跑（Phase 2 任务 7 节）。

默认窗口（Asia/Shanghai）：前一日 20:00:00 至当日 08:00:00。
延迟执行仍使用原始窗口（不得改为至实际运行时间）。
幂等键：scenario + report_date + window_start + window_end。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Tuple

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


def morning_window(report_date: date) -> Tuple[str, str]:
    """返回 (window_start, window_end) ISO-8601（Asia/Shanghai，含 +08:00）。

    报告日期 D：window = D-1 20:00 至 D 08:00。
    """
    start = datetime.combine(report_date - timedelta(days=1), time(20, 0), tzinfo=_SHANGHAI)
    end = datetime.combine(report_date, time(8, 0), tzinfo=_SHANGHAI)
    return start.isoformat(timespec="seconds"), end.isoformat(timespec="seconds")


def scheduled_for(report_date: date) -> str:
    """建议运行时间：报告日 08:10 Asia/Shanghai。"""
    return datetime.combine(report_date, time(8, 10), tzinfo=_SHANGHAI).isoformat(timespec="seconds")


def as_of_for(report_date: date) -> str:
    """数据截止时间 = 窗口结束（报告日 08:00）。"""
    return morning_window(report_date)[1]


def delay_info(actual_started_at: str, scheduled: str) -> Tuple[bool, int]:
    """计算是否延迟与延迟秒数。actual 晚于 scheduled 视为延迟。"""
    try:
        a = datetime.fromisoformat(actual_started_at.replace("Z", "+00:00"))
        s = datetime.fromisoformat(scheduled.replace("Z", "+00:00"))
    except ValueError:
        return False, 0
    if a.tzinfo is None:
        a = a.replace(tzinfo=_SHANGHAI)
    if s.tzinfo is None:
        s = s.replace(tzinfo=_SHANGHAI)
    a = a.astimezone(_SHANGHAI)
    s = s.astimezone(_SHANGHAI)
    delta = (a - s).total_seconds()
    if delta > 0:
        return True, int(delta)
    return False, 0


def parse_report_date(value: str) -> date:
    """解析 --date 参数（YYYY-MM-DD）。非法输入抛 ValueError。"""
    return date.fromisoformat(value.strip())


def idempotency_key(scenario: str, report_date: str, window_start: str, window_end: str) -> str:
    """幂等键：scenario + report_date + window_start + window_end。"""
    return f"{scenario}|{report_date}|{window_start}|{window_end}"


def report_path_for(report_date: date, reports_root: str) -> str:
    """晨报文件路径（指南 48 节命名规则）。"""
    from pathlib import Path

    p = (Path(reports_root) / "morning" / str(report_date.year)
         / f"{report_date.year:04d}-{report_date.month:02d}"
         / f"{report_date.isoformat()}_morning.md")
    return str(p)
