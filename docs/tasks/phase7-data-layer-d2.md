# P7-D2：Acquisition Execution Foundation

**TASKBOOK_STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE — P7-D2 FOUNDATION ONLY**
**MILESTONE: P7-D2**  
**DESIGN_COMMIT: `5976428`**  
**PARENT_ACCEPTED_IMPLEMENTATION_HEAD: `bc277817ee419410803f5541d74be75a330e9713`**  
**REAL_SOURCE_EXECUTION: NOT AUTHORIZED**  
**SPECIFIC_SOURCE_AUTHORIZATION: NONE**  
**NEW_COLLECTORS: 0**  
**SOURCE_EXPANSION: NO**  
**CAPABILITY_PROMOTION: NONE**  
**PRODUCTION_LLM_CALLS: 0**  
**GRAPH_WRITE: NONE**  
**PHASE6.1: NOT_AUTHORIZED**  
**DB: v6**  
**MIGRATIONS: NONE**  
**EXPECTED_SCHEMA_COUNT: 86**
**IMPLEMENTATION_CODE_HEAD: `b8c8de8cf3c1e81bb5c34be22298462ae33c0227`**
**VALIDATION_TEST_HEAD: `831afe4bc518ca2e5ffb23087d43ede4eadadd03`**

> 用户已于 2026-08-16 显式批准 P7-D2 Foundation implementation。本授权仅覆盖
> 本任务书冻结的 Foundation，不授权真实来源执行或任何具体来源。

设计权威：
`docs/superpowers/specs/2026-08-16-p7-d2-acquisition-execution-foundation-design.md`。

## 1. 唯一目标

建立一个生产默认关闭、真实来源为空、可用 Fake 证明的 Acquisition 执行基础：

```text
P7-D1 DataReadiness before
→ AcquisitionPlan
→ DataAcquisitionCoordinator
→ execution gate
→ existing Router
→ CollectorFetcherBridge
→ normalize + Schema validation
→ atomic idempotent RawItem persistence
→ P7-D1 DataReadiness after
→ existing Runner
```

本里程碑只证明执行基础设施正确，不证明任何真实来源可用。

## 2. 已冻结架构

### 2.1 唯一 Router

- `src/research_os/routing/router.py` 仍是唯一 source routing authority。
- 现有 `Router.resolve() -> DataRoute` 行为完全兼容。
- 新增 `resolve_with_items() -> RoutedDataBatch`，二者复用同一内部路由算法。
- 禁止 Router v2、第二套路由、Scenario 自选来源或 Plan 泄露来源。

### 2.2 唯一 Coordinator

`DataAcquisitionCoordinator` 固定运行在 P7-D1 preflight 与既有 Runner 之间：

```text
request validation
→ preflight before
→ coordinator
→ optional execution
→ readiness recheck
→ Runner.execute
```

普通 acquisition 失败不得覆盖 Runner 的 status / exit_code / missing_data。
只有控制面 Schema、配置、task/scenario/as_of 一致性错误才能在 Runner 前 fail closed。

### 2.3 生产默认关闭

新增严格配置：

```yaml
enabled: false
allowed_actions:
  - route_existing_sources
production_collector_ids: []
```

配置路径固定为 `config/data_acquisition_execution.yaml`。未知字段、未知 action、重复
collector ID 或非空但未授权的 production collector 列表均配置错误。Foundation 不增加
CLI / Dashboard live 开关；生产 factory 永远传 `live_authorized=false`。测试只注入内存
enabled policy + Fake Collector，不改写生产配置。

## 3. 执行门顺序

全局门与 step 门在任何网络或 DB 写入前依次通过：

