-- Phase 1 迁移：来源层数据底座。
-- sources 与 raw_items 已在 001 建立，此处新增来源探测、健康、路由与人工 inbox。

CREATE TABLE IF NOT EXISTS source_probes (
    probe_id    TEXT PRIMARY KEY,
    source_id   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL,
    started_at  TEXT,
    finished_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_probes_source ON source_probes(source_id);

CREATE TABLE IF NOT EXISTS source_health (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL,
    checked_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_health_source ON source_health(source_id, checked_at);

CREATE TABLE IF NOT EXISTS data_routes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    data_type     TEXT NOT NULL,
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL,
    selected_source TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_routes_type ON data_routes(data_type);

CREATE TABLE IF NOT EXISTS manual_inbox (
    inbox_id    TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    source_name TEXT NOT NULL,
    status      TEXT NOT NULL,
    submitted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_inbox_status ON manual_inbox(status);
