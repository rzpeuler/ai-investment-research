"""P7-D4 M3：FinancialStatementExtractor 离线测试。

synthetic DocumentBlock fixture（模拟 parse_pdf_text 输出的压缩文本块）。
覆盖：正常 consolidated 三表提取、current 列 authority、恒等式校验、parent reject、
fuzzy 不自动接受、非法数值/单位 reject、非 CORE code 跳过。零网络。
"""
from __future__ import annotations

import pytest

from research_os.financials.disclosure_extractor import FinancialStatementExtractor
from research_os.models import DocumentBlock

TS = "2026-04-30T10:00:00+08:00"


def _block(text: str, page: int = 1, block_id: str = "") -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id, document_id="doc-fixture", block_type="text",
        page_start=page, page_end=page, bbox=None, sequence_no=0,
        section_path=[], content_excerpt=text, content_hash="0" * 64,
        table_id=None, row_index=None, column_index=None,
        normalized_payload=None, extraction_method="native_text",
        confidence=None, correction_status="unreviewed",
        correction_of_block_id=None, source_id="cninfo",
        evidence_ids=[], version=1, created_at=TS,
    )


def _blocks_income_current_first() -> list:
    return [
        _block("单位：元", 1),
        _block("合并利润表", 2),
        _block("项目 本期金额 上期金额", 2),
        _block("一、营业总收入 10,000,000.00 9,000,000.00", 2),
        _block("营业收入 10,000,000.00 9,000,000.00", 2),
        _block("营业成本 6,000,000.00 5,500,000.00", 2),
        _block("营业利润 2,500,000.00 2,000,000.00", 2),
        _block("净利润 1,900,000.00 1,500,000.00", 2),
        _block("归属于母公司所有者的净利润 1,800,000.00 1,400,000.00", 2),
    ]


def _blocks_balance_sheet() -> list:
    return [
        _block("单位：元", 1),
        _block("合并资产负债表", 3),
        _block("项目 期末余额 期初余额", 3),
        _block("资产总计 25,000,000.00 20,000,000.00", 3),
        _block("负债合计 10,000,000.00 9,000,000.00", 3),
        _block("归属于母公司所有者权益合计 15,000,000.00 11,000,000.00", 3),
    ]


def _blocks_cash_flow() -> list:
    return [
        _block("单位：元", 1),
        _block("合并现金流量表", 4),
        _block("项目 本期金额 上期金额", 4),
        _block("经营活动产生的现金流量净额 3,000,000.00 2,500,000.00", 4),
    ]


def _extract(blocks):
    return FinancialStatementExtractor().extract(
        record=None, blocks=blocks, document=None,
        company_entity_id="company:maotai", fiscal_year=2025,
        period_end="2025-12-31", period_start="2025-01-01",
        published_at=TS,
    )


class TestConsolidatedExtraction:
    def test_income_statement_current_column(self):
        result = _extract(_blocks_income_current_first())
        by_code = {f.taxonomy_code: f for f in result.facts}
        assert by_code["revenue"].normalized_value == "10000000"
        assert by_code["revenue"].statement_type == "income_statement"
        assert by_code["revenue"].statement_scope == "consolidated"
        assert by_code["revenue"].period_end == "2025-12-31"
        assert by_code["revenue"].currency == "CNY"
        assert by_code["revenue"].unit_scale == 1
        assert by_code["revenue"].valid_from == TS
        assert by_code["net_profit_attr"].normalized_value == "1800000"
        assert by_code["operating_profit"].normalized_value == "2500000"

    def test_balance_sheet_identity_check_passes(self):
        result = _extract(_blocks_balance_sheet())
        by_code = {f.taxonomy_code: f for f in result.facts}
        assert by_code["total_assets"].normalized_value == "25000000"
        assert by_code["total_liabilities"].normalized_value == "10000000"
        assert by_code["equity_attr"].normalized_value == "15000000"
        assert by_code["total_assets"].instant_or_duration == "instant"

    def test_cash_flow_current_column(self):
        result = _extract(_blocks_cash_flow())
        by_code = {f.taxonomy_code: f for f in result.facts}
        assert by_code["operating_cash_flow"].normalized_value == "3000000"
        assert by_code["operating_cash_flow"].statement_type == "cash_flow"

    def test_balance_sheet_identity_failure_rejects_table(self):
        blocks = _blocks_balance_sheet()
        # 篡改权益行使恒等式不成立（2500 != 1000 + 1400）
        blocks[5] = _block("归属于母公司所有者权益合计 14,000,000.00 11,000,000.00", 3)
        result = _extract(blocks)
        assert result.facts == []  # 整表 reject，禁止猜测列
        assert any("恒等式" in r.reason for r in result.rejected_rows)


class TestFailClosed:
    def test_parent_statement_not_accepted(self):
        blocks = [
            _block("单位：元", 1),
            _block("母公司利润表", 2),
            _block("项目 本期金额 上期金额", 2),
            _block("营业收入 10,000,000.00 9,000,000.00", 2),
        ]
        result = _extract(blocks)
        assert result.facts == []

    def test_missing_column_authority_rejects(self):
        blocks = [
            _block("单位：元", 1),
            _block("合并利润表", 2),
            _block("营业收入 10,000,000.00 9,000,000.00", 2),  # 无表头
        ]
        result = _extract(blocks)
        assert result.facts == []
        assert any("current-period 列无法证明" in r.reason for r in result.rejected_rows)

    def test_missing_unit_authority_rejects(self):
        blocks = [
            _block("合并利润表", 2),  # 无“单位”字样
            _block("项目 本期金额 上期金额", 2),
            _block("营业收入 10,000,000.00 9,000,000.00", 2),
        ]
        result = _extract(blocks)
        assert result.facts == []
        assert any("无法证明报告单位" in w for w in result.warnings)

    def test_fuzzy_only_match_not_accepted(self):
        blocks = [
            _block("单位：元", 1),
            _block("合并利润表", 2),
            _block("项目 本期金额 上期金额", 2),
            _block("营业总收入额 10,000,000.00 9,000,000.00", 2),  # 不在 exact synonyms
        ]
        result = _extract(blocks)
        assert result.facts == []
        assert any("仅 fuzzy" in r.reason for r in result.rejected_rows)

    def test_unknown_label_ignored(self):
        blocks = [
            _block("单位：元", 1),
            _block("合并利润表", 2),
            _block("项目 本期金额 上期金额", 2),
            _block("非财务杂项 123.00 100.00", 2),
            _block("营业收入 10,000,000.00 9,000,000.00", 2),
        ]
        result = _extract(blocks)
        codes = {f.taxonomy_code for f in result.facts}
        assert codes == {"revenue"}

    def test_malformed_numeric_rejected(self):
        blocks = [
            _block("单位：元", 1),
            _block("合并利润表", 2),
            _block("项目 本期金额 上期金额", 2),
            _block("营业收入 10,00x,000.00 9,000,000.00", 2),
        ]
        result = _extract(blocks)
        assert result.facts == []

    def test_non_core_code_skipped(self):
        blocks = [
            _block("单位：元", 1),
            _block("合并利润表", 2),
            _block("项目 本期金额 上期金额", 2),
            _block("基本每股收益 2.50 2.00", 2),  # EPS 不在 CORE_FINANCIAL_CODES
            _block("营业收入 10,000,000.00 9,000,000.00", 2),
        ]
        result = _extract(blocks)
        codes = {f.taxonomy_code for f in result.facts}
        assert "revenue" in codes
        assert all(c in {"revenue"} for c in codes)
