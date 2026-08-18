# Agent Runtime / Skill / MCP 顶层架构（DeepSeek Harness）

> 状态：**DESIGN FROZEN / NOT IMPLEMENTED**
> 治理依据：`docs/project-state/DECISIONS.md` **Decision #54**
> 治理任务书：`docs/tasks/governance-agent-runtime-frontend-design-freeze.md`（GOV-ARUX1）
> 日期：2026-08-18
>
> 本文件冻结**目标架构**，不描述已上线系统。当前实际运行的会话入口仍是
> **P7-UX1 existing chat control layer**；DeepSeek Harness 尚未进入本项目生产。

---

## 1. 背景与设计动机

Research OS 当前由 P7-UX1（薄 ChatService + Dashboard）承担会话入口：用户通过本地
loopback 页面输入自然语言，Chat 层生成 Public Request Draft，最终统一进入
`Orchestrator.execute()`。该入口已完成独立验收（PASS / INDEPENDENTLY ACCEPTED），
但它是**薄会话网关**，不具备 Agent Loop、durable session、Skill 发现、Tool 调度、
goal continuation 等 Agent 运行时能力。

长期目标不是无限扩张这个薄 ChatService，而是：

1. 引入一个负责 Conversation / Agent Loop / Session / Skill orchestration 的
   Agent Runtime；
2. 让 Research OS 继续保有 Data / Evidence / PIT / Financial / Graph / Workflow
   Authority；
3. 通过 MCP 作为两者之间的首选 capability boundary；
4. 明确区分 Skill / Tool / Workflow，并冻结 Memory 三分法。

本架构只回答"未来怎么长"，不回答"现在改了什么"。P7-D4 及其后续实施不受本冻结影响。

## 2. 当前 P7-UX1 架构和限制

当前实现（只读事实，来自 `src/research_os/dashboard/*` 与 P7-UX1 taskbook）：

```text
用户自然语言 / 已选场景
→ 场景 Chat Schema（additionalProperties: false）
→ Public Request Draft（LLM 只写用户语义字段）
→ 确定性实体 / 行业 / 时间解析（唯一精确匹配）
→ Minimal Public Request
→ Orchestrator.execute()（唯一执行权威）
→ Runner.validate_request()
→ Formal Persisted Request / Run / ScenarioExecutionResult
```

限制：

- session 仅在进程内存保存（最多 20 轮 / 128 sessions），服务退出即消失；
  无 durable session、无 conversation 数据表、无 migration；
- Chat 层不是第二个 Orchestrator、研究管线、Evidence authority、实体 authority、
  时间 authority、Graph writer 或投资顾问；
- 每轮 Flash 预算固定（route≤1、extract≤1、total≤2，Pro=0）；
- 只有"LLM 理解自然语言"与"Research Live 数据"两个独立 gate，无 Skill / Tool 概念；
- 单轮短对话，不跨轮维护研究目标状态（除进程内存 session 外）。

## 3. Target Architecture

```text
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
```

## 4. Harness / Research OS Authority 矩阵

| 领域 | Owner | 说明 |
|---|---|---|
| Conversation / durable session / Agent Loop / context / goal continuation | **DeepSeek Harness** | Agent 运行时职责 |
| Skill discovery / loading / Tool selection | **DeepSeek Harness** | 只做"选什么" |
| Entity identity / Security-Company mapping | **Research OS** | 唯一权威 |
| as_of / PIT eligibility | **Research OS** | 唯一权威 |
| Data Requirement / Readiness / Gap / Acquisition Plan | **Research OS** | 唯一权威 |
| Source selection / Source Router / Collector authorization | **Research OS** | 唯一权威；Agent 不得直选来源 |
| RawItem / Evidence / Claim / structured research objects | **Research OS** | 唯一权威 |
| FinancialReport / FinancialFact / deterministic financial computation | **Research OS** | 唯一权威 |
| Document authority | **Research OS** | 唯一权威 |
| Research Workflow / Research status / Validator | **Research OS** | 唯一权威 |
| Knowledge Graph state / review / approval / deterministic apply | **Research OS** | 唯一权威 |
| Report artifact / business idempotency | **Research OS** | 唯一权威 |
| Agent model profile / Agent execution event stream | **DeepSeek Harness** | Agent 运行时职责 |

Harness 不得成为第二套：Source Router、Evidence authority、Financial database、
Graph authority、Research workflow authority、entity resolver authority。

## 5. Conversation / Research / Knowledge 三类 Memory

正式冻结三分法：

