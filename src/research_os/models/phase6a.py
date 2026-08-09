"""Phase 6A 数据模型：行业研究与主题发现。

与 schemas/industry_research_*.schema.json、theme_discovery_*.schema.json 一一对应。
所有对象遵循：
- JSON Schema 为完整权威契约（全部字段 required、additionalProperties:false）
- Pydantic 仅提供构造便利（默认值），model_dump() 后必须通过对应 Schema
- extra="forbid" 与 Schema additionalProperties:false 一致
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field, field_validator

from research_os.models.core import SourcePolicy, StrictModel, TaskDepth
from research_os.utils.time import validate_iso


def _iso(value: str) -> str:
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


def _iso_opt(value: Optional[str]) -> Optional[str]:
    if value is not None:
        return _iso(value)
    return value


class IndustryResearchRequest(StrictModel):
    """行业研究请求（血缘契约：Task → Plan → Request → Run → Result）。"""

    request_id: str
    task_id: str
    industry_id: str = Field(..., min_length=1)
    industry_name: str = ""
    as_of: Optional[str] = None
    depth: TaskDepth = "standard"
    live: bool = False
    dry_run: bool = False
    force: bool = False
    source_policy: SourcePolicy = "public_first"
    status: str = "planned"
    warnings: List[str] = Field(default_factory=list)
    requested_at: str
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)

    @field_validator("requested_at")
    @classmethod
    def _requested_at_v(cls, value: str) -> str:
        return _iso(value)


class IndustryResearchRun(StrictModel):
    """行业研究运行记录。"""

    run_id: str
    request_id: str
    task_id: str
    industry_id: str = Field(..., min_length=1)
    as_of: Optional[str] = None
    depth: TaskDepth = "standard"
    status: str = "running"
    findings_count: int = Field(0, ge=0)
    dimensions_covered: List[str] = Field(default_factory=list)
    dimensions_missing: List[str] = Field(default_factory=list)
    report_path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    data_degraded: bool = False
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)


class ThemeDiscoveryRequest(StrictModel):
    """主题发现请求（血缘契约：Task → Plan → Request → Run → Result）。"""

    request_id: str
    task_id: str
    as_of: Optional[str] = None
    discovery_mode: str = "scanning"
    industry_ids: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    depth: TaskDepth = "standard"
    live: bool = False
    dry_run: bool = False
    force: bool = False
    source_policy: SourcePolicy = "public_first"
    status: str = "planned"
    warnings: List[str] = Field(default_factory=list)
    requested_at: str
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)

    @field_validator("requested_at")
    @classmethod
    def _requested_at_v(cls, value: str) -> str:
        return _iso(value)


class ThemeDiscoveryRun(StrictModel):
    """主题发现运行记录。"""

    run_id: str
    request_id: str
    task_id: str
    as_of: Optional[str] = None
    discovery_mode: str = "scanning"
    status: str = "running"
    themes_discovered: int = Field(0, ge=0)
    sort_metrics_count: int = Field(0, ge=0)
    report_path: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    data_degraded: bool = False
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)
