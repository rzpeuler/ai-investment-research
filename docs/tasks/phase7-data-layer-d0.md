# P7-D0：Unified Data Layer Contracts & Brief Requirement Freeze

**TASKBOOK_STATUS: IMPLEMENTATION AUTHORIZED**
**MILESTONE: P7-D0**
**NEXT_MILESTONE: P7-D1 NOT AUTHORIZED**
**EXPECTED_BASE_MASTER_SHA: `efdb3e248dd045ca4736d9d612b241daf6f6ea41`**
**PHASE6.1: NOT AUTHORIZED**
**NEW COLLECTORS: NOT AUTHORIZED**
**SOURCE EXPANSION: NOT AUTHORIZED**
**GRAPH WRITE: NONE**
**DB: v6**
**MIGRATION: NONE**
**EXPECTED_SCHEMA_COUNT: 85**

> 本任务只冻结统一数据层契约与 Brief A/C 需求，不执行任何数据采集。
> 完成状态为 `IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE`，不得声明 PASS。

## 1. 本里程碑唯一目标

P7-D0 不负责"把数据采回来"，只回答四个结构问题并正式冻结 Brief 需求：

```text
1. 每个 Scenario 到底需要什么数据？
2. 系统以后如何结构化表达：数据够不够？
3. 如果不够，缺口属于什么类型？
4. 未来 Acquisition 应该执行什么动作？
```

正式冻结：

```text
A = 过去约 12 小时的新事件（NEW EVENT DISCOVERY）
C = 本报告窗口内相关从业人员正在关注什么（CURRENT-WINDOW ATTENTION MONITORING）
```

## 2. 新增治理决策

`docs/project-state/DECISIONS.md` 追加 Decision #47：

- 旧 Decision #1 将 `7×24快讯 / 深度媒体 / 社区 / 机构` 整体解释成同一"舆论监测体系"
  的语义被正式纠正 / supersede。
- `FAST_NEWS ∈ A`、`FAST_NEWS ∉ C`。
- C 不是持续监控系统（CONTINUOUS_MONITORING / HEAT_HISTORY / RANK_CHANGE /
  VELOCITY / ACCELERATION / PERSISTENCE 全部 NO）。
- A 和 C 不允许擅自产生第三种业务需求（四象限 / 信息差 / Narrative Risk 等禁止）。
- 数据层架构：Scenario → ScenarioDataRequirement → DataReadiness → DataGap →
  AcquisitionPlan → existing Router（本里程碑只实现前四类契约与 Registry）。
- `SCENARIO_DECLARES_SOURCE: NO`、`SECOND_ROUTER: NO`、`READINESS_NETWORK_ACCESS: NO`、
  `LLM_DATA_AUTHORITY: NO`、`ACQUISITION_PLAN_SELECTED_SOURCE: NO`。

## 3. 新增 Schema（5 个）

```text
schemas/scenario_data_requirement.schema.json
schemas/data_readiness.schema.json
schemas/data_gap.schema.json
schemas/acquisition_plan.schema.json
schemas/brief_attention_snapshot.schema.json
```

- `scenario` 只允许现有 10 个 Scenario；`purpose` 至少 research_input /
  brief_event_discovery / brief_attention_monitoring。
- `scope` 为结构化对象（global/subject/benchmark/peers/industry/watchlist/scenario），
  禁止 source_id / provider / URL / API endpoint。
- `time_policy` 至少 scenario_window / explicit_request_window / as_of_snapshot /
  latest_available / lookback_trading_days；Brief 使用 scenario_window，窗口由现有
  BriefWindowPolicy 决定，不在 Registry 重算日期。
- `point_in_time_policy` 至少 strict_as_of / window_bounded / current_snapshot /
  not_applicable。
- `DataReadiness` 状态只允许 READY / PARTIAL / MISSING / STALE / SOURCE_UNHEALTHY /
  MANUAL_REQUIRED / NOT_ACQUIRABLE；只描述状态，不执行网络。
- `DataGap` 分类只允许 AVAILABLE / AUTO_ACQUIRABLE / AUTO_DERIVABLE /
  STALE_REFRESHABLE / MANUAL_INPUT_REQUIRED / HUMAN_REVIEW_REQUIRED /
  GOVERNED_WORKFLOW_REQUIRED / UNAVAILABLE；不实现自动 GapClassifier。