| Memory | Owner | 内容 | 权限边界 |
|---|---|---|---|
| A. Conversation Memory | DeepSeek Harness Session | 用户和 Agent 最近在讨论什么：当前研究目标引用、用户问题、Agent 回答、tool execution references、report/evidence/entity identifiers、working conversational context | 不得作为 FinancialFact / Evidence / Graph / Research State authority |
| B. Research State | Research OS | 某一次正式研究真正执行了什么：Task / Plan / Request / Run / DataReadiness / Acquisition / structured result / report / audit state | Research OS 持久化权威 |
| C. Knowledge Memory | Research OS SQLite / Evidence / Versioned Graph | 长期可信知识 | Agent Memory 中记得的事实不得自动晋级为 Knowledge Memory |

## 6. Skill / Tool / Workflow 定义

```text
Skill    = Agent 可按需加载的"如何完成某类任务"的方法、说明、约束和能力导航。
Tool     = 具有严格输入输出契约的可执行能力接口。
Workflow = Research OS 中经过正式治理和验收的业务执行程序。
```

禁止三者混用：

- Skill 可以指导 Agent 选择 Tool；
- Skill 不拥有数据库；
- Skill 不拥有 source selection；
- Skill 不得绕过正式 Workflow 的必须步骤；
- 正式 Scenario Skill 调用**一个完整** Research OS Scenario Tool，不得让 Agent 自己
  复制正式 Workflow 的内部业务判定。

示例：

```text
Scenario Skill:  stock-research
Capability Skills: financial-analysis / data-readiness / industry-graph-research /
                   evidence-review
Tools:           get_company_profile / check_data_readiness / get_financial_facts /
                 query_industry_graph / lookup_evidence / acquire_missing_data /
                 run_stock_research
Formal Workflow: Orchestrator.execute("stock_research_report", ...)
```

## 7. Scenario Skills

正式 Scenario Skill 对应现有十个研究场景：

- morning-brief（每日晨报）
- abnormal-move-analysis（异动分析）
- stock-research（个股研报）
- evening-brief（每日晚报）
- daily-review（每日复盘）
- stock-review（个股复盘）
- industry-research（行业研究）
- theme-discovery（主题发现）
- earnings-expectation（财报预期）
- first-coverage（首次覆盖）

正式 Scenario Skill 可以调用一个完整 Research OS Scenario Tool（如
`run_research_scenario`），不得让 Agent 自己复制正式 Workflow 的内部业务判定。

## 8. Capability Skills

用于开放式研究和组合式交互：

- financial-analysis（财务分析）
- data-readiness（数据就绪）
- document-research（文档研究）
- evidence-review（证据复核）
- graph-research（图谱研究）
- company-profile（公司画像）
- acquisition-guidance（补数引导）

## 9. MCP Tool Surface

首选方向：

```text
Python application/control plane
  ↓ Python SDK / JSON-RPC
DeepSeek Harness Runtime

Harness Tool Execution
  ↓ MCP
Research OS MCP Server
  ↓
Existing Research OS services
```

- **Python SDK / JSON-RPC**：主要用于启动、驱动、恢复和观察 Harness Agent Runtime；
- **MCP**：主要作为 Harness → Research OS 的 capability boundary。

第一版 MCP 业务语义 Tool surface：

```text
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
```

PROHIBITED（第一版不得暴露低级 Collector）：

```text
cninfo_fetch_direct
nbs_fetch_direct
sina_fetch_direct
```

Graph 边界：

```text
query_graph:            ALLOW
propose_graph_change:   ALLOW（未来须独立授权）
approve_graph_change:   DENY
apply_graph_change:     DENY
```

Source 边界：

```text
acquire_missing_data:        通过现有 Acquisition / Router
direct_source_selection_by_agent: DENY
```

## 10. Model ownership

第一阶段允许双层模型控制：

- Agent-facing LLM：DeepSeek Harness；
- Formal Research Workflow internal LLM：existing `research_os.llm`。

保留当前已验收的：LlmClient、Provider Factory、Flash → Pro business escalation、
budget、validation、fallback、audit。P8-A0 不得顺便删除/重写 existing LlmClient。
未来如统一 provider/profile，必须另立 Decision + taskbook。

## 11. Security / permission model

生产 Research Agent Profile 目标默认：

```text
bash:                   OFF
filesystem_write:       OFF
editor:                 OFF
arbitrary_subprocess:   OFF
direct_network:         OFF（除非通过受治理 Research OS capability）
Research OS MCP:        ON
Skill:                  ON
Goal:                   ON
Evidence read:          ON
Graph query:            ON
Graph direct write:     OFF
```

所有权限 fail closed。Harness coding-agent 默认配置不得直接复制到 Research OS
产品环境。

## 12. Session persistence / privacy

