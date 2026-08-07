# 控制面、模型预算与证据资格补修设计

**日期：** 2026-08-07  
**范围：** Phase 0/3 统一控制面、Phase 4 模型预算与证据质量  
**目标状态：** 修复四个 BLOCKER 与专业评审 HIGH；不改变业务场景，不进入 Phase 5

## 1. 背景与问题

当前三个核心场景已经通过 `Orchestrator.execute()` 路由，但控制面尚未形成完整的统一审计链：异动 Pipeline 会重新生成 `task_id`，部分 Runner/Pipeline 未统一持久化 Task、Plan 和 ScenarioExecutionResult。

Phase 4 的共享 `BudgetTracker` 只在一次语义任务完成后记录一次 Flash，未按 Provider 实际调用计数，也未计入 Pro 升级，因而不能执行任务级调用上限。

语义输出目前只校验 Evidence ID 存在，不校验输出声明的 `required_evidence_types` 与实际 Evidence 类型是否一致；所有语义任务还共用同一组前置 Evidence，导致人工财务摘录可能被错误用于业务和竞争结论。

来源质量目前由任意 S/A Evidence 决定，可能让无关事件 Evidence 掩盖 Tier C 核心财务输入。专业评审各维度也统一引用前五条 Evidence，未形成维度级支持与反证关系。

## 2. 方案选择

采用“定向强化现有架构”方案：保留既有 Pipeline 和公开 CLI，只收紧控制面所有权、Provider 调用预算、语义证据资格、来源质量分域和专业评审证据映射。

不采用以下方案：

- 仅增加结果后置断言：无法保证失败和提前返回路径也持久化统一控制面对象。
- 将所有 Pipeline 重构为统一 ExecutionContext：长期方向合理，但改动面超出本轮定向验收。

## 3. 统一控制面设计

### 3.1 所有权

`Orchestrator` 是以下对象的唯一控制面所有者：

- Task ID 与 Task 状态；
- Plan；
- `reports/runs/{task_id}` 运行目录；
- ScenarioExecutionResult 审计快照。

业务 Pipeline 继续拥有场景专属 Request、Run、模块产物和报告，但必须沿用控制面传入的 `task_id`。

### 3.2 执行流

非 dry-run 执行顺序固定为：

1. Orchestrator 创建并校验 Task；
2. Orchestrator 创建非空 Plan；
3. Orchestrator 创建统一运行目录并写入初始 `task.json`、`plan.json`；
4. Runner 将控制面 `task_id` 传入业务 Pipeline；
5. Pipeline 的 Request、Run、目录和产物沿用该 Task ID；
6. Orchestrator 校验 Runner 返回的 Task ID 和运行目录；
7. Orchestrator 写入 `scenario_execution_result.json`，更新最终 Task 状态。

dry-run 保持零业务副作用，不创建运行目录或持久化对象。

### 3.3 一致性校验

以下任一情况视为控制面失败，不得返回成功：

- Runner 返回的 `task_id` 与 Task 不同；
- 返回的 `run_dir` 不是 `reports/runs/{task_id}`；
- 业务 Request 或 Run 的 `task_id` 与 Task 不同；
- 非 dry-run 缺少 `task.json`、`plan.json` 或 `scenario_execution_result.json`。

异动 Pipeline 增加可选外部 `task_id` 参数；未由统一控制面调用时仍可自行生成 ID，以保持内部兼容入口。

## 4. 模型调用预算设计

### 4.1 预算边界

`BudgetTracker` 仍为一次 Phase 4 研究任务共享实例，但预算检查和计数发生在每次实际 Provider 调用边界，而不是语义任务边界。

每次尝试遵循：

1. 确定本次模型级别（Flash 或 Pro）；
2. 调用前检查对应剩余额度；
3. 无额度则停止该路径，返回明确预算降级原因；
4. 有额度则立即占用一次，再调用 Provider；
5. Provider 异常、JSON/Schema 失败和成功都计入已用次数。

未配置 Provider 时不发生实际调用，不消耗预算。Provider 故障不触发业务 Pro 升级。Pro 只有在已满足业务升级条件且仍有 Pro 额度时才能调用。

### 4.2 接口

`LlmClient.generate_json()` 接受可选的调用预算控制器。未传入时保持现有 Phase 2/3 行为；Phase 4 的 `EquityLlmTasks` 必须传入共享 `BudgetTracker`。

`LlmResponse` 和 `model_route` 记录实际 Flash/Pro 尝试数、预算拒绝原因以及调用后的共享预算快照。不得通过模型返回的 `model_id` 反推预算消耗。

## 5. 语义 Evidence 资格设计

### 5.1 任务级输入策略

为每个 Phase 4 语义任务定义允许类型和最低证据数量：

