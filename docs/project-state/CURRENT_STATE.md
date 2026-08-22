# 当前项目状态（CURRENT STATE）

> 更新日期：2026-08-18
> Phase 6：CLOSED / PASS（P6-S6 Governance Closeout）
> P7-UX1：PASS / INDEPENDENTLY ACCEPTED（governance closeout）
> P7-D0：PASS / INDEPENDENTLY ACCEPTED（governance closeout 2026-08-11）
> P7-D1：PASS / INDEPENDENTLY ACCEPTED（accepted implementation head `bc27781`）
> P7-D2：PASS / INDEPENDENTLY ACCEPTED（2026-08-18，accepted head `55c4ba5`）
> P7-D3：PASS / INDEPENDENTLY ACCEPTED（2026-08-18，accepted head `e8a4a9f`；已合并进 master）
> P7-D4：IMPLEMENTED / ACCEPTED（2026-08-19 独立验收通过并 no-squash 合并进 master，accepted baseline `8b153b3`）
> 权威规范：`docs/engineering-guide.md` V1.9
> 本文件只陈述实际完成状态，不覆盖工程指南或正式决策。

## 工程基线

- `phase4_accepted_master_sha`: `4dfe84f7e53ec2ede04f1e8522b37116d04c87f7`
- `pre_phase5_engineering_baseline`: `ea026f18ce09efd2f0a24bab8a38255e75233911`
- `phase5_accepted_code_master_sha`: `1e1d4f9b77425d6800182055f8c4dd96aeb54a50`
- Phase5 之后的 governance-only commits 不改变 `phase5_accepted_code_master_sha`。
- `phase6_accepted_code_master_sha`: `3e0166de11ae9969792a4726913cb68a17c8f2a5`
- P6-S6 为 governance-only；其后续治理合并提交不改变 Phase 6 accepted code baseline。
- 基线来源：PR #3 以 Squash merge 合入 `master`，提交标题为
  `feat: complete phase4 full research capability`；上一工程基线为 `ce656b1`。
- 基线范围：保留统一控制面和 Evidence 治理补修，并完成真实 DeepSeek Provider、官方
  财务原件血缘、七项语义任务、时间治理及版本化在线验收摘要。
- 基线验收：1131 tests passed，5 online tests skipped，51/51 schemas passed；三个显式在线
  验收案例 3/3 通过；合并时仓库未配置远端状态检查。
- Phase 4.1 当前代码里程碑：`7a515a4`；真实验收产物位于 Git 忽略的本地 `reports/`，
  版本化验收清单位于 `config/equity_research_acceptance.yaml`。
- Phase 4.1 独立验收 SHA：`9506f6a19ab60187d1ab0bc4991cfa427606ecae`；验收结论
  `INDEPENDENT_ACCEPTANCE: PASS`。PR #3 已以 Squash 合并，master SHA 为
  `4dfe84f7e53ec2ede04f1e8522b37116d04c87f7`。

- `pre_phase5_engineering_baseline`:
  - `ea026f18ce09efd2f0a24bab8a38255e75233911`
  - 基线提交：`c35632b` — ci: add offline validation gate；
    `ea026f1` — fix: make cninfo collector platform independent
  - Offline CI baseline run 31154022296：Ubuntu / Python 3.12，
    1133 passed / 5 skipped / 51/51 schemas / compileall PASS；
    permissions: contents: read；无 DeepSeek key / 无 project secrets

## 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 / 0.1 | PASS | 项目骨架、契约和控制面基础已完成 |
| Phase 1 / 1.1 | PASS | 来源探测底座与行情契约边界已完成 |
| Phase 2 | PASS | 晨报已形成真实 RawItem→Evidence→Claim→EventCluster→Markdown 链路 |
| Phase 3 | PASS | 异动分析保持既有完成状态 |
| Phase 4 engineering foundation | PASS | 统一控制面、财务确定性能力、Evidence 血缘、Validator、正式语义任务入口、状态机和专业评审已接入 |
| Phase 4 full research capability | PASS | 两个真实 SUCCESS 和一个预期降级通过在线复验，独立验收已签字 |
| Phase 5 | PASS | **PR5B MERGED** (cfdeeba7)。M0-M10 PASS。**PR5C #6 MERGED / SQUASH** (master 1e1d4f9)。Post-merge governance hotfixes #7, #8 merged (master 1087520)。**M10 PASS** (accepted SHA 156ea35, CI 31292861813)。Phase 5 terminal state 不重新打开。 |
| Phase 6 Top-Level Design | FROZEN / APPROVED | DECISIONS #41 + #43 + #44；engineering-guide V1.3 §69。并行已取消，串行 S0→S6。 |
| P6-G0 | PASS / MERGED | Phase 6 顶层设计治理冻结（PR #13）。 |
| P6-F0 | PASS / MERGED | 共享契约冻结（PR #14）。 |
| Phase 6 | CLOSED / PASS | 七个研究场景已通过验收并由默认 Registry / Orchestrator 中央启用；USER_TRIAL_READY = YES。 |
| P7-UX1 Conversational Research Gateway | PASS / INDEPENDENTLY ACCEPTED | 本地 Chat UX / control-plane adapter 已通过独立验收；不代表 Phase 7 全阶段 PASS，不授权数据采集或 Phase 6.1。 |
| P7-D1 Data Readiness Control Plane | PASS / INDEPENDENTLY ACCEPTED | R1/R2/R3/R3.1 返修链已通过独立复验；PR #25 merge authorized / not merged；P7-D2 仅 taskbook 与架构设计获授权。 |
| P7-D2 Acquisition Execution Foundation | PASS / INDEPENDENTLY ACCEPTED | 2026-08-18 独立验收（accepted head `55c4ba5`）；Fake-proven execution foundation 正确；生产默认关闭、真实采集覆盖仍为 NONE。 |
| P7-D3 Free-Source Production MVP | PASS / INDEPENDENTLY ACCEPTED（2026-08-18，accepted head `e8a4a9f`）| nbs/cninfo 真实在线验收；allowlist [nbs, cninfo]；默认网络关闭；capability WORKFLOW_WIRED；独立验收 Decision #52，已合并进 master。 |
| P7-D4 CNINFO Filing → Core Financial Facts MVP | IMPLEMENTED / ACCEPTED | 2026-08-18 实施完成（implementation head `7c2791b`）；2026-08-19 独立验收通过并 no-squash 合并进 master（accepted baseline `8b153b3`）；company_document 年报 transient 下载 → DocumentRecord/Block/Evidence；derive_existing 首次实现（financial_statement_data ← company_document）；FinancialStatementExtractor；86 schema / DB v6。 |

## 2026-08-07 修复后的关键事实

- 三个核心 CLI 场景均调用统一 `Orchestrator.execute()`，再由显式 `ScenarioRegistry`
  分派到场景适配器和既有 Pipeline；Task ID 贯穿 Request、Run、运行目录和返回结果，
  非 dry-run 统一持久化 `task.json`、`plan.json` 与 `scenario_execution_result.json`。
- Plan 记录真实步骤、数据需求、运行预算、模型策略、降级路径和输出位置；dry-run
  使用内存数据库或纯计划路径，不创建业务产物。
- 晨报为每个窗口内 RawItem 建立 Evidence；Claim 和 EventCluster 只引用真实 Evidence ID；
  Markdown 同时区分 Claim 与 Evidence，并展示来源、发布时间和 URL。
- Phase 4 人工财务事实可反查 manifest、checksum、字段/行定位、导入来源、导入时间、
  解析器版本和是否法定披露原件；复用 Phase 2 事件时保留原始 Evidence ID。
- `EquityLlmTasks` 的四个最低任务进入正式 Pipeline，共享单个任务预算；每次 Flash 重试
  与 Pro 升级均在 Provider 调用前检查并即时计数，任务总上限可执行且审计记录准确。
- 四个语义任务按任务类型选择最低合格 Evidence；竞争因素同时校验引用 ID、实际
  `evidence_type` 与 `required_evidence_types`，不再接受人工财务 Evidence 冒充官方披露。
