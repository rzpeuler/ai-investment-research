# Harness Generation Control Architecture Design

STATUS: DESIGNED / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-B2-R5-HARNESS-GENERATION-CONTROL-ARCHITECTURE-DESIGN
（设计任务：不实现代码；为 P8-B3 工程开发提供决策依据）

## 1. 当前架构问题分析

### 1.1 实证基线（R3/R4，4 次真实 benchmark）

- schema_valid_rate 稳定约 **0.4-0.5**（R3 结构为测量最优）；目标 0.70 未达；
- 失败集中于 research_finding_generation 类复杂 schema 的**必填字段缺失**
  （finding_id 等 20 个必填字段各 ×5 cases — R4 missing_field_stats）；
- Prompt 层优化（Schema Context / Slice / Checklist / Self Validation）实证
  收敛：checklist/自检**系统性回归**（0.2×2），继续增加 Prompt 信息无法稳定
  提升结构遵循率。

### 1.2 根因

当前流程为**单次一次性生成**：

```text
Task Definition → Prompt Builder → LLM Generation → Schema Validator
```

LLM 一次性生成 20+ 必填字段的复杂 JSON 时：必填字段遗漏、字段覆盖不足、
内容正确但结构失败。瓶颈已从 **Prompt Layer** 转移至 **Generation Control
Layer**（生成过程的控制能力，而非提示内容）。

### 1.3 可复用的既有能力

Schema Contract（冻结）、Validator（冻结，产出字段级错误）、Normalizer
（冻结）、Benchmark Runner、**Failure Field Tracking（R4 已产出字段级
缺失统计 — 直接可作为修复输入）**、LlmClient 预算/审计/回退（唯一 AI 入口）。

## 2. 目标架构

```text
Task Definition
      ↓
Generation Controller        ← 新增（协调生成/校验/修复；预算与证据权威仍在 LlmClient）
      ↓
Provider Adapter（Harness / legacy）   ← 扩展（可选 JSON-mode 结构化输出）
      ↓
LLM Generation（pass 1）
      ↓
Validation Layer（既有 LlmOutputValidator，不变）
      ↓
[结构不完整?] → Repair Layer（基于字段级错误构造修复 prompt）
      ↓  （有界迭代，预算内）
LLM Generation（repair pass）
      ↓
Validation Layer（终验）
      ↓
最终输出（valid → artifact；仍失败 → 诚实 fallback）
```

### 2.1 Generation Controller

- 职责：执行 generate → validate → repair 循环；维护每任务生成状态
  （pass 数、修复轮数、token 用量、字段缺失历史）；遵守 LlmClient 预算。
- 位置：作为 **provider 包装层**（`GenerationControlledProvider` 实现
  LlmProvider 协议），使 LlmClient 的预算 / 审计 / 降级 / 单入口语义不变。
- 修复预算：每任务 max_repair_passes（建议 2），计入 provider 调用与 token
  预算（与 LlmClient flash 重试语义对齐，无隐藏重试 — 修复轮次在审计中
  显式记录）。

### 2.2 Validation Layer

- 复用既有 `LlmOutputValidator`（**不改**）；新增**结构化错误提取**：
  从 validator 错误串解析字段级问题（missing_required / enum / format —
  R4 已实现分类，扩展为修复输入）。

### 2.3 Repair Layer

- 输入：原始任务 prompt + 部分输出对象 + 字段级验证错误 + 证据；
- 输出：确定性修复 prompt（要求模型**基于证据**补齐缺失字段，禁止虚构
  证据引用；只修结构/字段，不重复完整生成 — 缩小修复面）；
- 规则：修复后的输出仍必须通过同一 Validator；仍失败 → 下一轮或诚实回退。

### 2.4 Provider Adapter

- 既有 `HarnessLlmProvider` / legacy 直连不变；
- 新增能力探测：dsh/Harness 是否支持结构化输出（如 DeepSeek
  response_format json_object — legacy 路径 0.8-0.9 的关键差异）。若 Harness
  profile 可配置 → 通过 profile 启用（治理决策）；否则 repair loop 独立生效。

## 3. 数据流设计

```text
Task(request, schema, evidence)
  → GenerationController.initialize(task_state)
  → pass N prompt = build_harness_prompt(task, schema, evidence[, partial, errors])
  → provider.complete_json(prompt)
  → validator.validate(output)  [既有路径]
  → errors 为空 → 完成（validated artifact）
  → errors 非空 且 修复预算未耗尽 → repair_prompt = build_repair_prompt(partial, errors, evidence)
  → 循环（max_repair_passes）
  → 仍失败 → 返回 provider 层错误（LlmClient 按既有语义 fallback）
```

每 pass 记录：pass_index、repair_round、token 用量、errors（字段级）、
状态 — 全部进入审计（provider usage / validation_errors 既有载体）。

## 4. 状态管理设计

- 每任务生成状态（in-memory，进程内）：
  `task_state = {request, schema, evidence, partial_output, rounds, field_missing_history, tokens}`；
