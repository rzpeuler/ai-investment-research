-- Phase 1.1 迁移：行情数据契约分离。
-- 实时快照表与历史日线表严格分离；日线必须含 trade_date/close（由 Schema 保证，
-- 表结构仅为存储，写入前必须通过对应 Schema 校验）。

CREATE TABLE IF NOT EXISTS market_realtime_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    observed_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_snapshots_symbol ON market_realtime_snapshots(symbol, observed_at);

CREATE TABLE IF NOT EXISTS market_daily_ohlcv (
    bar_id      TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    close       REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_daily_symbol_date ON market_daily_ohlcv(symbol, trade_date);