- 无 Provider 时 `llm_called=false` 且不生成 `MODEL_INFERENCE`；语义阶段和研究状态如实降级。
- Phase 4 状态由版本化集中规则判定；核心财务、业务竞争、事件和整体证据质量分开计算，
  无关 S/A 事件不能掩盖 Tier C 核心财务来源。
- 专业评审为确定性 0—5 分制，各维度只引用相关支持/反证 Evidence，不使用通用前五条兜底。

## Phase 4.1 真实能力证据

- DeepSeek `deepseek-v4-flash` 通过真实 probe 和结构化调用；API Key 仅从
  `DEEPSEEK_API_KEY` 读取，调用记录和验收摘要不保存密钥、Prompt 或响应全文。
- 巨潮资讯通过真实元数据检索、官方 PDF 定位、下载与 checksum 验证；四份年报原件
  默认不提交 Git。
- 600519.SH：`SUCCESS`，7/7 必需语义任务，Flash 8 / Pro 0，2 份官方年报，18 项
  核心财务事实全部可反查 locator，Validator `pass_with_warnings`，正文禁止项 0 命中。
- 300750.SZ：`SUCCESS`，7/7 必需语义任务，Flash 8 / Pro 0，2 份官方年报；2023
  万元与 2024 千元经确定性标准化后复算通过，Validator `pass_with_warnings`，禁止项 0 命中。
- 688981.SH：受控缺失财务文件，`INSUFFICIENT_DATA`，Flash/Pro 均为 0，未被提升为 success。
- 本轮定向复验将研究截止点固定为 `2026-08-07T00:00:00+08:00`，每个案例开始时
  捕获一次真实确认时间；36 个 locator 的 `confirmed_at` 均不晚于对应 `requested_at`，
  不再与 `as_of` 伪绑定。未来 `as_of` 仅允许最多 5 秒时钟误差。
- CNINFO 默认发现和健康检查窗口均按上海时区动态计算最近 5 个自然日；显式历史窗口
  继续严格尊重调用方输入，不含固定生产年份。
- 在线过程中观察到 Provider 间歇性超时；失败运行均受共享 8/1 预算约束并合法降级，
  不能复用成功案例状态掩盖新的调用失败。

## 数据与模型现状

- 自动财务源、自动历史日线、通用 PDF 表格/OCR 和完整行业/同行数据仍未验证或未接入。
- DeepSeek 已配置并真实验证；默认离线测试仍使用 Fake Provider，真实调用必须显式 `--live`。
- 人工财务导入属于 Tier C，不等价于法定披露原件；来源质量不足会导致 `degraded`。
- 报告的 `report_date`、`as_of`、`requested_at` 分开记录；默认日期使用上海时区，
  未显式给出 as_of 时标记为 `query_cutoff`，不能冒充实际数据日期。

## 当前准入结论

PR5B 已 squash merge 进入 master（`cfdeeba7604efed2ac730c8e0e15692d49809b4d`）。
PR5B closeout CI `31270208169`：2009 passed / 5 skipped / 55/55 schemas / compileall PASS。
M0-M9 全部通过独立验收。
M9 PASS（SHA `d097ca8`，CI `31275096225`，2068 passed / 5 skipped / 0 xfail / 55/55 schemas / DB v6）。
M9 scope：existing structured research objects → GraphChange candidate；
Graph→Research NOT implemented；no Schema/migration change；source whitelist frozen。
M10 PASS。PR5C #6 MERGED。Governance hotfixes #7, #8 MERGED。

## 2026-08-07 最终工程与在线验收

- 全量测试：`python -m pytest`，1136 collected / 1131 passed / 5 online skipped / 0 failed；
- Schema：`python -m research_os.cli.main validate`，51/51 通过；
- 编译：`python -m compileall -q src tests` 通过；
- 补丁格式：`git diff --check` 通过（仅 Windows LF→CRLF 提示）。
- 在线定向：修正时间语义后三个 Phase 4.1 验收案例在同一显式 `--live` 运行中 3/3 通过
  并重新生成脱敏摘要；此前 DeepSeek probe、巨潮元数据与 PDF 下载测试继续有效。

Phase 4 engineering foundation 与 full research capability 均为 `PASS`，Phase 4 正式收口；
M1 Graph Contracts 已通过独立架构验收（SHA `b097996`，CI `31165533237`）。
M2 Persistence and ontology seed 已完成（graph_nodes/graph_edges/graph_reviews 迁移、
GraphRepository 版本化持久层、本体种子导入）。
M3 GraphChange Candidate Pipeline 已通过验收（SHA `242e039`，CI `31240709634`，1480 passed / 5 skipped / 55/55 schemas）。
M4 Knowledge Validator 已通过验收（SHA `20b7a15`，CI `31241777234`，1611 passed / 5 skipped / 55/55 schemas）。
M5 Human Review Workflow 已通过验收（SHA `92649a7`，CI `31251491357`，1725 passed / 5 skipped / 0 xfail / 55/55 schemas）。
M6 Deterministic Apply Engine 已通过独立验收（SHA `480b209`，CI `31257395650`，1809 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变），状态 PASS。
M7 Supersede / Expire / History 已通过独立验收（SHA `651e9a1`，CI `31262745492`，1911 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变），状态 PASS。
M8 Query + Knowledge Context Builder 已通过独立验收（SHA `eac18e26fd9696094d3bfe5edbe662c84731c106`，Offline CI `31269460005`，2009 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变），状态 PASS。
PR5B 已 squash merge（master `cfdeeba7`）。M0-M10 PASS。PR5C #6 MERGED / SQUASH (master `1e1d4f9`)。Post-merge governance hotfix #7 MERGED (master `2c55c55`)。Phase5 CLOSED / PASS。

## Phase 6

| Milestone | Status |
|---|---|
| P6-G0 Top-Level Design | PASS / MERGED |
| P6-F0 Shared Contract | PASS / MERGED |
| P6-S0 Serial Governance Reset | PASS / MERGED |
| P6-S1 6B Final Closure | PASS / MERGED |
| P6-S2 6A Final Closure | PASS / MERGED |
| P6-S3 Earnings Expectation | PASS / MERGED |
| P6-S4 First Coverage | PASS / MERGED |
| P6-S5 Central Enablement | PASS / MERGED |
| P6-S6 Governance Closeout | GOVERNANCE CLOSEOUT |

### Phase 6 terminal summary

- Seven Phase 6 scenarios: `industry_research`, `theme_discovery`, `evening_brief`,
  `daily_review`, `stock_review`, `earnings_expectation`, `first_coverage`。
- Research capability: PASS。
- Default registry: ENABLED；public execution: `research execute`；public execution authority:
  `Orchestrator.execute()`。
- Graph→Research: READ ONLY / ENABLED VIA ACCEPTED 6A，唯一路径为 Versioned Graph →
  GraphQueryService → KnowledgeContextBuilder → Research Context。
- KnowledgeContext != Evidence；Graph FACT 必须重新加载权威 Evidence，并通过
  eligibility / as_of / source validation 后才能形成 Research Finding。
- Scenario direct Graph write: NONE；Phase 6 scenario → active Graph: PROHIBITED。
- Phase 5 GraphChange Candidate / Review / Apply capability 已存在；Phase 6 scenario
  Research→GraphChange Candidate integration: DEFERRED。
- Historical Phase 6 terminal snapshot: Schemas: 69；DB: v6；migrations: NONE；
  USER_TRIAL_READY: YES。该数字是 Decision #45 的历史验收快照，不是当前注册表数量。
- Current registry after P7-UX1 implementation: Schemas: 80；DB: v6；migrations: NONE。
- Current registry after P7-D0 contracts: Schemas: 85；DB: v6；migrations: NONE。
- P7-D1 新增：`data_layer` 控制面（readiness/gap/planning）+ `data_acquisition_capabilities.yaml`；Schema 仍 85。

## P7-UX1 当前状态（terminal / governance closeout）

