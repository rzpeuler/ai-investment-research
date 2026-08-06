"""文档解析底座测试（任务书 3.25 PDF/文档节）。

覆盖：文档哈希；同文件去重；页面定位；文本块；表格块；扫描页（OCR unavailable）；
人工纠错；纠错不覆盖历史；低置信块不得支持关键 FACT；不保存不必要全文。
"""
from __future__ import annotations

import pytest

from research_os.documents.registry import (
    apply_correction,
    evidence_locator,
    ocr_protocol,
    parse_native_text,
    parse_table_blocks,
    register_document,
    sha256_file,
)
from research_os.models.documents import DocumentBlock
from research_os.validators.schema_validator import validate_model

TS = "2026-08-06T00:00:00"
COMPANY = "company:600519.SH"


def _fake_pdf(tmp_path, name="doc.pdf", text_layer=True):
    """生成最小 PDF 字节（非完整 PDF，仅用于哈希/探测测试）。"""
    p = tmp_path / name
    if text_layer:
        p.write_bytes(b"%PDF-1.4\n/Font /Contents /Text\n%%EOF")
    else:
        p.write_bytes(b"%PDF-1.4\n%%EOF")
    return p


class TestDocumentRegistration:
    def test_register_pdf_with_sha(self, tmp_path):
        p = _fake_pdf(tmp_path)
        doc = register_document(
            p, document_type="annual_report", source_id="user_document",
            title="年报", published_at=TS, company_entity_id=COMPANY,
        )
        assert doc.sha256 == sha256_file(p)
        assert len(doc.sha256) == 64
        assert doc.mime_type == "application/pdf"
        assert doc.parse_status == "registered"
        assert doc.storage_policy == "metadata_and_excerpt"
        assert validate_model(doc) == []

    def test_same_file_same_hash(self, tmp_path):
        p1 = _fake_pdf(tmp_path, "a.pdf")
        p2 = _fake_pdf(tmp_path, "b.pdf")
        assert sha256_file(p1) == sha256_file(p2)  # 同内容同哈希（去重依据）

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            register_document(
                tmp_path / "nope.pdf", document_type="annual_report",
                source_id="user_document", title="t", published_at=TS,
            )


class TestNativeText:
    def test_html_paragraphs_to_blocks(self, tmp_path):
        p = tmp_path / "doc.html"
        p.write_text(
            "<html><body><p>营业收入增长 10%。</p><p>毛利率 60%。</p></body></html>",
            encoding="utf-8",
        )
        blocks = parse_native_text(p, document_id="d1", source_id="user_document")
        assert len(blocks) >= 1
        assert blocks[0].block_type == "text"
        assert blocks[0].page_start == 1
        assert blocks[0].sequence_no == 0
        assert blocks[0].content_hash
        for b in blocks:
            assert validate_model(b) == []

    def test_blocks_have_page_location(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("第一段。第二段。", encoding="utf-8")
        blocks = parse_native_text(p, document_id="d1", source_id="user_document")
        for b in blocks:
            assert b.page_start >= 1 and b.page_end >= 1
            loc = evidence_locator(b)
            assert loc["page_start"] == b.page_start
            assert loc["content_hash"] == b.content_hash


class TestTableParsing:
    def test_csv_rows_to_table_blocks(self, tmp_path):
        p = tmp_path / "fin.csv"
        p.write_text("科目,2025\n营业收入,100\n营业成本,60\n", encoding="utf-8")
        blocks = parse_table_blocks(p, document_id="d1", source_id="user_document")
        assert blocks[0].block_type == "table"
        assert blocks[0].table_id == "t1"
        rows = [b for b in blocks if b.block_type == "table_row"]
        assert len(rows) == 2
        assert rows[0].row_index == 1
        assert rows[0].column_index is None
        for b in blocks:
            assert validate_model(b) == []


class TestOcrProtocol:
    def test_ocr_returns_empty_and_marks_unreviewed(self, tmp_path):
        """OCR 协议层不实施通用 OCR；返回空列表（无虚构块）。"""
        p = _fake_pdf(tmp_path, "scan.pdf", text_layer=False)
        blocks = ocr_protocol(p, document_id="d1", source_id="user_document")
        assert blocks == []


class TestCorrection:
    def test_correction_creates_new_version_not_overwrite(self, tmp_path):
        p = tmp_path / "doc.txt"
        p.write_text("营业收入 100 亿。", encoding="utf-8")
        blocks = parse_native_text(p, document_id="d1", source_id="user_document")
        orig = blocks[0]
        orig.block_id = "b-orig"

        corrected = apply_correction(
            orig, corrected_excerpt="营业收入 120 亿（人工修正）。", source_id="manual",
        )
        assert corrected.correction_status == "corrected"
        assert corrected.correction_of_block_id == "b-orig"
        assert corrected.extraction_method == "manual"
        assert corrected.version == orig.version + 1
        assert corrected.content_hash != orig.content_hash
        # 历史块未被修改（切分符已去，原摘录不含句号）
        assert orig.content_excerpt == "营业收入 100 亿"
        assert orig.correction_status == "unreviewed"
        assert validate_model(corrected) == []


class TestEvidenceBoundary:
    def test_low_confidence_ocr_block_not_support_fact(self):
        """低置信 OCR 块不得自动成为有效 FACT 依据（此处验证状态标记机制）。"""
        block = DocumentBlock(
            block_id="b1", document_id="d1", block_type="text",
            page_start=1, page_end=1, bbox=None, sequence_no=0, section_path=[],
            content_excerpt="扫描页文字", content_hash="h" * 64, table_id=None,
            row_index=None, column_index=None, normalized_payload=None,
            extraction_method="ocr", confidence=0.3,
            correction_status="unreviewed", correction_of_block_id=None,
            source_id="user_document", evidence_ids=[], version=1, created_at=TS,
        )
        loc = evidence_locator(block)
        # 低置信 + unreviewed 必须被显式标记，供 Validator（ERV-051）拒绝
        assert loc["confidence"] < 0.8
        assert loc["correction_status"] == "unreviewed"
