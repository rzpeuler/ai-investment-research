# Phase 4.1 完整研究能力设计

> 日期：2026-08-07
> 起始分支：`master@e505762cf8fae341ecd06a0c6092f0a88dbb2c7c`
> 工程代码基线：`ce656b1866e0d65b1def292d26bed9c41474983b`
> 开发分支：`codex/phase4-full-research-capability`
> 状态：用户已批准设计；本文只授权 Phase 4.1，不授权 Phase 5。

## 1. 目标与边界

本轮补齐 Phase 4 的外部能力和真实覆盖：接入一个经验证的真实 LLM Provider，建立
官方披露原件到核心财务事实的可复核 Evidence 链，完成七个必需语义任务，并形成两个
真实成功案例和一个预期降级案例的端到端验收材料。

保持以下硬边界：

- 不新增研究场景，不开始 Phase 5，不自动批准或写入核心产业图谱；
- 不输出目标价、评级、仓位、交易动作或自动荐股内容；
- LLM 不创建 FACT，不修改财务事实、公式、同行资格或估值数值；
- 默认测试完全离线；网络调用必须由显式 `--live` 启用；
- 原始官方文件保存在 Git 忽略的数据目录，不提交仓库；
- 未满足真实验收条件时保持 `PARTIAL_SUCCESS` 和 Phase 5 `BLOCKED`。

## 2. 实施策略

采用纵向里程碑方案，不进行横向大重写，也不为三个验收公司建立专用旁路：

1. Provider 配置、工厂、适配器、探测和安全；
2. 官方披露原件导入及在线元数据/附件定位；
3. 核心财务事实与官方文档/locator 绑定；
4. 七个必需语义任务、正式产物、状态和 Validator；
5. 两个真实成功案例和一个预期降级案例；
6. 独立验收后的状态收尾。

每个里程碑单独提交，并在进入下一里程碑前运行相关测试。任何在线条件失败只影响真实
验收结论，不得破坏离线 Pipeline。

## 3. Provider 架构

### 3.1 已批准配置

```yaml
provider_id: deepseek
display_name: DeepSeek
adapter: deepseek_chat_completions
api_key_env: DEEPSEEK_API_KEY
base_url_env: DEEPSEEK_BASE_URL
default_base_url: https://api.deepseek.com
api_mode: chat_completions
flash_model: deepseek-v4-flash
pro_model: deepseek-v4-pro
supports_json_schema: false
supports_json_object: true
```

Base URL 是公开的非秘密配置，可由 `DEEPSEEK_BASE_URL` 覆盖；API Key 只从
`DEEPSEEK_API_KEY` 读取。配置文件不记录任何密钥值。

### 3.2 组件边界

业务调用链保持：

```text
EquityResearchPipeline
→ EquityLlmTasks
→ LlmClient
→ LlmProvider
→ DeepSeekChatCompletionsProvider
```

新增或等价实现以下组件：

- `provider_config`：加载、校验 Provider 配置和逻辑模型映射；
- `provider_factory`：只在 `live=true` 且配置有效时构造真实 Provider；
- `DeepSeekChatCompletionsProvider`：唯一可接触 HTTP 协议的实现；
- `redaction`：对异常、日志、调用记录和验收摘要做统一脱敏；
- `probe`：执行低成本、结构化、可审计的显式在线探测。

Provider 适配器使用 Python 标准库 HTTP 客户端，不新增供应商 SDK。请求使用
`POST /chat/completions` 和 JSON Object 模式；项目实际 JSON Schema 进入 Provider 请求
契约和最小 Prompt，返回后仍执行 JSON 解析、项目 Schema、Pydantic、再次 Schema 和
业务规则校验。Provider 不支持原生 JSON Schema 不会降低本地校验标准。

### 3.3 请求、错误和预算

每次真实请求携带 task/call/module/prompt version/hash、Evidence ID、逻辑模型级别、
输出 Schema 名和 timeout。审计只保存请求摘要、哈希、模型、次数、耗时、状态和脱敏错误，
不保存 Authorization、完整请求头或原始完整响应。

