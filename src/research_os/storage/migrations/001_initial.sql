-- Phase 0 初始迁移：核心对象表。
-- 约定：所有核心对象以 JSON payload 整行存储（与 JSON Schema 契约一致），
-- 关键字段拆出独立列用于查询/索引。payload 写入前必须通过对应 Schema 校验。

CREATE TABLE IF NOT EXISTS tasks (
    task_id     TEXT PRIMARY KEY,
    payload     TEXT NOT NULL,
    status      TEXT NOT NULL,
    scenario    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entities (
    entity_id      TEXT PRIMARY KEY,
    payload        TEXT NOT NULL,
    entity_type    TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    valid_from     TEXT,
    valid_to       TEXT
);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name ON entities(canonical_name);

CREATE TABLE IF NOT EXISTS raw_items (
    raw_item_id   TEXT PRIMARY KEY,
    payload       TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    published_at  TEXT,
    retrieved_at  TEXT,
    access_status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_raw_items_source ON raw_items(source_id);
CREATE INDEX IF NOT EXISTS idx_raw_items_hash ON raw_items(content_hash);

CREATE TABLE IF NOT EXISTS events (
    event_id   TEXT PRIMARY KEY,
    payload    TEXT NOT NULL,
    event_type TEXT NOT NULL,
    event_time TEXT,
    status     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_time ON events(event_time);

CREATE TABLE IF NOT EXISTS opinions (
    opinion_id       TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    speaker_entity_id TEXT NOT NULL,
    stance           TEXT NOT NULL,
    published_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_opinions_speaker ON opinions(speaker_entity_id);

CREATE TABLE IF NOT EXISTS claims (
    claim_id      TEXT PRIMARY KEY,
    payload       TEXT NOT NULL,
    claim_type    TEXT NOT NULL,
    review_status TEXT NOT NULL,
    as_of         TEXT
);
CREATE INDEX IF NOT EXISTS idx_claims_type ON claims(claim_type);

CREATE TABLE IF NOT EXISTS evidence (
    evidence_id       TEXT PRIMARY KEY,
    payload           TEXT NOT NULL,
    source_id         TEXT NOT NULL,
    raw_item_id       TEXT NOT NULL,
    independence_group TEXT NOT NULL,
    source_tier       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_source ON evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_indep ON evidence(independence_group);

CREATE TABLE IF NOT EXISTS module_results (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id    TEXT NOT NULL,
    module     TEXT NOT NULL,
    payload    TEXT NOT NULL,
    status     TEXT NOT NULL,
    as_of      TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_module_results_task ON module_results(task_id, module);

CREATE TABLE IF NOT EXISTS graph_changes (
    graph_change_id TEXT PRIMARY KEY,
    payload         TEXT NOT NULL,
    change_type     TEXT NOT NULL,
    review_status   TEXT NOT NULL,
    created_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_graph_changes_review ON graph_changes(review_status);

-- 来源备案（指南 23 节来源注册表）
CREATE TABLE IF NOT EXISTS sources (
    source_id        TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    payload          TEXT NOT NULL,
    status           TEXT NOT NULL,
    last_verified_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_sources_status ON sources(status);
