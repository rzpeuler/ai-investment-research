# P8-B2-R6 — Harness Generation Strategy Evaluation

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-B2-R6-HARNESS-GENERATION-STRATEGY-EVALUATION
（评估与设计任务：不实现代码；为 P8-B3 决策提供任务级 Runtime Selection
Strategy）

## 1. 目标与范围

评估 Harness 在 Sol AI 投研系统中的最佳定位，建立任务级 Runtime Selection
Strategy：

- 确定哪些任务适合 Harness；
- 确定哪些任务必须继续使用 Legacy Runtime；
- 提出 Task Runtime Suitability Model 与未来 Hybrid Architecture。

### 1.1 范围（允许 / 禁止）

| 允许 | 禁止 |
|---|---|
| analysis | runtime 切换 |
| benchmark 报告 | provider 修改 |
| architecture docs | schema 修改 |
| Task Router 设计（只设计，不实现） | production routing 修改 |

本任务不改变任何运行路径；默认 runtime 保持 legacy。

## 2. 评估基线（数据依据）

本评估以已记录的工程证据为准，不新增运行。

| 证据 | 来源 | 说明 |
|---|---|---|
| EVAL-001 首次运行（run 32444324435） | `docs/tasks/p8-b2-eval-001-harness-quality-benchmark.md` | harness 0.10 vs legacy 0.80 |
| R3 运行（run 32447199752） | CURRENT_STATE P8-B2_R3 | 0.10 → 0.50（prompt 优化） |
| R4 实证（4 次运行） | CURRENT_STATE P8-B2_R4 | checklist 回归；prompt 杠杆收敛 |
| R5-A 运行（run 32460687556） | CURRENT_STATE P8-B2_R5-A | missing_required 消除；json_format 5 |
| **R5-D 运行（最终）** | `reports/harness_benchmark_r5d.json` | **本报告主数据源** |
| R5-B structured output probe | DECISIONS #75 | Harness 无 provider 级结构化输出 seam |
| LIVE-01 RESUME-03 | CURRENT_STATE P8-B2_LIVE-01_RESUME-03 | 会话/回合可靠性 20/20；工具与证据使用 |

### 2.1 R5-D 关键指标

- schema_valid_rate = **0.10**（1/10）；task_success_rate = 0.10；
  fallback_rate = 0.90
- 对照：**legacy_schema_valid_rate = 0.90**（9/10）
- 失败分类：json_format_failure = **6**，missing_required_field = 0，
  enum_violation = 0，value_format_violation = 0，other = 3
- JSON recovery：attempted 10 / recovered 1 / failed 9（成功率 0.10）
- 延迟（由 `harness_benchmark_r5d.json` 每 case latency 计算）：harness
  p50 ≈ 19.1s（min 14.6 / max 45.4）vs legacy p50 ≈ 9.2s（min 5.1 /
  max 29.5）→ **Harness 约为 legacy 的 2 倍**；报告级
  `latency_p50_seconds` = 19.656s
- 全部 P8-B3 治理门槛除 schema_valid_rate 外 MET（fake inference 0 /
  validator bypass 0 / audit 100% / budget 0 / secret 0 / silent retry 0）

## 3. Task 分类

基于现有 Equity / Research 任务，按产出契约与认知负载分为四类：

| 类型 | 定义 | 现有任务示例 |
|---|---|---|
| **extraction** | 从证据中抽取既有事实/表述，尽量不推断 | management_statement_summary（说话者陈述抽取）、financial fact 抽取 |
| **normalization** | 将自由文本归一为受控结构（字段/枚举），低推断 | business_description_normalization、product_name_mapping |
| **reasoning** | 基于证据推断/组织（候选、反证、问题生成），模型推断为主 | catalyst_candidates、risk_candidates、competitive_factor_candidates、counter_evidence_organizing、research_questions、earnings_analysis |
| **generation** | 面向章节/摘要/叙事的文本生成 | company_summary、industry_summary、theme_analysis、market_context、research_finding_generation、report_section_generation |

> 注：以上分类服务于 Runtime Selection；**不修改**既有任务注册表
> （`EQUITY_LLM_SCHEMAS` / `SEMANTIC_EVIDENCE_POLICY`）与 schema。

## 4. Benchmark 每 Task 分析（R5-D）

