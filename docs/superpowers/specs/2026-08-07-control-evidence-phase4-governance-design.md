# 统一控制面、Evidence 链与 Phase 4 治理修复设计

## 1. 目标与边界

本次修复关闭四组问题：统一控制面未实际编排三个核心场景、晨报 Claim/Evidence
对象链倒置、Phase 4 语义能力与完成状态不符、日期和状态文档分叉。保持现有 CLI
参数、主要退出码、运行目录、报告路径、幂等和 dry-run 语义；不实施 Phase 5，不新增
目标价、评级、仓位、交易建议或自动数据源。

## 2. 架构选择

采用轻量 ScenarioRunner 注册与适配层。Orchestrator 持有真实场景注册表，注册
`morning_brief`、`abnormal_move_analysis`、`stock_research_report`。每个 Runner 负责请求
校验、计划构建和对现有 Pipeline 的适配；Orchestrator 负责统一任务、Plan、预算、模型
策略、降级策略、异常转换和执行结果。CLI 仅负责参数解析、请求组装、调用 Orchestrator、
打印结果和退出码映射。

统一 Plan 包含场景、版本、真实步骤、数据需求、运行预算、模型策略、降级策略、输出
路径、请求时间和数据截止时间。统一结果包含状态、退出码、任务与运行 ID、运行目录、
报告路径、校验状态、警告、缺失数据、模型路由和耗时。未注册场景明确失败。

## 3. 晨报 Evidence 链

流水线在 RawItem 通过窗口过滤后构建真实 Evidence，并持久化 RawItem、Evidence 和
Evidence 索引。CandidateItem 通过 `raw_item_ids` 解析其 Evidence；EventCluster 的
`primary_evidence_ids` 和 Claim 的 `evidence_ids` 只保存存在的 Evidence ID。

链路固定为：

```text
RawItem -> Evidence -> CandidateItem/EventCluster -> Claim -> Markdown
```

Evidence 保留原始 source_id、raw_item_id、发布者、发布时间、获取时间、URL、最小摘录、
来源等级和 independence_group。同源转载共享 independence_group。渲染器显示 Evidence
ID、来源、发布时间和追溯 URL；Claim ID 如展示则明确标为 Claim。

确定性关键词或规则不得产生 MODEL_INFERENCE。官方披露只有在实体、时间和原始证据完整
时生成 FACT；观点必须保存 speaker/publisher；其余确定性语义结果降级为 UNKNOWN。机械
Validator 对缺失 Evidence、伪装 ID、无说话者观点、低等级单一重大 FACT、回退模型推断及
Markdown 不可解析引用返回失败。

## 4. Phase 4 语义能力与证据继承

Pipeline 为整个研究任务创建一个 LlmClient、一个 EquityLlmTasks 和共享 BudgetTracker，
最低接入业务描述归一化、竞争因素候选、反证整理和研究问题。Provider 未配置时记录
`llm_called=false`，对应模块为 degraded/unavailable，不生成 MODEL_INFERENCE 或模板化完成
内容。调用成功后按 JSON Schema、Pydantic 和业务规则依次校验；禁止模型修改财务事实、
指标、公式、同行资格、估值数值或截止时间。

Phase 4 复用 Phase 2 事件时沿用原始 Evidence ID；允许记录派生事件关系，但不构造
`source_id=morning_brief_events` 或把聚合事件升级为 `official_disclosure`。人工财务 Evidence
绑定 Manifest、文件 checksum、DocumentRecord/原始文件记录和行/表/页/字段定位；无法定位
时显式 DATA_DEGRADED。

新增集中、版本化、可解释的研究状态计算器，检查财务、Evidence、业务产品、行业竞争、
风险、催化剂、反证、市场主要矛盾、估值适用性、语义能力、来源质量、截止时间和 Validator。
核心模块缺失时不得返回完整 success。

专业评审由确定性、版本化规则计算 0—5 分，只表达研究覆盖与证据质量，不映射交易动作。

## 5. 时间与文档治理

生产默认日期统一调用 Asia/Shanghai 时间工具；report_date、as_of、requested_at 和
retrieved_at 分离。删除 Phase 4 生产代码中的 `2026-08-06` 默认值，保留明确的历史 fixture。

文档优先级统一为：engineering-guide → DECISIONS → 阶段任务书 → CURRENT_STATE →
NEXT_PHASE → KNOWN_LIMITATIONS → README。engineering-guide 是唯一当前有效指南；baseline
仅为历史快照。指南实质修改更新版本、日期、DECISIONS 和 changelog。修复验收完成前
Phase 5 始终为 BLOCKED；Phase 4 工程底座与完整研究能力分别陈述。

## 6. 错误处理与兼容性

Runner 内部异常统一转换为失败结果，不向 CLI 泄漏 traceback。既有参数、退出码、报告路径、
运行目录和幂等键语义保持兼容。dry-run 在 Orchestrator/Runner 层提前返回，只生成内存 Plan
和结果，不创建数据库、目录、Manifest、报告或模型调用。

## 7. 测试与验收

新增单元、契约、集成与黄金回归，覆盖三个 CLI 必经 Orchestrator、未注册场景、非空 Plan、
三档预算、异常转换、dry-run 和幂等；覆盖完整晨报 Evidence 链、伪装 ID、缺失引用、转载
独立组、观点说话者、回退推断、Markdown 引用；覆盖 Phase 4 有/无 Provider、共享预算、
核心语义覆盖、原始 Evidence 继承、专业评审和集中状态判定；覆盖上海时区默认日期及显式
历史日期。

完成后运行 `python -m pytest --collect-only -q`、`python -m pytest -q` 以及项目实际配置的
质量检查，最后执行 Git 差异与禁止项自检。未经用户授权不 commit、不 push、不创建 PR。
