# P8-A1 Hybrid Agent Runtime Pilot Design

STATUS: DESIGNED / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN
（设计任务：不实现代码；建立 Hybrid Agent Runtime 生产试点使用规范）

## 1. 目标与范围

在 P8-ARCH-001（Hybrid Architecture Freeze）与 P8-A0（Spike）实证基础上，设计
DeepSeek Harness 在 Research OS 中的**生产试点方案**：

1. 建立 Hybrid Agent Runtime 使用规范；
2. 明确 Harness 能做什么 / 不能做什么 / 如何治理 / 如何进入后续生产试点；
3. 输出确定性 Runtime Router、Permission Model、Session Governance、Audit
   Boundary、Pilot Acceptance Criteria。

### 1.1 范围（允许 / 禁止）

| 允许 | 禁止 |
|---|---|
| architecture docs | 默认 runtime 切换 |
| governance docs | 删除 Legacy |
| pilot plan | 修改 LlmClient |
| | 修改 Schema |
| | 修改 Validator |

本任务不改变任何运行路径；默认 runtime 保持 legacy；Harness 保持 opt-in。

### 1.2 实证基线（数据依据）

- P8-A0 Spike：Harness SDK / durable session / skill discovery / MCP tool
  invocation / authority boundary 全部验证通过（4-turn 连续会话，4 Tool 调用，
  unauthorized=0，secret=0）。
- P8-B2：Harness 不适合严格 Schema Artifact 生成（schema_valid_rate 0.10 vs
  legacy 0.90；json_format 主导；无 provider 级结构化输出支持）。
- LIVE-01 RESUME-03：Harness 会话可靠性 20/20、0 drift、0 leak；但 agentic
  延迟显著（p50 6.2s、单回合 24-44k tokens）。
- P8-A0 观察：180s turn 超时下第 2 turn 触发 TURN_TIMEOUT → 300s 全部完成
  （agentic 延迟需充足 turn 预算）。

### 1.3 核心原则

```text
Exploration                       →  Harness（Agent Orchestration Runtime）
Structured Research Output        →  Legacy（research_os.llm 严格 schema 路径）
```

Hybrid = 探索（Harness）与成稿（Legacy）按任务类型分离；**不是**全局二选一。

## 2. Task Classification

按任务认知负载与产出契约分为两类（对应 `HARNESS_ALLOWED` / `LEGACY_REQUIRED`）。

### 2.1 HARNESS_ALLOWED（探索类）

候选任务：

- **industry exploration**（行业/产业链探索）
- **research preparation**（研究准备：目标识别、证据收集规划、问题清单）
- **evidence discovery assistance**（证据发现辅助：定位相关证据、归纳关注点）
- **multi-turn analyst assistant**（多轮分析师助手：追问、澄清、比较）
- **hypothesis generation**（假设生成：待验证命题、多空主要矛盾候选）

**要求**：此类任务的输出**不直接成为正式 Research Artifact**（不写入
Claim / ResearchFinding / Catalyst / RiskFactor 等权威对象）；产出为研究笔记 /
问题清单 / 探索性中间结论 / 给 Legacy 的输入素材。

### 2.2 LEGACY_REQUIRED（结构化成稿类）

必须走 Legacy（严格 Validator 把关）的任务：

- **FinancialFact 生成**
- **ResearchFinding 生成**
- **Catalyst / Risk Artifact**
- **Evidence binding**（证据绑定 / 血缘）
- **Final report sections**（研报章节成稿）

**原因**：这些对象必须通过 `LlmOutputValidator` 的严格 schema 校验（research_finding
22 必填字段等）；Harness 在严格 schema 生成上实证 0.10 不可用（P8-B2）。

### 2.3 分类归属（每任务确定性注册，非 LLM 判定）

任务分类作为**任务注册表元数据**（确定性），不在运行时由 LLM 自选。示例：

| 任务 | 分类 | 理由 |
|---|---|---|
| 行业/产业链探索 | HARNESS_ALLOWED | 自由文本探索；不产出正式 artifact |
| 研究准备 / 问题清单 | HARNESS_ALLOWED | 中间产物；给 Legacy 作输入 |
| 证据发现辅助 | HARNESS_ALLOWED | 定位/归纳；不生成权威 Claim |
| 多轮分析师助手 | HARNESS_ALLOWED | 会话上下文；不直接写 artifact |
| 假设生成 | HARNESS_ALLOWED | 候选待验证；非确定事实 |
| FinancialFact 生成 | LEGACY_REQUIRED | 严格 schema + 证据血缘 |
| ResearchFinding 生成 | LEGACY_REQUIRED | research_finding 22 必填字段 |
| Catalyst / Risk Artifact | LEGACY_REQUIRED | catalyst / risk_factor schema |
| Evidence binding | LEGACY_REQUIRED | 血缘确定性 |
| Final report sections | LEGACY_REQUIRED | 报告成稿 + 校验 |