- 授权：`LIMITED AUTHORIZATION`；状态：`PASS / INDEPENDENTLY ACCEPTED`（2026-08-10
  governance closeout，Decision #46.7 / #46.8）。P7-UX1 独立验收通过，但该状态
  不覆盖 Phase 7 全阶段，不授权数据采集或 Phase 6.1。
- 本地会话入口已经实现：`research dashboard` 或 `scripts/start_dashboard.bat`；用户选择
  具体场景或 AUTO 后使用自然语言，无需填写 JSON。
- Chat 只生成 Public Request Draft 与确定性 Minimal Public Request；正式执行仍唯一进入
  `Orchestrator.execute()`，并由 Runner 校验和持久化正式 artifacts。
- Chat DeepSeek 预算固定为 route≤1 Flash、extract≤1 Flash、total≤2 Flash、Pro=0；
  LLM 与 Research Live 是两个独立 gate。
- `P7 DATA ACQUISITION: NOT_STARTED / AWAITING_ARCHITECTURE_DISCUSSION`；
  `PHASE6.1: NOT_AUTHORIZED`；Phase 6 Research→GraphChange Candidate 继续 `DEFERRED`。
- Governance closeout 保持：`DATA_ACQUISITION_CHANGED: NO`、`COLLECTORS_CHANGED: NO`、
  `SOURCE_REGISTRY_CHANGED: NO`、`GRAPH_WRITE: NONE`、`DB: v6`、`MIGRATIONS: NONE`、
  `SCHEMAS: 85`（P7-D0 后）。

## P7-D0 当前状态（PASS / INDEPENDENTLY ACCEPTED）

- 授权：`IMPLEMENTATION AUTHORIZED — P7-D0 ONLY`；状态：`PASS /
  INDEPENDENTLY ACCEPTED`（2026-08-11，Decision #47.8 / #47.9）。独立架构验收
  通过；accepted implementation head = `d06d8d714958f58d44fb130f8fb30a3aff7e4a7a`。
  该状态不授权 P7-D1 或数据采集。
- P7-D0-R1 返修（contract strictness + governance closure）已包含在验收 head 内：
  `public_metrics` 改为严格 `array[PublicMetric]`、`scope` 完整字段全部 required、
  Registry 对第 11 个/missing scenario 与 wrapper 未知字段 fail-closed、watchlist
  增加 `content_scope`（财联社 = non_fast_news_only）、未验证条目
  `last_verified_at: null`、Router 治理措辞收口。详见 `docs/tasks/phase7-data-layer-d0-r1.md`。

## P7-D1 当前状态（PASS / INDEPENDENTLY ACCEPTED）

- 授权：`IMPLEMENTATION AUTHORIZED — P7-D1 ONLY`；终态：`PASS /
  INDEPENDENTLY ACCEPTED`（2026-08-16，Decision #48.10/#48.11）。accepted
  implementation head = `bc277817ee419410803f5541d74be75a330e9713`；Acceptance CI
  `31899546501`：3215 passed / 6 skipped / 0 failed，85/85 schemas，compileall PASS。
  PR #25 已获 merge authorization，但仍 OPEN / NOT MERGED。
- 实现 `src/research_os/data_layer/*` 控制面：RequirementContextResolver →
  DataReadinessService → GapClassifier → AcquisitionPlanner → DataPreflightService。
- `Plan.data_requirements` / `data_requirement_ids` 由中央
  `registry/scenario_data_requirements.yaml` 生成；Runner 旧字段 LEGACY。
- 新增 `registry/data_acquisition_capabilities.yaml`（22 data_type，与 scenario
  data_type 集合一致）；`schemas/data_readiness.schema.json` 的 coverage_ratio 支持 null。
- Preflight 在 Runner.execute 前；普通数据不足不 gate Runner；配置错误 fail closed。
- 非 dry-run 持久化 `data_readiness_before.jsonl` / `data_gaps.jsonl` /
  `acquisition_plan.json`；dry-run 零副作用。
- R3.1（P7-D1-R3.1）完成 Final Runtime Closure：
  完全消除 lexical datetime（parse-then-compare + date-only 显式边界 +
  malformed fail-closed）、REQUESTED_RUN_SET coverage 生效（valid/requested
  比率、去重、no-scan）、run_id 正式 artifact 证明（禁 directory fallback）、
  EntityMapping coverage 服从 binding（subject singleton / industry-global null）、
  Graph projectable payload 经 runtime projector 保留、8 类 schema-valid runtime
  fixtures 全循环、projection gate exact registry（9 个已实现）、binding-owned
  provenance/coverage/freshness 全链路。
  详见 `docs/tasks/phase7-data-layer-d1-r3-1.md`。
- R3（P7-D1-R3）完成 Runtime Semantic Binding Closure：
  BindingResolver/Projector 接入 production preflight（design-time = runtime）、
  Evidence subject scope 经 RawItem provenance、previous_run_ids 专用 context +
  prior_run_lineage 共享 helper、timezone-aware PIT/window、Document/Industry tier。
  详见 `docs/tasks/phase7-data-layer-d1-r3.md`。
- R2（P7-D1-R2）完成 Authority Semantics Closure：43/43
  RequirementReadinessBinding、minimum-field closure 100%、精确 6 项 D0 contract
  纠偏、SecurityProfile/Valuation 生命周期、Financial canonical value、Tier 全链路、
  Graph query_graph 实证、dry-run 拆两测试。详见 `docs/tasks/phase7-data-layer-d1-r2.md`。
- 冻结 5 个数据层契约：`ScenarioDataRequirement`、`DataReadiness`、`DataGap`、
  `AcquisitionPlan`、`BriefAttentionSnapshot`；Schema registry 为 85；DB 仍 v6；
  migrations NONE。
- 新增 `registry/scenario_data_requirements.yaml`（10/10 scenarios，43 requirements）
  与 `registry/brief_watchlist.yaml`（25 项 / 4 组）；`registry/data_requirements.yaml`
  新增 `brief_event_content` 与 `brief_attention_content`（primary/secondary 为空，
  仅声明需求存在，不接来源）。
- Brief Requirement A / C 已冻结（Decision #47 supersede 旧 Decision #1 的
  “舆论监测体系”整体语义）：`A = NEW EVENT DISCOVERY`、`C = CURRENT-WINDOW
  ATTENTION MONITORING`；`FAST_NEWS ∈ A`、`FAST_NEWS ∉ C`；C 为一次性窗口扫描，
  无持续监控 / 热度历史 / 排名变化 / 速度 / 加速度 / 持久化。
- P7-D1 收口时只授权 P7-D2 taskbook drafting 与 architecture design；后续 P7-D2
  Acquisition execution foundation 已获单独授权并完成实现；具体外部数据源、
  real-source execution、new collectors、source expansion 仍 `NOT AUTHORIZED`；
  `GRAPH_WRITE: NONE`；`PHASE6.1: NOT_AUTHORIZED`。

## P7-D2 当前状态（PASS / INDEPENDENTLY ACCEPTED）

- `P7-D2: PASS / INDEPENDENTLY ACCEPTED`（2026-08-18，Decision #50）。独立验收
  accepted head：`55c4ba55847aec91ae425d86bf3415fcf867e7f4`（基于交接 head
  `84f70b5` + 1 项返修：清除 D2 文档 19 处尾随空格以满足 diff-check gate）。
- `REAL DATA ACQUISITION COVERAGE: NONE`；最终 implementation / validation head：
  `84f70b5dec1a65c9842628c974e1693738ab9cca`。本治理记录只做验收收口，不把该 head
  自行提升为真实来源可用。
- Foundation 已实现 deterministic execution gates、existing Router bridge、atomic RawItem /
  DataRoute persistence、post-acquisition readiness recheck、orchestrator integration、artifacts
  与十个 Runner 的关闭路径回归；证明仅使用 Fake。
- Production execution policy：`enabled: false`；Production collector IDs: []；Real source
  execution: 0；Capability BUSINESS_SUFFICIENT promotions: 0；New collectors: 0；Source
  expansion: 0；LLM/provider calls: 0；Graph writes: 0。
