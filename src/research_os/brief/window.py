"""Morning/Evening Brief 共享时间窗口策略（Phase 6B 设计纠正，DECISIONS #43）。

evening_brief 是 morning_brief 的同构复用场景，唯一业务差异为信息采集时间窗口。
本模块把窗口策略参数化：

- morning_policy：前一日 20:00 → 当日 08:00（Asia/Shanghai，含开始不含结束）
- evening_policy：当日 08:00 → 当日 20:00（Asia/Shanghai，含开始不含结束）

延迟补跑不漂移：无论实际启动时间多晚，business window 固定。
幂等键：scenario + report_date + window_start + window_end。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Callable, Tuple

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


@dataclass(frozen=True)
class BriefWindowPolicy:
    """Brief 场景的窗口与身份策略。

    窗口语义统一为 [start, end)（inclusive start, exclusive end）：
    window() 返回的 end 时刻本身不在窗口内。
    """

    scenario_id: str
    title_prefix: str
    report_subdir: str          # reports/<subdir>/...
    report_suffix: str          # <date>_<suffix>.md
    window: Callable[[date], Tuple[str, str]]
    scheduled_for: Callable[[date], str]
    as_of: Callable[[date], str]
    report_path_for: Callable[[date, str], str]

    def idempotency_key(self, report_date: str, window_start: str, window_end: str) -> str:
        return f"{self.scenario_id}|{report_date}|{window_start}|{window_end}"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _report_path(report_subdir: str, report_suffix: str,
                 report_date: date, reports_root: str) -> str:
    p = (Path(reports_root) / report_subdir / str(report_date.year)
         / f"{report_date.year:04d}-{report_date.month:02d}"
         / f"{report_date.isoformat()}_{report_suffix}.md")
    return str(p)


def morning_policy() -> BriefWindowPolicy:
    """晨报策略：D-1 20:00 → D 08:00，建议运行 08:10，路径 reports/morning/。"""

    def window(report_date: date) -> Tuple[str, str]:
        start = datetime.combine(report_date - timedelta(days=1), time(20, 0), tzinfo=_SHANGHAI)
        end = datetime.combine(report_date, time(8, 0), tzinfo=_SHANGHAI)
        return _iso(start), _iso(end)

    def scheduled_for(report_date: date) -> str:
        return _iso(datetime.combine(report_date, time(8, 10), tzinfo=_SHANGHAI))

    def as_of(report_date: date) -> str:
        return window(report_date)[1]

    return BriefWindowPolicy(
        scenario_id="morning_brief",
        title_prefix="A股每日晨报",
        report_subdir="morning",
        report_suffix="morning",
        window=window,
        scheduled_for=scheduled_for,
        as_of=as_of,
        report_path_for=lambda d, root: _report_path("morning", "morning", d, root),
    )


def evening_policy() -> BriefWindowPolicy:
    """晚报策略：D 08:00 → D 20:00，建议运行 20:10，路径 reports/evening/。

    严格语义 [08:00, 20:00)：08:00:00 含、20:00:00 不含；延迟补跑不漂移。
    """

    def window(report_date: date) -> Tuple[str, str]:
        start = datetime.combine(report_date, time(8, 0), tzinfo=_SHANGHAI)
        end = datetime.combine(report_date, time(20, 0), tzinfo=_SHANGHAI)
        return _iso(start), _iso(end)

    def scheduled_for(report_date: date) -> str:
        return _iso(datetime.combine(report_date, time(20, 10), tzinfo=_SHANGHAI))

    def as_of(report_date: date) -> str:
        return window(report_date)[1]

    return BriefWindowPolicy(
        scenario_id="evening_brief",
        title_prefix="A股每日晚报",
        report_subdir="evening",
        report_suffix="evening",
        window=window,
        scheduled_for=scheduled_for,
        as_of=as_of,
        report_path_for=lambda d, root: _report_path("evening", "evening", d, root),
    )


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
