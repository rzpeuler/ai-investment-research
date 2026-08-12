# P7-D1：Data Readiness + Gap Classification + Acquisition Planning Control Plane

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED — P7-D1 ONLY**
**MILESTONE: P7-D1**
**P7-D2: NOT AUTHORIZED**
**BASE_MASTER_SHA: `6314b781c8b796b9e367358542f61b55f52def4b`**
**ACQUISITION_EXECUTION: NOT AUTHORIZED**
**NEW_COLLECTORS: NOT AUTHORIZED**
**SOURCE_EXPANSION: NOT AUTHORIZED**
**ROUTER_FETCHING_REDESIGN: NOT AUTHORIZED**
**PHASE6.1: NOT AUTHORIZED**
**GRAPH_WRITE: NONE**
**PRODUCTION_LLM_CALLS: 0**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMA_COUNT: 85**

> P7-D1 把 P7-D0 冻结的控制面正式实现并接入统一 `Orchestrator.execute()`。
> P7-D1 产生 AcquisitionPlan，不执行 AcquisitionPlan（执行属于 P7-D2）。

## 1. 本阶段运行链

```text
Public Request → ScenarioRunner.validate_request() → Task
→ authoritative ScenarioDataRequirement Registry
→ RequirementContextResolver → DataReadinessService → GapClassifier
→ AcquisitionPlanner → Data Preflight → Existing ScenarioRunner.execute()
```

## 2. 新增治理

- `docs/project-state/DECISIONS.md` Decision #48（P7-D1 Data Readiness & Acquisition
  Planning Control Plane）冻结：READINESS READ_ONLY/DETERMINISTIC、
  GAP_CLASSIFICATION DETERMINISTIC、ACQUISITION_EXECUTION NO、SECOND_ROUTER NO、
  ROUTER_CORE_CHANGE NO、NEW_COLLECTORS NO、SOURCE_EXPANSION NO、PRODUCTION_LLM 0、
  GRAPH_WRITE NONE、PHASE6.1 NOT_AUTHORIZED、DB v6、MIGRATIONS NONE、SCHEMAS 85。
- `docs/engineering-guide.md` V1.5 → V1.6，新增 §0.6。

## 3. Requirement Authority 切换

- 正式 Data Requirement Authority = `registry/scenario_data_requirements.yaml`。
- Runner `build_plan()["data_requirements"]` 变 LEGACY / NON_AUTHORITATIVE。
- `Plan.data_requirements` 由中央 Registry 生成（canonical data_type 列表，
  确定性顺序、去重）；新增 `Plan.data_requirement_ids`（Registry 顺序不去重）。

## 4. 新建统一 data_layer package

```text
src/research_os/data_layer/
    __init__.py
    context.py       # RequirementContextResolver + ResolvedRequirementContext
    checkers.py      # ReadinessCheckerRegistry + checker families
    readiness.py     # DataReadinessService
    capabilities.py  # AcquisitionCapabilityRegistry
    gaps.py          # GapClassifier
    planning.py      # AcquisitionPlanner
    preflight.py     # DataPreflightService + DataPreflightBundle
```

## 5. 关键实现规则

- Resolver 在 `ScenarioRunner.validate_request()` 之后；scenario_window 复用现有
  BriefWindowPolicy，禁止第二套窗口计算；scope fail closed，不猜测实体。
- Readiness 判定顺序：Scope → PIT → fields → coverage → tier → freshness → status。
- checker 缺 data_type 时抛 `CONTROL_PLANE_CONFIGURATION_ERROR`（fail closed）。
- coverage_ratio 支持 null（open-world 无合法 denominator）；`minimum_coverage>0`
  且 null 时不得 READY。
- capability registry 与 scenario data_type 集合完全一致（missing/extra 拒绝）；
  AUTO_ACQUIRABLE / STALE_REFRESHABLE 仅 BUSINESS_SUFFICIENT。
- AcquisitionPlanner：只为 classification!=AVAILABLE 建 step；一条 Gap 最多一个主
  step；顺序=Registry 顺序；step_id 确定性 UUID5；禁止 source 泄露。
- Preflight 在 Runner.execute 前；普通数据不足不 gate Runner；配置错误 fail closed。
- 非 dry-run 持久化 `data_readiness_before.jsonl` / `data_gaps.jsonl` /
  `acquisition_plan.json`（Schema 校验后原子写）。
- dry-run：零 DB 写 / 零文件写 / 零网络 / 零 LLM。

## 6. 禁止事项

Router v2 / AcquisitionExecutor / Readiness Recheck / 真实 network acquisition /
新 Collector / 新 Source / Source Probe / Source Registry 修改 / Scenario
Requirement 业务语义修改 / 第 86 个 Schema / DB migration / 新 DB table / LLM /
Graph write / Phase6.1 / 改变已有 Runner business success semantics —— 全部属于
P7-D2+。

## 7. 完成定义

10/10 Scenario 中央权威、43/43 requirements、100% checker coverage、100% capability
coverage、Resolver/Readiness/PIT/coverage-null/GapClassifier(8 类)/Capability
lifecycle/Planner(确定性 step_id, source-free)/Orchestrator preflight 接入全部完成；
Router / Collectors / Source Registry / Scenario Requirement Registry 不变；
DB v6 / Migrations NONE / Schemas 85 / LLM 0 / Graph write NONE / Phase6.1
NOT_AUTHORIZED / P7-D2 NOT_AUTHORIZED；pytest 0 failed；85/85 PASS；compileall PASS；
diff-check PASS；CI SUCCESS。

完成后只能报告：

```text
P7-D1: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
```

不得自行声明 PASS / CLOSED / INDEPENDENTLY ACCEPTED。

---

**Independent acceptance: CHANGES_REQUIRED**
See `docs/tasks/phase7-data-layer-d1-r1.md`（Readiness Semantic Correctness & Authority Alignment）。
