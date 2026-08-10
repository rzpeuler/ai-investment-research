"""Deterministic Shanghai-time expression resolver."""
from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
import re
from typing import Optional

from research_os.dashboard.models import TemporalResult


_ISO_DATE = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_CN_DATE = re.compile(r"(?<!\d)(\d{4})年(\d{1,2})月(\d{1,2})日")


def _subtract_month(day: date) -> date:
    year, month = day.year, day.month - 1
    if month == 0:
        year, month = year - 1, 12
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


class TemporalResolver:
    def resolve(self, expression: Optional[str], reference_now: datetime) -> TemporalResult:
        if expression is None or not str(expression).strip():
            return TemporalResult(status="omitted")
        text = re.sub(r"\s+", "", str(expression))
        today = reference_now.date()
        start = end = None
        match = _ISO_DATE.search(text) or _CN_DATE.search(text)
        if match:
            try:
                start = end = date(*(int(x) for x in match.groups()))
            except ValueError:
                return TemporalResult(status="clarification", message="日期无效，请使用 YYYY-MM-DD。")
        elif "最近7天" in text or "近7天" in text:
            start, end = today - timedelta(days=6), today
        elif "最近一个月" in text or "近一个月" in text:
            start, end = _subtract_month(today), today
        elif "本周" in text:
            start, end = today - timedelta(days=today.weekday()), today
        elif "本月" in text:
            start, end = today.replace(day=1), today
        elif "昨天" in text or "昨日" in text:
            start = end = today - timedelta(days=1)
        elif "今天" in text or "今日" in text:
            start = end = today
        else:
            return TemporalResult(status="clarification", message="无法确定时间，请使用明确日期或今天、昨天、本周、本月、最近7天、最近一个月。")
        as_of = (reference_now.isoformat(timespec="seconds") if end >= today else
                 datetime.combine(end, datetime.max.time()).replace(microsecond=0).isoformat())
        return TemporalResult(status="resolved", start_date=start.isoformat(),
                              end_date=end.isoformat(), as_of=as_of)