1. `dry_run == false`；
2. 中央配置 `enabled == true`；
3. system-controlled `live_authorized == true`；
4. AcquisitionPlan 通过权威 Schema；
5. task_id / scenario / as_of 与调用上下文一致；
6. 合法但非 `route_existing_sources` 的 action 记录为 `skipped`；
7. 对 `route_existing_sources`，requirement 来自同一个 Scenario Requirement Registry；
8. step data_type 与 requirement 一致；
9. capability 存在且 lifecycle 精确为 `BUSINESS_SUFFICIENT`；
10. 才允许调用 existing Router。

任一全局门失败 → 所有 step `NOT_EXECUTABLE`；route step 的 requirement/data-type/
capability 门失败 → 该 step `NOT_EXECUTABLE`。合法非 route action → `skipped`；未知 action
由 AcquisitionPlan Schema 拒绝。所有这些路径均 Router 0 / Collector 0 / Network 0 /
DB write 0。
当前真实 capability 全部低于 `BUSINESS_SUFFICIENT`，因此生产路径不可执行。

## 4. 新契约

新增且只新增一个权威 Schema：

```text
schemas/acquisition_execution_result.schema.json
```

对应 Pydantic 模型放在 `src/research_os/models/data_acquisition.py`，并注册到
`src/research_os/validators/schema_validator.py`。Schema registry 从 85 → 86。

`AcquisitionExecutionResult` 必须包含：

- deterministic `execution_id`（task_id + canonical plan SHA256 → UUID5）；
- task_id / scenario / as_of / plan_sha256；
- started_at / finished_at；
- overall status；
- 原 Plan 顺序的 step results；
- before/after requirement IDs（中央 Registry 顺序）；
- warnings 与结构化、脱敏 error records。

Overall status 精确为：

```text
not_executable | completed | partial_success | failed
```

Step status 精确为：

```text
not_executable | skipped | completed | partial_success | failed
```

Plan 保持不可变；不得回写 AcquisitionStep.status，不得向 Plan 添加 source/provider。

## 5. Collector Bridge

`CollectorFetcherBridge` 将注入的 `source_id -> CollectorAdapter` 映射适配为 Router
fetcher：

```text
discover → fetch each ItemRef → normalize each RawPayload
→ validate every RawItem → items + fields_present
```

- Bridge 不包含 CSS selector、Cookie、凭证、平台登录或来源专用业务规则。
- 保留 source ID、失败原因、adapter version 与 rate-limit policy 边界。
- Foundation production registry 为空；只有测试 Fake Collector。
- 任一 normalize 输出 Schema invalid，整次 source attempt 失败并如实进入 Router audit。

## 6. PIT 与时间规则

- Router time window 由既有 RequirementContext 确定性生成，终点为 task.as_of。
- 所有时间 parse-then-compare，禁止字符串字典序。
- `published_at > as_of` → `FUTURE_ITEM_REJECTED`，禁止持久化。
- malformed / missing authoritative publication time → ineligible / fail closed。
- retrieved_at 记录真实获取时间，不替代 publication/effective time。
- 历史 endpoint 返回旧文档不自动证明 PIT；真实来源须另行证明历史版本语义。
- recheck 复用同一 task_as_of、Requirement Binding、Projector、provenance、coverage、
  freshness、tier authority，不创建简化版 recheck。

## 7. 幂等与原子持久化

`AcquisitionWriteRepository` 在打开事务前完成全批验证与稳定 ID 计算。

RawItem UUID5 identity：

```text
external_id exists: source_id + external_id + content_hash
otherwise:          source_id + canonical_http_url + content_hash
```

URL canonicalization 只允许 scheme/host 小写、默认端口移除、fragment 移除、query 稳定排序；
不得任意删除 query 参数。

- 相同 identity 重跑复用首次持久化对象，不覆盖 retrieved_at。
- external_id 相同但 content_hash 不同 → 新内容版本。
- identity 碰撞且 source/content 不一致 → fail closed。
- Network 在事务外；DataRoute + 本 step 全部新 RawItem 在一个 SQLite transaction 内写入。
- 任一 insert 失败 → 整 step rollback。
- 不使用会逐条 commit 的 `Database.upsert()` 实现批次原子写；使用专用 repository。
- DB v6 已有 data_routes/raw_items，因此 migrations 保持 NONE。

