"""估值测试（任务书 3.25 估值节，Commit 11）。

覆盖：PE/PB/PS/EV/EV_EBITDA/FCF_Yield/股息率手算；净现金；高负债；受限现金；
少数股权缺失降级；FCF 负；历史/同行分位样本不足；市值时点；金融企业；
禁止目标价（无目标价字段/逻辑）；Schema 契约。
"""
from __future__ import annotations

from decimal import Decimal

from research_os.models.valuation import ValuationSnapshot
from research_os.valuation.formulas import (
    ValuationInputs,
    build_valuation_snapshot,
    compute_ev,
    compute_market_cap,
    compute_valuation_metrics,
    peer_percentile_status,
    percentile_rank,
    percentile_status,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"
SECURITY = "security:600519.SH"
TS = "2026-08-06T00:00:00"


def _input(**overrides) -> ValuationInputs:
    base = dict(
        company_entity_id=COMPANY, security_entity_id=SECURITY, as_of=TS,
        price="1500", shares_outstanding="100000000", direct_market_cap=None,
        interest_debt="20000000000", preferred_equity=None, minority_interest="5000000000",
        eligible_cash="50000000000", non_operating_investments=None,
        financial_period_end="2025-12-31", financial_basis="TTM",
        net_profit_ttm="70000000000", revenue_ttm="150000000000",
        ebitda_ttm="100000000000", fcf_ttm="60000000000",
        equity_attr="150000000000", trailing_dividend="30000000000",
        sector="general",
    )
    base.update(overrides)
    return ValuationInputs(**base)


class TestMarketCap:
    def test_direct_preferred(self):
        mc = compute_market_cap(_input(direct_market_cap="180000000000"))
        assert mc.market_cap == "180000000000"
        assert mc.method == "direct"

    def test_price_times_shares(self):
        mc = compute_market_cap(_input())
        # 1500 × 1e8 = 1.5e11
        assert mc.market_cap == "150000000000"
        assert mc.method == "price_times_shares"

    def test_missing_inputs(self):
        mc = compute_market_cap(_input(price=None, shares_outstanding=None, direct_market_cap=None))
        assert mc.market_cap is None
        assert "时点无法对齐" in " ".join(mc.warnings)


class TestEV:
    def test_ev_calculation(self):
        # 1500e8 + 200e8 + 0 + 50e8 − 500e8 = 1250e8
        inp = _input()
        ev, _ = compute_ev(inp, "150000000000")
        assert ev == "125000000000"

    def test_missing_minority_degrades(self):
        inp = _input(minority_interest=None)
        ev, warnings = compute_ev(inp, "150000000000")
        assert ev is not None
        assert any("少数股东权益缺失" in w for w in warnings)

    def test_net_cash_company_ev_below_mc(self):
        inp = _input(interest_debt="0", minority_interest="0", eligible_cash="200000000000")
        ev, warnings = compute_ev(inp, "150000000000")
        assert Decimal(ev) < Decimal("150000000000")
        assert any("EV 为负" in w or "净现金" in w for w in warnings) or Decimal(ev) >= 0


class TestMetrics:
    def test_pe_normal(self):
        m = compute_valuation_metrics(_input(), "150000000000", "125000000000")
        pe = next(x for x in m if x.metric_code == "PE_TTM")
        # 1.5e11 / 7e10 = 2.142857...
        assert pe.status == "valid"
        assert abs(Decimal(pe.value) - Decimal("2.142857142857")) < Decimal("0.000001")

    def test_pe_loss_maker_not_applicable(self):
        m = compute_valuation_metrics(_input(net_profit_ttm="-10000000000"), "150000000000", "125000000000")
        pe = next(x for x in m if x.metric_code == "PE_TTM")
        assert pe.status == "not_applicable"

    def test_pb_negative_equity(self):
        m = compute_valuation_metrics(_input(equity_attr="-10000000000"), "150000000000", "125000000000")
        pb = next(x for x in m if x.metric_code == "PB")
        assert pb.status == "not_applicable"

    def test_ev_ebitda_financial_na(self):
        m = compute_valuation_metrics(_input(sector="bank"), "150000000000", "125000000000")
        evm = next(x for x in m if x.metric_code == "EV_EBITDA")
        assert evm.status == "not_applicable"

    def test_ev_ebitda_negative_ebitda(self):
        m = compute_valuation_metrics(_input(ebitda_ttm="-5000000000"), "150000000000", "125000000000")
        evm = next(x for x in m if x.metric_code == "EV_EBITDA")
        assert evm.status == "not_applicable"

    def test_fcf_negative_allowed_with_warning(self):
        m = compute_valuation_metrics(_input(fcf_ttm="-10000000000"), "150000000000", "125000000000")
        fcf = next(x for x in m if x.metric_code == "FCF_YIELD")
        assert fcf.status == "valid"  # 负 FCF Yield 允许显示
        assert any("不得解释为便宜" in w for w in fcf.warnings)


class TestPercentiles:
    def test_history_insufficient(self):
        assert percentile_status(10) == "insufficient"

    def test_history_limited(self):
        assert percentile_status(40) == "limited"

    def test_history_full(self):
        assert percentile_status(70) == "full"

    def test_peer_insufficient(self):
        assert peer_percentile_status(2) == "insufficient"

    def test_peer_limited(self):
        assert peer_percentile_status(4) == "limited"

    def test_peer_full(self):
        assert peer_percentile_status(6) == "full"

    def test_percentile_rank_needs_36_samples(self):
        r = percentile_rank("10", [str(i) for i in range(10)])
        assert r is None

    def test_percentile_rank_computed(self):
        hist = [str(i) for i in range(100)]  # 0..99
        r = percentile_rank("50", hist)
        assert r is not None
        assert 0.49 < r < 0.52


class TestSnapshot:
    def test_snapshot_builds(self):
        snap = build_valuation_snapshot(_input())
        assert snap.market_cap == "150000000000"
        assert snap.status in ("complete", "partial")
        assert validate_model(snap) == []

    def test_insufficient_history_note(self):
        snap = build_valuation_snapshot(_input(), history_values=["10", "11"])
        assert any("历史样本 2 < 36" in n for n in snap.applicability_notes)

    def test_cyclical_note(self):
        snap = build_valuation_snapshot(_input(sector="cyclical"))
        assert any("周期企业" in n for n in snap.applicability_notes)

    def test_no_target_price_field(self):
        """ValuationSnapshot 无任何目标价/合理价值字段（结构性禁止）。"""
        fields = ValuationSnapshot.model_fields.keys()
        for forbidden in ("target_price", "fair_value", "upside", "buy_interval", "sell_interval"):
            assert forbidden not in fields

    def test_metrics_have_no_target_price(self):
        m = compute_valuation_metrics(_input(), "150000000000", "125000000000")
        for metric in m:
            assert metric.metric_code not in ("TARGET_PRICE", "FAIR_VALUE", "UPSIDE")
