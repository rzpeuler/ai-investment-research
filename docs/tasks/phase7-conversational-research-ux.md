# Phase 7 UX1：Schema-Driven Conversational Research Gateway

**TASKBOOK_STATUS: PASS / INDEPENDENTLY ACCEPTED**

**PHASE: Phase 7（LIMITED AUTHORIZATION）**

**MILESTONE: P7-UX1**

**DESIGN_BASELINE: `76fce914b5ffb0a2e5ff981e7f7fa89ab0f8974e`**

**IMPLEMENTATION_HEAD_BEFORE_GOVERNANCE: `55160cd`**

**ACCEPTED_HEAD: `75d2ccf`**

**PHASE6.1: NOT AUTHORIZED**

**P7 DATA ACQUISITION: NOT_STARTED / AWAITING_ARCHITECTURE_DISCUSSION**

**DATA_ACQUISITION_CHANGED: NO**
**COLLECTORS_CHANGED: NO**
**SOURCE_REGISTRY_CHANGED: NO**
**GRAPH_WRITE: NONE**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMAS: 80**

> P7-UX1 已通过独立验收（INDEPENDENT_ACCEPTANCE: PASS），terminal 状态为
> PASS / INDEPENDENTLY ACCEPTED。该状态只覆盖本地 Chat UX / control-plane adapter，
> 不授权 P7 数据采集、Phase 6.1、图谱写入或数据库迁移。

## 1. 目标与范围

P7-UX1 为现有十个研究场景增加本地会话式入口。用户可以选择场景或使用自动识别，
通过自然语言表达研究对象、问题、时间范围和明确假设；系统将其转换为经过 Schema
校验的 Public Request Draft，再由确定性代码解析权威身份和时间，构造最小公共请求，
最终交给现有 `Orchestrator.execute()` 与对应 Runner。

本里程碑只允许修改聊天控制面、Dashboard、Chat Schema、Schema registry、CLI、启动
脚本、测试与治理文档。不得修改研究 Runner 的业务语义，不得新增研究管线，不得开始
数据采集、Phase 6.1、图谱写入或数据库迁移。

## 2. 冻结架构

处理顺序固定为：用户自然语言、场景选择、场景专用 Chat Input JSON Schema、DeepSeek
严格结构化抽取、Schema 校验后的 Public Request Draft、确定性解析、Minimal Public
Request、现有 `Orchestrator.execute()`、现有 `Runner.validate_request()`、现有正式 Request
Model 和持久化 Request artifact。

边界原则：

- LLM 只填写用户表达的语义，不生成正式业务 Request。
- 代码负责实体、行业、时间和系统默认值等确定性解析。
- Runner 继续作为公共输入到正式业务契约的 anti-corruption layer。
- `Orchestrator.execute()` 是唯一业务执行权威。
- Chat 不是第二个 Orchestrator、研究管线、Evidence authority、实体 authority、时间
  authority、Graph writer 或投资顾问。
- Chat 层不得写 `*_request.json`、`*_run.json` 或
  `scenario_execution_result.json`。

JSON Schema 的结构合法性不等于业务 authority 合法性。因此，即使 UUID、证券代码或
时间字段格式合法，LLM 也不得据此创建持久化业务对象。

## 3. 字段所有权

### 3.1 LLM_WRITABLE / USER_SEMANTIC

Chat Schema 只允许表达用户说了什么，包括：

- `entity_mentions`、`company_mentions`、`industry_mentions`、`theme_keywords`
- `research_question`、`research_focus`
- `temporal_expression`、`report_date_expression`、`forecast_period_expression`
- `depth_hint`
- 用户明确提出的假设、指标和场景偏好

### 3.2 AUTHORITATIVE_RESOLVED

下列字段必须由代码、SQLite、accepted ontology 或 accepted research state 解析：

- `symbol`
- `company_entity_id`、`security_entity_id`
- `industry_id`、图谱节点身份
- `phase4_result_id`
- `previous_cutoff`
- financial/market manifest IDs
- 公司和证券的规范身份

