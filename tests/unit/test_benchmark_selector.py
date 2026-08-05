"""基准选择与板块联动测试（Phase 3 任务书 8、7.9-7.10 节）。"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from research_os.abnormal_move.benchmark_selector import (
    BenchmarkSelector,
    MarketBenchmarkRegistry,
    board_of,
)
from research_os.abnormal_move.peer_linkage_analyzer import PeerLinkageAnalyzer
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AnomalyMetric,
    MarketDailyOhlcv,
)
from research_os.utils.id import new_uuid

UUID = "12345678-1234-1234-1234-123456789abc"


def _bar(d: date, close: float) -> MarketDailyOhlcv:
    return MarketDailyOhlcv(
        bar_id=new_uuid(), symbol="T", trade_date=d.isoformat(),
        open=close, high=close * 1.01, low=close * 0.99,
        close=close, volume=1000,
    )


def _series(start: date, n: int, base: float = 10.0, drift: float = 0.001,
            vol: float = 0.0, noise: float = 0.0005) -> list:
    """生成 n 个连续交易日序列。noise>0 时收益率带周期波动（方差>0，相关性可算）。"""
    bars = []
    d = start
    price = base
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        jump = price * vol if vol else 0.0
        pattern = (i % 3) - 1  # -1, 0, 1 循环
        bars.append(_bar(d, price + jump))
        price *= (1 + drift + pattern * noise)
        d += timedelta(days=1)
    return bars


def _request() -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID, task_id=UUID, entity_id="600519.SH",
        entity_type="company", analysis_date="2026-08-05",
        window_start="2026-08-01", window_end="2026-08-05",
        as_of="2026-08-05T20:00:00",
    )


class TestBoardOf:
    def test_main_board(self):
        assert board_of("600519.SH") == "main"
        assert board_of("000858.SZ") == "main"

    def test_gem(self):
        assert board_of("300750.SZ") == "gem"

    def test_star(self):
        assert board_of("688981.SH") == "star"


class TestMarketBenchmarkRegistry:
    def test_load_and_select(self, tmp_path):
        reg = MarketBenchmarkRegistry(Path(tmp_path))
        # 用真实 registry 文件
        reg = MarketBenchmarkRegistry(Path("registry") / "market_benchmarks.yaml")
        assert reg.select_for_board("main") is not None
        assert reg.select_for_board("gem") == "index:399006.SZ"
        assert reg.select_for_board("star") == "index:000688.SH"


class TestBenchmarkSelector:
    def _selector(self):
        return BenchmarkSelector(MarketBenchmarkRegistry(
            Path("registry") / "market_benchmarks.yaml"))

    def test_industry_eligible_and_selected(self):
        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 160)
        bench_bars = _series(date(2026, 1, 1), 160, base=100.0, drift=0.001)
        concept_bars = _series(date(2026, 1, 1), 160, base=1000.0, drift=0.0008)
        req = _request()
        result = sel.select(
            req, "600519.SH",
            candidate_inputs=[
                {
                    "benchmark_entity_id": "industry:白酒",
                    "benchmark_type": "industry",
                    "relationship_valid_from": "2020-01-01",
                    "stable_industry_score": 5,
                    "main_business_score": 5,
                    "supply_chain_score": 3,
                    "preexisting_concept_score": 0,
                },
                {
                    "benchmark_entity_id": "concept:白酒概念",
                    "benchmark_type": "concept",
                    "relationship_valid_from": "2020-01-01",
                    "stable_industry_score": 4,
                    "main_business_score": 4,
                    "supply_chain_score": 4,
                    "preexisting_concept_score": 4,
                },
            ],
            entity_bars=entity_bars,
            benchmark_bars={"industry:白酒": bench_bars,
                            "concept:白酒概念": concept_bars},
            observation_id=UUID,
        )
        assert result.fallback_status == "full"
        assert result.industry_benchmark_id == "industry:白酒"
        assert result.concept_benchmark_ids == ["concept:白酒概念"]
        cand = result.candidates[0]
        assert cand.eligible is True
        assert cand.pre_window_subtotal >= 45.0
        # stable(25) + main(20) + supply(6) + corr(15) = 66 分
        assert cand.total_score >= 60.0

    def test_concept_after_window_rejected(self):
        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 120)
        bench_bars = _series(date(2026, 1, 1), 120, base=100.0)
        req = _request()
        result = sel.select(
            req, "600519.SH",
            candidate_inputs=[{
                "benchmark_entity_id": "concept:白酒概念",
                "benchmark_type": "concept",
                "relationship_valid_from": "2026-08-04",  # 晚于窗口开始 08-01
                "stable_industry_score": 5,
                "main_business_score": 5,
                "supply_chain_score": 5,
                "preexisting_concept_score": 5,
            }],
            entity_bars=entity_bars,
            benchmark_bars={"concept:白酒概念": bench_bars},
            observation_id=UUID,
        )
        cand = result.candidates[0]
        assert cand.eligible is False
        assert any("事后选择" in e for e in cand.exclusion_reasons)
        assert result.fallback_status != "full"

    def test_pre_window_subtotal_gate(self):
        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 120)
        bench_bars = _series(date(2026, 1, 1), 120, base=100.0)
        req = _request()
        # 窗口前维度全 0（只有事件期联动高）-> pre_window_subtotal=0 < 45
        result = sel.select(
            req, "600519.SH",
            candidate_inputs=[{
                "benchmark_entity_id": "concept:X",
                "benchmark_type": "concept",
                "relationship_valid_from": "2020-01-01",
                "stable_industry_score": 0,
                "main_business_score": 0,
                "supply_chain_score": 0,
                "preexisting_concept_score": 0,
            }],
            entity_bars=entity_bars,
            benchmark_bars={"concept:X": bench_bars},
            observation_id=UUID,
        )
        cand = result.candidates[0]
        assert cand.eligible is False
        assert any("窗口前已知关系小计" in e for e in cand.exclusion_reasons)

    def test_industry_stable_business_gate(self):
        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 160)
        bench_bars = _series(date(2026, 1, 1), 160, base=100.0)
        req = _request()
        result = sel.select(
            req, "600519.SH",
            candidate_inputs=[{
                "benchmark_entity_id": "industry:白酒",
                "benchmark_type": "industry",
                "relationship_valid_from": "2020-01-01",
                "stable_industry_score": 2,
                "main_business_score": 2,
                "supply_chain_score": 5,
                "preexisting_concept_score": 5,
                "current_event_relevance_score": 2,
            }],
            entity_bars=entity_bars,
            benchmark_bars={"industry:白酒": bench_bars},
            observation_id=UUID,
        )
        cand = result.candidates[0]
        # pre_window = 10+8+10+10+15 = 53 >= 45；total = 53+linkage(5)+currel(2) = 60 >= 60；
        # stable_business = 10+8 = 18 < 25 -> 拒绝
        assert cand.eligible is False
        assert any("稳定行业+主营" in e for e in cand.exclusion_reasons)

    def test_fallback_market_only(self):
        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 120)
        req = _request()
        result = sel.select(
            req, "600519.SH", candidate_inputs=[], entity_bars=entity_bars,
            benchmark_bars={},
            observation_id=UUID,
        )
        assert result.fallback_status == "market_only"
        assert result.market_benchmark_id is not None
        assert result.industry_benchmark_id is None

    def test_selection_schema_and_cutoff(self):
        from research_os.validators.schema_validator import validate_model

        sel = self._selector()
        entity_bars = _series(date(2026, 1, 1), 120)
        bench_bars = _series(date(2026, 1, 1), 120, base=100.0)
        req = _request()
        result = sel.select(
            req, "600519.SH",
            candidate_inputs=[{
                "benchmark_entity_id": "industry:白酒",
                "benchmark_type": "industry",
                "relationship_valid_from": "2020-01-01",
                "stable_industry_score": 5,
                "main_business_score": 5,
                "supply_chain_score": 3,
                "preexisting_concept_score": 4,
            }],
            entity_bars=entity_bars,
            benchmark_bars={"industry:白酒": bench_bars},
            observation_id=UUID,
        )
        assert validate_model(result.selection) == []
        # information_cutoff 必须 <= 窗口开始
        assert result.selection.information_cutoff <= "2026-08-01T23:59:59"
        for c in result.candidates:
            assert validate_model(c) == []


class TestPeerLinkageAnalyzer:
    def _observation(self, raw_return: float = 0.06) -> AbnormalMoveObservation:
        return AbnormalMoveObservation(
            observation_id=UUID, request_id=UUID, entity_id="600519.SH",
            entity_type="company", window_start="2026-08-01",
            window_end="2026-08-05", trade_date="2026-08-05",
            raw_return=raw_return,
        )

    def test_breadth_and_median(self):
        analyzer = PeerLinkageAnalyzer()
        peers = {}
        for i in range(12):
            bars = _series(date(2026, 1, 1), 80, base=10.0 + i, drift=0.001)
            # 10/12 家上涨
            if i < 10:
                last = bars[-1]
                bars[-1] = _bar(date.fromisoformat(last.trade_date),
                                close=last.close * 1.04)
            peers[f"peer:{i}"] = bars
        result = analyzer.analyze(self._observation(), peers)
        assert result.sample_ok is True
        assert result.effective_peers == 12
        assert result.advancing_ratio >= 0.8
        assert result.peer_median_return > 0
        assert len(result.peer_moves) == 12
        assert any(m.metric_type == "peer_breadth" for m in result.metrics)

    def test_insufficient_peers(self):
        analyzer = PeerLinkageAnalyzer()
        peers = {f"peer:{i}": _series(date(2026, 1, 1), 80) for i in range(3)}
        result = analyzer.analyze(self._observation(), peers)
        assert result.sample_ok is False
        assert any("有效同行数" in w for w in result.warnings)
        breadth = [m for m in result.metrics if m.metric_type == "peer_breadth"][0]
        assert breadth.status == "insufficient_sample"

    def test_cross_sectional_percentile(self):
        analyzer = PeerLinkageAnalyzer()
        peers = {}
        for i in range(10):
            bars = _series(date(2026, 1, 1), 80, base=10.0 + i)
            last = bars[-1]
            bars[-1] = _bar(date.fromisoformat(last.trade_date),
                            close=last.close * (1.0 + 0.005 * (i + 1)))
            peers[f"peer:{i}"] = bars
        result = analyzer.analyze(self._observation(raw_return=0.06), peers)
        assert result.subject_cross_sectional_percentile == 100.0

    def test_idiosyncratic_detected(self):
        analyzer = PeerLinkageAnalyzer()
        peers = {}
        for i in range(12):
            bars = _series(date(2026, 1, 1), 80, base=10.0 + i)
            last = bars[-1]
            # 板块中位收益接近 0（半数微涨半数微跌）
            change = 0.002 if i % 2 == 0 else -0.002
            bars[-1] = _bar(date.fromisoformat(last.trade_date),
                            close=last.close * (1.0 + change))
            peers[f"peer:{i}"] = bars
        # 对象 +6%（横截面分位 100%），板块中位接近 0（severity<=1）
        metric_by_type = {
            "industry_excess_return": AnomalyMetric(
                metric_id=new_uuid(), observation_id=UUID,
                metric_type="industry_excess_return", value=0.05, unit="pct",
                direction="positive", severity=5, sample_size=60,
                minimum_sample_size=40, status="valid",
                calculation_version="anomaly.v1"),
        }
        result = analyzer.analyze(self._observation(raw_return=0.06), peers,
                                  metric_by_type=metric_by_type)
        assert result.idiosyncratic is True
        assert any(m.metric_type == "idiosyncratic_move" for m in result.metrics)

    def test_peer_moves_schema(self):
        from research_os.validators.schema_validator import validate_model

        analyzer = PeerLinkageAnalyzer()
        peers = {f"peer:{i}": _series(date(2026, 1, 1), 80) for i in range(10)}
        result = analyzer.analyze(self._observation(), peers)
        obs = self._observation()
        obs.peer_moves = result.peer_moves
        obs.metric_ids = [m.metric_id for m in result.metrics]
        assert validate_model(obs) == []
        for m in result.metrics:
            assert validate_model(m) == []

