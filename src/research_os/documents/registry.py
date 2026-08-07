"""文档解析底座（Phase 4 任务书 3.7/Commit 4）。

文档不是财务事实本身：DocumentRecord → DocumentBlock → FinancialFact/Claim/Evidence。
规则：
- 文件哈希（SHA-256）与去重；页面定位；文本块/表格块/单元格；
- 先检查原生文本层；无文本层或指定失败页才用 OCR；OCR 输出默认 unreviewed；
- 低置信数字不得直接进入有效 FACT；
- 人工纠错保留前后值和纠错记录（correction_of_block_id），不覆盖历史；
- 不保存不必要全文（metadata_and_excerpt 边界）。
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.models.documents import (
    DocumentBlock,
    DocumentRecord,
)
from research_os.utils.time import now_iso

# 简单 PDF 原生文本层探测：检查文件头部是否含 /Font 或 /Text 等标记。
# 完整 PDF 解析（pypdf）为可选依赖；未安装时 text_layer_status=unknown 并如实记录。
PDF_TEXT_MARKERS = [b"/Font", b"/Text", b"/Contents"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _probe_pdf_text_layer(path: Path) -> str:
    """探测 PDF 原生文本层：present / absent / unknown。"""
    try:
        with Path(path).open("rb") as fh:
            head = fh.read(4096)
            rest = fh.read(65536)
        blob = head + rest
    except OSError:
        return "unknown"
    if any(m in blob for m in PDF_TEXT_MARKERS):
        return "present"
    return "absent"


def register_document(
    path: Path,
    *,
    document_type: str,
    source_id: str,
    title: str,
    published_at: str,
    company_entity_id: Optional[str] = None,
    security_entity_id: Optional[str] = None,
    report_period_end: Optional[str] = None,
    fiscal_year: Optional[int] = None,
    mime_type: Optional[str] = None,
    storage_policy: str = "metadata_and_excerpt",
    copyright_status: str = "user_provided",
    parser_name: Optional[str] = None,
    parser_version: Optional[str] = None,
    audit_status: str = "unknown",
) -> DocumentRecord:
    """登记一个文档文件为 DocumentRecord（不解析内容）。"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在: {path}")

    sha = sha256_file(path)
    size = path.stat().st_size
    mt = mime_type or _guess_mime(path)
    text_layer = "present" if mt == "text/html" else _probe_pdf_text_layer(path)
    ts = now_iso()

    return DocumentRecord(
        document_id="",  # 由调用方在持久化时分配或由 pipeline 分配
        company_entity_id=company_entity_id,
        security_entity_id=security_entity_id,
        document_type=document_type,  # type: ignore[arg-type]
        title=title,
        source_id=source_id,
        source_url=None,
        local_path=str(path),
        external_id=None,
        published_at=published_at,
        retrieved_at=ts,
        report_period_end=report_period_end,
        fiscal_year=fiscal_year,
        language="zh-CN",
        mime_type=mt,
        file_size_bytes=size,
        sha256=sha,
        version_label=None,
        supersedes_document_id=None,
        storage_policy=storage_policy,  # type: ignore[arg-type]
        copyright_status=copyright_status,  # type: ignore[arg-type]
        text_layer_status=text_layer,  # type: ignore[arg-type]
        table_parse_status="not_started",
        ocr_status="not_started",
        parser_name=parser_name,
        parser_version=parser_version,
        page_count=None,
        audit_status=audit_status,  # type: ignore[arg-type]
        parse_status="registered",
        warnings=[],
        version=1,
        created_at=ts,
        updated_at=ts,
    )


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in (".html", ".htm"):
        return "text/html"
    if suffix == ".txt":
        return "text/plain"
    if suffix == ".csv":
        return "text/csv"
    return "application/octet-stream"


def parse_native_text(path: Path, document_id: str, source_id: str) -> List[DocumentBlock]:
    """解析 HTML/TXT 原生文本层为文本块（每段一个块，带页码=1 与行号）。"""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    # 去 HTML 标签（简单实现；结构化 HTML 解析不属于本阶段范围）
    text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    blocks: List[DocumentBlock] = []
    sentences = [s.strip() for s in re.split(r"[。；\n]", text) if s.strip()]
    ts = now_iso()
    for i, sentence in enumerate(sentences[:500]):  # 限制块数，防超长文档
        blocks.append(DocumentBlock(
            block_id="",
            document_id=document_id,
            block_type="text",
            page_start=1,
            page_end=1,
            bbox=None,
            sequence_no=i,
            section_path=[],
            content_excerpt=sentence[:2000],
            content_hash=hashlib.sha256(sentence.encode("utf-8")).hexdigest(),
            table_id=None,
            row_index=None,
            column_index=None,
            normalized_payload=None,
            extraction_method="native_text",
            confidence=None,
            correction_status="unreviewed",
            correction_of_block_id=None,
            source_id=source_id,
            evidence_ids=[],
            version=1,
            created_at=ts,
        ))
    return blocks


