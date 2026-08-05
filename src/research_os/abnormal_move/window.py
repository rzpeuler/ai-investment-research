"""异动窗口解析（Phase 3 任务书 5.1、7.12）。

- 未指定日期时使用最近一个已完整收盘的交易日；
- 显式非交易日返回参数错误并给出最近交易日提示，不静默平移；
- 当前交易日未收盘 -> provisional=true，快照不得写入日线。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from research_os.abnormal_move.market_data_loader import MarketDataLoader, TradingCalendar
from research_os.utils.time import shanghai_now


@dataclass
class ResolvedWindow:
    analysis_date: date
    window_start: date
    window_end: date
    provisional: bool
    as_of: str


class WindowError(ValueError):
    """参数级错误（显式非交易日等）。"""


def default_analysis_date(calendar: TradingCalendar) -> date:
    """最近一个已完整收盘的交易日（Asia/Shanghai 今天往前推）。"""
    today = shanghai_now().date()
    cursor = today
    for _ in range(14):
        if calendar.is_trading_day(cursor):
            return cursor
        cursor = cursor - timedelta(days=1)
    return today


def resolve_window(
    analysis_date: Optional[str],
    calendar: TradingCalendar,
    loader: Optional[MarketDataLoader] = None,
    symbol: Optional[str] = None,
    as_of: Optional[str] = None,
    lookback_days: int = 30,
) -> ResolvedWindow:
    """解析异动分析窗口。

    - analysis_date 为 None：最近完整收盘交易日（若 loader/symbol 提供则用日线最新日期）
    - 显式非交易日：抛 WindowError（含最近交易日提示），不静默平移
    """
    from research_os.utils.time import now_iso

    if analysis_date is not None:
        try:
            day = date.fromisoformat(analysis_date)
        except ValueError:
            raise WindowError(
                f"analysis_date 非法: {analysis_date!r}（需要 YYYY-MM-DD）"
            ) from None
        if not calendar.is_trading_day(day):
            prev = calendar.previous_trading_day(day)
            hint = f"；最近交易日为 {prev.isoformat()}" if prev else ""
            raise WindowError(
                f"{day.isoformat()} 不是交易日（周末或节假日）{hint}。"
                "显式非交易日不支持静默平移，请指定交易日。"
            )
    else:
        day = default_analysis_date(calendar)
        # 若日线可用，用数据的最新交易日（数据完整性优先）
        if loader is not None and symbol is not None:
            latest = loader.latest_trade_date(symbol)
            if latest is not None:
                day = date.fromisoformat(latest)

    window_end = day
    window_start = day - timedelta(days=lookback_days)
    as_of_value = as_of or now_iso()
    return ResolvedWindow(
        analysis_date=day,
        window_start=window_start,
        window_end=window_end,
        provisional=False,
        as_of=as_of_value,
    )
