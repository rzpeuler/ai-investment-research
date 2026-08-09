"""晨报时间窗口与延迟补跑（Phase 2 任务 7 节）——兼容层。

默认窗口（Asia/Shanghai）：前一日 20:00:00 至当日 08:00:00。
延迟执行仍使用原始窗口（不得改为至实际运行时间）。
幂等键：scenario + report_date + window_start + window_end。

Phase 6B（DECISIONS #43）后，窗口策略实现在 `research_os.brief.window`；
本模块保留 Phase 2 公开 API 不变（morning 策略委托）。
"""
from __future__ import annotations

from datetime import date
from typing import Tuple

from research_os.brief.window import (
    delay_info,
    idempotency_key,
    morning_policy,
    parse_report_date,
)

_policy = morning_policy()


def morning_window(report_date: date) -> Tuple[str, str]:
    """返回 (window_start, window_end) ISO-8601（Asia/Shanghai，含 +08:00）。

    报告日期 D：window = D-1 20:00 至 D 08:00。
    """
    return _policy.window(report_date)


def scheduled_for(report_date: date) -> str:
    """建议运行时间：报告日 08:10 Asia/Shanghai。"""
    return _policy.scheduled_for(report_date)


def as_of_for(report_date: date) -> str:
    """数据截止时间 = 窗口结束（报告日 08:00）。"""
    return _policy.as_of(report_date)


def report_path_for(report_date: date, reports_root: str) -> str:
    """晨报文件路径（指南 48 节命名规则）。"""
    return _policy.report_path_for(report_date, reports_root)
