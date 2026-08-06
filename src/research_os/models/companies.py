"""公司与证券主数据模型（Phase 4 任务书 3.9.3-1/2）。

Entity(company) → CompanyProfile；Entity(security) → SecurityProfile(company_entity_id)。
Company 与 Security 分离：证券映射到公司主体，不得混淆。
"""
from __future__ import annotations

import re
from typing import Any, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MMDD_RE = re.compile(r"^\d{2}-\d{2}$")
SYMBOL_RE = re.compile(r"^\d{6}\.(SH|SZ|BJ)$")

OwnershipType = Literal[
    "state_owned", "central_state_owned", "local_state_owned", "private",
    "foreign_invested", "collective", "mixed", "unknown",
]
ProfileStatus = Literal["active", "superseded", "incomplete"]

Exchange = Literal["SH", "SZ", "BJ"]
Board = Literal["main", "gem", "star", "beijing", "other"]
SecurityType = Literal["common_share", "preferred_share", "convertible_bond", "other"]
SecurityStatus = Literal["listed", "suspended", "delisted", "unknown"]


def _check_time(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"{field} 必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


def _check_date(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD 日期: {value!r}")
    return value


def _check_currency(value: str) -> str:
    if len(value) != 3 or not value.isalpha() or not value.isupper():
        raise ValueError(f"币种必须为 ISO 4217 三位大写: {value!r}")
    return value


class CompanyProfile(StrictModel):
    """公司主体在某有效期内的主数据。"""

    company_profile_id: str
    entity_id: str
    canonical_name: str
    unified_social_credit_code: Optional[str] = None
    registered_address: Optional[str] = None
    industry_ids: List[str] = Field(default_factory=list)
    business_description: str = ""
    fiscal_year_end: str
    reporting_currency: str
    ownership_type: OwnershipType
    controlling_shareholder_entity_id: Optional[str] = None
    actual_controller_entity_ids: List[str] = Field(default_factory=list)
    valid_from: str
    valid_to: Optional[str] = None
    source_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    status: ProfileStatus = "active"
    version: int = 1
    created_at: str
    updated_at: str

    @field_validator("entity_id")
    @classmethod
    def _v_entity(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"entity_id 必须以 company: 开头: {value!r}")
        return value

    @field_validator("fiscal_year_end")
    @classmethod
    def _v_fye(cls, value: str) -> str:
        if not isinstance(value, str) or not MMDD_RE.match(value):
            raise ValueError(f"fiscal_year_end 必须为 MM-DD: {value!r}")
        return value

    @field_validator("reporting_currency")
    @classmethod
    def _v_currency(cls, value: str) -> str:
        return _check_currency(value)

    @field_validator("valid_from")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "valid_from")

    @field_validator("created_at", "updated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")


class FormerName(StrictModel):
    name: str
    valid_from: str
    valid_to: Optional[str] = None

    @field_validator("valid_from")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "valid_from")


class SecurityProfile(StrictModel):
    """证券与公司主体的映射。"""

    security_profile_id: str
    security_entity_id: str
    company_entity_id: str
    symbol: str
    exchange: Exchange
    board: Board
    security_type: SecurityType
    listing_date: str
    delisting_date: Optional[str] = None
    currency: str
    share_class: str
    current_name: str
    former_names: List[FormerName] = Field(default_factory=list)
    status: SecurityStatus = "listed"
    source_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str
    updated_at: str

    @field_validator("security_entity_id")
    @classmethod
    def _v_security(cls, value: str) -> str:
        if not value.startswith("security:"):
            raise ValueError(f"security_entity_id 必须以 security: 开头: {value!r}")
        return value

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"company_entity_id 必须以 company: 开头: {value!r}")
        return value

    @field_validator("symbol")
    @classmethod
    def _v_symbol(cls, value: str) -> str:
        if not isinstance(value, str) or not SYMBOL_RE.match(value):
            raise ValueError(f"symbol 必须为 6 位数字+交易所后缀: {value!r}")
        return value

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, value: str) -> str:
        return _check_currency(value)

    @field_validator("listing_date")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "listing_date")

    @field_validator("created_at", "updated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")