## 3. Runtime Router Design

确定性 Router（**不是 LLM 自行决定**），输入 4 个维度，输出 3 种决策。

### 3.1 输入

| 输入 | 取值 | 来源 |
|---|---|---|
| task_type | exploration / extraction / normalization / reasoning / generation | 任务注册表元数据 |
| output_contract | strict_schema / free_text / notes | 任务定义（schema 名称） |
| risk_level | low / medium / high | 任务注册表 + 治理策略 |
| authority_requirement | read_only / write_artifact / evidence_binding / none | 任务定义 |

### 3.2 决策规则（确定性纯函数）

```text
if output_contract == strict_schema:
    runtime = LEGACY_ONLY            # 默认、冻结、唯一选择
elif task_type == exploration and risk_level in {low, medium}:
    runtime = HARNESS_ALLOWED        # 仅当 governance_flag=true 且白名单内
else:
    runtime = LEGACY_ONLY
```

- **HYBRID** 表达为"任务内两阶段"：Phase A（Harness，free_text / notes）→
  Phase B（Legacy，strict_schema）。由 Orchestrator 层拆解，每个 phase 单独
  走上述规则。
- **拒绝在 provider 层做隐式选择**；选择记录进入 audit（`runtime_selection` +
  依据），无静默切换。
- 默认所有任务 `LEGACY_ONLY`；Harness 仅对显式白名单任务开放
  （governance_flag 默认 false）。

### 3.3 治理约束

- 白名单（per-task runtime policy）是**配置工件**，修改需独立 taskbook + Sol
  授权；不写死在 provider 代码。
- 本设计不新增 provider、不修改 schema / validator / normalizer / threshold /
  LlmClient / 默认 runtime。

## 4. Permission Model

定义 Harness 权限（继承 #54 / #80 的 deny-by-default 边界）。

### 4.1 允许（READ / 探索）

- `get_company_profile`（公司画像读取）
- `query_industry_graph`（图谱只读查询）
- `check_data_readiness`（数据就绪读取）
- （探索辅助）`run_research_scenario` 的 **bounded trigger**：仅校验场景注册并
  返回 task/plan 投影，不执行完整 LLM 管线、不写 DB/图

### 4.2 限制（DENY）

- `graph_write` / `graph_apply` / `graph_approve` / `apply_graph_change`
- `evidence mutation`（Evidence 修改）
- `financial fact creation`（FinancialFact 创建）
- `direct_data_source_access`（数据源直连）/ collector / sql

### 4.3 权限表（确定性）

| 能力 | Harness | Legacy | 说明 |
|---|---|---|---|
| 公司画像读取 | ALLOW | ALLOW | 只读 |
| 图谱查询 | ALLOW | ALLOW | 只读 |
| 数据就绪读取 | ALLOW | ALLOW | 只读 |
| 场景 bounded trigger | ALLOW | — | 只返回 plan 投影 |
| FinancialFact 创建 | DENY | ALLOW | 严格 validator |
| ResearchFinding / Catalyst / Risk 创建 | DENY | ALLOW | 严格 validator |
| Evidence 修改 | DENY | DENY | 血缘权威 |
| Graph 写 / approve / apply | DENY | 治理流程 | 独立授权 |
| 数据源直连 | DENY | 受治理 collector | Research OS 唯一 |
| 报告成稿 | DENY | ALLOW | validator 把关 |

## 5. Session Governance

定义 Harness 会话的生产边界。

### 5.1 Session lifetime

- 每会话有界：max_turns（建议 20，与 #54 一致）、max_active_sessions（128）；
- 空闲超时：idle_session_timeout（建议 1800s）；
- 会话过期/删除：operational 事件，不改变 authority；
- 会话不跨任务共享状态。

### 5.2 Timeout budget（区分三类）

| 超时 | 定义 | 建议预算 | 说明 |
|---|---|---|---|
| **LLM request timeout** | 单次 provider 请求 | 60s（provider_timeout） | 直连层单请求 |
| **Agent turn timeout** | 一个 agentic turn（可能含多工具调用） | **300s**（P8-A0 实测 180s 不足） | agentic loop 预算 |
| **Tool timeout** | 单次 MCP tool 调用 | 30s | 工具调用预算 |

- P8-A0 实证：180s turn 超时在第 2 turn 触发 TURN_TIMEOUT → 300s 后 4 turn 完成。
  生产 turn 预算**必须 ≥300s**，或拆分更小回合。
- 超时分类记录（不得把 agent turn 超时误报为 provider 超时）。

### 5.3 Token budget

