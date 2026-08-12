# P7-D1-R3：Runtime Semantic Binding Closure

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — P7-D1-R3 ONLY**
**MILESTONE: P7-D1-R3**
**START_HEAD: `87591f3e227ddf754b1260628a4b1ab180ab0513`**
**R2_INDEPENDENT_REACCEPTANCE: CHANGES_REQUIRED**
**R3_SCOPE: Runtime Semantic Binding Closure**
**P7-D2: NOT AUTHORIZED**
**BASE_MASTER_SHA: `6314b781c8b796b9e367358542f61b55f52def4b`**
**ACQUISITION_EXECUTION: NO**
**READINESS_RECHECK_AFTER_ACQUISITION: NO**
**ROUTER_CORE_CHANGE: NO**
**NEW_COLLECTORS: 0**
**SOURCE_EXPANSION: NO**
**PRODUCTION_LLM_CALLS: 0**
**GRAPH_WRITE: NONE**
**PHASE6.1: NOT_AUTHORIZED**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMAS: 85**

> R2 创建了 RequirementReadinessBindingResolver / MinimumFieldClosureValidator /
> ReadinessFieldProjector，但 production preflight 尚未消费它们（design-time semantics
> ≠ runtime semantics）。R3 唯一核心目标：DESIGN-TIME SEMANTICS = RUNTIME SEMANTICS。

## 1. R3-01：Binding Resolver 正式进入 Preflight

- `DataPreflightService.__init__()` 构造 `RequirementReadinessBindingResolver`
  （基于同一个 ScenarioDataRequirementRegistry，不加载第二份 authority）。
- 初始化即执行 43/43 closure gate + RuntimeStrategyGate（missing/duplicate/unknown
  strategy/invalid minimum-field source → CONTROL_PLANE_CONFIGURATION_ERROR），
  发生在 Router/Collector/Runner.execute 之前。
- 主循环每个 requirement → `binding_resolver.get(requirement_id)` → 注入 ctx；
  禁止只传 data_type 由 checker 重新推导 scenario semantics。

## 2. R3-02：ReadinessFieldProjector 正式进入 Runtime

- available_fields/missing_fields 按 requirement-facing canonical field names 计算
  （binding.minimum_field_sources 判定），不再仅依赖 payload.keys() union。
- FinancialFact `value` canonical（value_status reported/derived_from_report +
  normalized/raw 非空）真实进入 available_fields；statement_scope 是 direct field
  （严禁 statement_type 投影）。
- macro publish_date = date(published_at)；company = RawItem.entities 中确定性公司身份；
  Evidence source_ref = Evidence.source_id；entity symbol 经可证明 authority
  （禁止 aliases 冒充证券代码）。
- 未知 projection → CONTROL_PLANE_CONFIGURATION_ERROR（不得伪装成普通 missing field）。

## 3. R3-03：Evidence Subject Scope 经 RawItem Provenance

- subject/industry Evidence 必须 Evidence.raw_item_id → RawItem.entities → scope
  validation；RawItem 无法解引用 → ineligible（不得默认放行）。
- industry 支持 company → CompanyProfile membership 确定性证明；global Evidence
  不需 join 但仍执行 PIT/tier/freshness/canonical。

## 4. R3-04：Coverage 使用 Binding

- checker 用 binding.coverage_strategy（不得 spec.coverage_strategy 覆盖）。
- daily_review.claims → OPEN_WORLD（coverage null，禁止 1 claim → 1.0）；
  entity_mapping subject → SINGLETON、industry/global → OPEN_WORLD；
  REQUESTED_RUN_SET（daily_review.run_artifacts 用 previous_run_ids 计算 coverage）。

## 5. R3-05：RunArtifact Lineage

- CanonicalRequestContext 新增 previous_run_ids/previous_report_paths/previous_cutoff
  （专用字段，不得塞进 request_material_refs）。
- 共享 lineage helper 抽取到 `src/research_os/review/prior_run_lineage.py`
  （DailyReviewPipeline + RunArtifactChecker 共同调用；NO BUSINESS SEMANTIC CHANGE）。
- validation.json 必须存在且 status ∈ {ok, pass, pass_with_warnings}；
  run_id 来自 scenario_execution_result.json（非目录名伪造）；
  business cutoff 用既有 authority priority（P1 Run artifact window_end →
  P2 task.time_window.end → P3 task.as_of）；禁止 finished_at/created_at/mtime。
- previous_run_ids=[] 不得扫描全部 runs。

## 6. R3-06：Timezone-aware PIT / Window

- 所有 datetime eligibility 比较 parse_iso 后按时间比较（_in_window/_iso_gt/_iso_le），
  禁止字典序；offset-aware 测试（2026-08-10T16:30:00Z 等价于 08-11 00:30 +08:00）。

## 7. R3-07：Provenance 使用 Binding

- 所有 checker 用 binding.provenance_strategy / source_tier_applicable；
  DocumentRecord → document_source（source_id → SourceRegistry）；
  IndustryMembership 执行 minimum_source_tier；
  FinancialFact 支持 source_document → Document → Evidence/source 链。

## 8. R3-10：Strategy Implementation Registry

- SUPPORTED_SCOPE/PIT/COVERAGE/PROVENANCE/FRESHNESS/PROJECTION/AUTHORITY_STRATEGIES
  + RuntimeStrategyGate：binding strategy ∈ runtime supported（防止 binding 写名字、
  runtime 未实现）。

## 9. 完成定义

BindingResolver runtime-authoritative、43/43 bindings runtime-loadable、
MinimumFieldClosureValidator + RuntimeStrategyGate 生产执行、Projector 入 runtime、
Financial value/statement_scope 正确、Evidence subject join、claims open-world、
previous_run_ids 专用、lineage 复用、timezone-aware、Document/Industry tier；
Registry 全冻结（R3 无 contract correction）；Router/Collectors/schemas 不变；
DB v6 / Migrations NONE / Schemas 85 / Network 0 / LLM 0 / Graph write NONE /
P7-D2 NOT_AUTHORIZED；pytest 0 failed / 85/85 / compileall / diff-check / CI SUCCESS。

完成后只能报告：

```text
P7-D1: IMPLEMENTED / AWAITING INDEPENDENT RE-ACCEPTANCE
（R1/R2/R3 repair chain）
```

不得自行声明 PASS / ACCEPTED / CLOSED / MERGE AUTHORIZED。
