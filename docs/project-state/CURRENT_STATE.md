# 当前项目状态（CURRENT STATE）

> 更新日期：2026-08-07（本地修复复验）
> 权威规范：`docs/engineering-guide.md` V1.1
> 本文件只陈述实际完成状态，不覆盖工程指南或正式决策。

## 工程基线

- `code_baseline`: `ce656b1866e0d65b1def292d26bed9c41474983b`
- 基线来源：PR #1 以 Squash merge 合入 `master`，提交标题为
  `fix: unify research control plane and close evidence governance gaps`。
- 基线范围：统一研究控制面、模型调用预算、语义 Evidence 资格、核心财务来源质量
  和维度级专业评审 Evidence 治理补修。
- 基线验收：1067/1067 tests passed，50/50 schemas passed；合并时仓库未配置远端状态检查。

## 阶段状态

| 阶段 | 状态 | 说明 |
|---|---|---|
| Phase 0 / 0.1 | PASS | 项目骨架、契约和控制面基础已完成 |
| Phase 1 / 1.1 | PASS | 来源探测底座与行情契约边界已完成 |
| Phase 2 | PASS | 晨报已形成真实 RawItem→Evidence→Claim→EventCluster→Markdown 链路 |
| Phase 3 | PASS | 异动分析保持既有完成状态 |
| Phase 4 engineering foundation | PASS | 统一控制面、财务确定性能力、Evidence 血缘、Validator、正式语义任务入口、状态机和专业评审已接入 |
| Phase 4 full research capability | PARTIAL_SUCCESS | 未配置真实 Provider，自动来源及业务/行业竞争/风险/催化剂/反证/市场主要矛盾仍可能缺失；运行时按实际覆盖降级 |
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

## 数据与模型现状

- 自动财务源、自动历史日线、通用 PDF 表格/OCR 和完整行业/同行数据仍未验证或未接入。
- 真实 LLM Provider 未配置；Fake Provider 只用于离线链路测试，不能作为生产调用成功声明。
- 人工财务导入属于 Tier C，不等价于法定披露原件；来源质量不足会导致 `degraded`。
- 报告的 `report_date`、`as_of`、`requested_at` 分开记录；默认日期使用上海时区，
  未显式给出 as_of 时标记为 `query_cutoff`，不能冒充实际数据日期。

## 当前准入结论

Phase 4 的工程基础已达到可执行、可追溯和可降级标准，但完整研究能力仍依赖真实语义
Provider 与更多高质量结构化来源。当前不得把 Phase 4 写成单一完整 PASS；Phase 5 继续
`BLOCKED`。本次精确测试数字以完成报告中的实际命令输出为准，不以历史测试数量代替验收。

## 2026-08-07 定向补修验收

- 全量测试：`python -m pytest -q`，1067 collected / 1067 passed，0 failed；
- Schema：`python -m research_os.cli.main validate`，50/50 通过；
- 编译：`python -m compileall -q src tests` 通过；
- 补丁格式：`git diff --check` 通过（仅 Windows LF→CRLF 提示）。

本轮四个工程 BLOCKER 已由实现与回归测试关闭，Phase 4 engineering foundation 保持
`PASS`。真实 Provider、高质量核心财务原件及完整研究覆盖仍未满足，因此 Phase 4 full
research capability 保持 `PARTIAL_SUCCESS`，Phase 5 保持 `BLOCKED`。