- `business_description_normalization`：`official_disclosure`、`company_official`、`institution_material`，至少 1 条；
- `competitive_factor_candidates`：`official_disclosure`、`company_official`、`official_statistics`、`institution_material`、`news_report`、`media_report`，至少 1 条；
- `counter_evidence_organizing`：上述类型加 `manual_input`，至少 1 条；人工财务证据只能支持其明确包含的财务反证；
- `research_questions`：可使用全部非 `unknown` Evidence，至少 1 条。

Pipeline 按任务选择 Evidence，不再把 `evidence_models[:5]` 传给所有任务。输入顺序不得决定证据资格。

### 5.2 输出校验

所有语义输出继续校验 Evidence ID 存在，并新增：

- 引用 Evidence 必须属于该语义任务实际输入集合；
- `CompetitiveFactor.required_evidence_types` 必须非空；
- 每个引用 Evidence 的实际 `evidence_type` 必须属于 `required_evidence_types`；
- `required_evidence_types` 也必须属于该任务允许类型；
- 不满足最低输入或输出资格时，任务标记为 `insufficient_evidence` 或 `rejected`，不得计入语义覆盖。

## 6. 分域来源质量设计

`ResearchCoverage` 将单一 `source_quality_adequate` 拆为：

- `core_financial_source_quality`：核心财务事实是否由合格 S/A 原始或官方 Evidence 支持；
- `business_source_quality`：业务与竞争结论是否具有相关 S/A Evidence；
- `event_source_quality`：催化剂、风险和事件结论是否具有相关合格 Evidence；
- `overall_evidence_quality`：各必需领域是否同时满足最低质量，而不是全局 `any(S/A)`。

完整 `success` 必须满足核心财务来源质量。无关 S/A 事件不得提升核心财务质量。人工财务 Tier C 即使可追溯，也只能维持工程可执行与降级研究状态，不能单独满足完整成功。

状态产物同时保存四个质量维度和具体缺失原因，便于 Validator 与 Markdown 如实披露。

## 7. 专业评审维度级 Evidence

专业评审改为接收 `evidence_by_dimension`：

- 基本面、成长和财务质量引用财务事实/指标 Evidence；
- 周期、竞争优势和行业趋势引用业务竞争 Evidence；
- 估值约束引用估值输入及其财务/市场 Evidence；
- 事件可靠性引用催化剂和事件 Evidence；
- 空头反证引用风险、冲突和反证 Evidence；
- 信息完整度与证据质量引用各领域合格 Evidence 的去重并集。

每个维度只附着与其评分输入相关的 Evidence；无相关 Evidence 时保持空列表并形成证据缺口，不使用通用前五条兜底。

## 8. 状态与文档治理

补修完成并通过定向与全量测试前，项目状态调整为：

- 统一控制面 BLOCKER：`REOPENED`；
- 晨报 Evidence BLOCKER：`CLOSED`；
- Phase 4 完成定义 BLOCKER：`REOPENED`；
- 文档治理 HIGH：`CLOSED_WITH_MINOR_ISSUES`；
- Phase 4 engineering foundation：`CONDITIONAL_PASS`；
- Phase 4 full research capability：`PARTIAL_SUCCESS`；
- Phase 5：`BLOCKED`。

补修测试通过后，只关闭本设计覆盖的工程问题；真实 Provider 和高质量来源未接入前，Phase 4 full research capability 与 Phase 5 状态不变。

README 的 Validator 范围同步为 `ERV-001—ERV-079`。本轮遵照用户要求仅修改本地文件，不提交、不推送、不改写现有提交历史。

## 9. 测试与验收

新增或强化以下测试：

1. 三个真实 Runner 的 Task、Plan、业务 Request/Run、运行目录和 ScenarioExecutionResult 使用同一 Task ID；
2. 三个非 dry-run 场景均持久化统一 `task.json`、`plan.json`、`scenario_execution_result.json`；
3. standard 深度跨四个语义任务累计最多 5 次 Flash、1 次 Pro；失败尝试也计数；
4. Pro 预算耗尽后其他任务不能再次升级；无 Provider 不消耗预算；
5. `official_disclosure` 要求不能由 `manual_input` Evidence 满足；
6. 未达到任务最低 Evidence 输入时不调用 Provider，且不计入语义覆盖；
7. Tier C 核心财务加无关 S/A 事件仍不得得到完整 `success`；
8. 专业评审不同维度引用不同的相关 Evidence，缺证据维度不得附着通用 Evidence；
9. README 和状态文档规则编号及阶段状态一致；
10. 完整运行 `python -m pytest`、50 个 Schema 校验、`compileall` 和 `git diff --check`。

## 10. 非目标

- 不新增场景；
- 不接入或伪造外部数据源；
- 不改变财务公式、同行资格和估值规则；
- 不实现 Phase 5；
- 不输出目标价、评级、交易或仓位建议；
- 不在本轮改写或推送 Git 历史。