- DB: v6；Migrations: 6 / NONE added；Schemas: 86。
- Offline CI run `31945487755` 在 Ubuntu / Python 3.12.13 成功：3567 passed /
  6 skipped / 0 failed / 1 warning，417.14s；Schema 86/86 PASS；compile success。
  前一 run `31943822195` 仅因 fresh-process source-path portability 失败；该问题由
  validation/test head `831afe4bc518ca2e5ffb23087d43ede4eadadd03` 修复，继任 run 随后成功。
- 独立验收复现（2026-08-18，Windows 本地）：full pytest `3567 passed / 6 skipped /
  0 failed / 1 warning`；schema validation `86/86 PASS`（`PYTHONPATH=src`）；compileall
  PASS；diff-check PASS。验收矩阵逐项对照 taskbook §12 完成定义全部满足。
- 独立验收 PASS 只证明 Fake-proven Foundation 正确；不授权任何具体来源、Collector、
  capability promotion、Graph write 或 Phase 6.1。任何 real-source execution 仍须新的
  来源治理、taskbook、架构批准与显式 implementation authorization（P7-D3）。

## P7-D3 当前状态（PASS / INDEPENDENTLY ACCEPTED，2026-08-18）

- `P7-D3: PASS / INDEPENDENTLY ACCEPTED`（Decision #52，accepted head `e8a4a9f`，
  已合并进 master）。真实免费来源生产闭环已实现并通过独立验收：
  - `nbs → macro_data`：真实 stats.gov.cn 采集 → RawItem → 持久化 → readiness recheck；
    幂等验证 reuse=7；PIT 有效。
  - `cninfo → company_announcement`：沪市 600519（inserted=6 / reused=6 幂等）与
    深市 300750（验收窗口 6 条真实公告）真实采集；secid/orgId 官方映射。
  - `SourceQueryProjector`（canonical → source query）与 `FieldProjector`
    （RawItem → minimum-field evidence）精确注册表；未知组合 fail closed。
  - `--live-data` 显式门（与 `--live`/LLM 分离）；默认网络关闭；环境变量不能打开；
    allowlist 恰好 [nbs, cninfo]；capability 晋级 WORKFLOW_WIRED（非 BUSINESS_SUFFICIENT）。
- 独立验收复现（2026-08-18）：full pytest `3642 passed / 6 skipped / 0 failed`；
  schema `86/86 PASS`（`PYTHONPATH=src`）；compileall PASS；diff-check PASS；
  独立审查无 blocker（dry-run 零落盘、cninfo 窗口过滤、external_id 缺失跳过已修复）。
- 验收 PASS 不自动授权 capability BUSINESS_SUFFICIENT 或新增来源/Collector/付费接口/OCR/
  LLM 财务提取/Graph write/Phase 6.1/DB migration/新 Schema；BUSINESS_SUFFICIENT 由后续
  治理 closeout 单独晋级（NBS/CNINFO 分开）。
- 验收 artifact（本地，reports/ gitignored）：`reports/acceptance/nbs_online_acceptance.md`、
  `reports/acceptance/cninfo_online_acceptance.md`。

## P7-D4 当前状态（IMPLEMENTED / ACCEPTED，2026-08-19）

- `P7-D4: IMPLEMENTED / ACCEPTED`（2026-08-19 独立验收通过并授权合并；no-squash
  合并进 master，accepted baseline `8b153b3`；taskbook
  `docs/tasks/phase7-data-layer-d4.md`）。CNINFO 官方年报 → 核心 FinancialFact 生产链路已实现：
  - `TransientDisclosureMaterializer`（方案 B）：CNINFO 年报 transient PDF 下载（严格校验：
    magic header/Content-Type/HTML 拒绝/zero-byte/checksum）→ DocumentRecord/Block/Evidence
    幂等持久化（UUID5）；不永久保存完整 PDF；pypdf 转正式依赖。
  - `derive_existing` 首次正式实现：`DerivationPrerequisiteResolver`（§19 的 11 项证明，
    ZERO NETWORK）+ `FinancialDerivationService` + `FinancialDerivationExecutor`；
    plan dependencies 生成与 execution 强制（前置未 completed → DERIVATION_PREREQUISITE_MISSING）。
  - `FinancialStatementExtractor`：确定性三表提取（CORE 9 码/consolidated/exact taxonomy/
    current-period 列标题 authority + 恒等式校验/Decimal）；fuzzy 不自动接受；不确定即 reject。
  - Schema 契约演化（backward-compatible）：produced_record_refs / reused_record_refs +
    7 个 D4 reason codes；SCHEMA_COUNT 保持 86；DB v6 / migration NONE。
  - capability：company_document / financial_statement_data → WORKFLOW_WIRED
    （deterministic_derivation 保守 false；独立在线验收后 closeout 才允许 true）。
- 离线验证：extractor/materializer/prerequisite/derive/pipeline 测试全绿；合并后 master
  全量 pytest `3685 passed / 6 skipped / 0 failed`（2026-08-19）。在线验收
  （600519/300750 + 人工数字抽查）由独立验收者以 --live-data 执行并已通过
  （GOV-MERGE-P7D4-01，2026-08-19）。
- BUSINESS_SUFFICIENT（company_document）与 deterministic_derivation=true
  （financial_statement_data）的晋级由后续治理 closeout 单独批准（不随本 merge 自动发生）。

## GOV-ARUX1 顶层架构与产品治理冻结（2026-08-18，DESIGN FROZEN / NOT IMPLEMENTED）

- 任务书：`docs/tasks/governance-agent-runtime-frontend-design-freeze.md`；正式决策：
  `DECISIONS.md` **#54（Agent Runtime / Skill / MCP）** 与 **#55（Frontend Product
  Architecture）**；架构文档：`docs/architecture/agent-runtime-skill-architecture.md`、
  `docs/architecture/frontend-product-architecture.md`；工程指南升级 **V1.8**。
- 治理分支：`governance/agent-runtime-frontend-design-freeze`；GOV_BASE_SHA =
  `7c2791b2b854b88279c4c3126f7b1b2f8e861460`（D4 暂停 HEAD，与用户报告一致）。
- **P7-D4：IMPLEMENTED / ACCEPTED（2026-08-19 独立验收通过并合并进 master）**；
  implementation head = `7c2791b2b854b88279c4c3126f7b1b2f8e861460`。治理冻结期间
  D4 范围未改；D4 已按原 D4 taskbook 完成独立验收（GOV-MERGE-P7D4-01）。

