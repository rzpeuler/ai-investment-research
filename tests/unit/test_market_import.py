"""人工日线导入与统一日线接口测试（Phase 3 任务书 3.1-3.4 节）。"""
from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path

import pytest

from research_os.abnormal_move.market_data_loader import (
    DailyImportService,
    DailyRowValidator,
    MarketDataLoader,
    TradingCalendar,
)
from research_os.storage import Database


@pytest.fixture()
def db(tmp_path) -> Database:
    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


def _csv(tmp_path: Path, name: str, rows: list) -> Path:
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=[
            "symbol", "trade_date", "open", "high", "low", "close", "volume",
        ])
        writer.writeheader()
        writer.writerows(rows)
    return path


def _rows(start: str, end: str, symbol: str = "600519.SH", close: float = 10.0):
    """生成 start..end 的连续工作日行。"""
    from datetime import timedelta

    d = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    out = []
    while d <= stop:
        if d.weekday() < 5:
            out.append({
                "symbol": symbol, "trade_date": d.isoformat(),
                "open": close, "high": close + 0.1, "low": close - 0.1,
                "close": close, "volume": 1000,
            })
        d += timedelta(days=1)
    return out


class TestTradingCalendar:
    def test_weekday_is_trading_day(self):
        cal = TradingCalendar()
        assert cal.is_trading_day(date(2026, 8, 3))  # 周一
        assert not cal.is_trading_day(date(2026, 8, 8))  # 周六
        assert not cal.is_trading_day(date(2026, 8, 9))  # 周日

    def test_holidays_excluded(self):
        cal = TradingCalendar(holidays={"2026-08-03"})
        assert not cal.is_trading_day(date(2026, 8, 3))

    def test_previous_and_next(self):
        cal = TradingCalendar()
        # 2026-08-03 是周一，前一个交易日是 07-31（周五）
        assert cal.previous_trading_day(date(2026, 8, 3)).isoformat() == "2026-07-31"
        assert cal.next_trading_day(date(2026, 8, 7)).isoformat() == "2026-08-10"

    def test_trading_days_between(self):
        cal = TradingCalendar()
        days = cal.trading_days_between(date(2026, 8, 6), date(2026, 8, 10))
        assert [d.isoformat() for d in days] == ["2026-08-06", "2026-08-07", "2026-08-10"]