def parse_pdf_text(path: Path, document_id: str, source_id: str) -> List[DocumentBlock]:
    """使用可选 pypdf 提取原生文本层；缺依赖或解析失败时明确返回空列表。"""
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
    except Exception:  # noqa: BLE001 —— 可选解析能力失败由调用方标记 partial
        return []
    blocks: List[DocumentBlock] = []
    created_at = now_iso()
    sequence = 0
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            continue
        text = re.sub(r"\s+", " ", text).strip()
        for offset in range(0, len(text), 1800):
            excerpt = text[offset:offset + 1800].strip()
            if not excerpt:
                continue
            blocks.append(DocumentBlock(
                block_id="", document_id=document_id, block_type="text",
                page_start=page_number, page_end=page_number, bbox=None,
                sequence_no=sequence, section_path=[], content_excerpt=excerpt,
                content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
                table_id=None, row_index=None, column_index=None,
                normalized_payload={
                    "locator_kind": "text_offset", "text_start": offset,
                    "text_end": offset + len(excerpt),
                },
                extraction_method="native_text", confidence=None,
                correction_status="unreviewed", correction_of_block_id=None,
                source_id=source_id, evidence_ids=[], version=1,
                created_at=created_at,
            ))
            sequence += 1
            if sequence >= 1000:
                return blocks
    return blocks


def parse_table_blocks(path: Path, document_id: str, source_id: str) -> List[DocumentBlock]:
    """解析 CSV 为表格块（每行为 table_row，表头为 table）。"""
    import csv as _csv

    path = Path(path)
    blocks: List[DocumentBlock] = []
    ts = now_iso()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = _csv.reader(fh)
        rows = list(reader)
    if not rows:
        return blocks
    header = rows[0]
    blocks.append(DocumentBlock(
        block_id="",
        document_id=document_id,
        block_type="table",
        page_start=1,
        page_end=1,
        bbox=None,
        sequence_no=0,
        section_path=[],
        content_excerpt=",".join(header)[:2000],
        content_hash=hashlib.sha256(",".join(header).encode("utf-8")).hexdigest(),
        table_id="t1",
        row_index=None,
        column_index=None,
        normalized_payload={"header": header},
        extraction_method="table_parser",
        confidence=1.0,
        correction_status="unreviewed",
        correction_of_block_id=None,
        source_id=source_id,
        evidence_ids=[],
        version=1,
        created_at=ts,
    ))
    for i, row in enumerate(rows[1:], start=1):
        blocks.append(DocumentBlock(
            block_id="",
            document_id=document_id,
            block_type="table_row",
            page_start=1,
            page_end=1,
            bbox=None,
            sequence_no=i,
            section_path=[],
            content_excerpt=",".join(row)[:2000],
            content_hash=hashlib.sha256(",".join(row).encode("utf-8")).hexdigest(),
            table_id="t1",
            row_index=i,
            column_index=None,
            normalized_payload={"cells": row},
            extraction_method="table_parser",
            confidence=1.0,
            correction_status="unreviewed",
            correction_of_block_id=None,
            source_id=source_id,
            evidence_ids=[],
            version=1,
            created_at=ts,
        ))
    return blocks


def ocr_protocol(path: Path, document_id: str, source_id: str) -> List[DocumentBlock]:
    """OCR 协议层：Phase 4 只登记协议与状态，不实施通用 OCR。

    返回空列表并如实标记 ocr_status（由调用方在 DocumentRecord 上设置）。
    低置信结果不得自动批准进入有效 FACT。
    """
    return []


def apply_correction(
    original: DocumentBlock,
    *,
    corrected_excerpt: str,
    source_id: str,
    confidence: Optional[float] = None,
) -> DocumentBlock:
    """人工纠错：生成新版本块（correction_of_block_id 指向原块），不覆盖历史。"""
    ts = now_iso()
    new_block = original.model_copy(deep=True)
    new_block.block_id = ""  # 由调用方分配
    new_block.correction_status = "corrected"
    new_block.correction_of_block_id = original.block_id
    new_block.content_excerpt = corrected_excerpt
    new_block.content_hash = hashlib.sha256(corrected_excerpt.encode("utf-8")).hexdigest()
    new_block.extraction_method = "manual"
    if confidence is not None:
        new_block.confidence = confidence
    new_block.source_id = source_id
    new_block.created_at = ts
    new_block.version = original.version + 1
    return new_block


def evidence_locator(block: DocumentBlock) -> Dict[str, Any]:
    """由 block 生成证据定位信息（页码/表格/行列/摘录/哈希）。"""
    return {
        "block_id": block.block_id,
        "document_id": block.document_id,
        "page_start": block.page_start,
        "page_end": block.page_end,
        "table_id": block.table_id,
        "row_index": block.row_index,
        "column_index": block.column_index,
        "content_excerpt": block.content_excerpt,
        "content_hash": block.content_hash,
        "extraction_method": block.extraction_method,
        "correction_status": block.correction_status,
        "confidence": block.confidence,
    }