```text
AGENT_RUNTIME_ARCHITECTURE: DESIGN_FROZEN
HARNESS_ARCHITECTURE: DESIGN_FROZEN
HARNESS_IMPLEMENTATION: SPIKE_COMPLETE
HARNESS_PILOT_DESIGN: DESIGNED / AWAITING ACCEPTANCE (P8-A1, 2026-08-22)
HARNESS_PILOT_IMPLEMENTATION: IMPLEMENTED / AWAITING ACCEPTANCE (P8-A2, 2026-08-22; runtime router + policy + permission + audit + corpus + POSIX validation; default runtime legacy)
HARNESS_PILOT_EVALUATION: EVALUATED / AWAITING ACCEPTANCE (P8-A3, 2026-08-22; real Harness exploration corpus run; governance all-pass; agentic-latency finding on open exploration prompts; report docs/architecture/p8-a3-pilot-evaluation-report.md; default runtime legacy)
HARNESS_EXPLORATION_CONTROL: IMPLEMENTED / AWAITING ACCEPTANCE (P8-A3-R1, 2026-08-22; Exploration Execution Contract: objective/allowed_tools/max_turns/max_tool_calls/completion_rule/empty_data_policy; timeout_count 5->0; report docs/architecture/p8-a3-r1-exploration-control-report.md; default runtime legacy)
PRODUCTION_ACCEPTANCE: NO
DEEPSEEK_HARNESS: TECHNICAL_INTEGRATION_VIABLE / P8-B1 FOUNDATION AUTHORIZED
HARNESS_INTEGRATION: P8-A0 PASS / INDEPENDENTLY ACCEPTED
HARNESS_PRODUCTION_ACCEPTANCE: NO
CURRENT_CHAT_RUNTIME: P7-UX1 / LEGACY FALLBACK / IN_MEMORY_ONLY
FRONTEND_PRODUCT_ARCHITECTURE: DESIGN_FROZEN
CAPABILITY_GUIDE: DESIGNED / NOT_IMPLEMENTED
DATA_SOURCE_MANAGEMENT_UI: DESIGNED / NOT_IMPLEMENTED
FRONTEND_SOURCE_EDITING: NOT_IMPLEMENTED
P8-A0: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-A0_ACCEPTED_HEAD: f16a3163814345e9aee2d00615a42dae57fd86fb
P8-A0_HYBRID_SPIKE: EXECUTED / AWAITING INDEPENDENT ACCEPTANCE (2026-08-21; hybrid 4-tool MCP facade + 3 skills + real continuous session; report docs/architecture/p8-a0-hybrid-runtime-spike-report.md; default runtime legacy; P8-A1 NOT_AUTHORIZED)
P8-A1_HYBRID_PILOT_DESIGN: DESIGNED / AWAITING INDEPENDENT ACCEPTANCE (2026-08-22; pilot design docs/architecture/p8-a1-hybrid-pilot-design.md: task classification HARNESS_ALLOWED/LEGACY_REQUIRED, deterministic Runtime Router, permission model, session governance, audit boundary, pilot acceptance criteria; docs-only, no runtime switch; P8-A2 implementation NOT_AUTHORIZED)
P8-A2_HYBRID_PILOT_IMPLEMENTATION: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE (2026-08-22; runtime router + runtime_policy.yaml + permission policy + audit lineage + pilot corpus + POSIX validation workflow; default runtime legacy; P8-A3 NOT_AUTHORIZED)
P8-A3_HYBRID_PILOT_EVALUATION: EVALUATED / AWAITING INDEPENDENT ACCEPTANCE (2026-08-22; real Harness exploration corpus executed; governance audit 100% / unauthorized 0 / drift 0 / secret 0 / strict_schema never entered harness; 300s turn budget timeout finding on open exploration prompts; simple directed turn 9.5s; POSIX CI first run FAILED pre-fix, workflow ready for re-run; report docs/architecture/p8-a3-pilot-evaluation-report.md; default runtime legacy; P8-A4 NOT_AUTHORIZED)
P8-A3_R1_EXPLORATION_CONTROL: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE (2026-08-22; Exploration Execution Contract layer: config/exploration_policy.yaml + exploration_contract.py loader + exploration_controller.py bounded execution; objective/allowed_tools/max_turns/max_tool_calls/completion_rule.required_fields/empty_data_policy; timeout_count 5->0 in real run; audit +exploration control lineage; skills +contract metadata; report docs/architecture/p8-a3-r1-exploration-control-report.md; default runtime legacy; P8-A4 NOT_AUTHORIZED)
P8-B: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B1: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B_DESIGN_HEAD: 9aa7071
HARNESS_VERSION: @deepseek-ai/dsh@0.1.0-rc.7
HARNESS_UPSTREAM: DEVELOPER PREVIEW
P8-B1_MCP_NAMESPACE: research-os-mcp/v1
P8-B1_MCP_TOOLS: get_company_profile, check_data_readiness
P8-B1_DEFAULT_RUNTIME: legacy
P8-B1_PRODUCTION_ADOPTION: NOT_AUTHORIZED
P8-B1_R1: SUPERSEDED BY R2 FINDINGS / RE-ACCEPTANCE REQUIRED
P8-B1_R2: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B1_R3: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B2: IMPLEMENTED / PARTIAL / NOT ACCEPTED
P8-B2_R2: IMPLEMENTED / evidence-integrity repair delivered; PARTIAL official trial (no provider credential / Harness binary available in isolated worktree)
P8-B2_ENV-01: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE (environment readiness task `docs/tasks/p8-b2-env-01-trial-environment-readiness.md`); live probe on Windows host = FAIL (fail-closed: owned process-tree cleanup NOT_VERIFIED on Windows); pinned Harness boot / provider credential + connectivity / runtime-profile / MCP boot+namespace+toolset / secret hygiene all VERIFIED; FORMAL_TRIAL_READY = NO on this host; formal corpus NOT executed
P8-B2_LIVE-01: EXECUTED → PARTIAL (2026-08-20 RESUME-02 formal trial on GitHub Actions ubuntu-latest: readiness probe READY incl. provider connectivity; trial ran 1 provider-backed turn attempt → PROVIDER_TIMEOUT (typed, counted once, no retry); session 2 create → HARNESS_BOOT_FAILED (Harness process not READY after timeout) → latch tripped → fail-closed stop; SESSIONS completed=0/10 (1 create success), TURNS completed=0/20 (1 attempted); process cleanup VERIFIED (root TERMINATED / tree VERIFIED / residue NO); secret_scan PASS (0 leaks); rollback/restart/fallback drills PASS; MCP namespace+tools exact; evidence snapshot generated; FORMAL_CORPUS_EXECUTED=YES (bounded, provider-backed); P8-B2 NOT accepted — Sol verification required)
P8-B2_REPAIR-01: COMPLETE (2026-08-20 root cause: our stdio MCP server reported MCP protocolVersion "1", rejected by the pinned Harness's MCP SDK (@deepseek-ai/dsh-mcp-client) → dsh process crashed (exit 1) → turn failure masked as PROVIDER_TIMEOUT → supervisor FAILED → HARNESS_BOOT_FAILED; NOT provider latency — fixed turn completes in 22.7s. Minimal fix applied: negotiate_mcp_protocol_version (contracts.py) + stdio server uses it; namespace/tools/failure semantics unchanged. Bounded single-turn diagnostic after fix: TURN_COMPLETED 22.7s, process alive, supervisor READY. Re-run condition met; formal corpus NOT re-executed)
P8-B2_LIVE-01_RESUME-03: EXECUTED → PARTIAL (2026-08-21 formal trial re-run post-REPAIR-01 on GitHub Actions ubuntu-latest, run 32391248096: CORPUS COMPLETED — sessions 10/10, turns 20/20, turn_attempts=20, turn_completed=20, same_session_pass=20, turn2_reread_pass=10, turn1_evidence_pass=10, authority_drift=0, unauthorized=0, secret_leak=0, secret_scan=PASS, provider_failures=0, mcp_failures=0, typed_failures={}, process_residue=NO (root TERMINATED / tree VERIFIED), drills PASS, latency p50=6218ms/p95=8767ms, session_create 10/10; ONLY unpassed PASS gate: provider_tokens>0 — total_tokens=NOT_REPORTED because the accepted runtime reports usage under dsh-specific keys (projections.values.tokenUsage: uncachedInputTokens/outputTokens/cacheReadTokens/cacheWriteTokens) that _extract_usage does not map (extraction gap, same class as REPAIR-01; needs REPAIR-02 taskbook); P8-B2 NOT accepted — Sol verification required)
P8-B2_REPAIR-02: COMPLETE (2026-08-21 usage evidence extraction mapping fixed: _extract_usage now maps dsh rc.7 tokenUsage fields — uncachedInputTokens/outputTokens/cacheReadTokens/cacheWriteTokens → input_tokens/output_tokens/cached_tokens/cache_read_tokens/cache_write_tokens/total_tokens (total = uncached+output+cacheRead+cacheWrite; provider-reported only, no inference); 9 offline regression tests; real-runtime bounded validation: EXTRACTED_USAGE {input 23201, output 587, cached 10624, total 23788} → provider_tokens>0 TRUE. Governance finding: measured per-turn usage ~24-44k tokens × 20 turns ≈ 480-880k EXCEEDS frozen max_provider_tokens=200,000 — budget decision required from Sol before next formal trial run; budget NOT modified)
P8-B2_BUDGET-DECISION: DECIDED (2026-08-21 governance decision `docs/tasks/p8-b2-live-01-budget-decision.md`: Option A (keep 200,000) incompatible with the 20-turn contract (exhaustion ~turn 5-9 → corpus unreachable); Option C (fewer turns) rejected as standard-lowering; DECISION = Option B: raise max_provider_tokens 200,000 → 1,000,000 — observed 23.8k-44.3k tokens/turn (provider-reported), derived 20 turns ≈ 476k-886k, cap 1M = +13% headroom over observed high end, warning 0.8 → 800k; cost bounded (≤1M tokens, provider-reported only); acceptance gate / failure semantics / retry / timeout / concurrency unchanged. Implementation of the TrialBudget value change = ARCHITECTURE_DECISION_REQUIRED → follow-up authorized taskbook (no code change in this task); pending Sol acceptance)
P8-B2_BUDGET-IMPL: IMPLEMENTED (2026-08-21 BUDGET-IMPL-01: TrialBudget.max_provider_tokens 200,000 → 1,000,000 per BUDGET-DECISION-01; LIVE-00 §5.6 synced; budget test assertion pinned; full pytest/schema/compile/CI green)
P8-B2_NEXT: Sol acceptance of BUDGET-DECISION + BUDGET-IMPL; then re-run LIVE-01 (new RESUME taskbook) per LIVE-00 boundary
P8-B2_INTERNAL-TRIAL-001: COMPLETE (2026-08-21 harness internal-trial verification: audit confirms single AI entry = LlmClient, no second AI path; default provider stays legacy (frozen); opt-in HarnessLlmProvider (P8_B2_SCENARIO_TRIAL=1) routes scenario LLM calls through the pinned Harness control plane; 5 scenarios verified (first_coverage/earnings_expectation real EquityLlmTasks via Harness; evening_brief/stock_review/industry_research honest llm_called:false); failure/budget/audit/no-fake-MODEL_INFERENCE locked by 14 offline tests; P8-B3/production adoption NOT_AUTHORIZED)
P8-B2_R1: COMPLETE (2026-08-21 harness output contract stabilization: deterministic normalizer unwrap/key-conformance/prune between harness output and Sol schema validation; schema-valid success 0 → 1 (catalyst_candidates via real harness, errs=0); no standard lowering, no validator bypass, no fabrication; audit +resolved_model_id (observed deepseek-v4-flash); 27 offline tests; P8-B3/production adoption NOT_AUTHORIZED)
P8-B2_EVAL-001: ESTABLISHED (2026-08-21 harness quality benchmark: corpus 13 cases decoupled from LIVE-01; first real run 32444324435 — schema_valid_rate=0.10 vs legacy 0.80 (threshold 0.70 NOT_MET); all other P8-B3 thresholds MET (no fake MODEL_INFERENCE / no validator bypass / audit 100% / no budget violation / no secret leakage / no silent retry); failure cases honest fallback; P8-B3 recommendation: not yet — harness output conformance work required before re-run)
P8-B2_R3: COMPLETE (2026-08-21 harness agent output optimization: schema-aware context injection — JSON-only instruction + required-field list + constraint summary + deterministic example; schema/validator/normalizer unchanged. Benchmark re-run 32447199752: schema_valid_rate 0.10 → 0.50 (phase goal >=0.30 MET; P8-B3 threshold 0.70 NOT met — remaining 4 missing_required_field + 1 json_format); failure classification added; all other thresholds MET; P8-B3 not yet)
P8-B2_R4: COMPLETE (2026-08-21 harness schema adherence optimization: schema slice + completion checklist + self-validation + field-level missing stats implemented; empirical iteration over 4 benchmark runs — checklist/self-validation regressed (0.2x2), slice-only 0.3, measured-best R3 structure 0.4-0.5; target >=0.70 NOT MET (finding_id etc. 20 required fields missing x5 cases — model field-completion issue, prompt levers exhausted); schema/validator/normalizer/threshold unchanged; P8-B3 not yet)
P8-B2_R5-A: COMPLETE (2026-08-21 generation controller implemented: GenerationControlledProvider with bounded validator-driven repair loop (max 2 passes) + field-level error extraction + audit extension (generation_pass/repair_round/provider_calls); benchmark run 32460687556: missing_required_field 3-5 → 0 (repair effective); json_format 5 (honest fallback per contract); repair metrics: success 0.333 / avg rounds 1.67 / added calls 10; schema_valid_rate 0.3 (variance band); 0.70 not required in R5-A; schema/validator/normalizer/threshold unchanged; P8-B3 not yet)
P8-B2_R6: COMPLETE (2026-08-21 harness generation strategy evaluation: task-level runtime selection strategy — classify tasks extraction/normalization/reasoning/generation; R5-D evidence harness 0.10 vs legacy 0.90 (schema_valid_rate); Harness strong on agentic exploration/tools/multi-turn (LIVE-01 20/20), Legacy strong on strict-schema structured generation; recommendation: strict_schema → LEGACY_ONLY, tools/multi-turn → HARNESS_CANDIDATE (governance-flagged), hybrid = explore(Harness)→draft(Legacy); Task Runtime Router design only, no code, no runtime switch; P8-B3 structured-generation default stays legacy; docs/tasks/p8-b2-r6-harness-generation-strategy-evaluation.md + docs/architecture/harness-task-runtime-routing-design.md; P8-B3 NOT_AUTHORIZED)
FRONTEND IMPLEMENTATION: NOT_AUTHORIZED
```

