"""市场数据导入契约（Phase 3）。

MarketDailySeriesManifest：日线导入批次清单。一个批次只能使用一种复权口径；
file_checksum + data_version 进入异动任务幂等键。失败导入不得写入正式日线表。

MarketMinuteBar：分钟级行情。Phase 3 仅 Schema/模型/Loader Protocol，无来源；
不得创建虚构分钟源。
"""
from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

UUID_RE = re.compile(r"^[0-9a-fA-F-]{36}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

AdjustmentMethod = Literal["none", "qfq", "hfq"]
ManifestSourceKind = Literal["manual_import", "verified_automatic"]
ManifestValidationStatus = Literal["pending", "accepted", "rejected"]


def _check_uuid(value: str, field: str) -> str:
    if not UUID_RE.match(value):
        raise ValueError(f"{field} 必须是 UUID 字符串: {value!r}")
    return value


def _check_date(value: str, field: str) -> str:
    if not DATE_RE.match(value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD: {value!r}")
    return value


class MarketDailySeriesManifest(StrictModel):
    """日线导入批次清单。"""

    import_id: str
    source_id: str = Field(..., min_length=1)
    source_kind: ManifestSourceKind = "manual_import"
    file_name: str = Field(..., min_length=1)
    file_checksum: str = Field(..., min_length=1, description="SHA-256")
    imported_at: str
    imported_by: str = Field(..., min_length=1)
    symbols: List[str] = Field(..., min_length=1)
    date_start: str
    date_end: str
    row_count: int = Field(..., ge=0)
    adjustment_method: AdjustmentMethod = "none"
    adjustment_description: str = ""
    calendar_id: str = Field(..., min_length=1)
    calendar_version: str = Field(..., min_length=1)
    currency: str = Field(..., min_length=1)
    price_unit: str = Field(..., min_length=1)
    volume_unit: str = Field(..., min_length=1)
    available_optional_fields: List[str] = Field(default_factory=list)
    data_version: str = Field(..., min_length=1)
    validation_status: ManifestValidationStatus = "pending"
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @field_validator("import_id")
    @classmethod
    def _import_id(cls, value: str) -> str:
        return _check_uuid(value, "import_id")

    @field_validator("imported_at")
    @classmethod
    def _imported_at(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"imported_at 必须是 ISO-8601: {value!r}")
        return value

    @field_validator("date_start", "date_end")
    @classmethod
    def _date(cls, value: str, info) -> str:
        return _check_date(value, info.field_name)

    @field_validator("symbols")
    @classmethod
    def _symbols(cls, value: List[str]) -> List[str]:
        if not value or any(not s for s in value):
            raise ValueError("symbols 必须非空且每个符号非空")
        return value


class MarketMinuteBar(StrictModel):
    """分钟级行情。"""

    bar_id: str
    symbol: str = Field(..., min_length=1)
    trade_date: str
    bar_time: str
    timezone: str = "Asia/Shanghai"
    interval: str = Field(..., min_length=1)
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: Optional[float] = None
    source_id: str = Field(..., min_length=1)
    data_version: str = Field(..., min_length=1)
    status: str = "ok"
    warnings: List[str] = Field(default_factory=list)

    @field_validator("bar_id")
    @classmethod
    def _bar_id(cls, value: str) -> str:
        return _check_uuid(value, "bar_id")

    @field_validator("trade_date")
    @classmethod
    def _trade_date(cls, value: str) -> str:
        return _check_date(value, "trade_date")

    @field_validator("bar_time")
    @classmethod
    def _bar_time(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"bar_time 必须是 ISO-8601: {value!r}")
        return value

    @field_validator("timezone")
    @classmethod
    def _tz(cls, value: str) -> str:
        if value != "Asia/Shanghai":
            raise ValueError("timezone 必须为 Asia/Shanghai")
        return value
