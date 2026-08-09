"""晨报 Markdown 渲染（Phase 2 任务 18 节模板）——兼容层。

Phase 6B（DECISIONS #43）后共享渲染器实现在 `research_os.brief.renderer`；
render_morning_brief 即 render_brief 的 morning 默认参数封装，输出不变。
"""
from __future__ import annotations

from datetime import date

from research_os.brief.renderer import band_label, render_brief


def render_morning_brief(
    artifacts,
    report_date: date,
    window_start: str,
    window_end: str,
    as_of: str,
    scheduled_for: str,
    started_at: str,
    delayed: bool,
    delay_seconds: int,
) -> str:
    """渲染完整晨报 Markdown（含 Front Matter）。"""
    return render_brief(
        artifacts, report_date, window_start, window_end, as_of,
        scheduled_for, started_at, delayed, delay_seconds,
        scenario="morning_brief", title_prefix="A股每日晨报",
    )
