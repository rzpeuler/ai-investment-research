"""来源层数据模型（Phase 1）：Source / SourceProbe / DataRoute。

与 schemas/source.schema.json / source_probe.schema.json / data_route.schema.json
一一对应。遵循 schema-model-contract：模型负责构造，dump 后必须通过 Schema。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

AccessLevel = Literal[
    "public", "public_but_unstable", "login_required", "client_only",
    "paid", "manual_only", "unavailable", "unknown",
]
AutomationLevel = Literal[
    "api", "html", "browser", "export_import", "manual", "none", "unknown",
]
StoragePolicy = Literal["metadata_only", "metadata_and_excerpt", "full_text_allowed", "unknown"]
SourceStatus = Literal["candidate", "approved", "watchlist", "deprecated", "blocked"]
SourceTier = Literal["S", "A", "B", "C", "D"]
ProbeStatus = Literal["success", "partial", "blocked", "login_required", "failed"]
RouteStatus = Literal["success", "degraded", "insufficient_data", "failed"]


def _iso_opt(value: Optional[str]) -> Optional[str]:
    if value is not None:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


class Source(StrictModel):
    """来源注册表条目。分数均为 0-5 整数。"""

    source_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    platform: str = Field(..., min_length=1)
    base_domain: Optional[str] = Field(None, description="无域名的客户端/手动来源可为 null")
    source_type: str = Field(..., min_length=1)
    source_tier: SourceTier = "B"
    authority_score: int = Field(0, ge=0, le=5)
    accuracy_score: int = Field(0, ge=0, le=5)
    timeliness_score: int = Field(0, ge=0, le=5)
    coverage_score: int = Field(0, ge=0, le=5)
    stability_score: int = Field(0, ge=0, le=5)
    originality_score: int = Field(0, ge=0, le=5)
    opinion_influence_score: int = Field(0, ge=0, le=5)
    access_level: AccessLevel = "unknown"
    automation_level: AutomationLevel = "unknown"
    login_required: bool = False
    paid: bool = False
    storage_policy: StoragePolicy = "metadata_and_excerpt"
    rate_limit: Optional[str] = None
    update_frequency: str = "unknown"
    allowed_usage: str = "unknown"
    primary_topics: List[str] = Field(default_factory=list)
    status: SourceStatus = "candidate"
    last_verified_at: Optional[str] = None
    verification_evidence: List[str] = Field(default_factory=list)
    notes: str = ""

    @field_validator("last_verified_at")
    @classmethod
    def _v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)


class SourceProbe(StrictModel):
    """来源探测结果。"""

    probe_id: str
    source_id: str = Field(..., min_length=1)
    started_at: str
    finished_at: str
    status: ProbeStatus = "failed"
    http_status: Optional[int] = None
    access_level_detected: AccessLevel = "unknown"
    automation_level_detected: AutomationLevel = "unknown"
    historical_depth: Optional[str] = None
    fields_detected: List[str] = Field(default_factory=list)
    requires_javascript: bool = False
    requires_login: bool = False
    rate_limit_observed: Optional[str] = None
    storage_policy_recommendation: StoragePolicy = "metadata_and_excerpt"
    evidence: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)

    @field_validator("started_at", "finished_at")
    @classmethod
    def _iso(cls, value: str) -> str:
        if not validate_iso(value):
            raise ValueError(f"必须是合法 ISO-8601 时间字符串: {value!r}")
        return value


class DataRoute(StrictModel):
    """数据获取路由结果。"""

    data_type: str = Field(..., min_length=1)
    requested_sources: List[str] = Field(default_factory=list)
    attempted_sources: List[str] = Field(default_factory=list)
    selected_source: Optional[str] = None
    fallback_used: bool = False
    status: RouteStatus = "failed"
    missing_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ManualInbox(StrictModel):
    """人工 Inbox 条目（任务 9.1）。用户摘录不自动视为事实。"""

    inbox_id: str
    source_name: str = Field(..., min_length=1)
    source_url: str
    title: str = Field(..., min_length=1)
    published_at: Optional[str] = None
    submitted_at: str
    submitted_by: str = "user"
    content_excerpt: str = ""
    notes: str = ""
    intended_entities: List[str] = Field(default_factory=list)
    status: Literal["submitted", "parsed", "accepted", "rejected", "needs_review"] = "submitted"
    url_accessible: bool = True

    @field_validator("source_url")
    @classmethod
    def _url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parts = urlsplit(value.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            raise ValueError(f"source_url 必须是 http/https URL: {value!r}")
        return value.strip()

    @field_validator("published_at", "submitted_at")
    @classmethod
    def _iso_opt_v(cls, value: Optional[str]) -> Optional[str]:
        return _iso_opt(value)