### 3.3 SYSTEM_CONTROLLED

下列字段只能由系统代码生成：

- `task_id`、`request_id`、`run_id`
- `requested_at`、`created_at`、`as_of`、`timezone`
- `status`、`version`、`rule_versions`、`validation_status`
- `idempotency_key`

Chat Schema 必须以 `additionalProperties: false` 拒绝后二类字段，不能依赖 Prompt 约束。

## 4. Chat Schema 契约

新增 11 个严格 Draft-07 Schema：

- `chat_route`
- `chat_morning_brief_input`
- `chat_evening_brief_input`
- `chat_daily_review_input`
- `chat_abnormal_move_analysis_input`
- `chat_stock_research_report_input`
- `chat_stock_review_input`
- `chat_industry_research_input`
- `chat_theme_discovery_input`
- `chat_earnings_expectation_input`
- `chat_first_coverage_input`

全部 Schema 使用 `additionalProperties: false`。语义字段尽量全部列入 `required`；缺值用
`null` 或空数组表示，不通过省略字段制造歧义。这些 Schema 是 control-plane semantic
contract，不对应数据库表、迁移、JSON mirror 或持久化 Pydantic 业务对象。

`chat_route` 只包含 `scenario`、`confidence`、`needs_clarification` 和
`clarification_question`。其中 `scenario` 只能为 `null` 或 `DEFAULT_SCENARIOS` 成员。
静态 Schema enum、Task Schema scenario enum 与运行时场景集合必须由测试机械校验一致。

预计 Schema 总数由 69 增至 80，但实现与测试不得硬编码总数。

## 5. 场景选择和调用预算

用户选择的场景优先于 LLM。已选择具体场景时跳过 route 调用，直接加载对应场景
Schema；只有 `AUTO` 才允许调用 `chat_route`。`AUTO` 下仅输入公司名称或代码时必须
澄清，不得擅自选择个股研报、复盘、异动、财报预期或首次覆盖。

Chat 只复用现有 DeepSeek 链路：

- `create_provider(..., provider_id="deepseek", live=True)`
- `DeepSeekChatCompletionsProvider`
- `LlmClient.generate_json()`
- `LlmOutputValidator`
- 现有 provider routing、脱敏和调用审计

`config/llm_providers.yaml` 是 Provider 参数权威。密钥只从本地环境变量
`DEEPSEEK_API_KEY` 读取，可选地址覆盖使用 `DEEPSEEK_BASE_URL`。浏览器、API 响应、日志
和仓库文件都不得接收、保存或返回密钥；不得新增直接 HTTP DeepSeek 客户端。

预算固定为：AUTO route 最多一次 Flash；场景抽取最多一次 Flash；单轮总计最多两次
Flash；Pro 为零。每个阶段使用独立的单次预算，Schema invalid、Provider retryable error
或校验修复都不得触发第二次同阶段调用或 Pro 升级。无效输出不得部分接收，只能进入
确定性回退或澄清。

## 6. 场景规格表

以不可变 `ScenarioChatSpec` 建立中央 `CHAT_SCENARIO_SPECS`，每项至少登记：

- `scenario_id`
- `chat_input_schema_name`
- `target_policy`
- `time_policy`
- `completion_policy`
- `minimal_request_builder`

其 keys 必须与 `DEFAULT_SCENARIOS`、Task Schema scenario enum 和十个场景 Chat Schema
完全一致。禁止在 ChatService 中堆叠分散的 `if/elif` 场景实现。

各 builder 只输出当前 Runner 接受的最小公共字段：