Harness durable session 与 Research OS audit 分离。

Agent Session 可以保存：

- 用户对话
- assistant responses
- tool call metadata
- bounded structured tool results
- Research OS object references

禁止写入 session：

- API key / Authorization header / Cookie / password / credential
- 未经允许的完整网页正文
- 被 source storage policy 禁止长期保存的全文
- CNINFO transient PDF bytes
- 其他 governed full document blobs

Research Tool 返回 Harness 的内容优先为：

```text
structured value + bounded summary + object/evidence/reference IDs
```

而不是把整个官方 PDF / 网页正文塞进 Agent history。

生产 Session retention / encryption / cleanup policy：P8-A0 先验证，正式上线前
单独冻结。

## 13. Graph governance boundary

- Agent 只允许 `query_graph`（只读）与 `propose_graph_change`（未来独立授权）；
- `approve_graph_change` / `apply_graph_change` 对 Agent **DENY**；
- 前端/Agent 任何批准动作仍必须经过：Review Contract → Validator →
  Deterministic Apply；
- 在 Phase 6.1 / future integration 未授权时，不得出现"AI 自动更新图谱"开关；
- Research OS 继续拥有 Graph state / review / approval / deterministic apply
  的唯一 authority。

## 14. Data acquisition governance boundary

- Agent 不得直接选择 source；`direct_source_selection_by_agent: DENY`；
- `acquire_missing_data` 必须通过现有 Acquisition / Router；
- Agent 不得绕过 Source Router / Evidence / PIT / Graph Validator；
- "连接正常 / probe 成功" ≠ "业务充分（BUSINESS_SUFFICIENT）"；
- 任何 capability 晋级继续走正式治理（REGISTERED → PROBED → ADAPTER_IMPLEMENTED
  → WORKFLOW_WIRED → BUSINESS_SUFFICIENT）。

## 15. Transition strategy

```text
P7-UX1（当前生产会话入口，保留运行）
  ↓
P7-D4 完成 + 独立验收 + 合并（不受本冻结影响，按 D4 taskbook 恢复）
  ↓
P8-A0 DeepSeek Harness Integration Spike（最小范围，见下）
  ↓
P8-A0 独立架构验收
  ↓
再决定 Harness production adoption
```

Spike 成功前 P7-UX1 不下线。任何 UI / API implementation 需要独立 taskbook。

## 16. P8-A0 Spike

前置条件：P7-D4 **PASS + INDEPENDENTLY_ACCEPTED + MERGED**。

最小范围：

```text
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
```

验证会话：

```text
用户："研究一下宁德时代"
  → 识别 / Tool / 正式 scenario

用户："刚才这个公司的现金流怎么样？"
  → 同 session 保留目标上下文

用户："产业链上有什么风险？"
  → query graph

用户："再和亿纬锂能比较一下"
  → 新增第二 target，但不得污染第一 target authority
```

## 17. Harness version pinning / upgrade policy

- upstream：`deepseek-ai/deepseek-harness`
- 当前采用状态：**Developer Preview dependency candidate**
- 不允许自动跟 latest；
- 正式 Spike 必须 pin SDK/runtime exact version；
- SDK 与 runtime-bin 必须同版本；
- 升级必须走 compatibility test；
- breaking change 不得直接进入生产；
- Harness 不成为 Research OS 数据契约 authority。

## 18. Explicit non-goals

- 本架构不是 Agent Runtime 实施任务，不是前端 Coding 任务，不是 P7-D4 实施任务；
- 本架构不授权：安装 Harness、MCP 化、Skill 化、重构 Orchestrator / ChatService /
  LlmClient、修改模型 routing、扩大 source/graph scope、修改 DB schema、新增 migration；
- Harness 不成为第二套 Source Router / Evidence authority / Financial database /
  Graph authority / Research workflow authority / entity resolver authority；
- P7-D4 恢复后继续严格按当前 D4 taskbook 完成（**P7-D4 IS UNAFFECTED**）；
- D5 不得因为本设计自动开始。

## 19. Current status matrix

| 项 | 状态 |
|---|---|
| DeepSeek Harness candidate | **SELECTED** |
| Harness dependency | **NOT_INSTALLED** |
| Harness production runtime | **NOT_IMPLEMENTED** |
| Persistent agent session | **NOT_IMPLEMENTED** |
| Research OS MCP server | **NOT_IMPLEMENTED** |
| Scenario Skills | **NOT_IMPLEMENTED** |
| Capability Skills | **NOT_IMPLEMENTED** |
| P7-UX1 existing chat | **CURRENT** |
| Research OS authority | **CURRENT / MUST REMAIN** |
