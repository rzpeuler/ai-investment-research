"""财务标准化测试（任务书 3.25 财务公式手算/期间节，Commit 5 部分）。

覆盖：taxonomy 映射；期间 FY/H1/Q1/Q3；单季拆分；TTM；同比；环比；CAGR；
单位/币种；null/零/负值；重述优先级；冲突组。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from research_os.financials.normalizer import (
    FactCandidate,
    current_version_priority,
    detect_conflicts,
    normalize_fact,
)
from research_os.financials.periods import (
    PeriodKey,
    cagr,
    detect_duration_months,
    detect_period_basis,
    normalize_to_yuan,
    periods_compatible,
    qoq,
    single_quarter_split,
    ttm_fy_plus_ytd,
    yoy,
)
from research_os.financials.taxonomy import FinancialTaxonomy

COMPANY = "company:600519.SH"


def _key(**overrides) -> PeriodKey:
    base = dict(
        company=COMPANY, scope="consolidated", currency="CNY", unit_scale=10000,
        taxonomy_code="revenue", fiscal_year=2025, accounting_standard="CAS",
        restatement_version=1,
    )
    base.update(overrides)
    return PeriodKey(**base)


class TestTaxonomy:
    def test_exact_lookup(self):
        t = FinancialTaxonomy()
        assert t.lookup("营业收入") == "revenue"
        assert t.lookup("归属于母公司股东的净利润") == "net_profit_attr"

    def test_canonical_lookup(self):
        t = FinancialTaxonomy()
        assert t.lookup("营业总收入") == "revenue"
        assert t.lookup("资产总计") == "total_assets"

    def test_unknown_label_returns_none(self):
        t = FinancialTaxonomy()
        assert t.lookup("完全不存在的科目") is None

    def test_fuzzy_lookup(self):
        t = FinancialTaxonomy()
        assert t.fuzzy_lookup("营业收入") == "revenue"
        # 无匹配返回 None
        assert t.fuzzy_lookup("zzz") is None

    def test_statement_and_instant(self):
        t = FinancialTaxonomy()
        assert t.statement_of("revenue") == "income_statement"
        assert t.statement_of("total_assets") == "balance_sheet"
        assert t.instant_or_duration("total_assets") == "instant"
        assert t.instant_or_duration("revenue") == "duration"


class TestPeriodBasis:
    def test_detect_basis(self):
        assert detect_period_basis("2025-12-31") == "FY"
        assert detect_period_basis("2025-06-30") == "H1"
        assert detect_period_basis("2025-03-31") == "Q1"
        assert detect_period_basis("2025-09-30") == "Q3"
        assert detect_period_basis("2025-11-30") == "OTHER"

    def test_duration_months(self):
        assert detect_duration_months("2025-12-31") == 12
        assert detect_duration_months("2025-06-30") == 6
        assert detect_duration_months("2025-03-31") == 3
        assert detect_duration_months("2025-09-30") == 9

    def test_periods_compatible(self):
        a = _key()
        assert periods_compatible(a, _key())
        assert not periods_compatible(a, _key(scope="parent"))
        assert not periods_compatible(a, _key(currency="USD"))
        assert not periods_compatible(a, _key(fiscal_year=2024))
        assert not periods_compatible(a, _key(restatement_version=2))


class TestSingleQuarterSplit:
    def test_q2_split(self):
        # Q2 = H1 − Q1
        res = single_quarter_split(_key(), h1_ytd="100", q1_ytd="40", fy=None, q3_ytd=None)
        q2 = res[0]
        assert q2.quarter == "Q2"
        assert q2.value == "60"
        assert q2.status == "derived_from_report"

    def test_q3_q4_split(self):
        res = single_quarter_split(_key(), h1_ytd="100", q1_ytd="40", fy="200", q3_ytd="150")
        assert res[1].quarter == "Q3" and res[1].value == "50"
        assert res[2].quarter == "Q4" and res[2].value == "50"

    def test_missing_input_derived_missing(self):
        res = single_quarter_split(_key(), h1_ytd=None, q1_ytd="40", fy=None)
        assert res[0].status == "missing"
        assert res[0].value is None


class TestYoY:
    def test_normal(self):
        r = yoy("110", "100")
        assert r.value == "0.1"
        assert r.status == "valid"

    def test_zero_comparable(self):
        r = yoy("100", "0")
        assert r.status == "zero_denominator"
        assert r.value is None

    def test_missing(self):
        r = yoy(None, "100")
        assert r.status == "missing"

    def test_negative_base_warning(self):
        r = yoy("−100", "−50")  # 全角负号应被拒绝，用半角
        assert r.status == "missing"  # 全角负号不是合法 decimal
        r2 = yoy("-150", "-50")
        assert r2.status == "valid"
        assert "negative_base" in r2.warnings

    def test_qoq_uses_single_quarter(self):
        r = qoq("30", "25")
        assert r.value == "0.2"


class TestCAGR:
    def test_normal(self):
        r = cagr("100", "200", Decimal("2"))
        assert r.status == "valid"
        assert abs(Decimal(r.value) - (Decimal(2) ** Decimal("0.5") - 1)) < Decimal("0.0001")

    def test_zero_start_not_applicable(self):
        r = cagr("0", "200", Decimal("2"))
        assert r.status == "not_applicable"

    def test_negative_end_not_applicable(self):
        r = cagr("100", "-200", Decimal("2"))
        assert r.status == "not_applicable"

    def test_missing(self):
        r = cagr(None, "200", Decimal("2"))
        assert r.status == "missing"


class TestTTM:
    def test_fy_plus_ytd(self):
        r = ttm_fy_plus_ytd("400", "300", "250")
        assert r.value == "450"
        assert r.formula_id == "ttm_fy_plus_ytd"

    def test_missing_input(self):
        r = ttm_fy_plus_ytd(None, "300", "250")
        assert r.status == "missing"


class TestUnitNormalization:
    def test_cny_scale_conversion(self):
        v, unit, warn = normalize_to_yuan("100", 10000, "CNY")
        assert v == "1000000"
        assert unit == "yuan"

    def test_foreign_currency_kept(self):
        v, unit, warn = normalize_to_yuan("100", 1, "USD")
        assert v == "100"
        assert unit == "USD"
        assert any("外币" in w for w in warn)

    def test_none_value(self):
        v, unit, warn = normalize_to_yuan(None, 10000, "CNY")
        assert v is None

    def test_zero_scale_fallback(self):
        v, unit, warn = normalize_to_yuan("100", 0, "CNY")
        assert v == "100"


class TestNormalizer:
    def test_normalize_reported(self):
        c = FactCandidate(
            company_entity_id=COMPANY, taxonomy_code="revenue", label_raw="营业收入",
            period_end="2025-12-31", statement_scope="consolidated", currency="CNY",
            unit_scale=10000, raw_value="123450000", source_priority=5,
        )
        n = normalize_fact(c)
        assert n.value_status == "reported"
        assert n.normalized_value == "1234500000000"
        assert n.normalized_unit == "yuan"

    def test_normalize_missing(self):
        c = FactCandidate(
            company_entity_id=COMPANY, taxonomy_code="revenue", label_raw="营业收入",
            period_end="2025-12-31", statement_scope="consolidated", currency="CNY",
            unit_scale=1, raw_value=None, source_priority=5,
        )
        n = normalize_fact(c)
        assert n.value_status == "missing"
        assert n.normalized_value is None


class TestRestatementAndConflict:
    def _fact(self, raw, prio, restate="original", ver=1, key="revenue|2025|FY|consolidated"):
        return {
            "fact_key": key, "raw_value": raw, "source_priority": prio,
            "restatement_status": restate, "restatement_version": ver,
            "evidence_ids": [f"ev-{raw}-{prio}"],
        }

    def test_restated_preferred(self):
        facts = [
            self._fact("100", 1, "original", 1),
            self._fact("105", 2, "restated", 2),
        ]
        ranked = current_version_priority(facts)
        assert ranked[0]["restatement_status"] == "restated"

    def test_higher_priority_wins_within_same_status(self):
        facts = [
            self._fact("100", 5),  # 用户导入
            self._fact("100", 1),  # 法定披露
        ]
        ranked = current_version_priority(facts)
        assert ranked[0]["source_priority"] == 1

    def test_conflict_detected(self):
        facts = [self._fact("100", 1), self._fact("120", 5)]
        cg = detect_conflicts(facts)
        assert cg is not None
        assert cg.values == ["100", "120"]

    def test_same_value_not_conflict(self):
        facts = [self._fact("100", 1), self._fact("100", 5)]
        assert detect_conflicts(facts) is None

    def test_all_none_not_conflict(self):
        facts = [self._fact(None, 1), self._fact(None, 5)]
        assert detect_conflicts(facts) is None
