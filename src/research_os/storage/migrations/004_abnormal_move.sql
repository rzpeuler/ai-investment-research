-- Phase 3 迁移：异动分析 + 市场数据导入底座。
-- 约定：核心对象以 JSON payload 整行存储，检索列拆出；payload 写入前必须通过对应 Schema 校验。
-- 不得修改或合并既有实时快照表（market_realtime_snapshots）和日线表（market_daily_ohlcv）。

-- 日线导入批次清单
CREATE TABLE IF NOT EXISTS market_daily_series_manifests (
    import_id         TEXT PRIMARY KEY,
    payload           TEXT NOT NULL,
    source_kind       TEXT NOT NULL,
    adjustment_method TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    date_start        TEXT,
    date_end          TEXT,
    data_version      TEXT NOT NULL,
    imported_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_manifests_status ON market_daily_series_manifests(validation_status);
CREATE INDEX IF NOT EXISTS idx_manifests_dates ON market_daily_series_manifests(date_start, date_end);

-- 导入行暂存（含逐行质量标志；失败导入不写入正式日线表）
CREATE TABLE IF NOT EXISTS market_daily_import_rows (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id   TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    trade_date  TEXT NOT NULL,
    payload     TEXT NOT NULL,
    row_status  TEXT NOT NULL,
    issues      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_import_rows_import ON market_daily_import_rows(import_id);
CREATE INDEX IF NOT EXISTS idx_import_rows_symbol ON market_daily_import_rows(symbol, trade_date);

-- 异动分析请求
CREATE TABLE IF NOT EXISTS abnormal_move_requests (
    request_id    TEXT PRIMARY KEY,
    payload       TEXT NOT NULL,
    entity_id     TEXT NOT NULL,
    entity_type   TEXT NOT NULL,
    analysis_date TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_am_req_entity ON abnormal_move_requests(entity_id, analysis_date);
CREATE INDEX IF NOT EXISTS idx_am_req_status ON abnormal_move_requests(status);

-- 异动事实观察
CREATE TABLE IF NOT EXISTS abnormal_move_observations (
    observation_id TEXT PRIMARY KEY,
    payload        TEXT NOT NULL,
    request_id     TEXT NOT NULL,
    entity_id      TEXT NOT NULL,
    trade_date     TEXT NOT NULL,
    status         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_am_obs_request ON abnormal_move_observations(request_id);
CREATE INDEX IF NOT EXISTS idx_am_obs_entity ON abnormal_move_observations(entity_id, trade_date);

-- 异动指标
CREATE TABLE IF NOT EXISTS anomaly_metrics (
    metric_id      TEXT PRIMARY KEY,
    payload        TEXT NOT NULL,
    observation_id TEXT NOT NULL,
    metric_type    TEXT NOT NULL,
    status         TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_metrics_obs ON anomaly_metrics(observation_id);
CREATE INDEX IF NOT EXISTS idx_metrics_type ON anomaly_metrics(metric_type);

-- 基准候选
CREATE TABLE IF NOT EXISTS benchmark_candidates (
    benchmark_candidate_id TEXT PRIMARY KEY,
    payload                TEXT NOT NULL,
    request_id             TEXT NOT NULL,
    subject_entity_id      TEXT NOT NULL,
    benchmark_entity_id    TEXT NOT NULL,
    benchmark_type         TEXT NOT NULL,
    eligible               INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bc_request ON benchmark_candidates(request_id);
CREATE INDEX IF NOT EXISTS idx_bc_subject ON benchmark_candidates(subject_entity_id);

-- 基准选择
CREATE TABLE IF NOT EXISTS benchmark_selections (
    benchmark_selection_id TEXT PRIMARY KEY,
    payload                TEXT NOT NULL,
    request_id             TEXT NOT NULL,
    observation_id         TEXT NOT NULL,
    fallback_status        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bs_request ON benchmark_selections(request_id);
CREATE INDEX IF NOT EXISTS idx_bs_obs ON benchmark_selections(observation_id);

-- 原因候选
CREATE TABLE IF NOT EXISTS cause_candidates (
    cause_candidate_id TEXT PRIMARY KEY,
    payload            TEXT NOT NULL,
    request_id         TEXT NOT NULL,
    observation_id     TEXT NOT NULL,
    cause_category     TEXT NOT NULL,
    final_score        REAL NOT NULL,
    status             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cc_request ON cause_candidates(request_id);
CREATE INDEX IF NOT EXISTS idx_cc_obs ON cause_candidates(observation_id);
CREATE INDEX IF NOT EXISTS idx_cc_category ON cause_candidates(cause_category);

-- 原因-证据关联
CREATE TABLE IF NOT EXISTS cause_evidence_links (
    link_id            TEXT PRIMARY KEY,
    payload            TEXT NOT NULL,
    cause_candidate_id TEXT NOT NULL,
    evidence_id        TEXT NOT NULL,
    relation           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cel_cause ON cause_evidence_links(cause_candidate_id);
CREATE INDEX IF NOT EXISTS idx_cel_evidence ON cause_evidence_links(evidence_id);

-- 归因结果
CREATE TABLE IF NOT EXISTS attribution_results (
    attribution_result_id TEXT PRIMARY KEY,
    payload               TEXT NOT NULL,
    request_id            TEXT NOT NULL,
    observation_id        TEXT NOT NULL,
    attribution_status    TEXT NOT NULL,
    overall_confidence    REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ar_request ON attribution_results(request_id);
CREATE INDEX IF NOT EXISTS idx_ar_status ON attribution_results(attribution_status);

-- 异动运行记录（幂等键唯一约束）
CREATE TABLE IF NOT EXISTS abnormal_move_runs (
    run_id            TEXT PRIMARY KEY,
    payload           TEXT NOT NULL,
    task_id           TEXT NOT NULL,
    request_id        TEXT NOT NULL,
    idempotency_key   TEXT NOT NULL,
    run_version       INTEGER NOT NULL,
    status            TEXT NOT NULL,
    validation_status TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_runs_idem ON abnormal_move_runs(idempotency_key, run_version);
CREATE INDEX IF NOT EXISTS idx_runs_task ON abnormal_move_runs(task_id);

-- LLM 调用记录（Commit 8 起使用）
CREATE TABLE IF NOT EXISTS llm_call_records (
    call_id   TEXT PRIMARY KEY,
    payload   TEXT NOT NULL,
    task_id   TEXT NOT NULL,
    module    TEXT NOT NULL,
    status    TEXT NOT NULL,
    called_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_llm_task ON llm_call_records(task_id);