## P8-B2-R5-B — Harness Structured Output Capability Probe (2026-08-21)

The probe-only capability detector and bounded normal-vs-structured runner are
implemented. The pinned Harness adapter exposes no provider-level
`send_structured_message` seam; the real bounded probe ended
`BLOCKED / PROBE_TIMEOUT` before comparison metrics were available. No
structured-output support is claimed, and no production routing, schema,
validator, threshold, or default runtime changed. The report records
`fake_model_inference=0` and `validator_bypass=0`. P8-B2 remains
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`.

## P8-B2-R5-D — Harness Benchmark Reevaluation (2026-08-21)

The fixed EVAL-001 corpus contains 13 cases. With benchmark-only case timeout
20s and global timeout 900s, preflight/health passed and cleanup reported
`process_residue=NO`. Final report `reports/harness_benchmark_r5d.json`:
schema_valid_rate `0.10`, task success `0.10`, fallback `0.90`, JSON recovery
10 attempts / 1 success / 9 failures, recovery success rate `0.10`, and
`json_format_failure` 6 (R3 baseline 1; R5-A baseline 5). Repair success was
`1.0` for 1 case needing repair, average rounds `1.0`, added provider calls
5; provider calls 15, provider-reported token usage 0, latency p50 19.656s.
The P8-B3 schema gate `0.70` is `NOT_MET`; fake inference 0, validator bypass
0, audit completeness 100%, budget violation 0, and secret leakage 0.
No threshold, corpus, Schema, Validator, Normalizer, or runtime default
changed. P8-B3 remains not ready.

## P8-B2-R6 — Harness Generation Strategy Evaluation (2026-08-21)

Evaluation/design task (no code, no runtime switch). Task-level Runtime
Selection Strategy established from R5-D evidence
(`reports/harness_benchmark_r5d.json`): harness `schema_valid_rate` 0.10 vs
legacy 0.90, failure modes json_format_failure 6 + TURN_TIMEOUT 3 (harness
p50 latency 19.1s vs legacy 9.2s). Tasks classified extraction / normalization
/ reasoning / generation. Recommendation: strict-schema output →
`LEGACY_ONLY` (legacy 0.90); agentic exploration / tools / multi-turn →
`HARNESS_CANDIDATE` (governance-flagged, LIVE-01 20/20 sessions reliable);
hybrid = explore with Harness → draft with Legacy. Task Runtime Router designed
(deterministic, default legacy, audit `runtime_selection`), not implemented.
P8-B3 structured-generation default stays legacy; harness not the default
structured runtime. Deliverables: `docs/tasks/p8-b2-r6-harness-generation-
strategy-evaluation.md`, `docs/architecture/harness-task-runtime-routing-design.md`.
P8-B2 remains `IMPLEMENTED / PARTIAL / NOT ACCEPTED`; P8-B3 remains
`NOT_AUTHORIZED`.

## P8-ARCH-001 — Harness Hybrid Runtime Architecture Freeze (2026-08-21)

Governance-freeze task (docs only, production code 0 changes). DeepSeek Harness
Hybrid Runtime Architecture formally frozen into governance (Decision #80;
`docs/architecture/harness-hybrid-runtime-architecture.md`; engineering-guide
V1.9 §0.9). Based on P8-B2 evidence (harness schema_valid_rate 0.10 vs legacy
0.90, P8-B3 gate 0.70 NOT_MET): Harness = Agent Orchestration Runtime
(Conversation / Durable Session / Goal Management / Skill Loading / Tool
Scheduling / Exploration Workflow), NOT the default strict structured-generation
runtime; Research OS = Research Intelligence Authority (identity / readiness /
acquisition / evidence / PIT / graph / workflow / validator / report). LLM:
keep `research_os.llm`, allow dual LLM coexistence, no LlmClient rewrite. MCP:
Harness → MCP → Research OS Tools; no direct Data Source / Collector / DB /
Graph Write access. Skill = capability description + working method + routing
metadata; Tool = governed executable interface (allow get_company_profile /
check_data_readiness / query_industry_graph; deny apply_graph_change /
direct_data_source_access). Status: `HARNESS_ARCHITECTURE=DESIGN_FROZEN`,
`HARNESS_IMPLEMENTATION=NOT_IMPLEMENTED`, `PRODUCTION_ACCEPTANCE=NO`.
D4 scope unchanged (D4 already ACCEPTED/MERGED). Next after D4:
P8-A0 Hybrid Agent Runtime Spike (separate authorization).

## P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE — Hybrid Runtime Spike (2026-08-21)

P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE executed (branch
`task/P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE`): minimal Hybrid Runtime Spike
(Harness + Skills + MCP + Research OS Tools) forming a complete research loop.
Pinned `@deepseek-ai/dsh@0.1.0-rc.7` booted on host; MCP facade extended to the
4-tool spike surface (`get_company_profile` / `check_data_readiness` /
`query_industry_graph` / `run_research_scenario`) while the frozen 2-tool
P8-B1/P8-B2 contract stays the default (env-gated `P8_A0_HYBRID_SPIKE=1`).
3 skills (stock-research / financial-analysis / industry-graph-research)
discoverable and loaded with use-case/tool-selection/working-method content.
Real continuous session executed (4 turns: 研究宁德时代 → 现金流 → 产业链风险 →
比较亿纬锂能) with session continuity, tool invocation chain, audit trail and
authority checks (no source access / graph write / evidence mutation / validator
bypass; secret scan 0). Report:
`docs/architecture/p8-a0-hybrid-runtime-spike-report.md` +
`reports/p8_a0_hybrid_spike.json`. Tests: `tests/unit/test_p8_a0_hybrid_spike.py`
(offline); full pytest 2828 passed / 4 skipped / 0 failed; schema 86/86.
Default runtime remains legacy; P8-B3 / production adoption remain NOT_AUTHORIZED.
Windows process-cleanup evidence is fail-closed NOT_VERIFIED (accepted R2 model);
POSIX re-run recommended before P8-A1.

## P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN — Hybrid Agent Runtime Pilot Design (2026-08-22)

Design task (docs only, production code 0 changes). Hybrid Agent Runtime pilot
design established (`docs/architecture/p8-a1-hybrid-pilot-design.md`, Decision
#82): core principle Exploration → Harness, Structured Research Output → Legacy.
Task classification: `HARNESS_ALLOWED` (industry exploration / research
preparation / evidence discovery assistance / multi-turn analyst assistant /
hypothesis generation; output never directly becomes a formal Research
Artifact) vs `LEGACY_REQUIRED` (FinancialFact / ResearchFinding / Catalyst /
Risk / Evidence binding / Final report sections; strict Validator required).
Deterministic Runtime Router (inputs task_type / output_contract / risk_level /
authority_requirement → LEGACY_ONLY / HARNESS_ALLOWED / HYBRID; default
LEGACY_ONLY; whitelist is config artifact). Permission model (ALLOW company
profile / graph query / data readiness / bounded scenario trigger; DENY graph
write / evidence mutation / financial fact creation / datasource direct
access). Session governance (bounded lifetime; LLM request 60s / agent turn
300s / tool 30s timeouts; token budget provider-reported ≤ governance cap).
Audit boundary (runtime_selection / harness_session_id / skill_used /
tools_called / authority_checks / final_artifact_source → answers "which
runtime produced this conclusion?"). Pilot acceptance criteria (Reliability /
Governance / Value / Cost). No implementation authorized; default runtime
remains legacy; P8-A2 implementation NOT_AUTHORIZED.

## P8-A2-HYBRID-AGENT-RUNTIME-PILOT-IMPLEMENTATION — Hybrid Agent Runtime Pilot (2026-08-22)

P8-A2 pilot infrastructure implemented (Decision #83; default runtime remains
legacy; Harness is whitelist opt-in only). Runtime Router
(`agent_runtime/runtime_router.py`): deterministic, no LLM; inputs task_type /
output_contract / risk_level / authority_requirement → LEGACY_ONLY /
HARNESS_ALLOWED / HYBRID; strict_schema forces LEGACY_ONLY; unlisted tasks
default to legacy (fail-closed). Runtime Policy (`config/runtime_policy.yaml`
v1.0.0): config-driven exploration whitelist (industry_exploration /
research_preparation / evidence_discovery_assistance / analyst_assistant /
hypothesis_generation); default and strict_schema both forced legacy;
LEGACY_REQUIRED tasks rejected from whitelist. Permission Policy
(`agent_runtime/permission_policy.py`): fail-closed; ALLOW the 4 exploration
tools; DENY graph_write / evidence_mutation / financial_fact_creation /
direct_source_access. Audit Extension (`agent_runtime/pilot_audit.py`): runtime
lineage fields (runtime_selection / runtime_selection_reason / harness_session_id
/ skills_used / tools_called / authority_checks / final_artifact_source) and
`artifact_source()` answers "which runtime produced this artifact?". Harness
Pilot Entry (`agent_runtime/pilot_adapter.py`): Router → Permission → Runtime →
Audit; opt-in `P8_A2_HYBRID_PILOT=1`. Pilot Corpus
(`config/harness_pilot_corpus.yaml`): 8 cases (5 exploration + 3 negative
controls); no FinancialFact / ResearchFinding / final report Harness tasks.
POSIX validation (`scripts/p8_a2_posix_validation.py` + workflow
`p8-a2-posix-validation.yml`): Ubuntu CI `process_residue=NO`. Tests:
`tests/unit/test_p8_a2_hybrid_pilot.py` (29 offline); full pytest green; schema
86/86. No default runtime / LlmClient / Validator / Schema / authority changes.

## P8-A3-R1-HARNESS-EXPLORATION-CONTROL — Exploration Execution Contract (2026-08-22)

P8-A3-R1 fixes the P8-A3 open-ended exploration agent-loop finding (5/5 tasks
timed out at 300s/600s; directed prompts ~10s). Added an Exploration Execution
Contract layer (Decision #85): `config/exploration_policy.yaml` (v1.0.0,
config-driven) defines per HARNESS_ALLOWED task: objective / allowed_tools /
max_turns / max_tool_calls / turn_timeout_seconds /
completion_rule.required_fields (findings / unanswered_questions /
next_actions) / empty_data_policy (record_data_gap_and_stop) / failure_condition.
`agent_runtime/exploration_contract.py` (strict loader; missing contract refuses
execution) + `agent_runtime/exploration_controller.py` (bounded execution: turn 1
full contract prompt, turn N>1 bounded follow-up, per-turn tool counting from MCP
event log, deterministic completion detection — no LLM judge, empty-data stop —
no auto-retry, budget exhaustion → exploration_incomplete — fail closed).
`agent_runtime/pilot_adapter.py` enforces the contract for HARNESS_ALLOWED
(missing contract refused; tool subset within permission allowlist). Audit
extension (`pilot_audit.py`) adds exploration_contract / max_turns /
max_tool_calls / actual_turns / actual_tool_calls / completion_status while
keeping final_artifact_source. Skills updated with contract metadata. Real
pinned-Harness run: **timeout_count 5 → 0**, governance all-pass (audit 100% /
unauthorized 0 / drift 0 / secret 0 / strict_schema never entered harness),
negative controls stay LEGACY_ONLY. Tests:
`tests/unit/test_p8_a3_r1_exploration_control.py` (18 offline: contract load /
missing-contract refusal / turn-budget exit / tool-budget exit / empty-data
no-retry / governance). Report:
`docs/architecture/p8-a3-r1-exploration-control-report.md`. No Runtime Router
core / Legacy / LlmClient / Schema / Validator / authority changes. Default
runtime remains legacy; P8-A4 / P8-B3 / production adoption NOT_AUTHORIZED.

## P8-B2-R5-C — JSON Boundary Recovery Implementation (2026-08-21)

Implemented on branch `task/P8-B2-R5-C-JSON-BOUNDARY-RECOVERY-IMPLEMENTATION`.
The deterministic adapter recovers only whitespace/BOM, one Markdown JSON
fence, or one unique surrounding JSON object. Malformed, ambiguous,
duplicate-key, oversized, and unbalanced outputs fail closed. Recovery remains
before the unchanged Normalizer/Validator path; it never repairs fields or
values. Audit carries `json_recovery_attempted`, `json_recovery_type`,
`json_recovery_success`, boundary failure/candidate metadata, and bounded raw
length/hash.

Targeted regression tests: 56 passed. Schema validation: 86/86 PASS.
Compileall and diff check: PASS. Full Windows pytest did not complete within
the 10-minute limit and is not reported as PASS. The live provider benchmark
was blocked by the bounded Harness/provider process; no live result is claimed.
P8-B2 remains `IMPLEMENTED / PARTIAL / NOT ACCEPTED`; default runtime,
thresholds, Schema, Validator, and Normalizer remain unchanged.

Design complete; implementation is not authorized. The recommended future
position is an independent deterministic recovery adapter between raw provider
output and the unchanged Normalizer/Validator. It may recover only an
unambiguous JSON boundary and strict JSON object; it may not change syntax,
fields, values, or validation requirements. Recovery failures remain typed
`json_format_failure`/honest fallback and recovery metadata must be audited
without persisting raw output. R5-D is blocked pending separate implementation
and benchmark authorization. P8-B2 remains `IMPLEMENTED / PARTIAL / NOT
ACCEPTED`; P8-B3 and production adoption remain `NOT_AUTHORIZED`.

本治理冻结只改文档（AGENTS.md / README.md / engineering-guide / DECISIONS / 状态文档 /
architecture 文档 / 任务书）；production code 0 changes、schema count 86 不变、DB v6
不变、migrations NONE、source registry 不变。
## P8-A4-HYBRID-AGENT-RUNTIME-EXPANDED-PILOT (2026-08-22)

P8-A4 expanded the governed Hybrid Agent Runtime pilot corpus to 25 cases:
20 exploration cases across industry exploration, research preparation,
evidence discovery assistance, analyst assistance, and hypothesis generation;
5 Legacy-only negative controls. `config/exploration_policy.yaml` now contains
20 complete Exploration Execution Contracts, and missing contracts remain
fail-closed. The runtime whitelist, permission surface, audit lineage, and
formal Artifact authorities are unchanged.

Offline governance execution completed 20/20 bounded exploration cases and
routed 5/5 controls to Legacy. The real opt-in runner
`scripts/p8_a4_expanded_pilot.py` produced `PARTIAL / DATA_DEGRADED` because
the current environment lacked provider credentials; no offline result was
used to claim real reliability, value, or cost. Governance routing evidence is
100% audit complete with unauthorized_tool=0, authority_drift=0,
secret_leak=0, validator_bypass=0, and strict_schema_entered_harness=0.

The human evaluation interface is implemented and emits a `PENDING_REVIEW`
template for Sol. P8-A5 is not recommended until a provider-backed expanded run
and completed human evaluation are available. Default runtime remains legacy;
Harness production adoption remains NOT_AUTHORIZED.

## P8-A4-R1 REAL PROVIDER-BACKED VALIDATION (2026-08-22)

The explicit provider-backed runner completed 20/20 `HARNESS_ALLOWED` cases and
kept 5/5 `LEGACY_ONLY` negative controls on Legacy. Harness `0.1.0-rc.7` used
the existing `research-headless` profile and `research-os-mcp/v1` namespace.
Reliability was session success `1.00`, continuity `1.00`, timeout count `0`;
governance recorded audit completeness `25/25`, unauthorized tool `0`,
authority drift `0`, validator bypass `0`, secret leak `0`, and
strict-schema-entered-Harness `0`.

The result is `PASS CANDIDATE / AWAITING INDEPENDENT ACCEPTANCE`. Provider cost,
token, and latency evidence is recorded in the R1 report. Human value remains
`PENDING_REVIEW` with no automated usefulness score. Harness cleanup records the
root terminated but process-tree verification `NOT_VERIFIED`. Default runtime,
authorities, and production adoption status are unchanged; P8-A5 remains
`NOT_AUTHORIZED`.

## P8-A4-R2 HUMAN VALUE AND REGRESSION CLOSURE (2026-08-22)

R2 closed the regression and cleanup evidence gaps. Ubuntu run
`32570689988` passed full pytest (`3944 passed, 6 skipped, 1 warning`), schema
validation `86/86`, compile, and POSIX cleanup with `process_residue=NO`.
Windows full pytest was run under a 600-second bound and timed out after 3406
observed nodes / approximately 87%; the targeted slow Phase 5 groups passed,
with no single hung test identified.

The 20-case human review artifact is structurally valid but has 0/20 scored
cases and remains `PENDING_REVIEW`; no automated value score was used. Thus
P8-A4 is `PARTIAL / NOT_ACCEPTED`, Legacy remains default, and P8-A5 and
production adoption remain `NOT_AUTHORIZED`.
## P8-A4-R3 HUMAN REVIEW EVIDENCE BUNDLE (2026-08-22)

Generated `reports/p8_a4_human_review_bundle/` from the real R1 artifact without
rerunning Harness or changing any output. The bundle contains 20/20 case
directories with metadata, frozen corpus prompt, and exact R1 audit lineage.
R1 intentionally did not persist raw Harness responses, so all 20
`harness_output.txt` files are explicit `NOT_PERSISTED_BY_R1_ARTIFACT` markers;
no offline output or summary was substituted. Evidence completeness is
`metadata 20/20`, `prompt 20/20`, `audit 20/20`, `raw output 0/20`, complete
cases `0/20`. Human review remains blocked pending raw output evidence.

## P8-A4-R4 HARNESS EVALUATION ARTIFACT RETENTION (2026-08-22)

Added evaluation artifact retention to the governed real-run evaluator without
changing Harness behavior, prompt strategy, routing, permissions, or scoring.
Run `a3-eval-657677b514b8` retained 20/20 Harness case directories under
`reports/harness_evaluation_runs/<run_id>/`. Each case contains input, prompt,
raw Harness output, raw response records, session event delta, tool events,
audit lineage, per-case metrics, and SHA-256 file metadata. The run manifest
reports `raw_output_exists=true`, raw output 20/20, event snapshots 20/20,
audit 20/20, and immutable file hashes enabled.

The reviewer bundle was regenerated automatically from the retained run and is
now complete: metadata/prompt/output/audit 20/20 and complete cases 20/20.
Historical R1 artifacts remain unchanged and retain their original omission.