- 跨任务无共享状态（与 trial 会话隔离语义一致）；
- 状态不进 DB（生成过程是瞬时控制面状态）；审计记录保留在
  llm_call_records（既有）。

## 5. Failure Recovery 机制

| 失败 | 处理 |
|---|---|
| provider 超时/不可用 | 既有 typed 错误 → LlmClient fallback（不变） |
| 修复轮次耗尽 | 诚实 fallback（schema_valid=False，无伪造 MODEL_INFERENCE） |
| 预算超限 | LlmClient 预算拦截（repair 计入调用预算） |
| 修复引入新错误 | 终验失败 → fallback；不无限循环 |
| secret 泄露 | 既有 secret 扫描机制（修复 prompt 不含原始输出值 — 用字段级错误而非原始文本） |

## 6. 与现有 Schema / Validator / Normalizer 兼容方案

- Schema Contract：**冻结不变**；repair 只补字段，不改变 schema 语义；
- Validator：**不改**；其字段级错误输出是 repair 的输入（R4 已建）；
- Normalizer：**不改**；normalizer 先于 validator 生效（现状），repair 在
  validator 之后；
- LlmClient：**不改**；controller 是 provider 层包装，预算/审计/降级单入口
  保持；
- Benchmark：**不改 threshold**；新增"repair 轮数 / 每任务调用数"指标。

## 7. 方案比较（≥3）

### 方案 A — Multi-pass generation（分解生成）

- 思路：把复杂对象拆成多次小生成（core 字段 → 补充字段），确定性合并。
- 优点：每次生成面小，单 pass 结构遵循率更高；
- 缺点：pass 间一致性风险；调用数 ×2-3；合并逻辑复杂度；对 20 字段对象
  收益需验证；
- 成本：每任务 2-3 次 provider 调用。

### 方案 B — Validator-driven repair loop（校验反馈修复）

- 思路：先生成完整对象 → validator 字段级错误 → 有界修复轮次补全。
- 优点：直接消费 R4 字段级统计；修复面小（只补缺失字段）；调用数 1+k
  （k≤2）；与既有 fallback/预算语义对齐；实现面最小；
- 缺点：修复不收敛风险（有界兜底）；修复值质量依赖模型（证据锚定约束）；
- 成本：每任务 1-3 次 provider 调用。

### 方案 C — Provider structured-output enforcement（传输层 JSON 模式）

- 思路：启用 provider 结构化输出（response_format json_object / JSON
  schema mode）— legacy 路径 0.8-0.9 的关键差异。
- 优点：若可用，最直接；结构层强制；
- 缺点：**需 Harness/profile 变更**（治理决策）；dsh rc.7 支持度未知（需
  探测）；不解决"字段缺失"（JSON 模式保证合法 JSON，不保证必填字段完整 —
  实测 legacy 仍有 1-2 个字段级失败）。

### 推荐：方案 B（核心）+ 方案 C（探测互补）

理由：

1. 直接针对实测失败模式（字段缺失 → 字段级修复）；
2. 完全在既有边界内实现（provider 包装层；Schema/Validator/Normalizer/
   LlmClient 不变）；
3. 有界成本（≤3 调用/任务）与既有预算/审计/降级语义对齐；
4. C 作为互补：若 Harness JSON-mode 可启用（治理决策），先解决
   json_format_failure 类，B 解决 missing_required_field 类 — 两类叠加有望
   覆盖 0.4-0.5 → 0.7 的差距；A 作为 research_finding 极端场景的 fallback
   备选。

## 8. 开发阶段拆分

| 阶段 | 内容 | 依赖 |
|---|---|---|
| R5-A | GenerationController + Repair Layer（provider 包装）+ 字段级错误提取 + 离线测试（fake provider） | 本设计验收 |
| R5-B | Harness JSON-mode 探测（profile 支持度）+ 结构化输出适配（治理决策） | R5-A |
| R5-C | Multi-pass 分解（仅 research_finding 类复杂 schema，若 B 不足） | R5-A/B 实测 |
| R5-D | Benchmark 重跑（新增 repair 指标）+ P8-B3 评估 | R5-A/B/C |

## 9. 对现有系统影响

- 生产路径：无影响（controller 为 opt-in provider 包装，默认 legacy 不变）；
- 审计：llm_call_records 增加 repair 轮次/字段缺失历史（usage_metadata 扩展，
  向后兼容）；
- 预算：每任务调用数 1→≤3（计入既有 provider 调用与 token 预算）；
- 风险（如实）：修复轮次可能不收敛（有界兜底 + 诚实 fallback）；修复内容
  质量依赖模型（证据锚定 + validator 终验 + Research OS authority 不变）；
  成本增加（≤3×，benchmark 跟踪）；Harness JSON-mode 支持度未知（R5-B
  探测决定 C 可行性）。

## 10. 验收与下一步

- 本设计可实施、不破坏 Schema 体系、可指导 P8-B3 开发；
- 下一阶段建议：Sol 验收本设计 → R5-A 实现 taskbook（Generation
  Controller + Repair Layer + 测试）→ R5-D benchmark 重跑评估。
