# P7-D1-R3.1：Final Runtime Closure

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — P7-D1-R3.1 ONLY**
**MILESTONE: P7-D1-R3.1**
**START_HEAD: `33bbeb15b4bb973ba6e9a90e9e2f1cf07f118062`**
**R3_INDEPENDENT_REACCEPTANCE: CHANGES_REQUIRED**
**SCOPE: Final Runtime Closure**
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

> 本次不是新里程碑：P7-D1 → R1 → R2 → R3 → R3.1 FINAL RUNTIME CLOSURE。
> 只关闭独立复验发现的剩余 runtime correctness blocker，禁止扩设计。

## R3.1-01 — 完全消除 Lexical DateTime Eligibility

```text
DATETIME ELIGIBILITY: PARSE THEN COMPARE
```

决定 scope/PIT/window/candidate selection/latest-object/publication/freshness；
禁止 ISO 字符串字典序。RawItem SQL window prefilter 必须移除（不得作为
authoritative eligibility）；Financial publication PIT fetch exact object 后按
instant 比较；Valuation latest 按 parse_iso 排序（malformed → ineligible）。
date-only 字段（listing_date/delisting_date/trade_date/period_end）用
date.fromisoformat 显式 Asia/Shanghai 边界；malformed 时间 fail-closed。

## R3.1-02 — REQUESTED_RUN_SET 正式进入 Binding

`daily_review.run_artifacts` effective binding coverage_strategy =
`REQUESTED_RUN_SET`。coverage = valid requested / unique requested；
empty → coverage null / MISSING / NO AUTO SCAN；重复 ID 去重不扭曲 denominator；
minimum_coverage 真实影响 readiness（PARTIAL + COVERAGE_BELOW_MINIMUM）。

## R3.1-03 — run_id 必须被正式 Artifact 证明

`scenario_execution_result.json` 必须存在且可读；task_id 非空且 == requested
previous_run_id；run_id 非空；validation_status 若存在必须与共享 lineage
acceptance 一致。禁止 directory-name fallback。共享 helper
（review.prior_run_lineage）扩展 execution-result identity 校验。

## R3.1-04 — EntityMapping Coverage 服从 Binding

subject → SINGLETON_TARGET（1.0/0.0）；industry/global → OPEN_WORLD（null，
本阶段无完整权威 denominator）。禁止无条件 `coverage = 1.0 if eligible else 0.0`。

## R3.1-05 — Graph Canonical Projector 集成

GraphSnapshotChecker 仅在实际 query 证明后生成 projectable authority payload
（node_refs/edge_refs/as_of/industry_id）；runtime binding+projector 下这些字段
保留在 available_fields；global fail-closed 保留；零写入（monkeypatch 验证）。

## R3.1-06 — Schema-valid Runtime Fixture Gate

所有 PRODUCTION RUNTIME FIXTURE 必须：Pydantic construction → model_dump() →
validate_instance(schema) → assert [] → persist → actual checker →
DataReadinessService。覆盖 FinancialFact / DocumentRecord / RawItem+Evidence /
Claim+Evidence / ResearchFinding+Evidence / SecurityProfile / ValuationSnapshot /
MarketDailyOHLCV+MarketDailySeriesManifest。partial dict 不得称为 Schema-valid
fixture。

## R3.1-07 — Projection Strategy Gate 必须 Exact Match

`SUPPORTED_PROJECTION_STRATEGIES` 为精确 registry（仅当前真实实现且被 binding
正式使用的 9 个 projection）；RuntimeStrategyGate 与 MinimumFieldClosureValidator
均 exact match（禁止前缀匹配）；Projector `PROJECTION_HANDLERS` 与其机械一致
（parity 测试）；未知 projection 初始化即 CONTROL_PLANE_CONFIGURATION_ERROR；
删除 dead `projection:financial_facts.statement_type`。

## R3.1-08 — Binding-owned Runtime Behavior Audit

所有 checker 的 provenance/coverage/freshness 行为走
`_prov_strategy(ctx, spec)` / `_cov_strategy(ctx, spec)` / `_fresh_strategy(ctx, spec)`
（binding-owned）；generic spec 不得覆盖 effective binding。production preflight
强制 binding + projector 存在，无自动 fallback。

## 冻结

registry ×5、schemas/*、router.py、collectors/*、migrations/*、runners/*、
Graph write 全部不变；Network 0 / LLM 0 / Acquisition execution NO /
Readiness recheck NO。如需第 7 个 contract correction → STOP 报告，不自行修改。

## 完成后状态

```text
P7-D1: IMPLEMENTED / AWAITING INDEPENDENT RE-ACCEPTANCE
（R1/R2/R3/R3.1 repair chain）
```

不得自行声明 PASS / ACCEPTED / CLOSED / MERGE AUTHORIZED；PR #25 保持 OPEN /
DO NOT MERGE。

## Terminal Record（2026-08-16）

```text
ACCEPTED_IMPLEMENTATION_HEAD: bc277817ee419410803f5541d74be75a330e9713
INDEPENDENT_RE_ACCEPTANCE: PASS
P7-D1: PASS / INDEPENDENTLY ACCEPTED
ACCEPTANCE_CI: 31899546501
PYTEST: 3215 passed / 6 skipped / 0 failed
SCHEMAS: 85/85 PASS
COMPILEALL: PASS
PR_25: MERGE AUTHORIZED / NOT MERGED
P7-D2 TASKBOOK + ARCHITECTURE DESIGN: AUTHORIZED
P7-D2 IMPLEMENTATION: NOT AUTHORIZED
```

该记录由独立复验与用户授权产生，不改写本任务实施时的历史门禁。治理闭环见
`docs/tasks/phase7-data-layer-d1-governance-closeout.md`。
