"""财务数据模型（Phase 4 任务书 3.9.3-5/6/7/8）。

FinancialReport → FinancialFact → FinancialMetric 三层结构。
财务数值使用十进制定点字符串（Decimal 序列化），不得用二进制浮点保存原始财务值。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.decimal import normalize_decimal_string
from research_os.utils.time import validate_iso

SourceKind = Literal["manual_import", "disclosure_extraction", "verified_automatic"]
FileFormat = Literal["csv", "json", "xlsx", "pdf_extraction"]
ManifestValidationStatus = Literal["pending", "accepted", "partial", "rejected"]

ReportType = Literal["annual", "interim", "q1", "q3", "other"]
FiscalPeriod = Literal["FY", "H1", "Q1", "Q3", "OTHER"]
StatementScope = Literal["consolidated", "parent"]
AccountingStandard = Literal["CAS", "IFRS", "OTHER"]
AuditStatusFin = Literal["audited", "reviewed", "unaudited", "unknown"]
AuditOpinion = Literal["unmodified", "qualified", "adverse", "disclaimer", "not_applicable", "unknown"]
RestatementStatus = Literal["original", "restated", "superseded"]
DataStatus = Literal["complete", "partial", "failed"]

StatementType = Literal["income_statement", "balance_sheet", "cash_flow", "equity_statement", "note", "operating_data"]
InstantOrDuration = Literal["instant", "duration"]
PeriodBasis = Literal["reported_period", "ytd", "single_quarter", "ttm"]
ValueStatus = Literal["reported", "derived_from_report", "missing", "not_applicable", "conflict"]
SignConvention = Literal["reported", "debit_positive", "credit_positive"]

MetricPeriodBasis = Literal["annual", "interim", "single_quarter", "ttm", "point_in_time"]
MetricStatus = Literal["valid", "missing", "not_applicable", "zero_denominator", "conflict", "insufficient_sample"]
SectorApplicability = Literal["general", "non_financial", "financial", "cyclical"]
MetricInputPeriodRole = Literal["current", "start", "end", "comparable"]


def _check_time(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"{field} 必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


def _check_date(value: Any, field: str) -> Any:
    if value is None:
        return value
    import re
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        raise ValueError(f"{field} 必须是 YYYY-MM-DD 日期: {value!r}")
    return value


def _check_decimal(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str):
        raise ValueError(f"{field} 必须是十进制字符串: {value!r}")
    try:
        return normalize_decimal_string(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是有限十进制字符串: {value!r}") from exc


class FinancialDataManifest(StrictModel):
    """一次财务数据导入或抽取批次。"""

    manifest_id: str
    source_kind: SourceKind
    source_id: str
    file_name: str
    file_format: FileFormat
    file_checksum: str
    imported_at: str
    imported_by: str
    company_entity_ids: List[str] = Field(default_factory=list)
    document_ids: List[str] = Field(default_factory=list)
    report_period_start: Optional[str] = None
    report_period_end: Optional[str] = None
    default_statement_scope: Literal["consolidated", "parent", "unknown"] = "unknown"
    default_currency: Optional[str] = None
    default_unit_scale: Optional[int] = None
    row_count: int = Field(0, ge=0)
    accepted_count: int = Field(0, ge=0)
    rejected_count: int = Field(0, ge=0)
    data_version: str
    validation_status: ManifestValidationStatus = "pending"
    validation_errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    source_ids: List[str] = Field(default_factory=list)
    version: int = 1

    @field_validator("imported_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "imported_at")

    @field_validator("report_period_start", "report_period_end")
    @classmethod
    def _v_date(cls, value: Any) -> Any:
        return _check_date(value, "报告期")

    @field_validator("default_currency")
    @classmethod
    def _v_currency(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and (len(value) != 3 or not value.isalpha() or not value.isupper()):
            raise ValueError(f"币种必须为 ISO 4217 三位大写: {value!r}")
        return value


class FinancialReport(StrictModel):
    """一份定期报告的标准元数据。"""

    financial_report_id: str
    company_entity_id: str
    document_id: Optional[str] = None
    manifest_id: Optional[str] = None
    report_type: ReportType
    period_start: str
    period_end: str
    fiscal_year: int
    fiscal_period: FiscalPeriod
    duration_months: int = Field(..., ge=1)
    statement_scope: StatementScope
    accounting_standard: AccountingStandard = "CAS"
    currency: str
    unit_scale: int
    audit_status: AuditStatusFin = "unknown"
    audit_opinion: AuditOpinion = "unknown"
    restatement_status: RestatementStatus = "original"
    supersedes_report_id: Optional[str] = None
    filing_version: str
    source_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    data_status: DataStatus = "complete"
    version: int = 1
    published_at: str
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"company_entity_id 必须以 company: 开头: {value!r}")
        return value

    @field_validator("period_start", "period_end")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "报告期")

    @field_validator("published_at", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha() or not value.isupper():
            raise ValueError(f"币种必须为 ISO 4217 三位大写: {value!r}")
        return value


class FinancialFact(StrictModel):
    """一个标准科目在确定期间和口径下的值。"""

    fact_id: str
    fact_key: str
    financial_report_id: str
    company_entity_id: str
    statement_type: StatementType
    taxonomy_code: str
    label_raw: str
    period_start: Optional[str] = None
    period_end: str
    instant_or_duration: InstantOrDuration
    period_basis: PeriodBasis = "reported_period"
    statement_scope: StatementScope
    currency: str
    unit_scale: int
    raw_value: Optional[str] = None
    normalized_value: Optional[str] = None
    normalized_unit: str
    value_status: ValueStatus = "reported"
    sign_convention: SignConvention = "reported"
    audit_status: AuditStatusFin = "unknown"
    segment_id: Optional[str] = None
    source_document_id: Optional[str] = None
    source_block_ids: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    source_priority: int = Field(..., ge=1, le=6)
    restatement_version: int = Field(1, ge=1)
    valid_from: str
    valid_to: Optional[str] = None
    conflict_group_id: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"company_entity_id 必须以 company: 开头: {value!r}")
        return value

    @field_validator("period_end")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "period_end")

    @field_validator("raw_value", "normalized_value")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "财务值")

    @field_validator("valid_from", "created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "时间")

    @field_validator("currency")
    @classmethod
    def _v_currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha() or not value.isupper():
            raise ValueError(f"币种必须为 ISO 4217 三位大写: {value!r}")
        return value


class FinancialMetricInputBinding(StrictModel):
    """公式命名参数到原始事实的不可歧义绑定。"""

    parameter: str
    fact_id: str
    company_entity_id: str
    financial_report_id: str
    taxonomy_code: str
    statement_scope: StatementScope
    statement_type: StatementType
    period_start: Optional[str] = None
    period_end: str
    period_role: MetricInputPeriodRole
    currency: str
    unit_scale: int

    @field_validator("period_start", "period_end")
    @classmethod
    def _v_period(cls, value: Optional[str]) -> Optional[str]:
        return _check_date(value, "input_binding.period")

    @field_validator("company_entity_id")
    @classmethod
    def _v_binding_company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"input_binding.company_entity_id 非法: {value!r}")
        return value

    @field_validator("currency")
    @classmethod
    def _v_binding_currency(cls, value: str) -> str:
        if len(value) != 3 or not value.isalpha() or not value.isupper():
            raise ValueError(f"input_binding.currency 非法: {value!r}")
        return value


class FinancialMetric(StrictModel):
    """确定性派生财务指标（公式可复算，输入血缘完整）。"""

    metric_id: str
    company_entity_id: str
    metric_code: str
    period_end: str
    period_basis: MetricPeriodBasis
    value: Optional[str] = None
    unit: str
    status: MetricStatus = "valid"
    formula_id: str
    formula_version: str
    input_fact_ids: List[str] = Field(default_factory=list)
    input_bindings: List[FinancialMetricInputBinding] = Field(default_factory=list)
    input_metric_ids: List[str] = Field(default_factory=list)
    precision: int = Field(4, ge=0)
    sector_applicability: SectorApplicability = "general"
    quality_warnings: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
    calculated_at: str
    version: int = 1

    @field_validator("company_entity_id")
    @classmethod
    def _v_company(cls, value: str) -> str:
        if not value.startswith("company:"):
            raise ValueError(f"company_entity_id 必须以 company: 开头: {value!r}")
        return value

    @field_validator("period_end")
    @classmethod
    def _v_date(cls, value: str) -> str:
        return _check_date(value, "period_end")

    @field_validator("value")
    @classmethod
    def _v_decimal(cls, value: Any) -> Any:
        return _check_decimal(value, "指标值")

    @field_validator("calculated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_time(value, "calculated_at")
