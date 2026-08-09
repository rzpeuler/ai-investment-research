"""Phase 6A 数据模型：行业研究与主题发现。

与 schemas/industry_research_*.schema.json、theme_discovery_*.schema.json 一一对应。
所有对象遵循：
- JSON Schema 为完整权威契约（全部字段 required、additionalProperties:false）
- Pydantic 仅提供构造便利（默认值），model_dump() 后必须通过对应 Schema
- extra="forbid" 与 Schema additionalProperties:false 一致
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
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
    as_of: str
    as_of_basis: str = "user_provided"
    timezone: str = "Asia/Shanghai"
    depth: Literal['fast','standard','deep'] = "standard"
    deterministic_only: bool = False
    live: bool = False
    dry_run: bool = False
    force: bool = False
    source_policy: str = "public_first"
    status: str = "planned"
    warnings: List[str] = Field(default_factory=list)
    rule_versions: Dict[str, Any] = Field(default_factory=dict)
    requested_at: str
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("requested_at")
    @classmethod
    def _requested_at_v(cls, value: str) -> str:
        return _iso(value)


class IndustryResearchRun(StrictModel):
    """行业研究运行记录。"""

    run_id: str
    request_id: str
    task_id: str
    industry_id: str = ""
    industry_name: str = ""
    as_of: str
    depth: Literal['fast','standard','deep'] = "standard"
    idempotency_key: str
    run_version: int = Field(1, ge=1)
    started_at: str
    finished_at: Optional[str] = None
    status: Literal['success','partial_success','degraded','insufficient_evidence','failed'] = "failed"
    stage_statuses: List[Dict[str, Any]] = Field(default_factory=list)
    artifact_paths: List[str] = Field(default_factory=list)
    input_versions: Dict[str, Any] = Field(default_factory=dict)
    model_route_summary: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = "pending"
    error_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    findings_count: int = Field(0, ge=0)
    dimensions_covered: List[str] = Field(default_factory=list)
    dimensions_missing: List[str] = Field(default_factory=list)
    evidence_quality: Dict[str, Any] = Field(default_factory=dict)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    data_degraded: bool = False
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("started_at")
    @classmethod
    def _started_at_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("finished_at")
    @classmethod
    def _finished_at_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)


class ThemeDiscoveryRequest(StrictModel):
    """主题发现请求（血缘契约：Task → Plan → Request → Run → Result）。"""

    request_id: str
    task_id: str
    theme_triggers: List[Dict[str, str]] = Field(..., min_length=1)
    as_of: str
    as_of_basis: str = "user_provided"
    timezone: str = "Asia/Shanghai"
    depth: Literal['fast','standard','deep'] = "standard"
    discovery_mode: Literal['graph_based','evidence_driven','keyword_sweep','peer_diffusion'] = "graph_based"
    industry_ids: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    live: bool = False
    dry_run: bool = False
    force: bool = False
    source_policy: str = "public_first"
    status: str = "planned"
    warnings: List[str] = Field(default_factory=list)
    rule_versions: Dict[str, Any] = Field(default_factory=dict)
    requested_at: str
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("requested_at")
    @classmethod
    def _requested_at_v(cls, value: str) -> str:
        return _iso(value)


class ThemeDiscoveryRun(StrictModel):
    """主题发现运行记录。"""

    run_id: str
    request_id: str
    task_id: str
    as_of: str
    discovery_mode: Literal['graph_based','evidence_driven','keyword_sweep','peer_diffusion'] = "graph_based"
    idempotency_key: str
    run_version: int = Field(1, ge=1)
    started_at: str
    finished_at: Optional[str] = None
    status: Literal['success','partial_success','degraded','insufficient_evidence','failed'] = "failed"
    stage_statuses: List[Dict[str, Any]] = Field(default_factory=list)
    artifact_paths: List[str] = Field(default_factory=list)
    input_versions: Dict[str, Any] = Field(default_factory=dict)
    model_route_summary: Dict[str, Any] = Field(default_factory=dict)
    validation_status: str = "pending"
    error_codes: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    themes_discovered: int = Field(0, ge=0)
    industry_ids: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    version: int = Field(1, ge=1)

    @field_validator("as_of")
    @classmethod
    def _as_of_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("started_at")
    @classmethod
    def _started_at_v(cls, value: str) -> str:
        return _iso(value)

    @field_validator("finished_at")
    @classmethod
    def _finished_at_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)
