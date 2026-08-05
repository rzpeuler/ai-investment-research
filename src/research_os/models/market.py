"""行情数据契约（Phase 1.1 修正）。

实时快照（MarketRealtimeSnapshot）与历史日线（MarketDailyOhlcv）严格分离：
- 快照含 last_price/observed_at，不得映射为历史 close/trade_date；
- 日线必须含 trade_date 与 close；单次快照不得写入日线。
"""
from __future__ import annotations

from typing import Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso


def _check_date(value: str) -> str:
    import re

    if not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValueError(f"trade_date 必须是 YYYY-MM-DD: {value!r}")
    return value


class MarketRealtimeSnapshot(StrictModel):
    """当前交易日实时/延迟快照。"""

    snapshot_id: str
    symbol: str = Field(..., min_length=1)
    observed_at: str
    open: float
    high: float
    low: float
    last_price: float
    volume: float
    previous_close: Optional[float] = None
    amount: Optional[float] = None

    @field_validator("observed_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"observed_at 必须是 ISO-8601: {value!r}")
        return value


class MarketDailyOhlcv(StrictModel):
    """带明确交易日期的历史日线。"""

    bar_id: str
    symbol: str = Field(..., min_length=1)
    trade_date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None

    @field_validator("trade_date")
    @classmethod
    def _date(cls, value: str) -> str:
        return _check_date(value)
