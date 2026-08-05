"""异动检测确定性算法测试（Phase 3 任务书 7 节，可手工复算）。"""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta

import pytest

from research_os.abnormal_move.anomaly_detector import (
    AnomalyDetector,
    DetectResult,
    beta_adjusted_residual,
    historical_percentile,
    pct_change,
    robust_stats,
    robust_z_score,
    rolling_returns,
    severity_from_percentile,
    severity_from_z,
    streak_info,
    winsorize,
)
from research_os.abnormal_move.config import MIN_SAMPLE_LIMITED
from research_os.abnormal_move.window import WindowError, resolve_window
from research_os.abnormal_move.market_data_loader import TradingCalendar
from research_os.models import AbnormalMoveRequest, MarketDailyOhlcv
from research_os.utils.id import new_uuid

UUID = "12345678-1234-1234-1234-123456789abc"


def _bar(d: date, close: float, volume: float = 1000.0,
         open_: float = None, high: float = None, low: float = None,
         amount: float | None = None) -> MarketDailyOhlcv:
    o = open_ if open_ is not None else close
    h = high if high is not None else max(o, close) * 1.01
    l = low if low is not None else min(o, close) * 0.99
    return MarketDailyOhlcv(
        bar_id=new_uuid(), symbol="600519.SH", trade_date=d.isoformat(),
        open=o, high=h, low=l, close=close, volume=volume, amount=amount,
    )


def _series(start: date, n: int, base: float = 10.0,
            daily_ret: float = 0.001, vol_mult: float = 1.0) -> list:
    """生成 n 个连续交易日（跳过周末）的价格序列。"""
    bars = []
    d = start
    price = base
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        bars.append(_bar(d, price, volume=1000 * vol_mult, amount=price * 1000 * vol_mult))
        price *= (1 + daily_ret)
        d += timedelta(days=1)
    return bars


def _request(analysis_date: str = "2026-08-05") -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID, task_id=UUID, entity_id="600519.SH",
        entity_type="company", analysis_date=analysis_date,
        window_start="2026-07-01", window_end=analysis_date,
        as_of=f"{analysis_date}T20:00:00",
    )


class TestReturns:
    def test_pct_change_manual(self):
        prices = [10.0, 11.0, 9.9]
        r = pct_change(prices)
        assert r[0] is None
        assert abs(r[1] - 0.10) < 1e-9
        assert abs(r[2] - (-0.10)) < 1e-9

    def test_pct_change_zero_prev(self):
        r = pct_change([0.0, 10.0])
        assert r[1] is None


class TestRobustStats:
    def test_median_mad_manual(self):
        hist = [1.0, 2.0, 3.0, 4.0, 5.0]
        med, mad = robust_stats(hist)
        assert med == 3.0
        assert mad == 1.0  # |x-3|: 2,1,0,1,2 -> median=1

    def test_robust_z_manual(self):
        # median=3, mad=1 -> z = (8-3)/(1.4826*1) ≈ 3.3724
        z = robust_z_score(8.0, 3.0, 1.0)
        assert abs(z - 8.0 / 1.4826 + 3.0 / 1.4826) < 1e-6

    def test_mad_zero_returns_none(self):
        assert robust_z_score(5.0, 5.0, 0.0) is None

    def test_percentile(self):
        hist = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert historical_percentile(3.0, hist) == 60.0
        assert historical_percentile(5.0, hist) == 100.0
        assert historical_percentile(0.5, hist) == 0.0


class TestSeverity:
    def test_severity_table_boundaries(self):
        # 任务书 7.4 表：双侧分位
        assert severity_from_percentile(79.0) == 0
        assert severity_from_percentile(80.0) == 1
        assert severity_from_percentile(90.0) == 2
        assert severity_from_percentile(95.0) == 3
        assert severity_from_percentile(97.5) == 4
        assert severity_from_percentile(99.0) == 5

    def test_severity_z_boundaries(self):
        assert severity_from_z(1.28) == 1
        assert severity_from_z(1.65) == 2
        assert severity_from_z(1.96) == 3
        assert severity_from_z(2.24) == 4
        assert severity_from_z(2.58) == 5
        assert severity_from_z(0.5) == 0

    def test_winsorize(self):
        values = [1.0, 2.0, 3.0, 100.0]
        out = winsorize(values)
        assert max(out) <= 100.0
        assert min(out) >= 1.0


class TestStreakAndVol:
    def test_streak_detection(self):
        r = [None, 0.01, 0.01, 0.01, -0.02, 0.01]
        info = streak_info(r, 3)
        assert info["streak_direction"] == "up"
        assert info["streak_length"] == 3
        assert abs(info["cumulative_return"] - (1.01 ** 3 - 1)) < 1e-6

    def test_rolling_returns(self):
        r = [None, 0.01, 0.02, 0.03]
        rv = rolling_returns(r)
        assert rv[0] is None
        assert abs(rv[3] - math.sqrt(0.01 ** 2 + 0.02 ** 2 + 0.03 ** 2)) < 1e-9

    def test_beta_residual_basic(self):
        e = [0.01 * i for i in range(50)]
        m = [0.01 * i for i in range(50)]
        # 完全线性 -> 残差接近 0
        res = beta_adjusted_residual(e, m, None, 49)
        assert res is not None
        assert abs(res) < 1e-6

    def test_beta_residual_insufficient(self):
        e = [0.01] * 10
        m = [0.01] * 10
        assert beta_adjusted_residual(e, m, None, 9) is None


