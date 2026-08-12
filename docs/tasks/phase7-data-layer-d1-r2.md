# P7-D1-R2：Authority Semantics Closure & Requirement Contract Alignment

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — P7-D1-R2 ONLY**
**MILESTONE: P7-D1-R2**
**START_HEAD: `834f5c2db4cfe555044a23ab912da3c0cf14f534`**
**R1_INDEPENDENT_REACCEPTANCE: CHANGES_REQUIRED**
**R2_SCOPE: Authority Semantics Closure + exact requirement contract correction**
**P7-D2: NOT AUTHORIZED**
**BASE_MASTER_SHA: `6314b781c8b796b9e367358542f61b55f52def4b`**
**ACQUISITION_EXECUTION: NO**
**READINESS_RECHECK_AFTER_ACQUISITION: NO**
**NEW_COLLECTORS: NO**
**SOURCE_EXPANSION: NO**
**ROUTER_CORE_CHANGE: NO**
**PRODUCTION_LLM: 0**
**GRAPH_WRITE: NONE**
**PHASE6.1: NOT_AUTHORIZED**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMAS: 85**

> P7-D1-R1 独立复验发现仍需 Authority Semantics Closure。R2 把 22/22 checker
> registered 升级为 43/43 Requirement Semantic Closure（binding/context/authority/
> scope/PIT/min-field/provenance/coverage/freshness 全部有确定性语义）。

## 1. R2-01：D0 Contract Correction（唯一允许的 registry 修改）

`registry/scenario_data_requirements.yaml` 精确 6 项纠偏（1 scope_type + 5 time_policy
+ 5 point_in_time_policy；其余字段冻结）：

```text
stock_research_report.company_document:        explicit_request_window→as_of_snapshot; window_bounded→strict_as_of
stock_research_report.industry_membership:     scope industry→subject
industry_research.evidence_index:              explicit_request_window→as_of_snapshot; window_bounded→strict_as_of
theme_discovery.evidence_index:                explicit_request_window→as_of_snapshot; window_bounded→strict_as_of
theme_discovery.document_corpus:               explicit_request_window→as_of_snapshot; window_bounded→strict_as_of
earnings_expectation.company_announcement:     explicit_request_window→as_of_snapshot; window_bounded→strict_as_of
```

若发现第 7 个 mismatch → STOP（不擅改 registry）。

## 2. Requirement Semantic Binding（43/43）

- `RequirementReadinessBinding` + `RequirementReadinessBindingResolver`
  （src/research_os/data_layer/bindings.py）：每个 requirement 恰好一个 effective
  binding（context/authority/scope/pit/field-projection/provenance/coverage/freshness）。
- 不允许同一 data_type 在所有 scenario 下假设语义完全相同（industry_membership 在
  stock_research_report（subject/singleton）与 industry_research（open-world null）不同）。

## 3. Canonical Field Projector（minimum-field closure）

- `ReadinessFieldProjector` + `MinimumFieldClosureValidator`
  （src/research_os/data_layer/projector.py）：43/43 requirement 每个 minimum_field
  属于 authority direct field 或 explicit deterministic projection；否则
  CONTROL_PLANE_CONFIGURATION_ERROR。
- 已知投影：FinancialFact value（value_status reported/derived_from_report +
  normalized/raw）、industry_membership industry_id（actual matching industry_ids）、
  macro publish_date（date(published_at)）、company（company subject entity）、
  evidence source_ref（source_id）、entity_mapping symbol（symbol/aliases）、
  graph node_refs/edge_refs（query result）、run artifact task_id/run_id（lineage）。

## 4. R2-02：统一 Scenario Time Context

- `NormalizedRequestContextAdapter` 按 scenario 复用既有业务时间权威：
  DailyReview（day_start→min(day_end, as_of)）、StockReview（review_start→
  min(review_end 23:59:59, as_of)）、AbnormalMove（explicit → resolve_window →
  unresolved fail-closed）、morning/evening（BriefWindowPolicy）。
- as_of_snapshot requirement 不产生假 window unresolved（6 处纠偏后验证）。
- explicit window 真正过滤（evidence published_at / claim as_of ∈ [start, end)）。

## 5. R2-03/04：SecurityProfile / Valuation 生命周期

- SecurityProfile：listing_date/delisting_date/status（listed/suspended/delisted/
  unknown）；as_of<listing_date → PIT_INELIGIBLE；suspended 按自身语义；freshness
  用 updated_at。
- Valuation：complete/partial/not_applicable/insufficient_data；partial 需
  as_of/price/shares_outstanding 非空；多个 snapshot 确定性选 latest eligible
  （禁止 field union）。

## 6. R2-05/06：Financial / Industry

- Financial canonical value（value_status 门禁）；subject coverage null（无合法
  fact universe）；peer coverage = peers with eligible / N（peer unresolved → null）。
- IndustryMembership：subject scope（stock）→ singleton；industry scope 无权威完整
  成员全集 → coverage null（不得"一个成员→1.0"）。

## 7. R2-07：Provenance / Tier

- Evidence/event_evidence/evidence_index 用 evidence_tier；claims/research_findings
  用 evidence_ids→Evidence；market bar 用 accepted manifest→source_id→
  SourceRegistry tier；FinancialFact 支持 source_document→Evidence 链。
- 无法证明 → SOURCE_TIER_UNPROVEN（quality ineligible）。

## 8. R2-08：Graph 实证

- 实际调用 GraphQueryService.query_graph（root_node_id=industry_id, as_of）生成
  真实 node_refs/edge_refs；global scope fail-closed；零 Graph write。

## 9. R2-09：Dry-run 拆两测试

- Test A：preflight 实际读到既有 row（eligible_record_count>0）。
- Test B：orchestrator dry-run 零副作用（user_version / row count / payload hash
  前后一致）。

## 10. R2-10：RunArtifact lineage

- 正式 lineage（task.json completed、directory id==task_id、validation pass、
  cutoff<=as_of；previous_run_ids 只查 requested）；禁止目录数。

## 11. 完成定义

10/10 scenarios、43/43 requirements、22/22 checker、43/43 bindings、100%
minimum-field closure、精确 6 contract corrections、real time context、
explicit window 过滤、SecurityProfile/Valuation 生命周期正确、无 singleton field
union、Financial canonical value、subject/peer coverage 正确、Industry scope 正确、
Evidence/Claim/Finding/Market tier 执行、Graph query_graph 实证、dry-run 读 DB 零写、
Schema-valid positive fixtures、Router/Source registries/Capability/Collectors 不变、
DB v6 / Migrations NONE / Schemas 85 / Network 0 / LLM 0 / Graph write NONE /
P7-D2 NOT_AUTHORIZED；pytest 0 failed / 85/85 / compileall / diff-check / CI SUCCESS。

完成后只能报告：

```text
P7-D1: IMPLEMENTED / AWAITING INDEPENDENT RE-ACCEPTANCE
```

不得自行声明 PASS / ACCEPTED / CLOSED / MERGE AUTHORIZED。