错误分类固定为：

```text
authentication_error
authorization_error
rate_limited
timeout
network_error
provider_5xx
invalid_response
schema_validation_failed
budget_exhausted
provider_not_configured
```

认证、授权和参数错误不重试；限流、网络瞬时错误和 5xx 只按配置有限重试。每次实际 HTTP
请求在发出前消耗共享任务预算。Provider 故障不触发 Pro；只有既有业务升级条件或两次
Flash 结构校验失败才允许一次 Pro。

## 4. 官方披露与财务 Evidence

### 4.1 数据流

```text
巨潮元数据或用户提供的官方元数据
→ 官方原始文件下载/登记
→ SHA-256 内容寻址存储
→ DocumentRecord
→ DocumentBlock / locator
→ RawItem
→ Evidence
→ FinancialDataManifest
→ FinancialFact
→ Claim / ResearchFinding
→ 报告引用
```

在线路径复用已有 `CninfoCollector`，只扩展经真实 probe 验证的公告元数据查询、附件定位
和受控下载。在线失败时使用同一导入服务的辅助路径，要求用户提供官方文件、官方 URL、
披露时间、公司、来源和文档类型，不建立临时或未登记来源。

### 4.2 文件和文档治理

官方文件存入：

```text
data/disclosures/{entity_code}/{sha256}{original_suffix}
```

目录保持 Git 忽略。以 checksum 去重，同名不同内容分别保存，并记录原始文件名、实际
存储路径、retrieved_at、parser version、source URL、publisher 和 published_at。

导入命令提供等价于以下接口：

```text
research documents import-disclosure
```

缺 source URL、published_at、已登记官方来源、有效公司实体或文件时明确失败。用户声称
文件为年报不构成 S 级资格。

### 4.3 核心财务绑定

适用的 revenue、cost_of_sales、operating_profit、net_profit、net_profit_attr、
total_assets、total_liabilities、equity_attr 和 operating_cash_flow 必须逐项绑定：

- `derived_from_document_id`；
- `document_block_id`；
- 至少一种页/表/行/列/单元格/章节/文本偏移/结构化字段 locator；
- 原始文件 checksum；
- 官方 source URL；
- 是否人工确认或校正及其审计记录。

只有来源注册表资格、官方域名、checksum、有效 locator、as_of 和数值复核同时通过，核心
财务 Evidence 才能成为 S/A。普通财务 CSV、手工金额或无关官方事件保持原等级，不能
提升核心财务来源质量。

## 5. 语义任务与正式产物

七个必需任务为：

```text
business_description_normalization
management_statement_summary
competitive_factor_candidates
catalyst_candidates
risk_candidates
counter_evidence_organizing
research_questions
```

竞争、催化剂和风险沿用现有强类型对象。业务描述、反证和研究问题使用
`ResearchFinding` 并增加任务级嵌套对象校验。管理层陈述使用可保留 speaker、role、
published_at、statement、topic、company_view、Evidence 和 possible_bias 的结构化对象，
并转换为 Opinion/Claim/Evidence 链；不新增与现有正式决策冲突的顶层业务对象。

每个任务独立选择 Evidence，并验证实体、发布时间、as_of、Evidence ID、实际类型和
最低输入。竞争优势不能由单一管理层自述形成；催化剂和风险必须区分事实、来源观点、
推断和假设；反证必须包含受挑战主张、挑战 Evidence、未解决差异和下一项验证数据。
不存在真实反证时输出 `insufficient_counter_evidence`，不虚构反方观点。

标准档位仍保持 Flash 5/Pro 1 的预算，因此不能承诺七任务完整覆盖。两个真实成功案例
使用 `deep` 档位的 Flash 8/Pro 1 预算；任一必需任务缺失或业务校验失败即降级。

## 6. 状态与 Validator