- `AcquisitionPlan` step 的 action 至少 route_existing_sources / derive_existing /
  request_manual_input / request_human_review / governed_workflow / unavailable；
  step 禁止 source_id / selected_source / provider_id。
- `BriefAttentionSnapshot` 是 ONE REPORT RUN SNAPSHOT（非时间序列），scenario 只允许
  morning_brief / evening_brief；Schema 必须确认不存在 rank_change / previous_rank /
  velocity / acceleration / trend / persistence / history / historical_heat。
- heat_score 表示"本次报告窗口、本次实际覆盖样本中的相对关注程度"；不是历史变化、
  不是事实可信度、不是投资价值、不是机构交易行为。Heat 算法本阶段不实现。

## 4. Registry

- 新增 `registry/scenario_data_requirements.yaml`：覆盖全部 10 个 Scenario，只声明
  Data Type，禁止 source_id；无自动来源时如实体现 MISSING / MANUAL_REQUIRED /
  NOT_ACQUIRABLE。
- `registry/data_requirements.yaml` 新增 `brief_event_content` 与
  `brief_attention_content`，primary/secondary 为空，不接来源；fallback 仅复用已有
  人工入口；最低字段 title / published_at / url。
- 新增 `registry/brief_watchlist.yaml`：只迁移需求文档 / 工程指南 / 现有 registry 中
  已明确存在的名称；每个项目记录 watch_id / group / name / platform /
  source_reference / focus_tags / active / priority / access_mode /
  last_verified_at / notes。
- Watchlist 不等于 Source Registry；不得把每个博主账号变成 sources.yaml 平台级 Source。
- `registry/sources.yaml` 本阶段不得扩张。

## 5. 实现 Loader

- `src/research_os/routing/scenario_requirements.py`：
  ScenarioDataRequirementRegistry（加载 YAML、严格验证、按 Scenario 返回、确定性顺序、
  禁止重复 requirement_id、拒绝未知 Scenario / 未知字段 / Source ID 泄漏；不联网）。
- `src/research_os/brief/watchlist.py`：BriefWatchlistRegistry（读取、验证格式、
  过滤 active、按 group 返回、稳定排序；不采集网页、不访问网络）。

## 6. 现有代码边界

- 现有 Router（`src/research_os/routing/router.py`）不重写；resolve() 的来源选择语义
  不变，只允许必要的类型兼容 / 注释 / 测试辅助。
- BriefPipeline 不重构；不实现 Attention Topic 聚类 / Heat Ranking / 新采集 /
  LLM Brief Extraction / 全球新闻 Collector / 社区 Collector / 机构 Collector。
- 不新增数据库表（data_readiness / data_gap / attention / watchlist /
  acquisition_plan 全部禁止）；DB 保持 v6、无 migration。
- Schema 权威规则：JSON Schema = authoritative，Pydantic = constructor；
  model_dump() 后必须通过 JSON Schema revalidation；所有 Schema
  additionalProperties: false；完整对象字段全量 required。

## 7. 验证

- `python -m pytest`：0 failed；基线 2956 passed / 6 skipped，新增测试后 passed >= 2956。
- `python -m research_os.cli.main validate`：85/85 PASS。
- `python -m compileall -q src tests`：PASS。
- `git diff --check`：PASS。
- 本里程碑严禁联网验收（CNINFO / CLS / SSE / SZSE / NBS / CSRC / 社区 / 媒体 /
  Tushare / 任何新 API 全部禁止）；Offline CI 即可。
- 生产代码 LLM 调用数 = 0；Pro = 0。

## 8. 禁止事项

新增 Collector、修改 Source Registry 增加来源、Source Probe、联网爬取、Router v2、
DataReadinessService 实际查询 DB、GapClassifier、AcquisitionExecutor、自动补采、
Heat Ranking 算法、社区/博主/机构/全球新闻抓取、历史行情 API、财务 API、PDF LLM
Extractor、GraphChange、Graph write、Phase 6.1、DB migration、第 11 个 Scenario、
第二个 Orchestrator——全部属于后续任务。

## 9. 完成定义与交付

完成时报告 `P7-D0: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE`，不得自行升级
PASS。分支 `phase7/data-d0-contracts`，PR 保持 OPEN / NOT MERGED，等待独立架构验收。