- 晨报、晚报：仅在用户明确日期时解析 `report_date`。
- 每日复盘：仅在用户明确日期时解析业务日期。
- 异动分析：解析唯一实体后传 `entity_id`。
- 个股研报、个股复盘：传 `entity`；仅传用户明确要求的时间或深度。
- 行业研究：解析唯一 `industry_id`，并按现有 Runner 契约提供所需时间。
- 主题发现：传用户明确主题关键词、行业与时间；未明确 mode 时沿用 Runner 默认值。
- 财报预期：必须有权威公司、预测期间和至少一条用户明确假设。
- 首次覆盖：必须有权威公司、证券和唯一可用行业；Phase 4 baseline 选择仍由现有
  Runner 负责。

如果现有 Runner 无法接受安全的最小请求，应停止并报告 contract blocker，不修改
Runner 业务契约来迁就 Chat。

## 7. 确定性解析器

### 7.1 ResearchTargetResolver

权威名称来源为 `SecurityProfile.current_name`、`SecurityProfile.former_names` 和
`CompanyProfile.canonical_name`。允许 trim、大小写归一和 Unicode 空白归一，然后只做
唯一精确匹配；禁止模糊选择、编辑距离自动选择、LLM ticker 记忆或互联网查询。

合法完整 symbol 可直接用于只要求 entity 的场景。裸六位代码必须在
`SecurityProfile` 中唯一命中；零命中或多命中均澄清，禁止根据首位数字猜交易所。
财报预期和首次覆盖必须通过 profile 取得公司/证券权威身份，不能由 ticker 推导内部
ID。

### 7.2 TemporalResolver

每个 `/api/chat` turn 开始只调用一次 `reference_now = shanghai_now()`。本轮所有 today、
report date、review period、`as_of` 和用户输入假设的 `known_at` 均由该值派生。

支持确定性解析今天、昨天、最近 7 天、最近一个月、本周、本月和明确历史日期。用户
未明确时间时不复制 Runner 已有安全默认值；只有明确时间表达才加入最小请求。

### 7.3 IndustryResolver 与 SystemDefaultResolver

行业只从 accepted ontology、当前权威图谱读取状态或公司 profile 的唯一可用行业解析。
零命中、多命中或冲突均澄清。系统默认字段只由代码生成，不能由 LLM Draft 提供。

### 7.4 财报预期特殊约束

LLM 只提取公司 mention、预测期表达、指标表达、场景表达和用户明确假设。仅有公司名
时必须澄清预测期间及至少一个假设。系统不得发明增长率或其他假设；`as_of` 与用户
输入假设的 `known_at` 使用本轮唯一 `reference_now`。

## 8. Dashboard、API 与会话

Dashboard 位于 `src/research_os/dashboard/`，使用 Python 标准库
`ThreadingHTTPServer` 和 `importlib.resources`，不新增 Flask、FastAPI、Django、React、
Node 或 npm。服务只能监听 `127.0.0.1`，不得监听 `0.0.0.0`。

API 至少包括：

- `GET /api/meta`
- `POST /api/chat`
- `GET /api/recent`
- `GET /api/report`
- `GET /api/health`

`POST /api/chat` 接收 session ID、消息、用户选择的场景、LLM 开关和 Research Live
开关。浏览器永远不直接访问 DeepSeek。

会话只保存在内存中，最多保留 20 轮，可保存已选场景、上次解析目标、上次 Draft、
最小请求和最近 turns。服务器退出后会话消失；不新增 conversation/chat 数据表，不把
完整聊天写入 SQLite。现有脱敏后的 LLM call audit 保持不变。

Chat 状态限定为 `clarification`、`ready`、`executing`、`executed`、`failed`。
研究结果的 `partial_success`、`degraded` 和 `insufficient_evidence` 是已执行后的研究
状态，不得映射为 Chat `failed`。

当场景、Draft、完成条件和权威解析全部通过后自动调用 Orchestrator，不增加第二个
Run 按钮。高级调试区只读显示 Public Draft、Deterministically Resolved Minimal Request
与 `ScenarioExecutionResult`，不得把 Draft 标成正式 Request。

## 9. 双开关与无 LLM 回退