状态逻辑继续集中在版本化状态模块。完整 `SUCCESS` 必须同时满足：

- 至少两个可比完整年度和核心财务覆盖；
- 核心财务官方原件 Evidence 及分域来源质量合格；
- 业务、竞争、风险、催化剂、反证、市场主要矛盾和估值适用性覆盖；
- 七个必需语义任务全部由真实 Provider 成功输出并通过业务校验；
- as_of 已知，无未解决核心来源冲突；
- Validator pass，报告无禁止项。

Validator 使用 ERV-080 起的连续新编号，覆盖任务书列出的文档、checksum、locator、
Provider、脱敏、语义资格、Fake Provider、Tier C 财务和必需任务规则。严重问题为 error。
Fake Provider 仅用于离线链路测试，永远不能满足真实 Provider 条件。

## 7. CLI 与运行产物

新增：

```text
research llm probe [--provider deepseek] [--model-class flash|pro] --live
research documents import-disclosure ...
research run equity-research ... --live
```

`--dry-run` 优先于 `--live`，两者同时出现时不访问网络、不调用 Provider、不写业务产物。
未登记或未验证来源不能因 `--live` 自动启用。

运行目录除既有产物外补齐 document/raw item、管理层陈述、七任务结果、Provider 调用摘要
和机器可读 acceptance summary。失败产物保留明确状态，不用空文件掩盖。

当前源码布局下裸模块命令需要安装项目或设置 `PYTHONPATH=src`；安装与 CLI 验收将明确
验证控制台入口，不把环境问题误报为功能通过。

## 8. 验收组合

验收组合不是投资推荐，只用于覆盖不同数据和业务结构：

| 案例 | 股票 | 类型 | 预期 |
|---|---|---|---|
| A | `600519.SH` 贵州茅台 | 稳定消费 | 真实 `SUCCESS` |
| B | `300750.SZ` 宁德时代 | 技术/复杂制造 | 真实 `SUCCESS` |
| C | `688981.SH` 中芯国际 | 受控缺失案例 | `DATA_DEGRADED` 或 `PARTIAL_SUCCESS` |

案例 C 在版本化配置中显式缺少一项成功前置条件，不通过修改证据或模板获得 success。
如在线 probe 证明某个来源无法合法、稳定取得所需官方文件，保留该失败证据并使用辅助
导入路径；不得静默替换为低等级材料。

## 9. 测试与验收

默认 `python -m pytest -q` 使用 Fake Provider、本地官方文件和来源元数据 fixture、临时
数据库及临时运行目录，不访问网络。新增测试覆盖 Provider 错误、预算、脱敏、实体污染、
Evidence 类型、官方文件导入、checksum 去重、locator、数值核对、七任务产物、状态和
攻击性 Validator 场景。

在线测试位于 `tests/online/`，默认跳过；只有显式 `--live`、Provider 环境变量和来源开关
同时存在时才运行。在线测试限制调用次数和费用，只保存脱敏摘要与最小 fixture。

最终机械检查：

```text
python -m pytest --collect-only -q
python -m pytest -q
python -m research_os.cli.main validate
python -m compileall -q src tests
git diff --check
```

在线验收还必须得到两个真实 SUCCESS、一个预期降级、官方文件 checksum 和完整追溯链。
最终结论只使用任务书规定的 `READY_FOR_INDEPENDENT_ACCEPTANCE` 或 `NOT_READY_*`。

## 10. 完成和停止条件

工程实现完成但凭证、官方原件、语义覆盖或真实案例不足时，提交已有安全实现与脱敏证据，
保持：

```text
Phase 4 engineering foundation: PASS
Phase 4 full research capability: PARTIAL_SUCCESS
Phase 5: BLOCKED
```

只有独立验收通过并记录验收 SHA 后，才允许申请把完整能力改为 PASS；即使通过，Phase 5
也只可变为 `BLOCKED_PENDING_AUTHORIZATION`，不得在本任务中实施。