## 8. 空结果与错误语义

Reason code 精确集合：

```text
EXECUTION_DISABLED
LIVE_GATE_DISABLED
DRY_RUN_PROHIBITS_EXECUTION
PLAN_CONTEXT_MISMATCH
ACTION_SKIPPED
REQUIREMENT_NOT_FOUND
DATA_TYPE_MISMATCH
CAPABILITY_NOT_BUSINESS_SUFFICIENT
ROUTE_UNAVAILABLE
FETCH_FAILED
NORMALIZATION_FAILED
RAW_ITEM_SCHEMA_INVALID
FUTURE_ITEM_REJECTED
EMPTY_RESULT
PERSIST_FAILED
RECHECK_FAILED
CONTROL_PLANE_CONFIGURATION_ERROR
```

- 空响应：只持久化 DataRoute audit，RawItem 0，step=`partial_success` +
  `EMPTY_RESULT`，readiness 保持 MISSING/STALE；不得解释为无事件/无变化/无关注。
- 一条 invalid item：整 step 不持久化。
- persistence failure：rollback + `PERSIST_FAILED`。
- persistence 已 commit 但 recheck 配置失败：overall=`partial_success`；保留已写事实，
  禁止伪造 after readiness。
- error detail 必须脱敏，不保存凭证、Cookie、headers、完整 payload 或网页全文。

## 9. Artifacts

非 dry-run run directory 新增：

```text
acquisition_execution.json
data_readiness_after.jsonl
```

既有 artifacts 不改名、不改语义：

```text
data_readiness_before.jsonl
data_gaps.jsonl
acquisition_plan.json
```

dry-run 仍为零 network / 零 DB write / 零 artifact write。关闭 gate 的非 dry-run
运行写 `not_executable` audit，并执行只读 recheck；不得产生业务数据写入。

## 10. 文件边界

允许新增：

```text
config/data_acquisition_execution.yaml
schemas/acquisition_execution_result.schema.json
src/research_os/data_layer/execution_policy.py
src/research_os/data_layer/collector_bridge.py
src/research_os/data_layer/execution.py
src/research_os/data_layer/acquisition_repository.py
src/research_os/data_layer/coordinator.py
tests/contracts/test_data_acquisition_execution_contract.py
tests/unit/test_data_acquisition_execution_policy.py
tests/unit/test_data_acquisition_router.py
tests/unit/test_data_acquisition_repository.py
tests/unit/test_data_acquisition_execution.py
tests/integration/test_data_acquisition_foundation.py
```

允许最小修改：

```text
src/research_os/models/data_acquisition.py
src/research_os/models/__init__.py
src/research_os/validators/schema_validator.py
src/research_os/routing/router.py
src/research_os/data_layer/__init__.py
src/research_os/data_layer/preflight.py
src/research_os/orchestrator/orchestrator.py
tests/integration/test_data_layer_preflight.py
tests/unit/test_document_governance.py
docs/engineering-guide.md
docs/project-state/DECISIONS.md
docs/project-state/CURRENT_STATE.md
docs/project-state/NEXT_PHASE.md
docs/project-state/KNOWN_LIMITATIONS.md
README.md
```

禁止修改：

```text
registry/sources.yaml
registry/data_requirements.yaml
registry/scenario_data_requirements.yaml
registry/data_acquisition_capabilities.yaml（Foundation 不提升 capability）
src/research_os/collectors/**
src/research_os/orchestrator/runners/**
src/research_os/storage/migrations/**
knowledge/ontology/**
```

若实现发现必须越过禁止范围，立即 STOP，报告新的设计/授权需求。

## 11. 强制测试

### 11.1 Contract

