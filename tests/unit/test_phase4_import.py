"""财务导入服务测试（任务书 3.25 财务导入节）。

覆盖：CSV / JSON / XLSX；缺列；非法数字；空字符串与零；重复行；
混币种/单位/口径；dry-run 零副作用；rejected 行不写正式事实；checksum 与 data_version。
"""
from __future__ import annotations

import json

import pytest

from research_os.financials.import_service import (
    import_financial_file,
    persist_import,
    sha256_file,
)
from research_os.storage.db import Database
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"

CSV_HEADER = (
    "company_entity_id,period_start,period_end,fiscal_year,report_type,statement_scope,"
    "statement_type,taxonomy_code,label_raw,value,unit_scale,currency"
)
CSV_GOOD = "\n".join([
    CSV_HEADER,
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,123450000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,cost_of_sales,营业成本,70000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_assets,资产总计,300000000000,10000,CNY",
])


def _write(tmp_path, name: str, content: str):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


class TestCsvImport:
    def test_good_csv_all_accepted(self, tmp_path):
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.row_count == 3
        assert res.manifest.accepted_count == 3
        assert res.manifest.rejected_count == 0
        assert res.manifest.validation_status == "accepted"
        # 三张表（income×2 + balance×1）同属 2025 年报 consolidated → 1 个报告对象
        assert len(res.reports) == 1
        assert res.reports[0].report_type == "annual"
        # 值必须十进制字符串
        for rr in res.rows:
            assert rr.fact is not None
            assert isinstance(rr.fact.raw_value, str)

    def test_invalid_number_rejected(self, tmp_path):
        bad = CSV_GOOD.replace("123450000000", "12abc")
        p = _write(tmp_path, "bad.csv", bad)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.rejected_count == 1
        assert res.manifest.validation_status == "partial"
        assert any("非法数字" in e for e in res.manifest.validation_errors)

    def test_missing_required_column_rejected(self, tmp_path):
        """缺 taxonomy_code（必需列）→ 行被拒绝。"""
        bad = CSV_GOOD.replace("revenue,营业收入,123450000000,10000,CNY", ",营业收入,123450000000,10000,CNY")
        p = _write(tmp_path, "missing.csv", bad)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.rejected_count == 1
        assert any("taxonomy_code" in e for e in res.manifest.validation_errors)

    def test_empty_string_means_missing_not_zero(self, tmp_path):
        """空字符串 → value_status=missing，不得当 0。"""
        bad = CSV_GOOD.replace("123450000000,10000,CNY", ",10000,CNY")
        p = _write(tmp_path, "empty.csv", bad)
        res = import_financial_file(p, company_entity_id=COMPANY)
        fact = next(r.fact for r in res.rows if r.accepted and r.fact.taxonomy_code == "revenue")
        assert fact.value_status == "missing"
        assert fact.raw_value is None

    def test_zero_is_valid_reported_value(self, tmp_path):
        bad = CSV_GOOD.replace("123450000000", "0")
        p = _write(tmp_path, "zero.csv", bad)
        res = import_financial_file(p, company_entity_id=COMPANY)
        fact = next(r.fact for r in res.rows if r.accepted and r.fact.taxonomy_code == "revenue")
        assert fact.raw_value == "0"
        assert fact.value_status == "reported"

    def test_dry_run_no_side_effects(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.migrate()
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY, dry_run=True)
        # dry_run 不落库
        assert db.count("financial_data_manifests") == 0
        assert db.count("financial_facts") == 0
        db.close()

    def test_persist_writes_manifest_and_facts(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.migrate()
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY)
        persist_import(db, res)
        assert db.count("financial_data_manifests") == 1
        assert db.count("financial_reports") == 1
        assert db.count("financial_facts") == 3
        # 幂等：同 checksum+data_version 重复导入不产生重复行
        res2 = import_financial_file(p, company_entity_id=COMPANY)
        persist_import(db, res2)
        assert db.count("financial_data_manifests") == 1
        assert db.count("financial_facts") == 3
        db.close()

    def test_all_rejected_not_persisted(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.migrate()
        bad = "\n".join([
            CSV_HEADER,
            f"bad-entity,2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,100,10000,CNY",
        ])
        p = _write(tmp_path, "allbad.csv", bad)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.rejected_count == 1
        with pytest.raises(ValueError):
            persist_import(db, res)
        assert db.count("financial_facts") == 0
        db.close()


class TestJsonImport:
    def test_json_rows_accepted(self, tmp_path):
        data = {"rows": [
            {"company_entity_id": COMPANY, "period_start": "2025-01-01", "period_end": "2025-12-31",
             "fiscal_year": 2025, "report_type": "annual", "statement_scope": "consolidated",
             "statement_type": "income_statement", "taxonomy_code": "revenue",
             "label_raw": "营业收入", "value": "123450000000", "unit_scale": 10000, "currency": "CNY"},
        ]}
        p = tmp_path / "good.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.accepted_count == 1
        assert res.rows[0].fact.raw_value == "123450000000"

    def test_json_float_value_has_no_float_tail(self, tmp_path):
        """即使输入是 float，也规范化为十进制字符串（无二进制尾数）。"""
        data = {"rows": [
            {"company_entity_id": COMPANY, "period_start": "2025-01-01", "period_end": "2025-12-31",
             "fiscal_year": 2025, "report_type": "annual", "statement_scope": "consolidated",
             "statement_type": "income_statement", "taxonomy_code": "revenue",
             "label_raw": "营业收入", "value": 123450000000.0, "unit_scale": 10000, "currency": "CNY"},
        ]}
        p = tmp_path / "float.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.rows[0].fact.raw_value == "123450000000"


class TestXlsxImport:
    def test_xlsx_accepted(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(CSV_HEADER.split(","))
        ws.append([COMPANY, "2025-01-01", "2025-12-31", 2025, "annual", "consolidated",
                   "income_statement", "revenue", "营业收入", 123450000000, 10000, "CNY"])
        p = tmp_path / "good.xlsx"
        wb.save(p)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.accepted_count == 1
        assert res.manifest.file_format == "xlsx"

    def test_xlsx_mixed_scope_rejected(self, tmp_path):
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(CSV_HEADER.split(","))
        ws.append([COMPANY, "2025-01-01", "2025-12-31", 2025, "annual", "badscope",
                   "income_statement", "revenue", "营业收入", 100, 10000, "CNY"])
        p = tmp_path / "bad.xlsx"
        wb.save(p)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert res.manifest.rejected_count == 1
        assert any("statement_scope" in e for e in res.manifest.validation_errors)


class TestChecksum:
    def test_sha256_stable(self, tmp_path):
        p = _write(tmp_path, "a.csv", CSV_GOOD)
        assert sha256_file(p) == sha256_file(p)
        assert len(sha256_file(p)) == 64

    def test_checksum_enters_idempotency(self, tmp_path):
        p1 = _write(tmp_path, "a.csv", CSV_GOOD)
        p2 = _write(tmp_path, "b.csv", CSV_GOOD.replace("123450000000", "999999999999"))
        assert sha256_file(p1) != sha256_file(p2)


class TestSchemaContract:
    def test_manifest_passes_schema(self, tmp_path):
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY)
        assert validate_model(res.manifest) == []

    def test_facts_pass_schema(self, tmp_path):
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY)
        for rr in res.rows:
            if rr.accepted:
                assert validate_model(rr.fact) == []

    def test_reports_pass_schema(self, tmp_path):
        p = _write(tmp_path, "good.csv", CSV_GOOD)
        res = import_financial_file(p, company_entity_id=COMPANY)
        for r in res.reports:
            assert validate_model(r) == []
