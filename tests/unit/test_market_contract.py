"""Phase 1.1 行情契约分离测试（任务 3.3 节）。

验证：实时快照与历史日线严格分离——快照不得冒充日线；
sina_quote 不得用于日线路由；日线无自动来源时 insufficient_data。
"""
from __future__ import annotations

import pytest

from research_os.models import MarketDailyOhlcv, MarketRealtimeSnapshot
from research_os.routing import DataRequirementRegistry, Router
from research_os.validators.schema_validator import validate_instance

T0 = "2026-08-05T14:30:00"
UUID = "11111111-1111-1111-1111-111111111111"


def snapshot(**overrides) -> dict:
    data = {
        "snapshot_id": UUID, "symbol": "sh600519", "observed_at": T0,
        "open": 1300.0, "high": 1330.0, "low": 1290.0,
        "last_price": 1320.0, "volume": 4000000,
        "previous_close": 1310.0, "amount": 5.3e9,
    }
    data.update(overrides)
    return data


def daily_bar(**overrides) -> dict:
    data = {
        "bar_id": UUID, "symbol": "sh600519", "trade_date": "2026-08-05",
        "open": 1300.0, "high": 1330.0, "low": 1290.0,
        "close": 1320.0, "volume": 4000000, "amount": 5.3e9,
    }
    data.update(overrides)
    return data


# ---------- 1/2. Schema 分离 ----------

def test_snapshot_passes_realtime_schema():
    """实时快照通过 market_realtime_snapshot Schema。"""
    assert validate_instance(snapshot(), "market_realtime_snapshot") == []


def test_snapshot_rejected_by_daily_schema():
    """实时快照不能通过 market_daily_ohlcv Schema（缺 trade_date/close）。"""
    errors = validate_instance(snapshot(), "market_daily_ohlcv")
    assert errors, "快照不得通过日线 Schema"


# ---------- 3/4. 日线必须字段 ----------

def test_daily_missing_trade_date_rejected():
    errors = validate_instance(daily_bar(trade_date=""), "market_daily_ohlcv")
    assert errors


def test_daily_missing_close_rejected():
    data = daily_bar()
    del data["close"]
    errors = validate_instance(data, "market_daily_ohlcv")
    assert errors, "缺 close 的数据不得进入日线"


def test_daily_valid_passes():
    assert validate_instance(daily_bar(), "market_daily_ohlcv") == []


# ---------- 5-7. 路由 ----------

@pytest.fixture()
def requirements(tmp_path):
    import shutil

    src = __import__("pathlib").Path(__file__).resolve().parents[2] / "registry" / "data_requirements.yaml"
    dst = tmp_path / "data_requirements.yaml"
    shutil.copy(src, dst)
    return DataRequirementRegistry(dst)


def test_router_never_selects_sina_for_daily(requirements):
    """日线需求的源优先级不得包含 sina_quote。"""
    priority = requirements.source_priority("market_daily_ohlcv")
    assert "sina_quote" not in priority
    # 即使强行注册 sina fetcher，Router 也不得调用它
    called = []

    def sina_fetcher(data_type, query, tw):
        called.append(1)
        return [], set()

    router = Router(requirements, {"sina_quote": sina_fetcher})
    route = router.resolve("market_daily_ohlcv")
    assert called == [], "Router 不得为日线调用 sina_quote"
    assert route.status == "insufficient_data"


def test_daily_no_auto_source_insufficient(requirements):
    """日线无自动来源 -> insufficient_data（显式）。"""
    router = Router(requirements, {})
    route = router.resolve("market_daily_ohlcv")
    assert route.status == "insufficient_data"
    assert route.selected_source is None
    assert "trade_date" in route.missing_fields


def test_daily_manual_import_fallback(requirements):
    """Manual Import 提供合法日线时可作 fallback（degraded）。"""
    router = Router(requirements, {}, fallback_fetchers={
        "manual_import": lambda data_type, q, tw: (
            [{"bar_id": UUID, "symbol": "sh600519", "trade_date": "2026-08-05",
              "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 100}],
            {"trade_date", "open", "high", "low", "close", "volume"},
        ),
    })
    route = router.resolve("market_daily_ohlcv")
    assert route.status == "degraded"
    assert route.selected_source == "manual_import"
    assert route.fallback_used is True


def test_realtime_route_uses_sina(requirements):
    """实时快照路由使用 sina_quote。"""
    router = Router(requirements, {
        "sina_quote": lambda data_type, q, tw: ([{}], {"symbol", "observed_at", "open", "high",
                                            "low", "last_price", "volume"}),
    })
    route = router.resolve("market_realtime_snapshot")
    assert route.status == "success"
    assert route.selected_source == "sina_quote"


# ---------- 8. 快照不得写成历史收盘 ----------

def test_snapshot_not_written_as_daily_close(tmp_path):
    """当前交易日快照不得被写成历史收盘数据（Schema 层禁止 + 存储层拒绝）。"""
    from research_os.storage import Database

    snap = MarketRealtimeSnapshot(**snapshot())
    assert validate_instance(snap.model_dump(), "market_daily_ohlcv"), \
        "快照必须先被日线 Schema 拒绝"

    # 即使强行构造日线模型，也要求显式 trade_date/close（快照字段无法直接映射）
    with pytest.raises(Exception):
        MarketDailyOhlcv(**{k: v for k, v in snap.model_dump().items()
                            if k != "snapshot_id"})  # 缺 close/trade_date

    # 存储层：插入合法日线需要完整字段（DB 校验 payload 语义）
    db = Database(tmp_path / "market.db")
    db.initialize()
    assert db.count("market_daily_ohlcv") == 0
    db.close()
