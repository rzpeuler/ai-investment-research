"""P7-D4 M2：DerivationPrerequisiteResolver 离线测试（taskbook §19 的 11 项证明）。

ZERO NETWORK / ZERO WRITE（resolver 只读）。覆盖：全合格、subject 缺失、
非 annual、未来披露、period 缺失、非 cninfo、无原生文本、无 block、缺 sha256/url。
"""
from __future__ import annotations

import pytest

from research_os.data_layer.derivation import DerivationPrerequisiteResolver
from research_os.models import DocumentRecord

TS = "2026-04-30T10:00:00+08:00"


class _FakeDB:
    def __init__(self, records=None, blocks=None):
        self._records = records or []
        self._blocks = blocks or []

    def query(self, sql, params=()):
        if "document_records" in sql:
            return [{"payload": r.model_dump()} for r in self._records]
        if "document_blocks" in sql:
            return [{"payload": b} for b in self._blocks]
        return []


def _record(**overrides) -> DocumentRecord:
    base = dict(
        document_id="doc-1", company_entity_id="company:maotai",
        security_entity_id="security:600519.SH", document_type="annual_report",
        title="贵州茅台：2025年年度报告", source_id="cninfo",
        source_url="https://static.cninfo.com.cn/x.PDF", local_path=None,
        external_id="ann-1", published_at="2026-04-30T10:00:00+08:00",
        retrieved_at=TS, report_period_end="2025-12-31", fiscal_year=2025,
        mime_type="application/pdf", file_size_bytes=100, sha256="a" * 64,
        storage_policy="metadata_and_excerpt", copyright_status="statutory_filing",
        text_layer_status="present", table_parse_status="not_started",
        ocr_status="not_started", parser_name="pypdf", parser_version="6.0",
        page_count=10, audit_status="unknown", parse_status="parsed",
        warnings=[], version=1, created_at=TS, updated_at=TS,
    )
    base.update(overrides)
    return DocumentRecord(**base)


def _resolve(db, subject="company:maotai", as_of="2026-05-01T00:00:00+08:00"):
    return DerivationPrerequisiteResolver(db).resolve(
        db, subject_entity=subject, data_type="financial_statement_data", as_of=as_of)


class TestPrerequisiteEligible:
    def test_all_criteria_met(self):
        db = _FakeDB(records=[_record()], blocks=["x"] * 3)
        result = _resolve(db)
        assert result.ready is True
        assert result.missing == []
        assert len(result.eligible_documents) == 1

    def test_subject_missing_fails(self):
        db = _FakeDB(records=[_record()], blocks=["x"])
        result = _resolve(db, subject="")
        assert result.ready is False
        assert any("subject" in m for m in result.missing)

    def test_no_documents_fails(self):
        result = _resolve(_FakeDB(records=[], blocks=[]))
        assert result.ready is False
        assert any("无合格记录" in m for m in result.missing)


class TestPrerequisiteFailClosed:
    @pytest.mark.parametrize("overrides,reason", [
        ({"document_type": "interim_report"}, "document_type"),
        ({"published_at": "2026-06-01T00:00:00+08:00"}, "未来披露"),
        ({"report_period_end": None}, "report_period_end"),
        ({"source_id": "other"}, "source_id"),
        ({"text_layer_status": "absent"}, "原生文本"),
        ({"source_url": None}, "source_url"),
    ])
    def test_single_failure_rejects(self, overrides, reason):
        db = _FakeDB(records=[_record(**overrides)], blocks=["x"])
        result = _resolve(db)
        assert result.ready is False
        assert any(reason in w for w in result.warnings)

    def test_invalid_sha256_record_skipped_fail_closed(self):
        # sha256 非法在 DocumentRecord 构造层 fail closed → resolver 视为无合格记录
        rec = _record()
        rec.sha256 = "short"  # 构造后篡改（pydantic 默认不校验赋值）→ 重建时被跳过
        db = _FakeDB(records=[rec], blocks=["x"])
        result = _resolve(db)
        assert result.ready is False

    def test_no_blocks_fails(self):
        db = _FakeDB(records=[_record()], blocks=[])
        result = _resolve(db)
        assert result.ready is False
        assert any("DocumentBlock" in w for w in result.warnings)

    def test_future_published_rejected(self):
        db = _FakeDB(
            records=[_record(published_at="2026-06-01T00:00:00+08:00")], blocks=["x"])
        result = _resolve(db, as_of="2026-05-01T00:00:00+08:00")
        assert result.ready is False

    def test_wrong_data_type_fails(self):
        db = _FakeDB(records=[_record()], blocks=["x"])
        result = DerivationPrerequisiteResolver(db).resolve(
            db, subject_entity="company:maotai",
            data_type="market_valuation_snapshot", as_of=TS)
        assert result.ready is False