| case | 分类 | schema（必填字段数） | Harness | Legacy | Harness 失败模式 |
|---|---|---|---|---|---|
| eq_catalyst_candidates | reasoning | catalyst（22） | ✅ | ✅ | —（JSON boundary recovery 后 valid） |
| eq_business_description_normalization | normalization | research_finding（22） | ❌ | ✅ | TURN_TIMEOUT |
| eq_research_questions | reasoning | research_finding（22） | ❌ | ❌ | json_format_failure（legacy: value_format，entity 'UNKNOWN'） |
| eq_earnings_analysis | reasoning | research_finding（22） | ❌ | ✅ | TURN_TIMEOUT |
| eq_company_summary | generation | research_finding（22） | ❌ | ✅ | json_format_failure |
| rs_industry_summary | generation | research_finding（22） | ❌ | ✅ | TURN_TIMEOUT |
| rs_theme_analysis | generation | research_finding（22） | ❌ | ✅ | json_format_failure |
| rs_market_context | generation | research_finding（22） | ❌ | ✅ | json_format_failure |
| rs_research_finding_generation | generation | research_finding（22） | ❌ | ✅ | json_format_failure |
| rs_report_section_generation | generation | research_finding（22） | ❌ | ✅ | json_format_failure |

### 4.1 结论

1. **Harness 的结构化输出符合率远低于 legacy**（0.10 vs 0.90），差距主要来自
   **json_format_failure**（6/10）：Harness agent 上下文（persona / 工具指令 /
   多轮）下模型输出自由文本而非严格 JSON，且 R5-B 已确认 pinned Harness
   **无 provider 级结构化输出 seam**，无法在传输层强制 JSON。
2. **3/10 为 TURN_TIMEOUT**（agent 在回合预算内未产出）：Harness agentic
   loop + 工具调用延迟约为 legacy 2 倍（p50 19.1s vs 9.2s），在 20s case
   超时下不稳定。
3. **唯一成功（catalyst_candidates）依赖 R5-C JSON boundary recovery**
   （surrounding_text 恢复后 valid）— 说明即使在成功路径上，Harness 也需要
   恢复层兜底。
4. **Legacy 在 9/10 上直接产出 schema-valid 输出**，包括最复杂的
   research_finding（22 必填字段）与 catalyst（22 必填字段）；唯一失败
   eq_research_questions 是**实体映射**（company_entity_id='UNKNOWN'）——
   属于确定性映射可辅助的领域，不是结构生成能力问题。
5. **Benchmark 的局限（如实）**：corpus 全部 10 个 live case 都以严格 schema
   结构化对象为目标（9/10 为 research_finding），**未覆盖 Harness 的潜在优势
   领域**（开放多轮研究探索、自由文本产出、工具调用）。因此 0.10 只证明
   "Harness 不适合严格结构化生成"，**不能证明** "Harness 在其他任务上没有价值"。

## 5. Suitability Matrix

| Task | Legacy | Harness | Recommendation |
|---|---|---|---|
| 结构化发现生成（research_finding / catalyst / risk / competitive factor 等严格 schema 对象） | 高（0.90） | 低（0.10，json_format 主导） | **LEGACY_ONLY** |
| 归一化（business_description_normalization / product_name_mapping） | 高 | 低（TURN_TIMEOUT） | **LEGACY_ONLY** |
| 抽取（management_statement_summary / 财务事实抽取） | 高 | 中-低（无严格 schema 支撑时不稳定） | **LEGACY**（Harness 待传输层 JSON 支持后重评估） |
| 推理 → 严格 schema 对象（earnings_analysis / research_questions 等） | 中-高（1/10 实体映射失败） | 低 | **LEGACY**（实体映射用确定性辅助） |
| 开放研究探索（多轮、工具使用、自由文本/笔记产出） | 低（单轮、无工具） | **高**（agentic、工具、证据回读） | **HARNESS_CANDIDATE** |
| 自由文本摘要 / 章节草稿（面向用户阅读，非 schema 契约） | 中 | 中-高（但延迟高） | **HARNESS_CANDIDATE / HYBRID** |

## 6. Harness 优势场景（HARNESS_CANDIDATE）