class TestDetector:
    def test_flat_market_no_abnormal(self):
        bars = _series(date(2026, 5, 1), 70)
        result = AnomalyDetector(_request()).detect(bars)
        assert result.abnormal is False
        assert result.observation.status == "no_abnormal_move"
        assert result.sample_size == 70

    def test_big_move_detected_rule_a(self):
        bars = _series(date(2026, 5, 1), 65)
        # 最后一天 +9.5% 且放量 3 倍
        last = bars[-1]
        prev_close = bars[-2].close
        bars[-1] = _bar(date.fromisoformat(last.trade_date),
                        close=prev_close * 1.095, volume=3000,
                        amount=prev_close * 1.095 * 3000)
        result = AnomalyDetector(_request()).detect(bars)
        assert result.abnormal is True
        assert any(r.startswith("A") for r in result.reasons)
        ret_m = [m for m in result.metrics if m.metric_type == "absolute_return"][0]
        assert ret_m.severity >= 3
        vol_m = [m for m in result.metrics if m.metric_type == "volume_anomaly"][0]
        assert vol_m.severity >= 2

    def test_rule_b_severity_5(self):
        bars = _series(date(2026, 5, 1), 65)
        last = bars[-1]
        prev_close = bars[-2].close
        bars[-1] = _bar(date.fromisoformat(last.trade_date),
                        close=prev_close * 1.12, volume=5000)
        result = AnomalyDetector(_request()).detect(bars)
        assert result.abnormal is True
        assert any(r.startswith("B") for r in result.reasons)

    def test_sample_insufficient(self):
        bars = _series(date(2026, 5, 1), 10)
        result = AnomalyDetector(_request()).detect(bars)
        assert result.abnormal is False
        assert "NEW_LISTING" in result.observation.market_state_flags
        assert result.observation.confidence <= 0.4
        assert result.observation.missing_data

    def test_suspended_no_move(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(bars, flags={"suspended": True})
        assert result.abnormal is False
        assert result.observation.status == "suspended_no_move"

    def test_resumption_flag(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(bars, flags={"resumption": True})
        assert "RESUMPTION" in result.observation.market_state_flags

    def test_st_and_price_limit_flags(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(
            bars, flags={"st": True, "price_limit": "up"})
        flags = result.observation.market_state_flags
        assert "ST" in flags and "PRICE_LIMIT_UP" in flags

    def test_ex_rights_flag(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(
            bars, flags={"ex_rights": True, "ex_dividend": True})
        assert "EX_RIGHTS" in result.observation.market_state_flags

    def test_provisional_session(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(
            bars, flags={"provisional": True})
        assert result.observation.provisional is True
        assert "CURRENT_SESSION_NOT_CLOSED" in result.observation.market_state_flags

    def test_mixed_adjustment_lowers_confidence(self):
        bars = _series(date(2026, 5, 1), 65)
        result = AnomalyDetector(_request()).detect(
            bars, flags={"mixed_adjustment": True})
        assert "MIXED_ADJUSTMENT" in result.observation.market_state_flags
        assert result.observation.confidence <= 0.4

    def test_metrics_have_observation_id_and_pass_schema(self):
        from research_os.validators.schema_validator import validate_model

        bars = _series(date(2026, 5, 1), 70)
        result = AnomalyDetector(_request()).detect(bars)
        assert validate_model(result.observation) == []
        for m in result.metrics:
            assert m.observation_id == result.observation.observation_id
            assert validate_model(m) == []

    def test_benchmark_relative_return(self):
        bars = _series(date(2026, 5, 1), 65)
        market_bars = _series(date(2026, 5, 1), 65, base=3000.0)
        # 市场最后一天 +5%，个股最后一天 +9.5% -> 相对收益为正
        prev_m = market_bars[-2].close
        market_bars[-1] = _bar(date.fromisoformat(market_bars[-1].trade_date),
                               close=prev_m * 1.05, volume=1000)
        result = AnomalyDetector(_request()).detect(
            bars, benchmarks={"market": market_bars})
        rel = [m for m in result.metrics if m.metric_type == "market_excess_return"]
        assert rel, "应输出 market_excess_return"
        assert rel[0].value is not None

    def test_mad_zero_fallback(self):
        """历史收益率全同 -> MAD=0 -> 回退分位，写入 MAD_ZERO_FALLBACK_PERCENTILE。"""
        bars = []
        d = date(2026, 5, 1)
        price = 10.0
        for _ in range(65):
            while d.weekday() >= 5:
                d += timedelta(days=1)
            bars.append(_bar(d, price, volume=1000))
            d += timedelta(days=1)
        # 最后一天突变
        bars[-1] = _bar(date.fromisoformat(bars[-1].trade_date),
                        close=price * 1.05, volume=2000)
        result = AnomalyDetector(_request()).detect(bars)
        ret_m = [m for m in result.metrics if m.metric_type == "absolute_return"][0]
        assert ret_m.robust_z is None or any(
            "MAD_ZERO" in w for w in ret_m.warnings)
        assert ret_m.historical_percentile is not None


class TestWindow:
    def test_explicit_non_trading_day_errors(self):
        calendar = TradingCalendar()
        # 2026-08-08 是周六
        with pytest.raises(WindowError, match="不是交易日"):
            resolve_window("2026-08-08", calendar)

    def test_explicit_trading_day_ok(self):
        calendar = TradingCalendar()
        w = resolve_window("2026-08-07", calendar)
        assert w.analysis_date.isoformat() == "2026-08-07"

    def test_default_uses_latest_available(self):
        calendar = TradingCalendar()
        w = resolve_window(None, calendar)
        assert calendar.is_trading_day(w.analysis_date)

    def test_invalid_date_format(self):
        calendar = TradingCalendar()
        with pytest.raises(WindowError, match="非法"):
            resolve_window("2026/08/05", calendar)
