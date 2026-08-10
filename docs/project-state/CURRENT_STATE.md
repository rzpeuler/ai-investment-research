# 当前项目状态（CURRENT STATE）

> 更新日期：2026-08-10
> Phase 6：CLOSED / PASS（P6-S6 Governance Closeout）
> 权威规范：`docs/engineering-guide.md` V1.3
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
- Schemas: 69；DB: v6；migrations: NONE；USER_TRIAL_READY: YES。
