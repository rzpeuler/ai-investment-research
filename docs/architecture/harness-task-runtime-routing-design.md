# Harness Task Runtime Routing Design

STATUS: DESIGNED / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-B2-R6-HARNESS-GENERATION-STRATEGY-EVALUATION
（设计任务：不实现代码；为 P8-B3 决策提供任务级 Runtime Selection 架构）

## 1. 背景与问题

P8-B2-R5-D 实证：Harness schema_valid_rate 0.10 vs legacy 0.90（同一 corpus，
`reports/harness_benchmark_r5d.json`）。结论：Harness 不适合作为默认生产
结构化生成 runtime。但 Harness 在 agentic 探索 / 工具 / 多轮 / 自由文本领域
存在 Legacy 不具备的能力。因此需要**任务级 Runtime Selection**，而非全局
二选一。

## 2. 设计目标

1. 在 LlmClient 单入口 / 预算 / 审计 / 降级语义不变的前提下，提供任务级
   runtime 选择；
2. 默认保守：所有任务默认 `LEGACY_ONLY`；
3. 选择可审计、可治理、确定性（非 LLM 决策）；
4. 不修改 schema / validator / normalizer / threshold / provider；
5. 为未来 Hybrid（探索→成稿两阶段）预留架构位置。

## 3. 核心模型：Task Runtime Suitability Model

### 3.1 任务分类维度（每 LLM 任务注册表新增元数据，向后兼容）

| 维度 | 取值 | 说明 |
|---|---|---|
| `task_type` | extraction / normalization / reasoning / generation | 认知负载分类 |
| `output_contract` | strict_schema / free_text / notes | 产出契约（是否必须通过 schema 校验） |
| `needs_tools` | bool | 是否声明 MCP 工具依赖 |
| `needs_multi_turn` | bool | 是否需要多轮上下文累积 |
| `governance_flag` | HARNESS_ENABLED (bool) | per-task 治理白名单（默认 false） |

### 3.2 决策规则（确定性）

```text
if output_contract == strict_schema:
    runtime = LEGACY_ONLY            # 默认、冻结、唯一选择
elif needs_tools or needs_multi_turn:
    runtime = HARNESS_CANDIDATE      # 仅当 governance_flag=true 生效
else:
    runtime = LEGACY_ONLY
```

- HYBRID 由 Orchestrator 层表达：把任务拆成 Phase A（Harness，free_text）
  + Phase B（Legacy，strict_schema），每个 phase 单独走上述规则。
- 禁止在 provider 层做隐式选择；选择写入 audit。

## 4. 组件设计

```text
Task Definition（含 task_type / output_contract / needs_tools /
                needs_multi_turn / governance_flag）
      ↓
Task Runtime Router（确定性决策，基于 3.2 规则 + 治理策略表）
      ↓
runtime_selection ∈ {LEGACY_ONLY, HARNESS_CANDIDATE, HYBRID}
      ↓
LlmClient（单入口不变）→ 选定 provider（legacy 直连 / Harness opt-in）
      ↓
Validator（唯一质量判断来源，不变）
```

### 4.1 Task Runtime Router

- 位置：在 Orchestrator / 调用方与 LlmClient 之间的**决策层**（不是 provider
  包装层，也不是 LlmClient 内部）— 使 runtime 选择先于 LlmClient 注入。
- 输入：任务元数据 + 治理策略表；
- 输出：`runtime_selection` + 依据（一个 dict，供 audit 记录）；
- 确定性：纯函数，无 LLM 调用，无隐式重试；
- 降级：策略表加载失败 / 元数据缺失 → 保守回退 `LEGACY_ONLY`。

### 4.2 治理策略表

- 形式：配置工件（如 `config/llm_runtime_policy.yaml`），由 Sol 授权维护；
- 内容：per-task 白名单 `{task_name: {runtime, governance_flag, note}}`；
- 约束：修改策略表需独立 taskbook + Sol 授权；默认全部 `LEGACY_ONLY`；
- 校验：策略表通过既有 schema 校验器加载（新增 schema 属后续 taskbook，
  本设计不实现）。

### 4.3 Audit 扩展

- LlmClient 审计记录（llm_call_records）增加：
  `runtime_selection`（legacy | harness | hybrid）+ `runtime_selection_reason`
  （如 `output_contract=strict_schema`）；
- 向后兼容：新增字段，旧记录不填。

## 5. 与既有架构的兼容

| 既有组件 | 变化 |
|---|---|
| LlmClient | 不变（单入口语义保持） |
| HarnessLlmProvider / DeepSeekChatCompletionsProvider | 不变 |
| GenerationControlledProvider（R5-A） | 不变（可继续作为 harness 路径的包装层） |
| Schema / Validator / Normalizer | 不变（冻结） |
| EVAL-001 threshold 0.70 | 不变 |
| 默认 runtime | 不变（legacy） |

## 6. 与 P8-B3 的关系

- 本设计**不授权**任何 production routing 修改；仅提供决策模型与规则。
- P8-B3 结构化生成默认路径维持 legacy；Harness 生产采用仅限白名单探索类任务，
  且需独立 taskbook 授权。

## 7. 验收与下一步

- 本设计满足：有数据依据（R5-D 0.10 vs 0.90）、有 tradeoff 分析（§11 报告）、
  有明确建议（LEGACY_ONLY / HARNESS_CANDIDATE / HYBRID）。
- 实现不在本任务范围；如需实现，另立独立 taskbook。
