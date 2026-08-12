# P7-D1-R1：Readiness Semantic Correctness & Authority Alignment

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — P7-D1-R1 ONLY**
**MILESTONE: P7-D1-R1**
**START_HEAD: `91f83867e235b2c52fffad191fee70c7488d20d6`**
**INDEPENDENT_ACCEPTANCE: CHANGES_REQUIRED**
**REPAIR_SCOPE: Readiness semantic correctness**
**P7-D2: NOT AUTHORIZED**
**BASE_MASTER_SHA: `6314b781c8b796b9e367358542f61b55f52def4b`**
**ACQUISITION_EXECUTION: NOT AUTHORIZED**
**NEW_COLLECTORS: NOT AUTHORIZED**
**SOURCE_EXPANSION: NOT AUTHORIZED**
**ROUTER_CORE_CHANGE: NOT AUTHORIZED**
**PHASE6.1: NOT AUTHORIZED**
**GRAPH_WRITE: NONE**
**PRODUCTION_LLM_CALLS: 0**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMAS: 85**

> P7-D1 控制面骨架通过初步结构审查；独立验收发现 REGISTERED CHECKER COVERAGE
> ≠ SEMANTICALLY CORRECT READINESS。本次只修 Readiness 语义正确性，不推倒重写控制面。

## 1. R1-01 真实 Normalized Request Context

- 新增 `NormalizedRequestContextAdapter`（src/research_os/data_layer/request_context.py）：
  scenario → exact normalized request contract 机械映射（禁止 Generic Alias Guessing）。
- 已确认错误案例修复：abnormal_move_analysis→entity_id、stock_research_report→entity、
  stock_review→entity、industry_research→industry_id、first_coverage→
  company_entity_id+security_entity_id+industry_id。
- Task.entities 与 Resolver 共享同一 adapter（Orchestrator.execute 用
  `canonical.task_entities`）。
- 禁止修改 10 个业务 Runner（Data Layer 适配已存在的 Runner contract）。

## 2. R1-02 Authority Mapping

- 新增 `DataTypeReadinessSpec`（src/research_os/data_layer/specs.py）：22/22 data_type
  显式 spec（authority_kind/location/checker_family/scope/pit/provenance/coverage/freshness）。
- 错误共用表修正：claims→claims、security_profile→security_profiles、
  market_valuation_snapshot→valuation_snapshots、company_profile→company_profiles。
- RawItem 系（news_flash/company_announcement/macro_data/brief_event_content/
  brief_attention_content）共享 raw_items 但 semantic eligibility 独立
  （raw_category / source_id 确定性约束），禁止任意 RawItem 跨类型满足 Requirement。

## 3. R1-03 Provenance / Source Tier

- 新增 `ReadinessProvenanceResolver`（provenance.py）：evidence_tier / raw_item_source
  （source_id→sources.yaml）/ evidence_ids（→Evidence 表）确定性解析。
- 禁止从领域 payload 通用读取 source_tier/tier 伪造 provenance；
  无法 dereference → SOURCE_TIER_UNPROVEN（quality ineligible）。
- 内部 authority（entity_mapping/run_artifacts/knowledge_graph_snapshot/
  research_findings/claims）source_tier_applicable=false。

## 4. R1-04 Coverage 语义分离

- FIELD COMPLETENESS（available/missing_fields）≠ COVERAGE。
- coverage_strategy 显式声明：SINGLETON_TARGET / REQUESTED_ENTITY_SET /
  REQUESTED_PEER_SET / CONFIGURED_WATCHLIST / OPEN_WORLD / NOT_APPLICABLE。
- open-world（事件发现/宏观/广义新闻）：无论 0 条还是 N 条 → coverage=null +
  COVERAGE_NOT_MEASURABLE（禁止 0.0 伪造）。
- 删除工作日≈交易日近似（_trading_days_between）；市场无权威交易日历 →
  coverage=null（R1 不授权新增交易日历数据）。

## 5. R1-05 Freshness / Stale / Health

- freshness_seconds 真正执行；freshness_age = as_of - authoritative timestamp
  （不破坏历史 as_of 重放）；多条记录取保守 max(age)。
- 有合格数据但 freshness 超限 → STALE（优先于 coverage 降级）。
- freshness 无法证明 → FRESHNESS_UNPROVEN（PARTIAL）。
- SOURCE_UNHEALTHY 仅由已有持久化 health 证据证明；否则 SOURCE_HEALTH_UNPROVEN。
- 禁止联网 healthcheck / 新增 probe。

## 6. R1-06 Graph PIT Authority

- Graph checker 复用既有 HistoryService.resolve_node_as_of + GraphQueryService.get_node
  （versioned lifecycle authority），禁止 count_nodes/count_edges 作 READY 权威。
- as_of 必须进入 Graph read；industry scope 需 identity resolution；
  无法确定性完成 → MISSING/PARTIAL + GRAPH_SCOPE_UNRESOLVED。
- 零 Graph write。

## 7. R1-07 Dry-run 只读真实 DB

- dry_run = ZERO WRITE，≠ IGNORE EXISTING DATA。
- project_root/data/sqlite/research.db 存在 → Database.open_read_only() 读真实数据。
- DB 不存在 → EmptyReadView（不创建）。
- preflight 自开只读连接必须 finally close（禁止泄漏）。

## 8. R1-08 AUTO_DERIVABLE 前提证明

- 删除 eligible_record_count>0 通用规则。
- 新增 `DerivationPrerequisiteResolver`：无显式证明器的 data_type 不得 AUTO_DERIVABLE。
- 生产 AUTO_DERIVABLE 可以为 0（能力无法证明 → 不输出，比错误自动派生更好）。

## 9. 完成定义

real 10/10 Runner normalized requests supported；无 false unresolved（field-name
mismatch）；Task.entities 与 Resolver 共享 adapter；22/22 semantic authority
mappings；claims/security_profile/valuation 权威表正确；raw-item 不跨类型满足；
provenance 经既有 authority；无 payload 伪造 tier；field completeness 与 coverage
分离；open-world coverage 恒 null；无工作日近似；freshness 执行；STALE 可达；
SOURCE_UNHEALTHY 仅凭持久化证据；Graph 用既有 lifecycle authority + as_of；
dry-run 读已有 DB 只读；只读连接关闭；AUTO_DERIVABLE 需显式前提证明；
central requirement authority 保留；普通 gaps 不 gate Runner；Router/registries/
collectors 不变；DB v6 / Migrations NONE / Schemas 85 / LLM 0 / Graph write NONE /
P7-D2 NOT_AUTHORIZED；pytest 0 failed / 85/85 / compileall / diff-check / CI SUCCESS。

完成后只能报告：

```text
P7-D1: IMPLEMENTED / AWAITING INDEPENDENT RE-ACCEPTANCE
```

不得自行声明 PASS / ACCEPTED / CLOSED / MERGE AUTHORIZED。
