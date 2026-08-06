-- Phase 4 迁移：个股研报（任务书 3.10 节）。
-- 约定：核心对象以 JSON payload 整行存储，检索列拆出；payload 写入前必须通过对应 Schema 校验。
-- 不得修改或合并既有 Phase 0-3 表；不给旧表增加外键；禁止 ON DELETE CASCADE 删除研究历史。
-- 财务值检索列使用 TEXT decimal，不得仅以 REAL 持久化关键财务值。

-- 公司画像
CREATE TABLE IF NOT EXISTS company_profiles (
    company_profile_id TEXT PRIMARY KEY,
    payload            TEXT NOT NULL,
    entity_id          TEXT NOT NULL,
    valid_from         TEXT,
    valid_to           TEXT,
    status             TEXT NOT NULL,
    version            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cp_entity ON company_profiles(entity_id, valid_from, valid_to);
CREATE INDEX IF NOT EXISTS idx_cp_status ON company_profiles(status);

-- 证券画像
CREATE TABLE IF NOT EXISTS security_profiles (
    security_profile_id TEXT PRIMARY KEY,
    payload             TEXT NOT NULL,
    security_entity_id  TEXT NOT NULL,
    company_entity_id   TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    exchange            TEXT NOT NULL,
    status              TEXT NOT NULL,
    version             INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sp_symbol ON security_profiles(symbol, status);
CREATE INDEX IF NOT EXISTS idx_sp_company ON security_profiles(company_entity_id);

-- 文档登记
CREATE TABLE IF NOT EXISTS document_records (
    document_id     TEXT PRIMARY KEY,
    payload         TEXT NOT NULL,
    company_entity_id TEXT,
    document_type   TEXT NOT NULL,
    published_at    TEXT,
    sha256          TEXT NOT NULL,
    parse_status    TEXT NOT NULL,
    version         INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_dr_company ON document_records(company_entity_id, document_type, published_at);
CREATE INDEX IF NOT EXISTS idx_dr_sha ON document_records(sha256);
CREATE INDEX IF NOT EXISTS idx_dr_parse ON document_records(parse_status);

-- 文档块
CREATE TABLE IF NOT EXISTS document_blocks (
    block_id     TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    document_id  TEXT NOT NULL,
    page_start   INTEGER NOT NULL,
    sequence_no  INTEGER NOT NULL,
    block_type   TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    version      INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_db_doc ON document_blocks(document_id, page_start, sequence_no);
CREATE INDEX IF NOT EXISTS idx_db_type ON document_blocks(block_type);

-- 财务导入批次清单（幂等：checksum+data_version 唯一）
CREATE TABLE IF NOT EXISTS financial_data_manifests (
    manifest_id      TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    source_kind      TEXT NOT NULL,
    source_id        TEXT NOT NULL,
    file_name        TEXT NOT NULL,
    file_checksum    TEXT NOT NULL,
    data_version     TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    row_count        INTEGER NOT NULL,
    accepted_count   INTEGER NOT NULL,
    rejected_count   INTEGER NOT NULL,
    imported_at      TEXT,
    UNIQUE(file_checksum, data_version)
);
CREATE INDEX IF NOT EXISTS idx_fdm_status ON financial_data_manifests(validation_status);
CREATE INDEX IF NOT EXISTS idx_fdm_source ON financial_data_manifests(source_id);

-- 财务报告
CREATE TABLE IF NOT EXISTS financial_reports (
    financial_report_id TEXT PRIMARY KEY,
    payload             TEXT NOT NULL,
    company_entity_id   TEXT NOT NULL,
    document_id         TEXT,
    manifest_id         TEXT,
    report_type         TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    statement_scope     TEXT NOT NULL,
    fiscal_year         INTEGER NOT NULL,
    filing_version      TEXT NOT NULL,
    data_status         TEXT NOT NULL,
    version             INTEGER NOT NULL,
    UNIQUE(company_entity_id, period_end, report_type, statement_scope, filing_version)
);
CREATE INDEX IF NOT EXISTS idx_fr_company ON financial_reports(company_entity_id, period_end, statement_scope);

-- 财务事实（十进制字符串）
CREATE TABLE IF NOT EXISTS financial_facts (
    fact_id             TEXT PRIMARY KEY,
    payload             TEXT NOT NULL,
    fact_key            TEXT NOT NULL,
    financial_report_id TEXT NOT NULL,
    company_entity_id   TEXT NOT NULL,
    statement_type      TEXT NOT NULL,
    taxonomy_code       TEXT NOT NULL,
    period_end          TEXT NOT NULL,
    value_status        TEXT NOT NULL,
    source_document_id  TEXT,
    conflict_group_id   TEXT,
    restatement_version INTEGER NOT NULL,
    version             INTEGER NOT NULL,
    UNIQUE(fact_key, source_document_id, restatement_version, version)
);
CREATE INDEX IF NOT EXISTS idx_ff_company ON financial_facts(company_entity_id, taxonomy_code, period_end);
CREATE INDEX IF NOT EXISTS idx_ff_report ON financial_facts(financial_report_id, statement_type);
CREATE INDEX IF NOT EXISTS idx_ff_conflict ON financial_facts(conflict_group_id);
CREATE INDEX IF NOT EXISTS idx_ff_factkey ON financial_facts(fact_key);

-- 财务指标
CREATE TABLE IF NOT EXISTS financial_metrics (
    metric_id      TEXT PRIMARY KEY,
    payload        TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    metric_code    TEXT NOT NULL,
    period_end     TEXT NOT NULL,
    status         TEXT NOT NULL,
    value          TEXT,
    formula_version TEXT NOT NULL,
    version        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fm_company ON financial_metrics(company_entity_id, metric_code, period_end);
CREATE INDEX IF NOT EXISTS idx_fm_status ON financial_metrics(status);

-- 业务分部
CREATE TABLE IF NOT EXISTS business_segments (
    segment_id          TEXT PRIMARY KEY,
    payload             TEXT NOT NULL,
    company_entity_id   TEXT NOT NULL,
    financial_report_id TEXT NOT NULL,
    segment_type        TEXT NOT NULL,
    raw_name            TEXT NOT NULL,
    canonical_name      TEXT NOT NULL,
    valid_from          TEXT,
    status              TEXT NOT NULL,
    version             INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bs_company ON business_segments(company_entity_id, valid_from);
CREATE INDEX IF NOT EXISTS idx_bs_report ON business_segments(financial_report_id);

-- 同行候选（冻结：subject+candidate+cutoff+universe 唯一）
CREATE TABLE IF NOT EXISTS peer_candidates (
    peer_candidate_id    TEXT PRIMARY KEY,
    payload              TEXT NOT NULL,
    subject_company_id   TEXT NOT NULL,
    candidate_company_id TEXT NOT NULL,
    information_cutoff   TEXT NOT NULL,
    universe_version     TEXT NOT NULL,
    eligible             INTEGER NOT NULL,
    total_score          REAL NOT NULL,
    version              INTEGER NOT NULL,
    UNIQUE(subject_company_id, candidate_company_id, information_cutoff, universe_version)
);
CREATE INDEX IF NOT EXISTS idx_pc_subject ON peer_candidates(subject_company_id, eligible, total_score);
CREATE INDEX IF NOT EXISTS idx_pc_candidate ON peer_candidates(candidate_company_id);

-- 同行选择
CREATE TABLE IF NOT EXISTS peer_selections (
    peer_selection_id   TEXT PRIMARY KEY,
    payload             TEXT NOT NULL,
    request_id          TEXT NOT NULL,
    subject_company_id  TEXT NOT NULL,
    universe_version    TEXT NOT NULL,
    scoring_version     TEXT NOT NULL,
    status              TEXT NOT NULL,
    sample_size         INTEGER NOT NULL,
    version             INTEGER NOT NULL,
    UNIQUE(request_id, scoring_version, version)
);
CREATE INDEX IF NOT EXISTS idx_ps_request ON peer_selections(request_id);

-- 估值快照
CREATE TABLE IF NOT EXISTS valuation_snapshots (
    valuation_snapshot_id TEXT PRIMARY KEY,
    payload               TEXT NOT NULL,
    company_entity_id     TEXT NOT NULL,
    security_entity_id    TEXT NOT NULL,
    as_of                 TEXT NOT NULL,
    status                TEXT NOT NULL,
    version               INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vs_security ON valuation_snapshots(security_entity_id, as_of);

-- 情景预测
CREATE TABLE IF NOT EXISTS forecast_scenarios (
    scenario_id      TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    request_id       TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    scenario_type    TEXT NOT NULL,
    enabled          INTEGER NOT NULL,
    status           TEXT NOT NULL,
    version          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fs_request ON forecast_scenarios(request_id);
CREATE INDEX IF NOT EXISTS idx_fs_company ON forecast_scenarios(company_entity_id);

-- 竞争因素
CREATE TABLE IF NOT EXISTS competitive_factors (
    factor_id          TEXT PRIMARY KEY,
    payload            TEXT NOT NULL,
    company_entity_id  TEXT NOT NULL,
    factor_type        TEXT NOT NULL,
    direction          TEXT NOT NULL,
    status             TEXT NOT NULL,
    management_only    INTEGER NOT NULL,
    version            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cf_company ON competitive_factors(company_entity_id, status);

-- 催化剂
CREATE TABLE IF NOT EXISTS catalysts (
    catalyst_id      TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    catalyst_type    TEXT NOT NULL,
    status           TEXT NOT NULL,
    time_window_start TEXT,
    source_phase     TEXT NOT NULL,
    version          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cat_company ON catalysts(company_entity_id, status, time_window_start);

-- 风险
CREATE TABLE IF NOT EXISTS risk_factors (
    risk_id          TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    risk_type        TEXT NOT NULL,
    status           TEXT NOT NULL,
    source_phase     TEXT NOT NULL,
    version          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rf_company ON risk_factors(company_entity_id, status);

-- 研究发现
CREATE TABLE IF NOT EXISTS research_findings (
    finding_id       TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    request_id       TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    finding_type     TEXT NOT NULL,
    materiality      TEXT NOT NULL,
    status           TEXT NOT NULL,
    version          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rfnd_request ON research_findings(request_id, finding_type, materiality);
CREATE INDEX IF NOT EXISTS idx_rfnd_company ON research_findings(company_entity_id);

-- 研报请求
CREATE TABLE IF NOT EXISTS equity_research_requests (
    request_id         TEXT PRIMARY KEY,
    payload            TEXT NOT NULL,
    task_id            TEXT NOT NULL,
    company_entity_id  TEXT NOT NULL,
    security_entity_id TEXT NOT NULL,
    report_date        TEXT NOT NULL,
    depth              TEXT NOT NULL,
    status             TEXT NOT NULL,
    version            INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_err_company ON equity_research_requests(company_entity_id, report_date);
CREATE INDEX IF NOT EXISTS idx_err_task ON equity_research_requests(task_id);

-- 研报运行（幂等键唯一约束）
CREATE TABLE IF NOT EXISTS equity_research_runs (
    run_id           TEXT PRIMARY KEY,
    payload          TEXT NOT NULL,
    request_id       TEXT NOT NULL,
    task_id          TEXT NOT NULL,
    idempotency_key  TEXT NOT NULL,
    run_version      INTEGER NOT NULL,
    status           TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    started_at       TEXT,
    UNIQUE(idempotency_key, run_version)
);
CREATE INDEX IF NOT EXISTS idx_err_runs_key ON equity_research_runs(idempotency_key, run_version);
CREATE INDEX IF NOT EXISTS idx_err_runs_request ON equity_research_runs(request_id);

-- 研报结果
CREATE TABLE IF NOT EXISTS equity_research_results (
    result_id         TEXT PRIMARY KEY,
    payload           TEXT NOT NULL,
    run_id            TEXT NOT NULL,
    request_id        TEXT NOT NULL,
    company_entity_id TEXT NOT NULL,
    research_status   TEXT NOT NULL,
    version           INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_err_res_request ON equity_research_results(request_id, research_status);