class TestDailyRowValidator:
    def test_valid_row(self):
        cal = TradingCalendar()
        seen = set()
        check = DailyRowValidator(cal).check_row(
            {"symbol": "600519.SH", "trade_date": "2026-08-03",
             "open": 10, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100},
            seen,
        )
        assert not check.rejected
        assert check.issues == []

    def test_bad_date(self):
        seen = set()
        check = DailyRowValidator(TradingCalendar()).check_row(
            {"symbol": "600519.SH", "trade_date": "2026-13-99",
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}, seen)
        assert check.rejected

    def test_ohlc_violation(self):
        seen = set()
        check = DailyRowValidator(TradingCalendar()).check_row(
            {"symbol": "600519.SH", "trade_date": "2026-08-03",
             "open": 10, "high": 9, "low": 8, "close": 10, "volume": 100}, seen)
        assert check.rejected
        assert any("OHLC" in i for i in check.issues)

    def test_negative_price(self):
        seen = set()
        check = DailyRowValidator(TradingCalendar()).check_row(
            {"symbol": "600519.SH", "trade_date": "2026-08-03",
             "open": -10, "high": 11, "low": 9, "close": 10, "volume": 100}, seen)
        assert check.rejected
        assert any("负值" in i for i in check.issues)

    def test_duplicate_key(self):
        cal = TradingCalendar()
        seen = set()
        row = {"symbol": "600519.SH", "trade_date": "2026-08-03",
               "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}
        first = DailyRowValidator(cal).check_row(row, seen)
        second = DailyRowValidator(cal).check_row(row, seen)
        assert not first.rejected
        assert second.rejected
        assert any("重复键" in i for i in second.issues)

    def test_weekend_date_warns(self):
        seen = set()
        check = DailyRowValidator(TradingCalendar()).check_row(
            {"symbol": "600519.SH", "trade_date": "2026-08-08",  # 周六
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100}, seen)
        assert check.rejected
        assert any("非交易日" in i for i in check.issues)


class TestDailyImportService:
    def test_dry_run_zero_side_effect(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        service = DailyImportService(db)
        before_tables = {t: db.count(t) for t in
                         ("market_daily_series_manifests", "market_daily_import_rows",
                          "market_daily_ohlcv")}
        result = service.import_file(path, dry_run=True)
        assert result.persisted is False
        assert result.manifest is None
        assert result.validation_status == "preview"
        assert result.preview.rows_total == 5
        assert result.preview.rows_accepted == 5
        assert result.preview.date_start == "2026-08-03"
        assert result.preview.date_end == "2026-08-07"
        after_tables = {t: db.count(t) for t in before_tables}
        assert before_tables == after_tables, "dry-run 不得产生任何数据库副作用"

    def test_import_writes_manifest_rows_and_bars(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        service = DailyImportService(db)
        result = service.import_file(path, adjustment="qfq", imported_by="tester")
        assert result.persisted is True
        assert result.written_rows == 5
        assert result.validation_status == "accepted"
        assert db.count("market_daily_series_manifests") == 1
        assert db.count("market_daily_import_rows") == 5
        assert db.count("market_daily_ohlcv") == 5

        manifest = db.get("market_daily_series_manifests", result.manifest.import_id)
        assert manifest["adjustment_method"] == "qfq"
        assert manifest["validation_status"] == "accepted"
        assert manifest["symbols"] == ["600519.SH"]

    def test_rejected_rows_not_written_to_official_table(self, db, tmp_path):
        rows = _rows("2026-08-03", "2026-08-07")
        rows.append({"symbol": "600519.SH", "trade_date": "2026-08-10",
                     "open": 10, "high": 5, "low": 9, "close": 10, "volume": 100})  # OHLC 违反
        path = _csv(tmp_path, "bad.csv", rows)
        service = DailyImportService(db)
        result = service.import_file(path)
        assert result.validation_status == "rejected"
        assert result.preview.rows_rejected == 1
        assert result.written_rows == 5
        assert db.count("market_daily_ohlcv") == 5, "rejected 行不得写入正式日线表"
        assert db.count("market_daily_import_rows") == 6, "所有行进入 import_rows 留痕"

    def test_missing_required_column_fails(self, db, tmp_path):
        path = tmp_path / "missing.csv"
        with path.open("w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=["symbol", "trade_date", "close"])
            writer.writeheader()
            writer.writerow({"symbol": "600519.SH", "trade_date": "2026-08-03", "close": 10})
        service = DailyImportService(db)
        with pytest.raises(ValueError, match="缺少必填列"):
            service.import_file(path)

    def test_unsupported_format_fails_clearly(self, db, tmp_path):
        path = tmp_path / "data.xlsx"
        path.write_text("x", encoding="utf-8")
        service = DailyImportService(db)
        with pytest.raises(ValueError, match="不支持的文件格式"):
            service.import_file(path)

    def test_gap_warning_detected(self, db, tmp_path):
        rows = [
            {"symbol": "600519.SH", "trade_date": "2026-08-03",
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"symbol": "600519.SH", "trade_date": "2026-08-05",  # 跳过 08-04
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
        ]
        path = _csv(tmp_path, "gap.csv", rows)
        service = DailyImportService(db)
        result = service.import_file(path, dry_run=True)
        assert any("缺失交易日" in w for w in result.preview.warnings)

    def test_invalid_adjustment_rejected(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        service = DailyImportService(db)
        with pytest.raises(ValueError, match="复权口径非法"):
            service.import_file(path, adjustment="xxx")


class TestMarketDataLoader:
    def test_load_daily_returns_sorted_bars(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        DailyImportService(db).import_file(path)
        loader = MarketDataLoader(db)
        bars = loader.load_daily("600519.SH")
        assert len(bars) == 5
        assert [b.trade_date for b in bars] == sorted(b.trade_date for b in bars)
        assert bars[0].close == 10.0

    def test_load_daily_window_filter(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-14"))
        DailyImportService(db).import_file(path)
        loader = MarketDataLoader(db)
        bars = loader.load_daily("600519.SH", start="2026-08-10", end="2026-08-14")
        assert len(bars) == 5
        assert bars[0].trade_date == "2026-08-10"

    def test_available_dates_and_latest(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        DailyImportService(db).import_file(path)
        loader = MarketDataLoader(db)
        assert loader.available_dates("600519.SH") == [
            "2026-08-03", "2026-08-04", "2026-08-05", "2026-08-06", "2026-08-07"]
        assert loader.latest_trade_date("600519.SH") == "2026-08-07"

    def test_no_data_returns_empty(self, db):
        loader = MarketDataLoader(db)
        assert loader.load_daily("000001.SZ") == []
        assert loader.latest_trade_date("000001.SZ") is None

    def test_reimport_same_key_does_not_overwrite(self, db, tmp_path):
        path = _csv(tmp_path, "ok.csv", _rows("2026-08-03", "2026-08-07"))
        service = DailyImportService(db)
        r1 = service.import_file(path)
        result = service.import_file(path)  # 重复导入同批
        assert r1.written_rows == 5
        assert result.written_rows == 0
        assert result.preview.rows_rejected == 0  # 文件内无重复
        assert db.count("market_daily_ohlcv") == 5, "不得覆盖或重复写入既有日线"
        assert any("键冲突" in w for w in result.manifest.warnings), \
            "键冲突必须显式提示，不得静默"
