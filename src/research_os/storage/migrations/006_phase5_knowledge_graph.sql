-- Phase 5 M2 迁移：知识图谱持久化表（架构评审修正版）。
-- 约定：graph_nodes/graph_edges 为版本化追加表（复合主键），禁止 UPDATE。
-- graph_reviews/graph_applications 为辅助审计表。
-- payload 写入前必须通过对应 Schema 校验。
-- 不得修改或合并既有 Phase 0-4 表；不给旧表增加外键。
-- M2 修正：CHECK(version >= 1)、graph_applications 最小结构、FK 约束收紧。

-- 图谱节点（版本化追加：node_id + version 复合主键，禁止对已有版本 UPDATE）
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id                     TEXT NOT NULL,
    version                     INTEGER NOT NULL CHECK(version >= 1),
    payload                     TEXT NOT NULL,
    node_type                   TEXT NOT NULL,
    name                        TEXT NOT NULL,
    status                      TEXT NOT NULL,
    review_status               TEXT NOT NULL,
    origin_kind                 TEXT NOT NULL,
    created_at                  TEXT NOT NULL,
    valid_from                  TEXT,
    valid_to                    TEXT,
    last_reviewed_at            TEXT,
    originating_graph_change_id TEXT,
    PRIMARY KEY (node_id, version)
);
CREATE INDEX IF NOT EXISTS idx_gn_type ON graph_nodes(node_type, status);
CREATE INDEX IF NOT EXISTS idx_gn_origin ON graph_nodes(origin_kind);
CREATE INDEX IF NOT EXISTS idx_gn_review ON graph_nodes(review_status);
CREATE INDEX IF NOT EXISTS idx_gn_created ON graph_nodes(created_at);

-- 图谱关系（版本化追加：edge_id + version 复合主键，禁止对已有版本 UPDATE）
CREATE TABLE IF NOT EXISTS graph_edges (
    edge_id                     TEXT NOT NULL,
    version                     INTEGER NOT NULL CHECK(version >= 1),
    payload                     TEXT NOT NULL,
    source_node_id              TEXT NOT NULL,
    relation                    TEXT NOT NULL,
    target_node_id              TEXT NOT NULL,
    assertion_type              TEXT NOT NULL,
    review_status               TEXT NOT NULL,
    created_at                  TEXT NOT NULL,
    valid_from                  TEXT,
    valid_to                    TEXT,
    confidence                  REAL NOT NULL,
    last_reviewed_at            TEXT,
    originating_graph_change_id TEXT,
    PRIMARY KEY (edge_id, version)
);
CREATE INDEX IF NOT EXISTS idx_ge_source ON graph_edges(source_node_id, relation);
CREATE INDEX IF NOT EXISTS idx_ge_target ON graph_edges(target_node_id, relation);
CREATE INDEX IF NOT EXISTS idx_ge_assertion ON graph_edges(assertion_type);
CREATE INDEX IF NOT EXISTS idx_ge_review ON graph_edges(review_status);
CREATE INDEX IF NOT EXISTS idx_ge_created ON graph_edges(created_at);

-- 审核记录：每笔 GraphChange 可有多条 review（audit trail）
CREATE TABLE IF NOT EXISTS graph_reviews (
    review_id                  TEXT PRIMARY KEY,
    payload                    TEXT NOT NULL,
    graph_change_id            TEXT NOT NULL,
    decision                   TEXT NOT NULL,
    reviewer_id                TEXT NOT NULL,
    reviewed_at                TEXT NOT NULL,
    candidate_hash             TEXT NOT NULL,
    resulting_graph_change_id  TEXT,
    FOREIGN KEY (graph_change_id) REFERENCES graph_changes(graph_change_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_grev_change ON graph_reviews(graph_change_id, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_grev_decision ON graph_reviews(decision);

-- Apply 记录：哪条 GraphChange 被 applied 到哪个 node/edge 版本。
-- M2 修正：最小结构，仅保留 application_id / graph_change_id / review_id /
--          idempotency_key / payload / applied_at。
--          idempotency_key 严格 UNIQUE，防止重复 apply。
CREATE TABLE IF NOT EXISTS graph_applications (
    application_id             TEXT PRIMARY KEY,
    graph_change_id            TEXT NOT NULL,
    review_id                  TEXT NOT NULL,
    idempotency_key            TEXT NOT NULL UNIQUE,
    payload                    TEXT NOT NULL,
    applied_at                 TEXT NOT NULL,
    FOREIGN KEY (graph_change_id) REFERENCES graph_changes(graph_change_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT,
    FOREIGN KEY (review_id) REFERENCES graph_reviews(review_id)
        ON UPDATE RESTRICT ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_gapp_change ON graph_applications(graph_change_id);
CREATE INDEX IF NOT EXISTS idx_gapp_review ON graph_applications(review_id);
CREATE INDEX IF NOT EXISTS idx_gapp_applied ON graph_applications(applied_at);