- ExecutionResult normal / boundary / failure；
- additionalProperties false；unknown status/reason 拒绝；
- Pydantic dump → Schema 通过；
- AcquisitionPlan 继续拒绝 source/provider 泄露；
- SCHEMA_NAMES 精确 86。

### 11.2 Unit

- 每个 gate 的 zero Router / Collector / network / write 证明；
- Router.resolve 兼容 + resolve_with_items decision parity；
- Bridge 调用顺序、field union、错误传播；
- stable UUID5、replay reuse、content version、collision；
- 全批 validate-before-write、atomic commit/rollback；
- future/malformed time rejection；
- empty result；error sanitization；LLM 0。

### 11.3 Integration

- MISSING → Fake acquisition → READY；
- STALE → new content version → READY；
- primary fail → secondary success，audit 完整；
- empty → readiness 不升级；
- replay RawItem count 不增长；
- 一条 invalid → 全 step rollback；
- commit 后 recheck failure → partial_success；
- disabled path 与 P7-D1 Runner 行为一致；
- 10/10 Runner status / exit_code / missing_data 不变。

## 12. 完成定义

```text
Implementation scope: P7-D2 Foundation only
Real source execution: 0
Production collector IDs: []
Capability BUSINESS_SUFFICIENT promotions: 0
New collectors: 0
Source expansion: 0
LLM/provider calls: 0
Graph writes: 0
DB: v6
Migrations: 6 / NONE added
Schemas: 86
pytest: 0 failed
schema validation: 86/86 PASS
compileall: PASS
diff-check: PASS
Offline CI: SUCCESS
```

完成后只能报告：

```text
P7-D2 FOUNDATION: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
REAL DATA ACQUISITION COVERAGE: NONE
```

不得自行声明 PASS / CLOSED / REAL SOURCE READY / MERGE AUTHORIZED。

## 13. 实施授权门

开始代码前必须全部满足：

1. 本 taskbook 与详细实施计划已提交；
2. 用户确认 taskbook/plan；
3. 用户显式回复批准 P7-D2 Foundation implementation；
4. 将 header 状态改为 `IMPLEMENTATION AUTHORIZED — P7-D2 FOUNDATION ONLY`；
5. 在 Decision #49 与 engineering-guide V1.7 写入批准边界；
6. 工作树干净，基线测试通过。

2026-08-16 授权记录：用户显式批准 P7-D2 Foundation implementation；第 1–5 项已满足。
第 6 项由实施 Agent 在开始与交付前机械复核，不扩大上述授权边界。

## 14. 实施交接（2026-08-16）

```text
P7-D2 FOUNDATION: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
REAL DATA ACQUISITION COVERAGE: NONE
Implementation code head: b8c8de8cf3c1e81bb5c34be22298462ae33c0227
Validation/test head: 831afe4bc518ca2e5ffb23087d43ede4eadadd03
Production policy enabled: false
Real source execution: 0
Production collector IDs: []
Capability BUSINESS_SUFFICIENT promotions: 0
New collectors: 0
Source expansion: 0
LLM/provider calls: 0
Graph writes: 0
DB: v6
Migrations: 6 / NONE added
Schemas: 86
Offline CI run: 31944228373
Offline CI URL: https://github.com/rzpeuler/ai-investment-research/actions/runs/31944228373
Environment: Ubuntu / Python 3.12.13
pytest full: 3563 passed / 6 skipped / 0 failed / 1 warning / 363.27s
schema validation: 86/86 PASS
compileall: PASS
Offline CI: SUCCESS
```

本节只交接已实现的 Fake-proven Foundation，等待独立验收；不声明 PASS / CLOSED /
operational / real-source ready，不授权任何具体真实来源或 Phase 6.1。

首次 Ubuntu run `31943822195` 仅因 fresh-process source-path portability 失败；
validation/test head `831afe4bc518ca2e5ffb23087d43ede4eadadd03` 修复该问题后，继任 run
`31944228373` 成功。该成功仍只是 Offline/Fake 证明，不构成独立验收或真实来源授权。
