# GOV-ARUX1 — Agent Runtime + Frontend Product Architecture Governance Freeze
# AI＋A股投研 Research OS 顶层架构与工程控制文档治理任务书

状态：
DESIGN APPROVED / GOVERNANCE IMPLEMENTATION AUTHORIZED
DOCUMENTATION-ONLY
PRODUCTION CODE CHANGE: PROHIBITED
P7-D4 BUSINESS IMPLEMENTATION: PAUSED / MUST REMAIN UNCHANGED
INDEPENDENT ACCEPTANCE: REQUIRED AFTER IMPLEMENTATION
MERGE AUTHORIZATION: NO

日期：
2026-08-18

仓库：
rzpeuler/ai-investment-research

默认主分支：
master

用户报告的当前本地 P7-D4 暂停 HEAD：
7c2791b
fix(orchestrator): static 方法中 derivation executor 用类引用（P7-D4 M2）

用户报告的当前 D4 提交链：
7c2791b fix(orchestrator): static 方法中 derivation executor 用类引用（P7-D4 M2）
6bc9b13 docs: P7-D4 taskbook + 治理记录 (Decision #53) + 在线验收 harness（M6+M7）
9f795f4 feat(data-layer): capability WORKFLOW_WIRED + section-boundary 修复 + pipeline 集成测试（M5）
520f5bc feat(data-layer): derive_existing 执行 + 前置条件解析器 + plan 依赖 + schema refs（M2+M4）
2cdfdae feat(documents): TransientDisclosureMaterializer（方案 B，CNINFO 年报 transient PDF）（M1）
aaccf82 feat(financials): deterministic FinancialStatementExtractor（M3）

注意：
上述 D4 HEAD/commit chain 当前尚未由 GitHub connector 远端验证。
执行 Agent 必须以本地 git 工作树为准重新确认。
不得因远端暂不可见而重建、丢弃、reset、cherry-pick 或改写这些 D4 提交。

======================================================================
一、任务目的
======================================================================

本任务只完成一次“顶层设计与产品架构治理冻结”，把已经确认的两项长期设计正式写入
项目权威文档：

A. DeepSeek Harness Agent Runtime + Skill + Tool + MCP 顶层架构；
B. AI 投研工作台 Frontend Product Architecture，包括新增：
   1. 能力指南；
   2. 数据中心 / 数据采集层治理界面。

本任务不是 Agent Runtime 实施任务。
本任务不是前端 Coding 任务。
本任务不是 P7-D4 实施任务。
本任务不得修改任何 Research OS 生产代码。

目标是确保后续任何 Hermes / DeepSeek / Codex Agent 在读取仓库后，能够明确知道：

1. Research OS 的长期目标不是继续无限扩张当前薄 ChatService；
2. DeepSeek Harness 是批准进入 Spike 的首选 Agent Runtime；
3. Harness 负责 Conversation / Agent Loop / Session / Skill orchestration；
4. Research OS 保留 Data / Evidence / PIT / Financial / Graph / Workflow Authority；
5. Skill、Tool、Workflow 三者必须区分；
6. Research OS 与 Harness 的首选能力边界是 MCP；
7. 当前 P7-UX1 仍是实际运行的会话入口，Harness 尚未进入生产；
8. 前端最终产品结构已经冻结到页面和职责层；
9. “能力指南”和“数据中心”成为正式一级产品能力；
10. 前端不得把 Registry 存在、Collector 存在、连接测试成功误表示成业务能力可用；
11. 数据源编辑必须遵守 Source Governance，而不是直接编辑 YAML；
12. P7-D4 当前代码和任务边界完全不受本治理任务影响。

======================================================================
二、文档权威顺序
======================================================================

执行时严格遵守：

docs/engineering-guide.md
→ docs/project-state/DECISIONS.md
→ docs/tasks/*.md
→ docs/project-state/CURRENT_STATE.md
→ docs/project-state/NEXT_PHASE.md
→ docs/project-state/KNOWN_LIMITATIONS.md
→ README.md

AGENTS.md 为执行 Agent 的入口规则，但与 engineering-guide 冲突时以
engineering-guide 为准。

本任务开始前必须完整/定向读取：

1. AGENTS.md
2. docs/engineering-guide.md
3. docs/project-state/DECISIONS.md
4. 当前 P7-D4 taskbook
5. docs/project-state/CURRENT_STATE.md
6. docs/project-state/NEXT_PHASE.md
7. docs/project-state/KNOWN_LIMITATIONS.md
8. README.md
9. P7-UX1 conversational UX taskbook
10. 当前 dashboard/session/chat_service/runtime 相关实现，仅用于确认真实现状
11. 当前 source / data requirement / acquisition capability registries，仅用于确认前端
    数据中心设计不会制造第二套 authority

必须区分：
“当前实际实现”
与
“本轮冻结的未来目标架构”。

======================================================================
三、Git / Branch 前置检查
======================================================================

开始前执行：

git status --short
git branch --show-current
git rev-parse HEAD
git log --oneline -12

必须确认用户报告的 D4 工作是否真实存在于当前本地仓库。

若 HEAD == 7c2791b 或其完整 SHA：
以该 HEAD 为治理基线。

若 HEAD 已在其之后：
不得 reset。
检查后续 commit 是否属于用户/其他 Agent 的合法变更，以当前实际 HEAD 为基线。

若 HEAD 早于 7c2791b：
STOP，不得覆盖用户报告的未合并工作。
仅输出基线不一致报告。

建议从当前确认后的 D4 HEAD 创建：

governance/agent-runtime-frontend-design-freeze

本治理分支必须基于当前暂停的 D4 HEAD，而不是重新从远端 master 创建，
否则会丢失 D4 已经占用的 Decision #53 等治理上下文。

不得：
- force reset
- rebase -i 改写 D4 历史
- squash D4 commits
- cherry-pick 重构 D4
- 删除任何 D4 文件
- 修改 D4 production code

======================================================================
四、Decision 编号规则
======================================================================

用户报告：

Decision #53 已由 P7-D4 使用。

执行 Agent 必须检查当前本地：

docs/project-state/DECISIONS.md

确认真实最大 Decision 编号。

若：
#53 = P7-D4
且 #54/#55 未占用：

使用：

Decision #54
Agent Runtime / Skill / MCP Target Architecture

Decision #55
Frontend Product Architecture / Capability & Data Governance UX

若 #54 或 #55 已被其他真实本地提交使用：
使用之后两个连续未占用编号。

绝对禁止：
- 覆盖 Decision #53
- 重编号旧 Decision
- 把 Agent Runtime 内容塞进 D4 Decision #53
- 修改历史 Decision 的原意

======================================================================
五、必须新增的架构文档
======================================================================

建议创建目录：

docs/architecture/

新增：

docs/architecture/agent-runtime-skill-architecture.md

docs/architecture/frontend-product-architecture.md

并把本任务书保存为：

docs/tasks/governance-agent-runtime-frontend-design-freeze.md

若仓库实际已有等价 architecture/product 目录，可在不制造第二套文档体系的前提下使用
既有目录；否则采用上述路径。

======================================================================
六、Decision #54 — Agent Runtime / Skill / MCP 顶层架构冻结
======================================================================

Decision 必须明确状态：

AGENT_RUNTIME_TARGET_ARCHITECTURE:
APPROVED / DESIGN_FROZEN

PRIMARY_RUNTIME_CANDIDATE:
deepseek-ai/deepseek-harness

HARNESS_ADOPTION_STATUS:
SELECTED_FOR_INTEGRATION_SPIKE

PRODUCTION_ADOPTION:
NOT_ACCEPTED

IMPLEMENTATION:
NOT_STARTED

CURRENT_PRODUCTION_CHAT_RUNTIME:
P7-UX1 EXISTING CHAT CONTROL LAYER

不得写：
“DeepSeek Harness 已成为生产 Runtime”
“已迁移”
“Agent session persistence 已上线”
“Skill Registry 已接入 Research OS”

----------------------------------------------------------------------
6.1 目标架构
----------------------------------------------------------------------

冻结为：

User
  ↓
Frontend
  ↓
DeepSeek Harness
  ├─ Agent Loop
  ├─ Conversation
  ├─ Durable Session
  ├─ Context Management
  ├─ Goal Management
  ├─ Skill Registry
  ├─ Tool Scheduling
  ├─ Subagent capability
  └─ Agent-facing model runtime
  ↓
Scenario Skills / Capability Skills
  ↓
Research OS Tool Surface
  ↓
MCP
  ↓
Existing Python Research OS
  ├─ Orchestrator
  ├─ Scenario Registry
  ├─ Runner
  ├─ DataPreflight
  ├─ GapClassifier
  ├─ AcquisitionPlan / Execution
  ├─ Existing Router
  ├─ Collectors
  ├─ Documents
  ├─ Financial Facts
  ├─ Evidence
  ├─ PIT
  ├─ Knowledge Graph
  ├─ Graph Governance
  └─ Validators
  ↓
SQLite / governed external sources

----------------------------------------------------------------------
6.2 Harness 与 Research OS Authority 边界
----------------------------------------------------------------------

DeepSeek Harness 负责：

- Conversation
- durable agent session
- Agent Loop
- model-facing context
- Skill discovery / loading
- Tool selection
- goal continuation
- optional subagent orchestration
- agent-level model profile
- Agent execution event stream

Research OS 继续拥有唯一 Authority：

- Entity identity
- Security / Company mapping
- as_of / PIT eligibility
- Data Requirement
- Data Readiness
- Data Gap
- Acquisition Plan
- Source selection
- Source Router
- Collector authorization
- RawItem
- Evidence
- Claim / structured research objects
- FinancialReport / FinancialFact
- deterministic financial computation
- Document authority
- Research Workflow
- Research status
- Validator
- Knowledge Graph state
- Graph review / approval / deterministic apply
- Report artifact
- business idempotency

Harness 不得成为第二套：

- Source Router
- Evidence authority
- Financial database
- Graph authority
- Research workflow authority
- entity resolver authority

----------------------------------------------------------------------
6.3 三种 Memory 正式分离
----------------------------------------------------------------------

必须冻结：

A. Conversation Memory
Owner:
DeepSeek Harness Session

用途：
“用户和 Agent 最近在讨论什么”。

允许：
- 当前研究目标的对话引用
- 用户问题
- Agent 回答
- tool execution references
- report/evidence/entity identifiers
- working conversational context

不得作为：
FinancialFact / Evidence / Graph / Research State authority。

B. Research State
Owner:
Research OS

用途：
“某一次正式研究真正执行了什么”。

包括：
- Task
- Plan
- Request
- Run
- DataReadiness
- Acquisition
- structured result
- report
- audit state

C. Knowledge Memory
Owner:
Research OS SQLite / Evidence / Versioned Graph

用途：
长期可信知识。

Agent Memory 中记得的事实不得自动晋级为 Knowledge Memory。

----------------------------------------------------------------------
6.4 Skill / Tool / Workflow 三层定义
----------------------------------------------------------------------

正式定义：

Skill
=
Agent 可按需加载的“如何完成某类任务”的方法、说明、约束和能力导航。

Tool
=
具有严格输入输出契约的可执行能力接口。

Workflow
=
Research OS 中经过正式治理和验收的业务执行程序。

禁止三者混用。

例：

Scenario Skill:
stock-research

Capability Skills:
financial-analysis
data-readiness
industry-graph-research
evidence-review

Tools:
get_company_profile
check_data_readiness
get_financial_facts
query_industry_graph
lookup_evidence
acquire_missing_data
run_stock_research

Formal Workflow:
Orchestrator.execute("stock_research_report", ...)

Skill 可以指导 Agent 选择 Tool。
Skill 不拥有数据库。
Skill 不拥有 source selection。
Skill 不得绕过正式 Workflow 的必须步骤。

----------------------------------------------------------------------
6.5 两类 Skill
----------------------------------------------------------------------

A. Scenario Skill

例如：
- morning-brief
- abnormal-move-analysis
- stock-research
- evening-brief
- daily-review
- stock-review
- industry-research
- theme-discovery
- earnings-expectation
- first-coverage

正式 Scenario Skill 可以调用一个完整 Research OS Scenario Tool，
不得让 Agent 自己复制正式 Workflow 的内部业务判定。

B. Capability Skill

例如：
- financial-analysis
- data-readiness
- document-research
- evidence-review
- graph-research
- company-profile
- acquisition-guidance

用于开放式研究和组合式交互。

----------------------------------------------------------------------
6.6 MCP 边界
----------------------------------------------------------------------

冻结首选方向：

Python application/control plane
  ↓ Python SDK / JSON-RPC
DeepSeek Harness Runtime

Harness Tool Execution
  ↓ MCP
Research OS MCP Server
  ↓
Existing Research OS services

明确：

Python SDK / JSON-RPC：
主要用于启动、驱动、恢复和观察 Harness Agent Runtime。

MCP：
主要作为 Harness → Research OS 的 capability boundary。

第一版 MCP 不得暴露低级 Collector：

PROHIBITED:
cninfo_fetch_direct
nbs_fetch_direct
sina_fetch_direct

应暴露业务语义 Tool：

ALLOWED TARGET SURFACE:
get_company_profile
check_data_readiness
acquire_missing_data
get_financial_facts
query_documents
lookup_evidence
query_industry_graph
run_research_scenario
propose_graph_change

Graph：

query_graph:
ALLOW

propose_graph_change:
ALLOW（未来须独立授权）

approve_graph_change:
DENY

apply_graph_change:
DENY

Source：

acquire_missing_data:
通过现有 Acquisition / Router

direct_source_selection_by_agent:
DENY

----------------------------------------------------------------------
6.7 Harness Security Profile
----------------------------------------------------------------------

生产 Research Agent Profile 目标必须默认：

bash:
OFF

filesystem_write:
OFF

editor:
OFF

arbitrary_subprocess:
OFF

direct_network:
OFF，除非通过受治理 Research OS capability

Research OS MCP:
ON

Skill:
ON

Goal:
ON

Evidence read:
ON

Graph query:
ON

Graph direct write:
OFF

所有权限须 fail closed。

Harness coding-agent 默认配置不得直接复制到 Research OS 产品环境。

----------------------------------------------------------------------
6.8 Session / Privacy / Storage Policy
----------------------------------------------------------------------

Harness durable session 与 Research OS audit 必须分离。

Agent Session 可以保存：
- 用户对话
- assistant responses
- tool call metadata
- bounded structured tool results
- Research OS object references

禁止写入 session：
- API key
- Authorization header
- Cookie
- password
- credential
- 未经允许的完整网页正文
- 被 source storage policy 禁止长期保存的全文
- CNINFO transient PDF bytes
- 其他 governed full document blobs

Research Tool 返回 Harness 的内容应优先为：

structured value
+
bounded summary
+
object/evidence/reference IDs

而不是把整个官方 PDF / 网页正文塞进 Agent history。

生产 Session retention / encryption / cleanup policy：
P8-A0 先验证，正式上线前单独冻结。

----------------------------------------------------------------------
6.9 LLM Ownership
----------------------------------------------------------------------

第一阶段允许双层模型控制：

Agent-facing LLM:
DeepSeek Harness

Formal Research Workflow internal LLM:
existing research_os.llm

保留当前已验收：

LlmClient
Provider Factory
Flash → Pro business escalation
budget
validation
fallback
audit

P8-A0 不得顺便删除/重写 existing LlmClient。

未来如统一 provider/profile：
必须另立 Decision + taskbook。

----------------------------------------------------------------------
6.10 DeepSeek Harness 版本治理
----------------------------------------------------------------------

记录：

upstream:
deepseek-ai/deepseek-harness

当前采用状态：
Developer Preview dependency candidate

因此：

- 不允许自动跟 latest
- 正式 Spike 必须 pin SDK/runtime exact version
- SDK 与 runtime-bin 必须同版本
- 升级必须走 compatibility test
- breaking change 不得直接进入生产
- Harness 不成为 Research OS 数据契约 authority

本治理任务：
不得修改 pyproject.toml
不得安装 Harness
不得 vendoring Harness
不得添加 Node runtime
不得启动真实 Harness

----------------------------------------------------------------------
6.11 P8-A0 Harness Integration Spike
----------------------------------------------------------------------

在 P7-D4：

PASS
+
INDEPENDENTLY_ACCEPTED
+
MERGED

之后，优先进行：

P8-A0 DeepSeek Harness Integration Spike

而不是直接进行完整 Agent migration。

Spike 最小范围：

Harness:
- Python SDK
- pinned runtime
- durable session
- research-specific profile
- Skill discovery
- Agent Loop

Research OS Tools:
1. get_company_profile
2. check_data_readiness
3. query_industry_graph
4. run_research_scenario

Skills:
1. stock-research
2. financial-analysis
3. industry-graph-research

验证会话：

用户：
“研究一下宁德时代”

→ 识别 / Tool / 正式 scenario

用户：
“刚才这个公司的现金流怎么样？”

→ 同 session 保留目标上下文

用户：
“产业链上有什么风险？”

→ query graph

用户：
“再和亿纬锂能比较一下”

→ 新增第二 target，但不得污染第一 target authority

Spike 成功前：
P7-UX1 不下线。

----------------------------------------------------------------------
6.12 P7-D4 Unaffected Rule
----------------------------------------------------------------------

必须明确写入 Decision：

P7-D4 IS UNAFFECTED BY THIS ARCHITECTURE FREEZE.

本 Decision 不授权 P7-D4：

- 使用 Harness
- 安装 Harness
- MCP 化
- Skill 化
- 重构 Orchestrator
- 重构 ChatService
- 修改 LlmClient
- 修改模型 routing
- 扩大 source scope
- 扩大 Graph scope
- 修改 DB schema
- 新增 migration

D4 恢复后继续严格按当前 D4 taskbook 完成。

======================================================================
七、docs/architecture/agent-runtime-skill-architecture.md 内容要求
======================================================================

完整文档至少包含：

1. 背景与设计动机
2. 当前 P7-UX1 架构和限制
3. Target Architecture
4. Harness / Research OS authority matrix
5. Conversation / Research / Knowledge 三类 Memory
6. Skill / Tool / Workflow definitions
7. Scenario Skills
8. Capability Skills
9. MCP Tool Surface
10. Model ownership
11. Security / permission model
12. Session persistence / privacy
13. Graph governance boundary
14. Data acquisition governance boundary
15. Transition strategy
16. P8-A0 Spike
17. Harness version pinning / upgrade policy
18. Explicit non-goals
19. Current status matrix

必须有状态表：

DeepSeek Harness candidate    SELECTED
Harness dependency            NOT_INSTALLED
Harness production runtime    NOT_IMPLEMENTED
Persistent agent session      NOT_IMPLEMENTED
Research OS MCP server        NOT_IMPLEMENTED
Scenario Skills               NOT_IMPLEMENTED
Capability Skills             NOT_IMPLEMENTED
P7-UX1 existing chat          CURRENT
Research OS authority         CURRENT / MUST REMAIN

======================================================================
八、Decision #55 — Frontend Product Architecture Freeze
======================================================================

状态：

FRONTEND_PRODUCT_ARCHITECTURE:
APPROVED / DESIGN_FROZEN

FRONTEND_IMPLEMENTATION:
NOT_AUTHORIZED BY THIS TASK

UI CODE:
UNCHANGED

产品定位：

“个人 AI 投研操作系统 / AI Research OS”

核心价值：

用对话发起研究；
用真实数据支撑研究；
用 Evidence 验证研究；
用产业图谱积累长期认知。

不得把产品定位成：
- 交易终端
- 自动荐股系统
- 量化下单系统
- 目标价生成器
- ChatGPT 套壳

----------------------------------------------------------------------
8.1 一级产品信息架构
----------------------------------------------------------------------

左侧主导航冻结为：

今天

研究
  AI研究
  公司
  产业图谱
  研究库

系统能力
  能力指南
  数据中心
  待审核

右上：
设置

全局：
搜索 / 当前研究上下文 / Evidence drawer / status indicator

允许后续视觉调整，但一级页面职责不得由实现 Agent 擅自改变。

----------------------------------------------------------------------
8.2 今天
----------------------------------------------------------------------

“今天”是日常工作入口，不使用工程术语 Dashboard。

包含：

- 大型自然语言研究输入框
- 快捷入口：
  今日晨报
  今日复盘
  行业研究
  个股研究
- 最近研究
- 当前数据高层状态
- 当前需要用户处理的待审核项

禁止首页主要展示：

pytest 数量
schema 数量
DB version
CI run
内部 class name
debug logs

这些只进入高级/工程状态。

----------------------------------------------------------------------
8.3 AI研究
----------------------------------------------------------------------

目标布局：

左：
- AUTO / 10 个正式研究场景
- 历史研究 / 会话

中：
- Conversation
- Business Progress
- Research Result

右：
- current target
- as_of
- data readiness
- online data
- model profile/status
- source/evidence context

业务进度显示：

正在确认研究对象
正在检查数据
正在获取缺失数据
正在读取财务
正在读取产业图谱
正在整理证据
正在运行研究
正在验证结果
已完成

禁止显示模型 private chain-of-thought。

----------------------------------------------------------------------
8.4 两个独立开关
----------------------------------------------------------------------

必须继续保留：

AI 理解
≠
在线数据

不得合并。

未来 Harness 接入后也保持语义：

AI / Agent enabled
控制 Agent/LLM 交互。

Research Live Data
控制正式 Research OS 数据获取权限。

Agent ON 不等于自动联网。
Online Data ON 不等于允许任意 Agent 网络访问。

----------------------------------------------------------------------
8.5 用户状态词
----------------------------------------------------------------------

前端统一使用：

已完成
部分完成
数据不足
正在获取数据
正在研究
需要你确认
执行失败

必须冻结：

DATA INSUFFICIENT != EXECUTION FAILED

partial_success / degraded / insufficient_evidence
不得统一映射成“失败”。

----------------------------------------------------------------------
8.6 研究结果页
----------------------------------------------------------------------

Tabs：

研究结论
财务
事件
风险与催化
证据
数据状态

默认显示：

- 研究对象
- 场景
- as_of
- 状态
- 信息完整度
- 核心研究判断
- 财务质量
- 竞争优势/弱点
- 风险
- 催化
- 研究限制

禁止：

Buy
Sell
目标价
仓位
自动交易

----------------------------------------------------------------------
8.7 Evidence Drawer
----------------------------------------------------------------------

对事实性结论支持：

“查看依据”

右侧 drawer 至少展示：

- source
- publisher
- document/report
- published_at
- page / block / locator
- excerpt or structured value
- source tier
- Evidence ID
- RawItem / Document reference
- as_of eligibility

Evidence UI 不得凭前端自己创造 source authority。

----------------------------------------------------------------------
8.8 公司页
----------------------------------------------------------------------

Tabs：

概览
财务
公告
研究
产业链
证据

未有真实数据时必须显式显示：

“尚未自动接入”
“数据不足”
“仅支持人工输入”

禁止伪造 K 线、实时价格、历史估值。

D4 / D5 / realtime 能力只有在对应独立验收后才允许 UI 宣布自动可用。

----------------------------------------------------------------------
8.9 产业图谱
----------------------------------------------------------------------

默认：

行业树
+
1-hop graph
+
节点详情

支持：

上游
下游
竞争
替代
受益
受损

根据实际 ontology/relations 显示，不在前端写死虚构行业关系。

显示 epistemic：

基础治理结构      GOVERNANCE
已证实事实        FACT
研究判断          MODEL_INFERENCE

MODEL_INFERENCE 必须可查看：
- evidence
- confidence
- as_of
- review state

as_of selector 为正式产品能力。

不得用超大蜘蛛网作为默认首页。

----------------------------------------------------------------------
8.10 研究库
----------------------------------------------------------------------

支持按：

公司
行业
主题
日期
场景
状态

检索历史研究。

Report / Run / Evidence authority 仍来自 Research OS。

----------------------------------------------------------------------
8.11 待审核
----------------------------------------------------------------------

对应现有 Graph candidate / review / apply 治理。

展示：

subject
relation
object
fact / inference
evidence
conflict
review state

用户动作：

批准
修改后批准
暂缓
拒绝

但任何前端批准动作仍必须经过：

Review Contract
→ Validator
→ Deterministic Apply

前端按钮不得绕过 Validator。

在 Phase 6.1 / future integration 未授权时：
不得出现“AI 自动更新图谱”开关。

======================================================================
九、新增正式一级能力：能力指南
======================================================================

“能力指南”不是静态帮助页面。

它回答：

1. 系统能做什么？
2. 某个真实研究场景怎么工作？
3. 工作流经过哪些步骤？
4. 每一步由哪个功能模块负责？
5. 每个模块需要什么数据？
6. 使用哪些 Skill / Tool / Workflow？
7. 当前能力是可用、部分可用还是未接入？

页面提供两个入口：

按研究场景
按功能模块

----------------------------------------------------------------------
9.1 需求场景层
----------------------------------------------------------------------

必须从正式 Scenario Registry / accepted scenario metadata 投影当前十场景：

每日晨报
异动分析
个股研报
每日晚报
每日复盘
个股复盘
行业研究
主题发现
财报预期
首次覆盖

不得维护第二套硬编码业务场景 authority。

每个场景页面至少包括：

- 这个能力做什么
- 适合什么时候使用
- 示例提问
- 需要的数据
- 输出
- 正式工作流
- 每一步状态
- 相关功能模块
- 相关 Skill
- 相关 Tool
- 相关数据类型
- 当前限制

----------------------------------------------------------------------
9.2 Workflow 可视化
----------------------------------------------------------------------

例如：

个股研报

理解需求
→ 确认公司
→ 检查数据
→ 补充数据
→ 财务分析
→ 业务/竞争分析
→ 图谱上下文
→ 语义研究
→ Evidence validation
→ 正式报告

这里显示：
Business workflow state

禁止显示：
private chain-of-thought。

----------------------------------------------------------------------
9.3 功能模块层
----------------------------------------------------------------------

按功能模块展示：

研究入口
研究控制
数据处理
研究分析
知识能力
输出能力

每个模块至少显示：

- 负责什么
- 被哪些场景使用
- 输入
- 输出
- 是否确定性
- 是否使用 LLM
- 是否允许网络
- 是否写数据库
- 依赖数据
- 当前状态
- 实现位置（高级信息）
- Skill / Tool mapping

----------------------------------------------------------------------
9.4 Capability Catalog 原则
----------------------------------------------------------------------

能力指南不得在 HTML/JS 中硬写完整能力真相。

未来建立：

Capability Catalog Projection

它不是新的 business authority。

它应组合读取：

Scenario Registry
Scenario Data Requirements
Data Acquisition Capabilities
Source Registry
module metadata
Research OS tool metadata
未来 Harness Skill Registry

前端只消费 projection。

禁止创建：

frontend_capabilities.yaml

作为第二套 authority，除非后续正式 Decision 明确批准。

======================================================================
十、新增正式一级能力：数据中心 / 数据采集层总览
======================================================================

数据中心 Tabs：

数据准备度
数据源
采集能力
采集记录

----------------------------------------------------------------------
10.1 数据准备度
----------------------------------------------------------------------

面向业务显示：

数据类型
当前状态
覆盖对象
覆盖期间
最新时间
来源等级
自动化程度
缺口

DataGap 状态翻译：

READY / AVAILABLE
→ 已准备

AUTO_ACQUIRABLE
→ 可以自动获取

STALE_REFRESHABLE
→ 数据较旧，可以更新

MANUAL_INPUT_REQUIRED
→ 需要你提供数据

HUMAN_REVIEW_REQUIRED
→ 需要确认

NOT_ACQUIRABLE / UNAVAILABLE
→ 当前没有可用数据源

SOURCE_UNHEALTHY
→ 数据源暂时不可用

不得把“Source Registry 已登记”翻译成“数据已准备”。

----------------------------------------------------------------------
10.2 数据源
----------------------------------------------------------------------

按 Platform → Source 展示。

一个平台可以包含多个 Source。

展示字段至少：

- 平台
- source_id
- display name
- source type
- source tier
- access level
- paid
- login required
- automation level
- update frequency
- storage policy
- allowed usage
- governance status
- verification status
- lifecycle
- 提供的数据类型
- 被哪些场景使用

需要支持：

官方披露
政府监管
行情
新闻
社区
人工数据
未来其他平台

实际名单只能来自 Source Registry / governance metadata。

----------------------------------------------------------------------
10.3 Source != Capability
----------------------------------------------------------------------

前端必须明确区分：

Source Registered
≠
Collector Implemented
≠
Workflow Wired
≠
Business Sufficient

数据源详情展示 lifecycle：

REGISTERED
→ PROBED
→ ADAPTER_IMPLEMENTED
→ WORKFLOW_WIRED
→ BUSINESS_SUFFICIENT

但实际枚举和值必须以项目当前正式 lifecycle contract 为准。

禁止前端自行晋级状态。

----------------------------------------------------------------------
10.4 数据能力矩阵
----------------------------------------------------------------------

展示：

Data Type
Current primary path
Automation
Lifecycle
Readiness
Used by scenarios
Known limitations

矩阵来源：

scenario_data_requirements
+
data_requirements
+
data_acquisition_capabilities
+
source registry
+
readiness projection

不得从单一 sources.yaml 猜业务充分性。

----------------------------------------------------------------------
10.5 数据源详情
----------------------------------------------------------------------

例如 CNINFO 页面应能够展示：

平台信息
来源等级
访问方式
费用
登录要求
存储策略
允许用途
提供数据
Collector / Adapter 状态
Workflow 状态
Capability lifecycle
最近验证
被哪些数据类型使用
被哪些场景间接使用
Known limitations

必须明确：

“连接正常”
≠
“业务充分”。

----------------------------------------------------------------------
10.6 测试连接
----------------------------------------------------------------------

未来 UI 可以提供：

测试连接

但：

Test Connection PASS
只代表 connectivity / probe。

绝对不得自动：

REGISTERED → WORKFLOW_WIRED
或
WORKFLOW_WIRED → BUSINESS_SUFFICIENT

任何 capability 晋级继续走正式治理。

======================================================================
十一、数据源编辑前端治理
======================================================================

允许未来提供：

编辑数据源
新增数据源
停用数据源

但禁止把 Source Registry 暴露为普通 YAML 编辑器。

----------------------------------------------------------------------
11.1 两类修改
----------------------------------------------------------------------

A. Runtime / operational preference

例如：
- 临时禁用
- 请求频率限制
- 当前不优先使用
- 用户 preference

B. Governance fields

例如：
- source_tier
- paid
- login_required
- allowed_usage
- storage_policy
- source_type
- authority
- status

两类修改必须分开处理。

----------------------------------------------------------------------
11.2 Governance 修改流程
----------------------------------------------------------------------

编辑
→ Validate
→ Diff Preview
→ Impact Analysis
→ User Confirm
→ Governance Write Path
→ Audit Record
→ New Effective Configuration

不得：

表单保存
→ 直接无提示覆盖 registry

----------------------------------------------------------------------
11.3 Impact Analysis
----------------------------------------------------------------------

前端至少展示：

修改前
修改后
影响的数据类型
影响的场景
影响的 storage policy
影响的 acquisition capability
可能要求重新 probe / acceptance 的项目

例如：

metadata_and_excerpt
→ full_text

必须高亮：

存储政策变化
版权/来源治理变化
Evidence/Document 影响

不得静默生效。

----------------------------------------------------------------------
11.4 新增数据源
----------------------------------------------------------------------

未来向导：

基本信息
→ 访问方式
→ 数据内容
→ 使用范围
→ 存储政策
→ Probe
→ Governance Review
→ Register

必须显示：

“登记数据源 ≠ 自动可用于正式研究”。

======================================================================
十二、前端与 Agent Runtime 的连接关系
======================================================================

最终目标：

Frontend
   ↓
Harness Session / Agent
   ↓
Skill
   ↓
Tool
   ↓
Research OS
   ↓
Data / Evidence / Graph / Report

能力指南：

Scenario
↕
Skill
↕
Capability Module
↕
Tool
↕
Data Type
↕
Source
↕
Evidence

数据中心：

Source
↕
Data Type
↕
Capability
↕
Scenario

要求：

用户可以从“个股研报 → 财务数据步骤”跳转到
“数据中心 → financial_statement_data”。

也可以从：

“CNINFO → 被哪些研究使用”

反向看到相关场景。

这种关联是 read-model / projection，
不是改变业务 authority。

======================================================================
十三、engineering-guide.md 更新
======================================================================

必须更新工程指南版本。

执行前读取当前本地版本。

若仍为 V1.7：
升级 V1.8。

若 D4 本地已经合法升级到 V1.8：
本次升级 V1.9。

规则：
只增加一个版本号，不反复跳号。

更新日期：
2026-08-18

新增长期稳定原则，至少包括：

1. 四层业务架构不变：
   需求场景层
   功能模块层
   数据采集层
   知识库层

2. Agent Runtime 归横向工程控制面，不是第五业务层。

3. Frontend/Product Surface 不是第五业务层。

4. 长期目标采用：
   Agent Runtime + Skill Interface + Deterministic Research OS Core。

5. Harness target status 与 production status 分开。

6. Skill / Tool / Workflow 正式定义。

7. Memory 三分法。

8. MCP 是首选 Agent→Research OS capability boundary。

9. Agent 不得绕过 Source Router / Evidence / PIT / Graph Validator。

10. 当前 Research Workflow LLM 与 Harness Agent LLM 第一阶段允许并存。

11. Production Research Agent 默认禁止 arbitrary shell/fs-write/direct network。

12. Capability Guide / Data Center 必须是 authoritative projection，不得建立
    第二套业务事实。

13. Frontend 状态展示不得夸大能力。

14. 数据不足 != 执行失败。

15. LLM / Agent gate 与 Research Live Data gate 独立。

16. Evidence drawer / lineage 是正式产品能力。

17. 数据源编辑属于治理写操作，必须 Diff + Impact + Confirm + Audit。

18. Harness version 必须 pin，禁止自动 latest。

不要把 Harness 0.1 的易变 package/class 名称大量写入 engineering-guide。
具体实现细节放 architecture doc。

======================================================================
十四、AGENTS.md 更新
======================================================================

加入简洁长期执行规则：

1. DeepSeek Harness 是已批准的 Agent Runtime target，但当前 NOT_IMPLEMENTED。
2. 未经 P8-A0 taskbook 不得安装/集成 Harness。
3. Agent Runtime 不得替代 Research OS authority。
4. Skill 不得直接执行 source-specific collector routing。
5. Graph direct write/approve/apply 不得暴露给 Agent。
6. 前端不得硬编码虚假 capability status。
7. 数据源连接成功不得自动晋级 lifecycle。
8. 前端不得显示 private chain-of-thought。
9. 新的 UI/API implementation 需要独立 taskbook。
10. D4 恢复时继续遵循现有 D4 taskbook，不因 Agent Runtime Decision 改范围。

AGENTS.md 不写长篇产品设计，只放执行者必须知道的约束。

======================================================================
十五、CURRENT_STATE.md 更新
======================================================================

必须如实写：

P7-D4:
IMPLEMENTATION IN PROGRESS / TEMPORARILY PAUSED FOR GOVERNANCE FREEZE

仅在本地实际 HEAD 核对成功后记录：

PAUSED_HEAD:
7c2791b...（完整 SHA）

不得写：
P7-D4 PASS
D4 independently accepted
M6/M7 PASS
除非真实独立验收已经发生。

新增：

AGENT_RUNTIME_ARCHITECTURE:
DESIGN_FROZEN

DEEPSEEK_HARNESS:
PRIMARY_INTEGRATION_CANDIDATE

HARNESS_INTEGRATION:
NOT_IMPLEMENTED

HARNESS_PRODUCTION_ACCEPTANCE:
NO

CURRENT_CHAT_RUNTIME:
P7-UX1 / IN_MEMORY_ONLY

FRONTEND_PRODUCT_ARCHITECTURE:
DESIGN_FROZEN

CAPABILITY_GUIDE:
DESIGNED / NOT_IMPLEMENTED

DATA_SOURCE_MANAGEMENT_UI:
DESIGNED / NOT_IMPLEMENTED

FRONTEND_SOURCE_EDITING:
NOT_IMPLEMENTED

同时保留 D3/D4 等真实状态。

======================================================================
十六、NEXT_PHASE.md 更新
======================================================================

当前立即顺序冻结：

1. 完成本 GOV-ARUX1 governance freeze
2. 用户/独立架构验收
3. 恢复 P7-D4 coding
4. 完成 D4
5. D4 independent acceptance
6. D4 merge
7. P8-A0 DeepSeek Harness Integration Spike
8. P8-A0 independent architecture acceptance
9. 再决定 Harness production adoption
10. D5 / 后续数据能力按新路线继续

明确：

P8-A0 DESIGN INTENT:
APPROVED

P8-A0 IMPLEMENTATION:
NOT_AUTHORIZED BY THIS TASK

D5:
不得因为本次设计自动开始。

Frontend implementation：
NOT_AUTHORIZED。
后续须独立 frontend taskbook。

可以记录：

Frontend foundation 可在未来与部分数据阶段解耦实施，
但 AI Research session integration 必须兼容最终 Harness boundary。

======================================================================
十七、KNOWN_LIMITATIONS.md 更新
======================================================================

新增/更新：

1. 当前会话仍是 P7-UX1 IN_MEMORY_ONLY。
2. Harness 尚未集成。
3. Persistent Agent Conversation 尚不可用。
4. Skill Registry 尚未进入本项目 production。
5. Research OS MCP Server 尚未实现。
6. Capability Guide 尚未实现。
7. 数据中心目前没有完整前端 product surface。
8. Source editing API 尚未实现。
9. Source registration / capability lifecycle 不能由前端修改。
10. Test connection 尚不构成 business sufficiency。
11. Agent model profile / 套餐 UI 尚未实现。
12. Harness 为 developer-preview upstream，正式采用前有 compatibility risk。
13. D4 仍未独立验收。
14. Frontend 不得宣称 D4/D5/realtime 等尚未验收能力已自动可用。

======================================================================
十八、README.md 更新
======================================================================

README 只做导航摘要，不重新定义架构。

增加链接：

Agent Runtime / Skill Architecture
→ docs/architecture/agent-runtime-skill-architecture.md

Frontend Product Architecture
→ docs/architecture/frontend-product-architecture.md

并明确状态：

DESIGN FROZEN / NOT IMPLEMENTED

避免在 README 写大量重复内容。

======================================================================
十九、docs/architecture/frontend-product-architecture.md 内容要求
======================================================================

文档至少包括：

1. 产品定位
2. 设计原则
3. 一级导航
4. 全局布局
5. 今天
6. AI研究
7. 研究结果
8. Evidence Drawer
9. 公司
10. 产业图谱
11. 研究库
12. 能力指南
13. 数据中心
14. 数据源详情
15. 数据能力矩阵
16. 数据源编辑
17. 待审核
18. 设置 / Agent Profile 未来入口
19. 用户状态语言
20. AI/Live 两开关
21. Capability lifecycle UI semantics
22. 权威数据来源
23. Feature gating
24. 当前可实现 / D4 后 / D5 后 / future
25. 明确禁止项

增加能力状态表：

功能                     当前设计状态
今天                     DESIGN_FROZEN
AI研究                   EXISTING UX1 + FUTURE HARNESS EVOLUTION
公司                     DESIGN_FROZEN
产业图谱                 DESIGN_FROZEN
研究库                   DESIGN_FROZEN
能力指南                 DESIGN_FROZEN / NOT_IMPLEMENTED
数据中心                 DESIGN_FROZEN / PARTIAL BACKEND CAPABILITY
数据源编辑               DESIGN_FROZEN / NOT_IMPLEMENTED
待审核                   BACKEND GOVERNANCE EXISTS / PRODUCT UI NOT IMPLEMENTED
Harness session UI        NOT_IMPLEMENTED

======================================================================
二十、禁止事项
======================================================================

本任务严格禁止修改：

src/
tests/  （除非仅有既存测试，不新增测试代码）
schemas/
registry/
config/   （除非只读）
migrations/
pyproject.toml
package.json
任何 Collector
任何 Router
任何 Orchestrator
任何 D4 extractor/materializer/executor
任何 dashboard HTML/CSS/JS
任何 LLM client/provider
任何 Graph production code

不得：

- 安装 deepseek-harness-sdk
- 新增 MCP Server
- 新增 Skill 文件作为 production capability
- 修改数据库
- 添加 migration
- 修改 schema count
- 修改 source registry
- 修改 acquisition lifecycle
- 修改 D4 taskbook 业务范围
- 自动恢复 D4 coding
- 自动启动 D5
- 调用真实 DeepSeek
- 调用真实数据源
- 进行 online acceptance
- 自动 merge master

======================================================================
二十一、文档一致性检查
======================================================================

必须机械检查：

1. Decision #53 仍是 D4，内容没有被覆盖。
2. Agent Runtime 使用新 Decision。
3. Frontend 使用独立新 Decision。
4. engineering-guide 版本唯一、日期一致。
5. CURRENT_STATE 只写当前事实。
6. NEXT_PHASE 只写未来准入。
7. KNOWN_LIMITATIONS 不声称未来能力已实现。
8. README 只做摘要。
9. P7-UX1 历史记录不得被改写成 Harness。
10. D4 taskbook 不改变。
11. D4 status 不被错误写成 PASS。
12. Harness status 全仓一致：

SELECTED / DESIGN FROZEN / NOT IMPLEMENTED / NOT PRODUCTION ACCEPTED

13. Frontend status 全仓一致：

DESIGN FROZEN / IMPLEMENTATION NOT AUTHORIZED

14. “connection/probe success != BUSINESS_SUFFICIENT” 一致。
15. “Agent Memory != Knowledge Authority” 一致。
16. “Agent != second Source Router” 一致。
17. “Skill != Tool != Workflow” 一致。
18. “AI gate != Research Live Data gate” 一致。
19. “insufficient data != execution failure” 一致。
20. “private chain-of-thought not displayed” 一致。

======================================================================
二十二、测试与验证
======================================================================

本任务开始前先记录 baseline：

git status --short
git rev-parse HEAD

若当前 D4 分支已有可运行 offline test baseline，
记录其当前状态。

修改完成后至少执行：

git diff --check

python -m research_os.cli.main validate

python -m compileall -q src tests

python -m pytest

由于本轮仅文档修改：

- 不允许网络
- 不允许 --live
- 不允许 --live-data
- 不允许 DeepSeek API
- 不允许真实 CNINFO/NBS

若 D4 暂停 HEAD 本身存在已知 pre-existing test failure：

必须：
1. 先证明该失败在治理文档修改前就存在；
2. 文档修改后不得新增 failure；
3. handoff 中明确标记 PRE-EXISTING；
4. 不得借本治理任务修改 D4 code 修复。

检查 changed files：

git diff --name-only <GOV_BASE_SHA>..HEAD

允许的业务文件范围应仅为：

AGENTS.md
README.md
docs/engineering-guide.md
docs/project-state/DECISIONS.md
docs/project-state/CURRENT_STATE.md
docs/project-state/NEXT_PHASE.md
docs/project-state/KNOWN_LIMITATIONS.md
docs/architecture/agent-runtime-skill-architecture.md
docs/architecture/frontend-product-architecture.md
docs/tasks/governance-agent-runtime-frontend-design-freeze.md

如需要额外 Markdown index 文件，可增加，但必须说明原因。

任何 src/tests/schema/registry/config/migration 改动：
FAIL / STOP。

======================================================================
二十三、Definition of Done
======================================================================

全部满足才可交付：

[ ] 本地 D4 HEAD 和提交链已核对
[ ] 没有丢失/改写 D4 commits
[ ] Decision #53 未被覆盖
[ ] Agent Runtime 新 Decision 已新增
[ ] Frontend 新 Decision 已新增
[ ] engineering-guide 版本已正确递增
[ ] Agent Runtime architecture 文档完整
[ ] Frontend product architecture 文档完整
[ ] AGENTS.md 执行边界同步
[ ] CURRENT_STATE 事实状态同步
[ ] NEXT_PHASE 路线同步
[ ] KNOWN_LIMITATIONS 同步
[ ] README 导航同步
[ ] Harness 明确 NOT_IMPLEMENTED
[ ] Frontend implementation 明确 NOT_AUTHORIZED
[ ] P7-D4 明确 UNAFFECTED
[ ] P8-A0 明确为 D4 后 Spike
[ ] Research OS Authority 未被 Harness 取代
[ ] Skill / Tool / Workflow 定义清楚
[ ] Memory 三分法清楚
[ ] MCP 边界清楚
[ ] 数据源前端治理边界清楚
[ ] Capability Guide projection 原则清楚
[ ] Source != Capability 原则清楚
[ ] 数据不足 != 失败原则清楚
[ ] AI gate != live-data gate
[ ] private chain-of-thought 不进入前端设计
[ ] DB version 未变
[ ] migrations 未变
[ ] schema count 未变
[ ] production code 0 changes
[ ] git diff --check PASS
[ ] schema validate 无新增失败
[ ] compileall 无新增失败
[ ] pytest 无新增失败
[ ] 最终只有 governance/docs commit

======================================================================
二十四、提交要求
======================================================================

建议单独一个治理 commit：

docs: freeze agent runtime and frontend product architecture

不得把本提交 squash 到现有 D4 实现提交中。

Commit 必须保持：

GOVERNANCE_ONLY: YES
PRODUCTION_CODE_DELTA: 0
SCHEMA_DELTA: 0
MIGRATION_DELTA: 0
DB_VERSION_DELTA: 0
SOURCE_REGISTRY_DELTA: 0
D4_BUSINESS_LOGIC_DELTA: 0

完成后：

不得自行 merge master。
不得自行恢复 D4 coding。

等待独立架构验收。

======================================================================
二十五、最终 Handoff 格式
======================================================================

最终必须返回：

GOV-ARUX1:
IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

BASE_SHA:
<full sha>

FINAL_HEAD:
<full sha>

BRANCH:
<name>

DECISIONS:
Agent Runtime = #<actual>
Frontend = #<actual>

ENGINEERING_GUIDE:
<old version> → <new version>

FILES_CREATED:
...

FILES_MODIFIED:
...

PRODUCTION_CODE_CHANGED:
NO

D4_CODE_CHANGED:
NO

D4_STATUS:
PAUSED / NOT INDEPENDENTLY ACCEPTED

AGENT_RUNTIME:
DESIGN_FROZEN / NOT_IMPLEMENTED

DEEPSEEK_HARNESS:
PRIMARY_INTEGRATION_CANDIDATE / NOT_PRODUCTION_ACCEPTED

FRONTEND:
DESIGN_FROZEN / NOT_IMPLEMENTED

CAPABILITY_GUIDE:
DESIGN_FROZEN / NOT_IMPLEMENTED

DATA_SOURCE_MANAGEMENT_UI:
DESIGN_FROZEN / NOT_IMPLEMENTED

DB:
v6 / NO CHANGE

MIGRATIONS:
NONE ADDED

SCHEMAS:
NO COUNT CHANGE

TESTS:
pytest = ...
schema validate = ...
compileall = ...
diff-check = ...

OPEN_QUESTIONS:
仅列仍需未来 P8-A0 / frontend taskbook 决定的问题，
不得把已经冻结的 authority boundary 重新列为开放问题。

NEXT:
1. independent governance acceptance
2. resume P7-D4 from frozen code state
3. finish + independently accept D4
4. P8-A0 Harness Integration Spike
5. decide production Harness adoption
6. separate frontend implementation taskbook

======================================================================
二十六、STOP 条件
======================================================================

遇到以下任何一项立即 STOP 并报告：

- 本地找不到用户报告的 D4 commits，且当前 HEAD 早于 7c2791b
- 工作树有无法解释的用户未提交修改
- Decision #53 实际不是 D4 且编号历史与用户报告严重冲突
- 必须修改 production code 才能完成文档
- 必须新增 Schema / migration
- 需要修改 D4 business scope
- 需要删除现有 P7-UX1 才能描述新架构
- 需要将 Harness 声明为已生产采用
- 需要真实联网才能完成治理文档
- 出现第二套 Source Router / Evidence Authority / Graph Authority 设计
- 前端设计要求绕过 Source Governance
- 前端设计要求显示模型 private chain-of-thought
- 任何 Agent 获得直接 Graph approve/apply 权限
- 任何 Agent 获得绕过 Router 的 source-specific production access

本任务在这些情况下宁可停在治理设计阶段，也不得扩大实施范围。