基于 LIVE-01 RESUME-03（20/20 回合完成、same_session_pass=20、
turn2_reread_pass=10、turn1_evidence_pass=10、authority_drift=0、
unauthorized=0、secret_leak=0）与设计意图：

1. **开放多轮研究探索**：需要多轮对话、上下文累积、证据回读的研究任务；
   输出是研究笔记 / 问题清单 / 探索性中间结论，而非必须通过严格 schema
   校验的对象。
2. **工具辅助研究**：通过 MCP 工具（get_company_profile /
   check_data_readiness）在会话内获取公司画像与数据就绪状态后再分析 —
   legacy 单轮直连无法表达工具调用链。
3. **面向人读的自由文本产出**：研究报告章节叙述、晨报 / 异动解说段落，不
   以 schema 契约交付，validator 不参与把关，只需事实来源与证据锚定。
4. **研究问题的探索与候选生成**（若最终以自由文本 / 笔记落盘，而非
   research_finding 对象）。

**前提（诚实）**：上述优势是**设计意图 + LIVE-01 会话可靠性证据**，不是
schema_valid_rate 类 benchmark 证据。若进入 HARNESS_CANDIDATE，必须建立
面向该领域的独立评估指标（探索成功率 / 证据锚定率 / 工具使用正确率），
不能套用 EVAL-001 的 schema_valid_rate 门槛。

## 7. Legacy 优势场景（LEGACY_ONLY）

1. **所有产出必须通过严格 schema 校验的结构化任务**：research_finding /
   catalyst / risk_factor / competitive_factor / business_segment 等 —
   legacy 0.90 直接满足，Harness 0.10 不可用。
2. **确定性可表达的任务**（指南 §3）：抽取 / 归一化 / 实体映射 / 字段补全 —
   这些本应由确定性代码或直连模型完成，不需要 agentic 上下文。
3. **低延迟 / 有界成本任务**：legacy p50 9.2s vs harness 19.1s，且 legacy
   单轮 token 消耗远低于 Harness agentic 多轮（LIVE-01 观测单回合 24-44k
   tokens，REPAIR-02 已记录）。
4. **生产默认路径**：默认 runtime = legacy 保持冻结，直到 P8-B3 另行授权。

## 8. 未来 Hybrid Architecture（设计意图）

```text
复杂研究任务
   │
   ├─ Phase A（探索 / 理解）─ HARNESS（agentic、工具、多轮）
   │    输出：研究笔记 / 问题清单 / 候选方向（自由文本或宽松中间结构）
   │    把关：证据锚定 + 来源登记（不强制严格 schema）
   │
   └─ Phase B（结构化成稿）─ LEGACY（单轮、严格 schema）
        输入：Phase A 笔记 + 证据
        输出：通过 schema 校验的结构化对象（research_finding 等）
        把关：既有 LlmOutputValidator（唯一质量判断来源）
```

- 边界：Phase A 是"探索"，不直接产生权威结构化事实；Phase B 是"成稿"，
  走既有 validator / normalizer / 审计路径不变。
- 价值：把 Harness 的 agentic 能力放在它擅长的探索阶段，把结构符合率要求
  放在 legacy 擅长的成稿阶段 — 两类失败的短板被架构性隔开。
- 约束：Phase A 的输出不得进入 Claim / ResearchFinding 等权威对象；
  authority 仍在 Research OS；Phase A 不进行 Graph write/approve/apply。

## 9. Task Router 设计（只设计，不实现）

### 9.1 设计目标

在 LlmClient 单入口语义不变的前提下，建立任务级 runtime 选择模型，使
runtime 选择**可审计、可治理、默认保守（legacy）**。

### 9.2 输入

| 输入 | 来源 |
|---|---|
| task_type（extraction / normalization / reasoning / generation） | 任务注册表元数据（新字段，向后兼容） |
| output_contract（strict_schema \| free_text \| notes） | 任务定义 / schema 名称 |
| needs_tools（bool） | 任务是否声明 MCP 工具依赖 |
| needs_multi_turn（bool） | 任务是否需要多轮上下文累积 |
| governance_flag（per-task HARNESS_ENABLED） | 治理策略表（默认 false） |

### 9.3 决策规则（确定性，非 LLM 决策）

