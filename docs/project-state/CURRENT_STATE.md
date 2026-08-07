# 当前项目状态（CURRENT STATE）

> 更新日期：2026-08-07（Phase 4.1 真实端到端验收准备完成）
> 权威规范：`docs/engineering-guide.md` V1.1
> 本文件只陈述实际完成状态，不覆盖工程指南或正式决策。

## 工程基线

- `code_baseline`: `ce656b1866e0d65b1def292d26bed9c41474983b`
- 基线来源：PR #1 以 Squash merge 合入 `master`，提交标题为
  `fix: unify research control plane and close evidence governance gaps`。
- 基线范围：统一研究控制面、模型调用预算、语义 Evidence 资格、核心财务来源质量
  和维度级专业评审 Evidence 治理补修。
- 基线验收：1067/1067 tests passed，50/50 schemas passed；合并时仓库未配置远端状态检查。
- Phase 4.1 代码里程碑：`633cf74`；真实验收产物位于 Git 忽略的本地 `reports/`，
  版本化验收清单位于 `config/equity_research_acceptance.yaml`。

## 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 / 0.1 | PASS | 项目骨架、契约和控制面基础已完成 |
| Phase 1 / 1.1 | PASS | 来源探测底座与行情契约边界已完成 |
| Phase 2 | PASS | 晨报已形成真实 RawItem→Evidence→Claim→EventCluster→Markdown 链路 |
| Phase 3 | PASS | 异动分析保持既有完成状态 |
| Phase 4 engineering foundation | PASS | 统一控制面、财务确定性能力、Evidence 血缘、Validator、正式语义任务入口、状态机和专业评审已接入 |
| Phase 4 full research capability | PARTIAL_SUCCESS / READY_FOR_INDEPENDENT_ACCEPTANCE | 两个真实 SUCCESS 和一个预期降级已通过本地定向验收；独立验收签字前不提前改为 PASS |
| Phase 5 | BLOCKED | 未满足全部解锁条件，不得开始产业图谱实现或自动批准 |

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
- 600519.SH：`SUCCESS`，7/7 必需语义任务，Flash 7 / Pro 0，2 份官方年报，18 项
  核心财务事实全部可反查 locator，Validator `pass_with_warnings`，正文禁止项 0 命中。
- 300750.SZ：`SUCCESS`，7/7 必需语义任务，Flash 7 / Pro 0，2 份官方年报；2023
  万元与 2024 千元经确定性标准化后复算通过，Validator `pass_with_warnings`，禁止项 0 命中。
- 688981.SH：受控缺失财务文件，`INSUFFICIENT_DATA`，Flash/Pro 均为 0，未被提升为 success。
- 在线过程中观察到 Provider 间歇性超时；失败运行均受共享 8/1 预算约束并合法降级，
  不能复用成功案例状态掩盖新的调用失败。

## 数据与模型现状

- 自动财务源、自动历史日线、通用 PDF 表格/OCR 和完整行业/同行数据仍未验证或未接入。
- DeepSeek 已配置并真实验证；默认离线测试仍使用 Fake Provider，真实调用必须显式 `--live`。
- 人工财务导入属于 Tier C，不等价于法定披露原件；来源质量不足会导致 `degraded`。
- 报告的 `report_date`、`as_of`、`requested_at` 分开记录；默认日期使用上海时区，
  未显式给出 as_of 时标记为 `query_cutoff`，不能冒充实际数据日期。

## 当前准入结论

Phase 4.1 已满足申请独立验收所需的本地工程与真实案例条件，结论为
`READY_FOR_INDEPENDENT_ACCEPTANCE`。独立验收签字前，正式 full capability 状态仍保持
`PARTIAL_SUCCESS`；Phase 5 继续 `BLOCKED`。

## 2026-08-07 最终工程与在线验收

- 全量测试：`python -m pytest -q`，1093 collected / 1088 passed / 5 online skipped / 0 failed；
- Schema：`python -m research_os.cli.main validate`，51/51 通过；
- 编译：`python -m compileall -q src tests` 通过；
- 补丁格式：`git diff --check` 通过（仅 Windows LF→CRLF 提示）。
- 在线定向：DeepSeek probe、巨潮元数据与 PDF 下载测试通过；三个验收案例分别单独显式
  `--live` 运行并生成脱敏摘要。

Phase 4 engineering foundation 保持 `PASS`；full research capability 已从“缺真实能力”
推进到“等待独立验收”，正式状态暂保持 `PARTIAL_SUCCESS`；Phase 5 保持 `BLOCKED`。