“使用 LLM 理解自然语言”只控制 Chat 的 DeepSeek 语义解析；“Research Live 数据”只
控制正式研究执行的 live 能力，两个开关不得合并。

DeepSeek 未配置或 LLM 被禁用时，系统仍支持：

- 用户已锁定场景并输入完整 symbol。
- 用户已锁定场景并输入可唯一精确匹配的名称。
- `AUTO` 下“今天晨报”“今天晚报”等有限确定性关键词。

其他复杂自然语言进入澄清，并明确提示启用 LLM；不得伪装已经调用模型。

## 10. UI、CLI 与包装

UI 为轻量 chat-first 布局：场景选择、中央对话、识别结果、执行状态、报告和缺失数据。
场景列表由运行时场景规格生成，不维护第三份手写 ID 列表。高级调试默认折叠。

CLI 新增 `research dashboard --port --no-browser`。Windows 新增
`scripts/start_dashboard.bat`，依次尝试 `.venv\Scripts\python.exe`、`py -3` 和
`python`。安装后的 wheel 必须包含 HTML、CSS 和 JavaScript 静态资源，不能只在源码
目录运行。

## 11. HTTP 与研究边界安全

- HTTP 服务只允许 loopback bind。
- `POST` 强制 JSON Content-Type，并设置有限请求体上限。
- `/api/report` 只能读取解析后仍位于 `PROJECT_ROOT/reports` 内的普通文件。
- `../`、编码穿越、任意绝对路径、目录读取和符号链接逃逸全部 fail closed。
- Prompt 和确定性 guards 继续禁止目标价、买卖评级、仓位、次日交易、自动荐股和交易
  信号。
- Chat 不写 Graph、GraphChange candidate 或 ontology。
- 不修改 collectors、sources registry、Phase 2–6 pipelines、graph core 或 DB migration。

## 12. 验证计划

### 12.0 已实现组件与验收证据位置

- 会话网关：`src/research_os/dashboard/`（场景规格、Draft 抽取、确定性解析、最小请求、
  双 gate、会话、HTTP server 与静态 Dashboard）。
- Chat Schema：`schemas/chat_*.schema.json`；注册表与 LLM Validator 继续动态加载。
- 用户入口：`research dashboard` 与 `scripts/start_dashboard.bat`。
- 契约 / builder / resolver / budget：`tests/contracts/test_chat_input_schemas.py`、
  `tests/unit/test_chat_request_builder.py`、`tests/unit/test_dashboard_core.py`、
  `tests/unit/test_chat_services.py`。
- HTTP / session / runtime / packaging：`tests/unit/test_dashboard_server.py`、
  `tests/unit/test_dashboard_session.py`、`tests/unit/test_dashboard_runtime.py`、
  `tests/contracts/test_dashboard_package.py`。
- wheel 使用 `packages = ["src/research_os"]` 包含 Dashboard 静态资源；不再重复
  `force-include` 同一路径，避免 Hatch 生成重复 archive entry。
- `stock_review` 的 selected/no-LLM/offline Chat→真实默认 Orchestrator→实际
  `StockReviewScenarioRunner`→正式 request/run/result artifact：
  `tests/integration/test_chat_core_flow.py`。晨报与个股研报继续由 builder→Runner contract
  覆盖；不得把自定义 capture Runner 测试表述为正式场景 artifact 验收。
- 治理一致性与动态 Schema / DB gate：`tests/unit/test_document_governance.py`。

最终验证数字只记录实际命令结果，不以设计预估替代；见 §12.4。

### 12.1 契约与预算

- 11 个 Chat Schema 均为合法、已注册、可由 `LlmOutputValidator` 加载的 Draft-07 Schema。
- Schema 机械拒绝系统字段和权威字段。
- 场景集合、Task enum、规格表和场景 Schema 动态 parity。
- 已选场景完全跳过 route；AUTO 才 route；AUTO 公司-only 必须澄清。
- route/extraction 各最多一次 Flash，合计最多两次，所有路径 Pro 为零。
- Schema invalid、Provider 故障、预算耗尽均不进入 Resolver。

