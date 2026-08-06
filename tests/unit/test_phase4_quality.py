"""财务质量与勾稽测试（任务书 3.25 财务质量节 + 勾稽节）。

覆盖：资产负债恒等容差；现金流勾稽 partial；四层阈值（会计硬规则/robust/后备）；
告警不得认定造假；规则版本；动态阈值。
"""
from __future__ import annotations

from decimal import Decimal

from research_os.financials.quality import (
    QUALITY_RULES_VERSION,
    audit_opinion_change,
    goodwill_concentration,
    gross_margin_abnormal,
    high_dividend_high_debt,
    high_non_recurring,
    profit_growth_cashflow_deterioration,
    rd_capitalization_abnormal,
    receivable_growth_exceeds_revenue,
    related_party_transactions,
    restatement_present,
    restricted_cash,
    robust_z_series,
    run_quality_checks,
)
from research_os.financials.reconciler import (
    reconcile_balance_sheet,
    reconcile_cash_flow,
)


class TestBalanceSheetReconciliation:
    def test_identity_holds(self):
        r = reconcile_balance_sheet("100", "60", "40")
        assert r.ok

    def test_identity_within_tolerance(self):
        # 差 0.00001 在相对容差内（100*0.0001=0.01）
        r = reconcile_balance_sheet("100", "60", "39.99999")
        assert r.ok

    def test_identity_out_of_tolerance(self):
        r = reconcile_balance_sheet("100", "60", "30")
        assert not r.ok
        assert r.issues[0].severity == "error"

    def test_missing_input_partial_not_error(self):
        r = reconcile_balance_sheet(None, "60", "40")
        assert not r.ok
        assert r.issues[0].severity == "warning"  # 不认定报表错误


class TestCashFlowReconciliation:
    def test_flow_holds(self):
        r = reconcile_cash_flow("130", "100", "30", "0", "0")
        assert r.ok

    def test_partial_when_inputs_missing(self):
        r = reconcile_cash_flow(None, "100", "30")
        assert not r.ok
        assert r.issues[0].code == "cash_flow_partial"

    def test_mismatch_is_warning_not_fraud(self):
        r = reconcile_cash_flow("150", "100", "30")
        assert not r.ok
        assert r.issues[0].severity == "warning"  # 缺披露项可能为 partial，不得认定错误


class TestHardRules:
    def test_audit_opinion_downgrade(self):
        w = audit_opinion_change("unmodified", "qualified")
        assert len(w) == 1 and w[0].severity == "warning"

    def test_audit_opinion_same_no_warning(self):
        assert audit_opinion_change("unmodified", "unmodified") == []

    def test_restatement_detected(self):
        w = restatement_present(["original", "restated"])
        assert len(w) == 1

    def test_no_restatement(self):
        assert restatement_present(["original"]) == []


class TestDynamicRules:
    def test_profit_up_cfo_down(self):
        w = profit_growth_cashflow_deterioration("0.2", "-0.1", "80", "100")
        assert any(x.rule_code == "profit_growth_cashflow_deterioration" for x in w)

    def test_cfo_np_below_floor(self):
        w = profit_growth_cashflow_deterioration(None, None, "50", "100")
        assert len(w) == 1  # 0.5 < 0.8

    def test_receivable_exceeds_revenue(self):
        w = receivable_growth_exceeds_revenue("0.30", "0.05", "0.40", "0.30")
        # 25pp > 20pp 且 10pp 上升 >= 5pp
        assert len(w) == 1

    def test_receivable_no_trigger(self):
        w = receivable_growth_exceeds_revenue("0.10", "0.05", "0.40", "0.30")
        assert w == []

    def test_gross_margin_change_and_z(self):
        w = gross_margin_abnormal("0.60", "0.50", robust_z="4")
        assert len(w) == 1

    def test_gross_margin_outside_peer_range(self):
        w = gross_margin_abnormal("0.30", "0.30", peer_p5="0.35", peer_p95="0.70")
        assert len(w) == 1

    def test_non_recurring_high(self):
        w = high_non_recurring("40", "100")
        assert len(w) == 1  # 40% > 30%

    def test_non_recurring_very_high(self):
        w = high_non_recurring("60", "100")
        assert w[0].message  # 60% > 50% 标高

    def test_goodwill_concentration(self):
        w = goodwill_concentration("25", "100")
        assert len(w) == 1

    def test_rd_capitalization(self):
        w = rd_capitalization_abnormal("60", "100")
        assert len(w) == 1  # 60% > 50%

    def test_related_party(self):
        w = related_party_transactions("6", "100")
        assert len(w) == 1  # 6% > 5%

    def test_dividend_high_debt(self):
        w = high_dividend_high_debt("120", "100", net_debt_rising=True)
        assert len(w) == 1

    def test_dividend_no_trigger_without_debt_rise(self):
        w = high_dividend_high_debt("120", "100", net_debt_rising=False)
        assert w == []

    def test_restricted_cash(self):
        w = restricted_cash("100", "40")
        assert len(w) == 1


class TestRobustStats:
    def test_robust_z_series(self):
        values = ["10", "10.5", "9.8", "10.2", "25"]  # 最后一个为异常
        z = robust_z_series(values)
        assert z is not None
        assert abs(z) > 3

    def test_robust_z_insufficient_sample(self):
        assert robust_z_series(["10", "11"]) is None

    def test_robust_z_mad_zero_returns_none(self):
        assert robust_z_series(["10", "10", "10", "10", "10"]) is None


class TestQualitySummary:
    def test_run_quality_checks_collects(self):
        w = run_quality_checks(
            net_profit_growth="0.2", cfo_growth="-0.1", cfo="50", net_profit="100",
            gross_margin_current="0.6", gross_margin_previous="0.5",
            gross_margin_history=["0.5", "0.51", "0.49", "0.5", "0.6"],
        )
        assert any(x.rule_code == "profit_growth_cashflow_deterioration" for x in w)
        assert any(x.rule_code == "gross_margin_abnormal" for x in w)
        # 所有告警带规则版本
        for x in w:
            assert x.rule_version == QUALITY_RULES_VERSION

    def test_no_fraud_conclusion_generated(self):
        """规则只输出告警对象，无造假/必然风险结论字段。"""
        w = run_quality_checks(net_profit_growth="0.2", cfo_growth="-0.5", cfo="10", net_profit="100")
        assert w
        for x in w:
            assert "造假" not in x.message
            assert "必然" not in x.message
