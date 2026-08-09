"""Phase 6B 周期复盘工作流数据模型（6B-owned）。

EveningBriefRequest / EveningBriefRun / DailyReviewRequest / DailyReviewRun /
StockReviewRequest / StockReviewRun，与 schemas/evening_brief_*、
daily_review_*、stock_review_* 一致。

evening_brief 是 morning_brief 的同构复用场景（DECISIONS #43）：唯一业务差异为
信息采集时间窗口 [08:00, 20:00) Asia/Shanghai；运行记录结构与晨报一致。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

RequestStatus = Literal["planned", "validated", "rejected"]
RunStatus = Literal["success", "partial_success", "degraded", "insufficient_evidence", "failed"]
ReviewStatus = Literal["supported", "weakened", "falsified", "unchanged", "unknown"]


def _iso(value: str) -> str:
    if not validate_iso(value):
        raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


class _BriefRunFields:
    """Brief 运行记录公共字段（morning/evening 同构）。"""

    report_id: str
    task_id: str
    as_of: str
    window_start: str
    window_end: str
    actual_started_at: str
    actual_finished_at: str
    scheduled_for: str
    delayed: bool = False
    delay_seconds: int = 0
    coverage: List[Dict[str, Any]] = Field(default_factory=list)
    selected_cluster_ids: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status: RunStatus = "success"

    @field_validator("as_of", "window_start", "window_end",
                     "actual_started_at", "actual_finished_at", "scheduled_for")
    @classmethod
    def _iso_v(cls, value: str) -> str:
        return _iso(value)


class EveningBriefRequest(StrictModel):
    """晚报请求。"""

    request_id: str
    task_id: str
    report_date: str
    as_of: str
    timezone: str = "Asia/Shanghai"
    depth: Literal["fast", "standard", "deep"] = "standard"
    entities: List[str] = Field(default_factory=list)
    force: bool = False
    dry_run: bool = False
    live: bool = False
    status: RequestStatus = "planned"
    warnings: List[str] = Field(default_factory=list)
    requested_at: str

    @field_validator("report_date")
    @classmethod
    def _date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)  # 非法抛 ValueError
        return value

    @field_validator("as_of", "requested_at")
    @classmethod
    def _iso_v(cls, value: str) -> str:
        return _iso(value)


class EveningBriefRun(_BriefRunFields, StrictModel):
    """晚报运行记录（结构与晨报运行记录一致，仅 scenario 身份不同）。"""


class DailyReviewRequest(StrictModel):
    """每日复盘请求。

    review_business_date 为所复盘交易日；as_of 为研究时点（默认复盘日 20:00）。
    previous_run_ids / previous_report_paths 指向此前 morning_brief /
    evening_brief 的产物（previous_research_view 来源）；两者可省略，省略时
    复盘明确进入 degraded / insufficient_evidence 状态，不得虚构历史判断。
    """

    request_id: str
    task_id: str
    review_business_date: str
    as_of: str
    previous_cutoff: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    previous_run_ids: List[str] = Field(default_factory=list)
    previous_report_paths: List[str] = Field(default_factory=list)
    entities: List[str] = Field(default_factory=list)
    depth: Literal["fast", "standard", "deep"] = "standard"
    force: bool = False
    dry_run: bool = False
    status: RequestStatus = "planned"
    warnings: List[str] = Field(default_factory=list)
    requested_at: str

    @field_validator("review_business_date")
    @classmethod
    def _date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("as_of", "requested_at")
    @classmethod
    def _iso_v(cls, value: str) -> str:
        return _iso(value)


class DailyReviewRun(StrictModel):
    """每日复盘运行记录。"""

    run_id: str
    task_id: str
    review_business_date: str
    as_of: str
    previous_cutoff: Optional[str] = None
    observed_fact_count: int = 0
    previous_view_count: int = 0
    new_evidence_count: int = 0
    supported_count: int = 0
    weakened_count: int = 0
    falsified_count: int = 0
    unchanged_count: int = 0
    unknown_count: int = 0
    report_path: Optional[str] = None
    missing_data: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status: RunStatus = "success"

    @field_validator("review_business_date")
    @classmethod
    def _date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("as_of", "previous_cutoff")
    @classmethod
    def _iso_v(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _iso(value)


class StockReviewRequest(StrictModel):
    """个股增量复盘请求。

    entity 为证券/公司标识（Phase 4/5 实体映射）；review_start / review_end 为
    增量窗口；previous_cutoff 为上次研究截止（previous research cutoff），
    用于界定"新增 Evidence"。
    """

    request_id: str
    task_id: str
    entity: str
    review_start: str
    review_end: str
    as_of: str
    previous_cutoff: Optional[str] = None
    timezone: str = "Asia/Shanghai"
    depth: Literal["fast", "standard", "deep"] = "standard"
    force: bool = False
    dry_run: bool = False
    status: RequestStatus = "planned"
    warnings: List[str] = Field(default_factory=list)
    requested_at: str

    @field_validator("review_start", "review_end")
    @classmethod
    def _date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("as_of", "previous_cutoff", "requested_at")
    @classmethod
    def _iso_v(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _iso(value)


class StockReviewRun(StrictModel):
    """个股增量复盘运行记录。"""

    run_id: str
    task_id: str
    entity: str
    review_start: str
    review_end: str
    as_of: str
    previous_cutoff: Optional[str] = None
    what_changed: List[str] = Field(default_factory=list)
    new_evidence_count: int = 0
    thesis_supported: List[str] = Field(default_factory=list)
    thesis_weakened: List[str] = Field(default_factory=list)
    risk_changed: List[str] = Field(default_factory=list)
    catalyst_changed: List[str] = Field(default_factory=list)
    valuation_assumption_changed: List[str] = Field(default_factory=list)
    remaining_questions: List[str] = Field(default_factory=list)
    report_path: Optional[str] = None
    missing_data: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    status: RunStatus = "success"

    @field_validator("review_start", "review_end")
    @classmethod
    def _date(cls, value: str) -> str:
        from datetime import date

        date.fromisoformat(value)
        return value

    @field_validator("as_of", "previous_cutoff")
    @classmethod
    def _iso_v(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return _iso(value)