### 12.2 Resolver 与场景

- 完整 symbol、唯一裸代码、现用名、曾用名、公司规范名、未知和歧义实体。
- 今天、昨天、最近 7 天、最近一个月、本周、本月和明确历史日期，均使用固定的单一
  reference time。
- 十个场景的完成策略与最小请求 builder。
- 财报预期无假设时澄清且不执行；正例只采用用户明确假设。
- 首次覆盖需要唯一公司、证券和行业 authority。

### 12.3 HTTP、包装与端到端

- loopback、Content-Type、body limit、内存会话上限和报告路径攻击。
- Fake Provider 与隔离数据库覆盖 Chat 到真实 `Orchestrator.execute()`、现有 Runner
  validation 的端到端路径。
- 证明 Chat 层不会写正式 Request/Run/Result artifact。
- wheel 安装后 CLI 与静态资源可用，Windows 启动脚本按约定回退。

完整验证命令：

```text
python -m pytest
python -m research_os.cli.main validate
python -m compileall -q src tests
git diff --check
```

验收要求为零失败、全部 Schema 通过、compileall 与 diff check 通过、DB 保持 v6、无
migration。最终还要检查允许目录 diff，并取得与最终 head 完全一致的 Offline CI 成功
结果。

### 12.4 本地实现验证（2026-08-10）

- Governance commit `3628e21` targeted gateway / governance suite：`521 passed`。
- Governance commit `3628e21` full suite：`2940 passed, 6 skipped, 0 failed`
  （包装修复后运行，671.33 秒）。后续规格审查仅调整验收测试与本段说明；最终集成
  head 仍须由 root acceptance 重新运行完整 suite 并记录最终数字。
- Specification-review follow-up targeted gateway / governance suite：`519 passed`。
- Schema validation：`80/80`。
- `python -m compileall -q src tests`：PASS。
- `git diff --check`：PASS（仅 Windows LF→CRLF 提示）。
- DB / migrations：`user_version=6`；6 个既有 migration；新增 migration = NONE。
- Wheel：`python -m pip wheel --no-deps .` build isolation PASS；ZIP 包含
  `research_os/dashboard/static/index.html`、`dashboard.js`、`dashboard.css`。
- Scope gate：未修改 Runner、Pipeline、Collector、Source Registry、Graph core 或 migration。

上述本地实现验证与 Offline CI 通过后，P7-UX1 已完成独立验收；terminal 状态见
本任务书头部与 Decision #46.7 / #46.8。

## 13. 治理与交付

实现阶段新增 Decision #46，冻结本任务的架构和三类字段所有权；同步更新
`CURRENT_STATE.md`、`NEXT_PHASE.md`、`KNOWN_LIMITATIONS.md`、工程指南和 README。
P7-UX1 已完成独立验收（`INDEPENDENT_ACCEPTANCE: PASS`），terminal 状态为
`PASS / INDEPENDENTLY ACCEPTED`。

分支固定为 `phase7/ux1-conversational-research`，PR 标题固定为
`Phase 7 UX1: Schema-Driven Conversational Research`。PR 改为 READY 后保持
OPEN / NOT MERGED；执行 Agent 不得自行合并。

实现、测试、治理和 CI 全部通过后，报告：

```text
P7_UX1: PASS / INDEPENDENTLY ACCEPTED
P7_DATA_ACQUISITION: NOT_STARTED / AWAITING_ARCHITECTURE_DISCUSSION
PHASE6.1: NOT_AUTHORIZED
DATA_ACQUISITION_CHANGED: NO
COLLECTORS_CHANGED: NO
SOURCE_REGISTRY_CHANGED: NO
GRAPH_WRITE: NONE
DB: v6
MIGRATIONS: NONE
SCHEMAS: 80
```

完成后停止，不开始数据采集或 Phase 6.1。
