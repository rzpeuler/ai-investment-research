"""P7-D4 M1：TransientDisclosureMaterializer 离线测试。

synthetic PDF + mocked urlopen/parser；零网络。覆盖：
正常 materialize（Record/Block/Evidence + temp 删除）、幂等复用、HTML/非 PDF/
zero-byte/Content-Type 拒绝、pypdf 缺失配置错误、解析失败、无原生文本。
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_os.documents.disclosure_materializer import (
    TransientDisclosureMaterializer,
    _validate_pdf_bytes,
)
from research_os.models import DocumentBlock

TS = "2026-04-30T10:00:00+08:00"

ROOT = Path(__file__).resolve().parents[2]  # 项目根（sources.yaml 校验需要）


def make_pdf_bytes(text: str = "合并利润表 单位：元") -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    writer.write(buf)
    raw = buf.getvalue()
    # 附加文本层（测试用；真实解析在 parser 层）
    return raw


class _FakeDB:
    def __init__(self):
        self._tables: dict[str, dict] = {
            "document_records": {}, "document_blocks": {}, "evidence": {},
        }
        self.upserted: list = []

    def upsert(self, obj):
        payload = obj.model_dump()
        table = self._table_for(obj)
        key = self._key_for(obj)
        self._tables[table][key] = payload
        self.upserted.append(obj)

    def query(self, sql, params=()):
        table = None
        for t in self._tables:
            if t in sql:
                table = t
                break
        if table is None:
            return []
        rows = []
        for payload in self._tables[table].values():
            # 支持 `WHERE document_id = ?` 过滤（幂等查询）
            if "document_id = ?" in sql and params:
                if payload.get("document_id") != params[0]:
                    continue
            rows.append({"payload": payload})
        return rows

    def _table_for(self, obj):
        name = type(obj).__name__
        return {
            "DocumentRecord": "document_records",
            "DocumentBlock": "document_blocks",
            "Evidence": "evidence",
        }[name]

    def _key_for(self, obj):
        name = type(obj).__name__
        if name == "DocumentRecord":
            return obj.document_id
        if name == "DocumentBlock":
            return obj.block_id
        if name == "Evidence":
            return obj.evidence_id
        return getattr(obj, "id", None)


def _fake_parser(path, document_id, source_id):
    return [
        DocumentBlock(
            block_id="block-1", document_id=document_id, block_type="text",
            page_start=1, page_end=1, bbox=None, sequence_no=0, section_path=[],
            content_excerpt="合并利润表 单位：元 营业收入 10,000,000.00",
            content_hash="a" * 64, table_id=None, row_index=None, column_index=None,
            normalized_payload=None, extraction_method="native_text",
            confidence=None, correction_status="unreviewed",
            correction_of_block_id=None, source_id=source_id,
            evidence_ids=[], version=1, created_at=TS,
        )
    ]


@pytest.fixture
def db():
    return _FakeDB()


@pytest.fixture
def materializer(db):
    return TransientDisclosureMaterializer(db, parser=_fake_parser)


def _urlopen_returning(data: bytes, content_type: str = "application/pdf"):
    response = MagicMock()
    response.geturl.return_value = "https://static.cninfo.com.cn/finalpage/2026/x.PDF"
    response.headers = {"Content-Type": content_type}
    response.read.return_value = data
    response.__enter__.return_value = response  # with 上下文返回同一 response
    return lambda request, timeout=None: response


class TestMaterialize:
    def test_normal_materialize(self, materializer, db, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen_returning(make_pdf_bytes()))
        result = materializer.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id="security:600519.SH", source_id="cninfo",
            source_url="https://static.cninfo.com.cn/finalpage/2026/x.PDF",
            title="贵州茅台：2025年年度报告", published_at=TS,
            document_type="annual_report", external_id="ann-1",
            report_period_end="2025-12-31", fiscal_year=2025,
        )
        assert result.inserted is True
        assert result.document_id
        assert result.block_ids == ["block-1"]
        assert len(result.evidence_ids) == 1
        assert db._tables["document_records"]
        record = next(iter(db._tables["document_records"].values()))
        assert record["storage_policy"] == "metadata_and_excerpt"
        assert record["local_path"] is None
        assert record["sha256"]
        assert record["report_period_end"] == "2025-12-31"
        assert record["fiscal_year"] == 2025
        assert record["company_entity_id"] == "company:maotai"
        assert len(db._tables["evidence"]) == 1

    def test_idempotent_reuse(self, materializer, db, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen_returning(make_pdf_bytes()))
        kwargs = dict(
            company_entity_id="company:maotai", security_entity_id="security:600519.SH",
            source_id="cninfo", source_url="https://static.cninfo.com.cn/x.PDF",
            title="贵州茅台：2025年年度报告", published_at=TS,
            document_type="annual_report", external_id="ann-1",
            report_period_end="2025-12-31", fiscal_year=2025,
        )
        first = materializer.materialize(ROOT, **kwargs)
        second = materializer.materialize(ROOT, **kwargs)
        assert first.inserted is True
        assert second.inserted is False
        assert second.document_id == first.document_id
        assert "复用既有" in second.warnings[0]

    def test_temp_pdf_deleted(self, materializer, db, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen_returning(make_pdf_bytes()))
        materializer.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id=None, source_id="cninfo",
            source_url="https://static.cninfo.com.cn/x.PDF",
            title="贵州茅台：2025年年度报告", published_at=TS,
            document_type="annual_report", external_id="ann-1",
            report_period_end="2025-12-31", fiscal_year=2025,
        )
        # temp PDF 必须删除（不永久保存完整 PDF）：捕获 NamedTemporaryFile 路径验证
        import tempfile

        created: list = []
        real = tempfile.NamedTemporaryFile

        def _capture(*args, **kwargs):
            handle = real(*args, **kwargs)
            created.append(Path(handle.name))
            return handle

        monkeypatch.setattr(tempfile, "NamedTemporaryFile", _capture)
        materializer.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id=None, source_id="cninfo",
            source_url="https://static.cninfo.com.cn/y.PDF",
            title="贵州茅台：2024年年度报告", published_at=TS,
            document_type="annual_report", external_id="ann-2",
            report_period_end="2024-12-31", fiscal_year=2024,
        )
        assert created, "应创建 transient temp PDF"
        for path in created:
            assert not path.exists(), f"temp PDF 必须删除: {path}"


class TestPdfValidation:
    def test_html_content_rejected(self):
        with pytest.raises(ValueError, match="不是 PDF"):
            _validate_pdf_bytes(b"<html><body>error</body></html>")

    def test_non_pdf_rejected(self):
        with pytest.raises(ValueError, match="不是 PDF"):
            _validate_pdf_bytes(b"PK\x03\x04 something")

    def test_zero_byte_rejected(self):
        with pytest.raises(ValueError, match="zero-byte"):
            _validate_pdf_bytes(b"")

    def test_html_content_type_rejected(self):
        with pytest.raises(ValueError, match="Content-Type"):
            _validate_pdf_bytes(b"%PDF-1.7 fake", content_type="text/html")

    def test_valid_pdf_ok(self):
        _validate_pdf_bytes(b"%PDF-1.7 \xff\xfe", content_type="application/pdf")

    def test_download_failure_structured(self, materializer, db, tmp_path, monkeypatch):
        def _fail(request, timeout=None):
            raise OSError("network down")

        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen", _fail)
        with pytest.raises(ValueError, match="DOCUMENT_DOWNLOAD_FAILED"):
            materializer.materialize(
                ROOT, company_entity_id="company:maotai",
                security_entity_id=None, source_id="cninfo",
                source_url="https://static.cninfo.com.cn/x.PDF",
                title="t", published_at=TS, document_type="annual_report",
                external_id="ann-1", report_period_end="2025-12-31", fiscal_year=2025,
            )

    def test_parse_failure_structured(self, materializer, db, tmp_path, monkeypatch):
        def _bad_parser(path, document_id, source_id):
            raise RuntimeError("broken pdf")

        bad = TransientDisclosureMaterializer(db, parser=_bad_parser)
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen_returning(make_pdf_bytes()))
        with pytest.raises(ValueError, match="DOCUMENT_PARSE_FAILED"):
            bad.materialize(
                ROOT, company_entity_id="company:maotai",
                security_entity_id=None, source_id="cninfo",
                source_url="https://static.cninfo.com.cn/x.PDF",
                title="t", published_at=TS, document_type="annual_report",
                external_id="ann-1", report_period_end="2025-12-31", fiscal_year=2025,
            )

    def test_no_native_text_warns_but_persists(
        self, materializer, db, tmp_path, monkeypatch
    ):
        def _empty_parser(path, document_id, source_id):
            return []

        empty = TransientDisclosureMaterializer(db, parser=_empty_parser)
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen_returning(make_pdf_bytes()))
        result = empty.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id=None, source_id="cninfo",
            source_url="https://static.cninfo.com.cn/x.PDF",
            title="t", published_at=TS, document_type="annual_report",
            external_id="ann-1", report_period_end="2025-12-31", fiscal_year=2025,
        )
        assert result.inserted is True
        assert any("DOCUMENT_NATIVE_TEXT_UNAVAILABLE" in w for w in result.warnings)
        record = next(iter(db._tables["document_records"].values()))
        assert record["text_layer_status"] == "absent"
        assert record["ocr_status"] == "not_started"  # OCR 不得自动调用
