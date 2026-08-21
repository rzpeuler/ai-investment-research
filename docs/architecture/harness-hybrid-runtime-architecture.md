# Harness Hybrid Runtime Architecture（DeepSeek Harness）

> 状态：**DESIGN FROZEN / NOT IMPLEMENTED**
> 治理依据：`docs/project-state/DECISIONS.md` **Decision #80**
> 任务书：`docs/tasks/p8-arch-001-harness-hybrid-runtime-architecture-freeze.md`
> 日期：2026-08-21
>
> 本文件冻结**目标架构**，不描述已上线系统。当前实际运行的会话入口仍是
> **P7-UX1 existing chat control layer**（IN_MEMORY_ONLY）；DeepSeek Harness
> 尚未进入本项目生产。

---

## 1. 背景与设计动机

P8-A0 技术集成与 P8-B 设计均已独立验收；P8-B2 阶段完成实际验证后发现：
Harness **不适合作为默认严格结构化研究生成 Runtime**（benchmark：
Harness schema_valid_rate = 0.10，Legacy = 0.90，P8-B3 门槛 0.70 NOT_MET）。
因此架构从"Harness 作为 Agent Runtime 基座 + 全量研究运行"调整为
**Hybrid Agent Runtime Architecture**：

- Harness 定位为 **Agent Orchestration Runtime**（会话 / 目标 / Skill / Tool /
  探索工作流）；
- Research OS 定位为 **Research Intelligence Authority**（身份 / 就绪 / 采集 /
  证据 / PIT / 图谱 / 工作流 / Validator / 报告）；
- 严格结构化生成继续走 Legacy（`research_os.llm`）路径。

本文件与 `agent-runtime-skill-architecture.md`（Decision #54）的关系：
#54 冻结的是"Agent Runtime / Skill / MCP 顶层目标架构"，本文件在 #54 基础上
**明确 Hybrid 运行时边界**（Harness 不承担结构化生成默认 runtime），二者
不冲突；#54 的 Authority / Memory / MCP / Skill / Tool / Security 边界全部
保留并继承。

## 2. Harness 定位（Agent Orchestration Runtime）

### 2.1 负责

- **Conversation**
- **Durable Session**
- **Goal Management**
- **Skill Loading**
- **Tool Scheduling**
- **Exploration Workflow**（开放多轮研究探索、自由文本/笔记产出、工具调用）

### 2.2 不负责（明确禁止）

- Financial Authority（财务权威）
- Evidence Authority（证据权威）
- Knowledge Authority（知识权威）
- Structured Artifact Validation（结构化产物的 schema 校验与把关）

Harness 不得成为第二套 Source Router / Evidence authority / Financial database /
Graph authority / Research workflow authority / entity resolver authority。

## 3. Research OS 定位（Research Intelligence Authority）

Research OS 继续拥有并唯一承担：

- Company identity
- DataReadiness
- Acquisition
- FinancialFact
- Evidence
- PIT（point-in-time / as_of）
- Industry Graph
- Research Workflow
- Validator
- Report Generation

## 4. LLM 边界

保留 `research_os.llm`，继续负责：

- Structured Generation
- Schema Validation
- Budget Control
- Audit
- Fallback

### 4.1 第一阶段允许

- **Harness Agent LLM**（会话 / 探索 / 工具编排）
- 与
- **Research Workflow LLM**（`research_os.llm` 结构化生成）

**并存**。

### 4.2 禁止

- **因为接入 Harness 而重写 LlmClient**。
- 删除 / 绕过已验收的 Provider Factory、Flash→Pro business escalation、
  budget、validation、fallback、audit。

## 5. MCP 边界

冻结目标拓扑：

```text
Harness
  ↓
MCP
  ↓
Research OS Tools（Research OS Tool Boundary）
```

Harness 不得直接访问：

- Data Source（数据源）
- Collector（采集器）
- Database（数据库）
- Graph Write（图谱写入）

所有能力必须经过 **Research OS Tool Boundary**（`research-os-mcp/v1`），
即通过受治理的业务语义 Tool 暴露，而非暴露低级 Collector / SQL / 直写接口。

## 6. Skill 定义（冻结）

```text
Skill = 能力说明 + 工作方法 + Agent routing metadata。
```

Skill **不是**：

- 业务代码；
- 数据 Authority；
- Validator。

Skill 可以指导 Agent 选择 Tool；Skill 不拥有数据库、不拥有 source selection、
不得绕过正式 Workflow 的必须步骤。

## 7. Tool 定义（冻结）

```text
Tool = 可执行、受治理能力接口。
```

允许（示例）：

- `get_company_profile`
- `check_data_readiness`
- `query_industry_graph`

限制（示例）：