```text
if output_contract == strict_schema:
    runtime = LEGACY_ONLY            # 默认、冻结、唯一选择
elif needs_tools or needs_multi_turn:
    runtime = HARNESS_CANDIDATE      # 仅当 governance_flag=true 生效
else:
    runtime = LEGACY_ONLY
```

- **HYBRID** 表达为"任务内两阶段"：由 Orchestrator 层把任务拆成
  Phase A（Harness，free_text）+ Phase B（Legacy，strict_schema），
  每个 phase 单独走上述规则。
- 拒绝在 provider 层做隐式选择；选择记录进入 audit
  （`runtime_selection: legacy|harness|hybrid` + 依据字段），无静默切换。

### 9.4 治理约束

- 策略表（per-task runtime 白名单）是**配置工件**，修改需独立 taskbook +
  Sol 授权；不写死在 provider 代码。
- 默认所有任务 `LEGACY_ONLY`；Harness 仅对显式列入白名单的任务开放。
- 本设计不新增 provider、不修改 schema / validator / normalizer / threshold。

## 10. P8-B3 建议

**结论：暂不建议将 Harness 作为默认生产结构化生成 runtime 进入 P8-B3
决策。**

理由（数据依据）：

1. schema_valid_rate 0.10 远低于 P8-B3 门槛 0.70，且失败模式（json_format
   主导 + TURN_TIMEOUT）无法用既有 prompt / repair 杠杆解决 — R4 已实证
   prompt 杠杆收敛，R5-A repair 只解决 missing_required（当前为 0），
   json_format 需传输层 JSON 支持（R5-B 已确认当前 pinned Harness 无此能力）。
2. Harness 的潜在价值在**探索 / 工具 / 多轮 / 自由文本**领域，而这些领域
   **尚未被 EVAL-001 benchmark 覆盖**。用"结构化生成符合率"作为唯一门槛
   会系统性低估 Harness。

**建议的分层路径（供 P8-B3 决策参考）**：

| 决策面 | 建议 |
|---|---|
| 默认结构化生成 runtime | **保持 legacy**（0.90，满足质量与延迟/成本约束） |
| P8-B3 门槛 | 维持 schema_valid_rate ≥ 0.70 对 legacy；**不为 Harness 降低门槛** |
| Harness 评估 | 为 HARNESS_CANDIDATE 领域建立**独立指标**（探索成功率 / 证据锚定率 / 工具使用正确率 / 回合完成率），不套用 schema_valid_rate |
| 生产采用 | Harness 生产采用仅限明确列入白名单的探索类任务（§9 治理），且需独立 taskbook 授权 |

## 11. Tradeoff 分析

| 维度 | Legacy | Harness | 说明 |
|---|---|---|---|
| 结构符合率 | 0.90 | 0.10 | Harness agent 上下文与严格 JSON 不兼容 |
| 失败模式 | 实体映射（1/10，确定性可辅助） | json_format 6 + TURN_TIMEOUT 3 | Harness 失败需传输层/行为层解决，非 prompt |
| 延迟 | p50 9.2s | p50 19.1s（2×） | agentic loop + 工具调用 |
| 成本 | 低（单轮） | 高（多轮 24-44k tokens/回合） | LIVE-01 观测 |
| 能力 | 单轮、无工具、无多轮 | 多轮、工具、证据回读、会话连续 | Harness 独占能力 |
| 治理安全性 | 已冻结 | 20/20 回合、0 泄漏、0 drift | LIVE-01 已验证可靠 |

**核心判断**：Legacy 与 Harness 的能力空间**几乎不重叠** —
Harness 输在 Legacy 的主场（严格结构化生成），Legacy 输在 Harness 的主场
（agentic 探索 / 工具 / 多轮）。因此问题不是"谁更好"，而是**按任务类型选择
正确的 runtime**（Task Runtime Suitability Model），而非用单一 benchmark
的单一指标决定全局默认。

## 12. 验收与下一步

- 本报告可指导 P8-B3 决策；未改变任何运行路径 / schema / provider / threshold。
- 下一步建议：Sol 验收本评估 → 若认可 HARNESS_CANDIDATE 领域，另立独立
  taskbook 建立"Harness 探索能力评估"（新指标 + 新 corpus，与 EVAL-001
  解耦）；P8-B3 结构化生成默认路径维持 legacy。
- P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED；P8-B3 保持 NOT_AUTHORIZED。
