"""文档数据模型（Phase 4 任务书 3.9.3-3/4）。

与 schemas/document_record.schema.json、document_block.schema.json 一一对应。
文档不是财务事实本身：DocumentRecord → DocumentBlock → FinancialFact/Claim/Evidence。
"""
from __future__ import annotations

from typing import Any, List, Literal, Optional

from pydantic import Field, field_validator

from research_os.models.core import StrictModel
from research_os.utils.time import validate_iso

DocumentType = Literal[
    "annual_report", "interim_report", "quarterly_report", "announcement",
    "inquiry_letter", "inquiry_response", "prospectus", "ir_record",
    "audit_report", "other",
]
StoragePolicyDoc = Literal["metadata_only", "metadata_and_excerpt", "local_file_reference"]
CopyrightStatus = Literal["statutory_filing", "user_provided", "licensed", "unknown"]
TextLayerStatus = Literal["present", "absent", "partial", "unknown"]
TableParseStatus = Literal["not_started", "success", "partial", "failed"]
OcrStatus = Literal["not_needed", "not_available", "not_started", "success", "partial", "failed"]
AuditStatusDoc = Literal["audited", "reviewed", "unaudited", "not_applicable", "unknown"]
ParseStatus = Literal["registered", "parsed", "partial", "failed", "corrected"]

BlockType = Literal[
    "text", "table", "table_row", "table_cell", "image_caption",
    "header", "footer", "note",
]
ExtractionMethod = Literal["native_text", "table_parser", "ocr", "manual"]
CorrectionStatus = Literal["unreviewed", "accepted", "corrected", "rejected"]


def _check_iso(value: Any, field: str) -> Any:
    if value is None:
        return value
    if not isinstance(value, str) or not validate_iso(value):
        raise ValueError(f"{field} 必须是合法 ISO-8601 时间字符串: {value!r}")
    return value


class BBox(StrictModel):
    x0: float
    y0: float
    x1: float
    y1: float


class DocumentRecord(StrictModel):
    """文档登记（哈希/解析状态/审计状态）。"""

    document_id: str
    company_entity_id: Optional[str] = None
    security_entity_id: Optional[str] = None
    document_type: DocumentType
    title: str
    source_id: str
    source_url: Optional[str] = None
    local_path: Optional[str] = None
    external_id: Optional[str] = None
    published_at: str
    retrieved_at: str
    report_period_end: Optional[str] = None
    fiscal_year: Optional[int] = None
    language: str = "zh-CN"
    mime_type: str
    file_size_bytes: Optional[int] = None
    sha256: str
    version_label: Optional[str] = None
    supersedes_document_id: Optional[str] = None
    storage_policy: StoragePolicyDoc
    copyright_status: CopyrightStatus
    text_layer_status: TextLayerStatus
    table_parse_status: TableParseStatus = "not_started"
    ocr_status: OcrStatus = "not_started"
    parser_name: Optional[str] = None
    parser_version: Optional[str] = None
    page_count: Optional[int] = None
    audit_status: AuditStatusDoc = "unknown"
    parse_status: ParseStatus = "registered"
    warnings: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str
    updated_at: str

    @field_validator("published_at", "retrieved_at", "created_at", "updated_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_iso(value, "时间")

    @field_validator("sha256")
    @classmethod
    def _v_sha(cls, value: str) -> str:
        if not isinstance(value, str) or len(value) != 64 or not all(c in "0123456789abcdef" for c in value):
            raise ValueError(f"sha256 必须为 64 位十六进制: {value!r}")
        return value


class DocumentBlock(StrictModel):
    """可定位的证据块（文本/表格/单元格，含纠错状态）。"""

    block_id: str
    document_id: str
    block_type: BlockType
    page_start: int = Field(..., ge=1)
    page_end: int = Field(..., ge=1)
    bbox: Optional[BBox] = None
    sequence_no: int = Field(0, ge=0)
    section_path: List[str] = Field(default_factory=list)
    content_excerpt: Optional[str] = None
    content_hash: str
    table_id: Optional[str] = None
    row_index: Optional[int] = None
    column_index: Optional[int] = None
    normalized_payload: Optional[dict] = None
    extraction_method: ExtractionMethod
    confidence: Optional[float] = Field(None, ge=0, le=1)
    correction_status: CorrectionStatus = "unreviewed"
    correction_of_block_id: Optional[str] = None
    source_id: str
    evidence_ids: List[str] = Field(default_factory=list)
    version: int = 1
    created_at: str

    @field_validator("created_at")
    @classmethod
    def _v_time(cls, value: Any) -> Any:
        return _check_iso(value, "时间")

    @field_validator("page_end")
    @classmethod
    def _v_page(cls, value: int, info: Any) -> int:
        page_start = info.data.get("page_start")
        if page_start is not None and value < page_start:
            raise ValueError("page_end 不得小于 page_start")
        return value
