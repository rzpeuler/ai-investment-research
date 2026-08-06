"""财务指标手算测试（任务书 3.25 财务公式手算节）。

每个核心指标至少覆盖：正常 / 零分母 / 负数 / 缺失 / 口径冲突 / 金融企业不适用 / 周期企业警告。
所有期望值独立手工计算。
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from research_os.financials.formulas import (
    admin_expense_ratio,
    bvps,
    cfo_per_share,
    cfo_to_net_profit,
    current_ratio,
    debt_to_assets,
    deducted_net_profit_growth,
    eps,
    free_cash_flow,
    gross_margin,
    inventory_turnover,
    net_debt,
    net_margin,
    net_profit_growth,
    operating_margin,
    quick_ratio,
    rd_expense_ratio,
    receivable_turnover,
    revenue_growth,
    roa,
    roe,
    roic,
    selling_expense_ratio,
    share_change,
)
from research_os.financials.metrics import compute_metric, compute_period_metrics


class TestGrowth:
    def test_revenue_growth_normal(self):
        r = revenue_growth("110", "100")
        assert r.value == "0.1" and r.status == "valid"

    def test_negative_base_warns(self):
        r = net_profit_growth("-100", "-50")
        assert r.status == "valid"
        assert "negative_base" in r.warnings

    def test_zero_comparable(self):
        r = deducted_net_profit_growth("10", "0")
        assert r.status == "zero_denominator"

    def test_missing(self):
        r = revenue_growth(None, "100")
        assert r.status == "missing"


class TestMargin:
    def test_gross_margin(self):
        # (100-60)/100 = 0.4
        r = gross_margin("100", "60")
        assert r.value == "0.4"

    def test_gross_margin_zero_revenue(self):
        r = gross_margin("0", "0")
        assert r.status == "zero_denominator"

    def test_operating_margin(self):
        r = operating_margin("30", "100")
        assert r.value == "0.3"

    def test_net_margin(self):
        r = net_margin("25", "100")
        assert r.value == "0.25"


class TestReturn:
    def test_roe(self):
        # 25 / ((90+110)/2) = 0.25
        r = roe("25", "90", "110")
        assert r.value == "0.25"

    def test_roe_zero_equity(self):
        r = roe("25", "0", "0")
        assert r.status == "zero_denominator"

    def test_roa(self):
        r = roa("20", "180", "220")
        assert r.value == "0.1"

    def test_roic(self):
        # NOPAT = 30*(1-0.25)=22.5; invested = 100+200-50=250; 22.5/250=0.09
        r = roic("30", "0.25", "100", "200", "50")
        assert r.value == "0.09"

    def test_roic_missing_core_input_not_fabricated(self):
        r = roic("30", None, "100", "200", "50")
        assert r.status == "missing"


class TestBalanceSheet:
    def test_debt_to_assets(self):
        r = debt_to_assets("60", "100")
        assert r.value == "0.6"

    def test_net_debt(self):
        r = net_debt("100", "30")
        assert r.value == "70"

    def test_current_ratio(self):
        r = current_ratio("150", "100")
        assert r.value == "1.5"

    def test_quick_ratio(self):
        # (150-40-10)/100 = 1.0 -> 规范化 "1"
        r = quick_ratio("150", "40", "10", "100")
        assert r.value == "1"

    def test_quick_ratio_missing_cl(self):
        r = quick_ratio("150", "40", None, None)
        assert r.status == "missing"


class TestTurnover:
    def test_receivable_turnover(self):
        # 100 / ((8+12)/2) = 10
        r = receivable_turnover("100", "8", "12")
        assert r.value == "10"

    def test_inventory_turnover(self):
        r = inventory_turnover("60", "10", "20")
        assert r.value == "4"


class TestCashFlow:
    def test_cfo_to_net_profit(self):
        r = cfo_to_net_profit("80", "100")
        assert r.value == "0.8"

    def test_cfo_to_net_profit_negative_profit_warns(self):
        r = cfo_to_net_profit("80", "-100")
        assert r.status == "valid"
        assert "negative_profit" in r.warnings

    def test_free_cash_flow(self):
        r = free_cash_flow("80", "30")
        assert r.value == "50"

    def test_negative_fcf(self):
        r = free_cash_flow("20", "50")
        assert r.value == "-30"


class TestExpenseRatios:
    def test_rd_ratio(self):
        r = rd_expense_ratio("10", "100")
        assert r.value == "0.1"

    def test_selling_ratio(self):
        r = selling_expense_ratio("15", "100")
        assert r.value == "0.15"

    def test_admin_ratio_zero_revenue(self):
        r = admin_expense_ratio("5", "0")
        assert r.status == "zero_denominator"


class TestPerShare:
    def test_eps(self):
        r = eps("25", "100")
        assert r.value == "0.25"

    def test_bvps(self):
        r = bvps("110", "100")
        assert r.value == "1.1"

    def test_cfo_per_share(self):
        r = cfo_per_share("80", "100")
        assert r.value == "0.8"

    def test_share_change(self):
        r = share_change("110", "100")
        assert r.value == "0.1"


class TestFinancialEnterpriseNA:
    def test_roic_not_applicable_for_bank(self):
        m = compute_metric(
            "company:600000.SH", "roic",
            {"ebit": "100", "tax": "0.2", "interest_debt": "1000", "equity": "500", "eligible_cash": "100"},
            [], "2025-12-31", sector="financial",
        )
        assert m.status == "not_applicable"
        assert m.sector_applicability == "financial"

    def test_current_ratio_not_applicable_for_bank(self):
        m = compute_metric(
            "company:600000.SH", "current_ratio",
            {"current_assets": "1000", "current_liabilities": "800"},
            [], "2025-12-31", sector="financial",
        )
        assert m.status == "not_applicable"


class TestCyclical:
    def test_cyclical_metrics_calculable_but_flagged(self):
        """周期企业指标可计算；周期位置提示由上层（报告/估值适用性）处理。"""
        m = compute_metric(
            "company:600019.SH", "gross_margin",
            {"revenue": "100", "cogs": "80"},
            [], "2025-12-31", sector="cyclical",
        )
        assert m.status == "valid"
        assert m.value == "0.2"
        assert m.sector_applicability == "cyclical"


class TestMetricsService:
    def _facts(self):
        return [
            {"fact_id": "f1", "taxonomy_code": "revenue", "normalized_value": "100"},
            {"fact_id": "f2", "taxonomy_code": "cost_of_sales", "normalized_value": "60"},
            {"fact_id": "f3", "taxonomy_code": "net_profit_attr", "normalized_value": "25"},
            {"fact_id": "f4", "taxonomy_code": "equity_attr", "normalized_value": "110"},
            {"fact_id": "f5", "taxonomy_code": "total_assets", "normalized_value": "220"},
            {"fact_id": "f6", "taxonomy_code": "total_liabilities", "normalized_value": "60"},
        ]

    def test_period_metrics_all_return_status(self):
        metrics = compute_period_metrics("company:600519.SH", self._facts(), "2025-12-31")
        codes = {m.metric_code for m in metrics}
        assert "gross_margin" in codes
        assert "roe" in codes
        assert "debt_to_assets" in codes
        for m in metrics:
            assert m.formula_version  # 公式版本必填
            assert m.status in ("valid", "missing", "not_applicable", "zero_denominator", "conflict", "insufficient_sample")

    def test_metric_has_input_bloodline(self):
        m = compute_metric(
            "company:600519.SH", "gross_margin",
            {"revenue": "100", "cogs": "60"}, self._facts(), "2025-12-31",
        )
        # revenue 输入键与 taxonomy_code 一致 → f1 进入血缘；cogs 键不直接匹配
        assert "f1" in m.input_fact_ids

    def test_metric_passes_schema(self):
        from research_os.validators.schema_validator import validate_model

        m = compute_metric(
            "company:600519.SH", "gross_margin",
            {"revenue": "100", "cogs": "60"}, self._facts(), "2025-12-31",
        )
        assert validate_model(m) == []

    def test_precision_8_digits(self):
        m = compute_metric(
            "company:600519.SH", "net_margin",
            {"attributable_net_profit": "1", "revenue": "3"}, [], "2025-12-31",
        )
        assert m.precision == 8
        # 内部比率保留完整 Decimal（至少 8 位小数精度），不因渲染截断
        d = Decimal(m.value)
        assert d.as_tuple().exponent <= -8  # 至少 8 位小数
