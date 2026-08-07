-- Phase 5 M2 迁移：知识图谱持久化表（任务书 29 节）。
-- 约定：graph_nodes/graph_edges 为版本化追加表（复合主键），禁止 UPDATE。
-- graph_reviews/graph_applications 为辅助审计表。
-- payload 写入前必须通过对应 Schema 校验。
-- 不得修改或合并既有 Phase 0-4 表；不给旧表增加外键。

-- 图谱节点（版本化追加：node_id + version 复合主键，禁止对已有版本 UPDATE）
CREATE TABLE IF NOT EXISTS graph_nodes (
    node_id                     TEXT NOT NULL,
    version                     INTEGER NOT NULL,
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
    version                     INTEGER NOT NULL,
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
);
CREATE INDEX IF NOT EXISTS idx_grev_change ON graph_reviews(graph_change_id, reviewed_at);
CREATE INDEX IF NOT EXISTS idx_grev_decision ON graph_reviews(decision);

-- Apply 记录：哪条 GraphChange 被 applied，产生哪个节点/边版本
CREATE TABLE IF NOT EXISTS graph_applications (
    application_id             TEXT PRIMARY KEY,
    payload                    TEXT NOT NULL,
    graph_change_id            TEXT NOT NULL,
    review_id                  TEXT NOT NULL,
    applied_at                 TEXT NOT NULL,
    node_id                    TEXT,
    node_version               INTEGER,
    edge_id                    TEXT,
    edge_version               INTEGER,
    FOREIGN KEY (graph_change_id) REFERENCES graph_changes(graph_change_id),
    FOREIGN KEY (review_id) REFERENCES graph_reviews(review_id)
);
CREATE INDEX IF NOT EXISTS idx_gapp_change ON graph_applications(graph_change_id);
CREATE INDEX IF NOT EXISTS idx_gapp_node ON graph_applications(node_id, node_version);
CREATE INDEX IF NOT EXISTS idx_gapp_edge ON graph_applications(edge_id, edge_version);