- `apply_graph_change` — DENY
- `direct_data_source_access` — DENY
- `approve_graph_change` — DENY
- `collector_execute` / `sql_query` — DENY

## 8. Memory 边界（继承 #54 三分法）

| Memory | Owner | 内容 | 权限边界 |
|---|---|---|---|
| A. Conversation Memory | Harness Session | 当前研究目标引用、用户问题、Agent 回答、tool execution references、object/evidence/entity identifiers、working conversational context | 不得作为 FinancialFact / Evidence / Graph / Research State authority |
| B. Research State | Research OS | Task / Plan / Request / Run / DataReadiness / Acquisition / structured result / report / audit state | Research OS 持久化权威 |
| C. Knowledge Memory | Research OS SQLite / Evidence / Versioned Graph | 长期可信知识 | Agent Memory 中记得的事实不得自动晋级为 Knowledge Memory |

## 9. 运行时选择（继承 P8-B2-R6 Task Runtime Suitability Model）

```text
output_contract == strict_schema  →  LEGACY_ONLY（默认、冻结、唯一）
needs_tools or needs_multi_turn   →  HARNESS_CANDIDATE（governance 白名单）
其他                              →  LEGACY_ONLY
```

HYBRID 表达为"任务内两阶段"：

```text
Phase A（探索 / 理解）— HARNESS（agentic、工具、多轮、自由文本）
Phase B（结构化成稿）— LEGACY（单轮、严格 schema）
```

- Phase A 输出不得进入 Claim / ResearchFinding 等权威对象；
- Phase B 走既有 LlmOutputValidator（唯一质量判断来源）；
- 详见 `docs/architecture/harness-task-runtime-routing-design.md`。

## 10. Current status matrix

| 项 | 状态 |
|---|---|
| HARNESS_ARCHITECTURE | **DESIGN_FROZEN** |
| HARNESS_IMPLEMENTATION | **NOT_IMPLEMENTED** |
| PRODUCTION_ACCEPTANCE | **NO** |
| DeepSeek Harness candidate | SELECTED |
| Harness production runtime | NOT_IMPLEMENTED |
| Persistent agent session | NOT_IMPLEMENTED |
| Research OS MCP server | NOT_IMPLEMENTED（仅 P8-B1 foundation 授权 2 只读工具） |
| Scenario Skills / Capability Skills | NOT_IMPLEMENTED |
| P7-UX1 existing chat | CURRENT / LEGACY FALLBACK / IN_MEMORY_ONLY |
| Research OS authority | CURRENT / MUST REMAIN |

## 11. Transition strategy

```text
P7-UX1（当前生产会话入口，保留运行）
  ↓
P7-D4 完成（已完成：IMPLEMENTED / ACCEPTED / MERGED，2026-08-19）
  ↓
P8-A0 Hybrid Agent Runtime Spike（最小范围，另行授权）
  ↓
P8-A0 独立架构验收
  ↓
再决定 Harness production adoption
```

Spike 成功前 P7-UX1 不下线。任何 UI / API implementation 需要独立 taskbook。

## 12. Explicit non-goals

- 本文件不是实施任务；不授权安装 Harness / MCP 化 / Skill 化 / 重构
  Orchestrator / ChatService / LlmClient / 修改模型 routing / 修改 DB schema /
  新增 migration；
- 不授权 runtime 切换（默认 runtime 保持 legacy）；
- 不扩大 source/graph scope；
- P7-D4 范围不变（D4 已完成验收，不受本冻结影响）。

## 13. 与旧设计（#54）的差异

| 维度 | #54 旧设计 | 本文件（Hybrid） |
|---|---|---|
| Harness 定位 | Agent Runtime 基座（Agent Loop / Session / Skill / Goal / Tool / MCP） | Agent Orchestration Runtime；**不承担默认严格结构化生成** |
| 结构化生成 runtime | 未明确默认 | **LEGACY_ONLY**（0.90 vs Harness 0.10） |
| 会话 / 探索 | Agent 运行时职责 | Agent 运行时职责（保留） |
| Research OS authority | 唯一权威 | 唯一权威（保留，明确列全） |
| LLM | 双层并存 | 双层并存（明确禁止重写 LlmClient） |
| MCP | capability boundary | capability boundary（明确 Harness 不得直连 Data Source / Collector / DB / Graph Write） |
| Skill / Tool | 定义 + 禁止混用 | Skill=能力说明+工作方法+routing metadata；Tool=可执行受治理接口（示例 allow/deny 固化） |
| Memory 三分法 | 已冻结 | 继承不变 |

本文件与 #54 不冲突：#54 冻结 Agent Runtime 顶层目标，本文件在其上**冻结
Hybrid 运行时边界与定位**。所有 Authority / Memory / MCP / Skill / Tool /
Security 边界继承。