- 每任务 / 每会话 token 预算（provider-reported，不推断）；
- 参考 LIVE-01：单回合 24-44k tokens；20 回合 ≈ 480-880k；
- 治理上限按场景配置（如 1M / 会话，继承 BUDGET-DECISION-01 语义）；
- 超限 fail-closed，不静默截断或伪造 usage。

### 5.4 Audit requirements

- 每会话 / 每 turn 记录：session_id、runtime、skill、tool calls、usage、
  latency、authority checks、final artifact source（见 §6）；
- 原始 prompt / response / credential 不落盘（bounded 报告只记 hash / 元数据）。

## 6. Audit Boundary

目标：未来可以回答 **"这个研究结论由哪个 runtime 产生？"**

### 6.1 每任务审计字段

| 字段 | 说明 |
|---|---|
| `runtime_selection` | legacy / harness / hybrid |
| `runtime_selection_reason` | 决策依据（如 output_contract=strict_schema） |
| `harness_session_id` | Harness 内部会话标识（不暴露原始内部 ID） |
| `skill_used` | 本次使用的 skill 名 |
| `tools_called` | 本次 MCP tool 调用清单 |
| `authority_checks` | 权限边界校验结果（unauthorized=0 等） |
| `final_artifact_source` | 最终 artifact 由哪个 runtime 产生（Hybrid 时 Phase B=Legacy） |

### 6.2 血缘规则

- Harness 探索输出（notes / 问题清单 / 假设候选）**不得**直接标注
  MODEL_INFERENCE 或作为 Claim / ResearchFinding 源；
- 只有经 Legacy + Validator 通过的对象才可进入正式 Research State /
  Knowledge Memory；
- Agent Memory 中记得的事实不得自动晋级为 Knowledge Memory（继承 #54）。

### 6.3 可回答性问题

```text
"这条 ResearchFinding 由哪个 runtime 产生？" → final_artifact_source=legacy
"这个假设是模型推断吗？" → harness 探索输出 + MODEL_INFERENCE 标注（若进入 Phase B）
```

## 7. Pilot Acceptance Criteria

进入生产试点的准入条件（P8-A2 实施前 Sol 验收）。

### 7.1 Reliability

| 指标 | 要求 |
|---|---|
| session success rate | ≥ 阈值（建议 ≥0.95，参考 LIVE-01 20/20） |
| session continuity | 100%（same_session_all_turns） |
| cleanup evidence | `process_residue=NO`（机械证明，需 POSIX CI） |
| turn timeout 处理 | 分类记录，无静默失败 |

### 7.2 Governance

| 指标 | 要求 |
|---|---|
| audit completeness | 100%（runtime_selection / session_id / skill / tools / authority / artifact_source） |
| zero unauthorized access | unauthorized_tools = 0 |
| secret leak | 0 |
| validator bypass | 0 |
| authority drift | 0 |

### 7.3 Value

| 指标 | 要求 |
|---|---|
| analyst usefulness | Sol 主观评估（试点任务完成后） |
| exploration quality | 探索输出对 Legacy 成稿的可用率（如 → Phase B 命中率） |
| artifact source clarity | 100% 可回答"由哪个 runtime 产生" |

### 7.4 Cost

| 指标 | 要求 |
|---|---|
| latency | agent turn p95 有界（记录；较 legacy 高为预期，需 budget 覆盖） |
| token usage | provider-reported，≤ 治理上限（如 1M/会话）；不推断 |

### 7.5 准入判定

- 仅当 Reliability + Governance **全过**，且 Value / Cost 记录完整、Sol 认可
  时，才进入 P8-A2 生产试点实施；
- 单项不满足 → 不进入；Harness 保持 opt-in，默认 legacy 不变。

## 8. 与既有架构的兼容

| 组件 | 变化 |
|---|---|
| 默认 runtime | 不变（legacy） |
| LlmClient | 不变（单入口 / 预算 / 审计 / 降级） |
| Schema / Validator / Normalizer | 不变（冻结） |
| EVAL-001 threshold 0.70 | 不变 |
| P8-A0 spike 4-tool MCP facade | 保留为 opt-in；白名单任务经 Router 使用 |
| Task Runtime Router（R6 设计） | 本设计是其在生产试点前的完整规范 |

## 9. 验收与下一步

- 本设计满足：有数据依据（P8-A0 / P8-B2 / LIVE-01）、有 tradeoff 分析、
  有明确建议（HARNESS_ALLOWED / LEGACY_REQUIRED / HYBRID 规则）。
- 下一步建议（P8-A2）：Sol 验收本设计 → 在 POSIX CI 重跑 P8-A0 spike 取得
  `process_residue=NO` → 独立 taskbook 授权 P8-A2（生产试点实施：
  Runtime Router 配置工件 + 权限表落地 + audit 字段扩展 + 试点 corpus）。
- 默认 runtime 保持 legacy；P8-B3 / production adoption 保持 NOT_AUTHORIZED。
