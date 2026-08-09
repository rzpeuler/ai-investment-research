# Phase 6：研究工作流 — 串行任务书

**TASKBOOK_STATUS: APPROVED FOR EXECUTION**
**PHASE: Phase 6**
**MILESTONE: P6-S0-R2**
**SERIAL_EXECUTION: REQUIRED**
**PARALLEL_PHASE6_BUSINESS_DEVELOPMENT: CANCELLED**
**CURRENT_MILESTONE: P6-S0**
**BUSINESS_CODE_CHANGE: PROHIBITED**
**NEXT_MILESTONE: P6-S1 — NOT_AUTHORIZED**

---

## 1. Phase 6 总体串行拓扑

```text
P6-G0  Top-Level Design Governance Freeze  → PASS / MERGED
P6-F0  Shared Contract Freeze              → PASS / MERGED

P6-S0  Serial Governance Reset             → AUTHORIZED (governance-only)
         ↓
P6-S1  6B Final Closure + Acceptance + Merge
         ↓
P6-S2  6A Final Closure + Acceptance + Merge
         ↓
P6-S3  Earnings Expectation
         ↓
P6-S4  First Coverage
         ↓
P6-S5  Central Enablement + Cross-Scenario Acceptance
         ↓
P6-S6  Governance Closeout
```

### 1.1 串行工程规则

- MAX_ACTIVE_PHASE6_BUSINESS_BRANCHES = 1
- MAX_ACTIVE_PHASE6_BUSINESS_WORKTREES = 1
- 上一 milestone 未 PASS + MERGED → 下一 milestone NOT_AUTHORIZED
- 每个 milestone 从最新 accepted master 创建 clean branch
- 每个 milestone 必须：implementation → tests → push → PR → CI → independent acceptance → merge → clean workspace → next milestone
- 禁止：并行 Phase6 实现、跨 track cherry-pick、复用旧 worktree、executor self-unlock、executor self-merge

### 1.2 七场景分配

```text
6A：industry_research、theme_discovery
6B：evening_brief、daily_review、stock_review
6C：first_coverage、earnings_expectation
```

## 2. 当前真实工程库存

### 2.1 Master (e98f5ed)

```
P6-G0: PASS / MERGED
P6-F0: PASS / MERGED
Phase6 production business code: NONE
DB: v6
Schemas: 55
```

### 2.2 6B off-master implementation

```
Scenarios: evening_brief, daily_review, stock_review
Status: IMPLEMENTED OFF-MASTER / NOT_FINAL_ACCEPTED / NOT_MERGED / NOT_CENTRALLY_ENABLED
Branch: phase6/p6-b-periodic-review (PR #15)
CI: Offline CI 31302397542 — 2177 passed / 5 skipped / 61 schemas / compileall PASS
Known gap: RunStatus still contains "insufficient_data" (must unify to "insufficient_evidence")
```

### 2.3 6A off-master implementation

```
Scenarios: industry_research, theme_discovery
Status: IMPLEMENTED OFF-MASTER / NOT_FINAL_ACCEPTED / NOT_MERGED / NOT_CENTRALLY_ENABLED
Branch: phase6/a-industry-theme (clean, no 6B/6C contamination)
Known: Graph→Research read-only bridge, Evidence eligibility adapter,
       21 dimensions, 5 theme lifecycle states, single data model
```

### 2.4 6C

```
earnings_expectation: NOT_IMPLEMENTED
first_coverage: NOT_IMPLEMENTED
Old local 6C workspace: ABANDONED / NOT A VALID BASE
```

---

## 3. P6-S0 — Serial Governance Reset

**状态：AUTHORIZED（当前唯一授权里程碑）**

S0 是 governance-only milestone，不实现任何业务代码。

S0 交付：
- Decision #43 (Evening Brief Design Correction)
- Decision #44 (Phase 6 Serial Recovery and Completion)
- Engineering Guide V1.2 → V1.3（并行→串行拓扑）
- Shared Contract 串行语义更新
- CURRENT_STATE / NEXT_PHASE / README 同步
- 治理测试（5/5）
- PR + Offline CI

S0 验收后 merge master，才能授权 S1。

---

## 4. P6-S1 — 6B Final Closure

**状态：NOT_AUTHORIZED（需要 S0 PASS + MERGED）**

### 4.1 S1 场景

- evening_brief
- daily_review
- stock_review

### 4.2 evening_brief 正式定义

永久定义：

```text
evening_brief = morning_brief 同构复用（同一 BriefPipeline）
```

唯一业务差异为时间窗口：

```text
morning_brief: [D-1 20:00, D 08:00) Asia/Shanghai
evening_brief: [D 08:00, D 20:00) Asia/Shanghai
```

必须复用：

```text
same BriefPipeline
same RawItem processing
same Evidence generation
same filtering / scoring / exact dedup / clustering
same Claim generation
same validator / degradation / safety policy
```

正式废止：

```text
material_update
new_since_morning
already_known_in_morning
morning/evening cross-report dedup
morning expectation validation
market feedback validation
```

### 4.3 daily_review contract

必须固定五层结构：

```text
observed_fact
previous_research_view
new_evidence
updated_interpretation
remaining_unknown
```

明确：

```text
fact != previous view
fact != updated interpretation
```

所有 Evidence：`published_at <= as_of`。历史复盘：no future leakage。

previous cutoff 优先级：
1. explicit previous_cutoff
2. accepted prior artifact business cutoff

只允许使用：`window_end` / `as_of` / `research_cutoff` / `data_cutoff`。
禁止使用：`finished_at` / `created_at` / `updated_at` / runtime completion timestamp。

无法确定 cutoff：`previous_cutoff = None` + explicit degradation + no fabricated new_evidence。

### 4.4 stock_review contract

stock_review 是 **incremental review**，不是 full Phase4 regeneration。

必须复用：

```text
Phase3 abnormal move outputs
Phase4 ResearchFinding / risks / catalysts / valuation assumptions
```

所有 Evidence：entity-relevant + as_of-safe。

明确：

```text
new_evidence = evidence after previous_cutoff AND evidence <= as_of AND target-entity relevant
```

只有 new_evidence 可以影响：

```text
thesis_supported / thesis_weakened
risk_changed / catalyst_changed
valuation_assumption_changed
```

禁止旧 Evidence 重复改变研究判断。

无法确定 previous_cutoff：`new_evidence = []` + explicit degradation + no incremental judgment。

Run artifact：`new_evidence_count = len(actual new_evidence)`，不得使用 `len(window_evidence)`。

### 4.5 S1 status vocabulary

Phase 6 统一：

```text
success / partial_success / degraded / insufficient_evidence / failed
```

6B 必须删除自有对象中的 `insufficient_data`。

Phase4 历史 `INSUFFICIENT_DATA` 不属于 S1 修改范围。不得顺手修改 Phase4。

### 4.6 S1 acceptance

至少：

```text
morning regression
evening parity
daily future-leakage attacks
daily previous-cutoff attacks
stock entity-filter attacks
stock new-evidence-only attacks
stock future-leakage attacks
full pytest
schema validation
compileall
diff-check
Offline CI
```

之后：independent acceptance → merge master → remove S1 worktree → 授权 S2。

---

## 5. P6-S2 — 6A Final Closure

**状态：NOT_AUTHORIZED（需要 S1 PASS + MERGED）**

### 5.1 S2 场景

- industry_research
- theme_discovery

### 5.2 Graph→Research contract

唯一合法路径：

```text
Versioned Graph
→ GraphQueryService
→ KnowledgeContextBuilder
→ read-only Research Context
```

永久：`KnowledgeContext != Evidence`。

Graph 只能用于：research navigation / entity discovery / industry mapping / relation discovery / retrieval direction / context organization。不能直接证明 FACT。

Graph FACT 如要进入报告：

```text
Graph object
→ evidence_ids
→ authoritative Evidence reload
→ eligibility validation（source_tier, evidence_type, published_at <= as_of, entity relevance）
→ as_of validation
→ source validation
→ entity/relevance validation
→ ResearchFinding / Claim
→ Markdown
```

禁止：`Graph payload → report FACT`。

`MODEL_INFERENCE` 永远不得自动变为 `FACT`。

### 5.3 industry_research methodology

必须只有一套 canonical industry research dimensions。不能 model 层一套、pipeline 另一套。

最低必须能表达：

```text
scope_and_boundary / industry_classification
value_chain / key_segments
supply / demand
competitive_landscape / technology_path
materials / equipment / applications
policy_and_events / key_metrics / key_companies
catalysts / risks / core_controversies
supporting_evidence / counter_evidence
unknowns / open_questions
evidence_quality
```

每一维度必须产生：

```text
evidence-backed finding
OR explicit insufficient_evidence
OR explicit unknown
OR explicit conflict
```

禁止因 pipeline 未实现该维度而静默缺失。

### 5.4 theme_discovery methodology

正式路径：

```text
Event / Policy / Technology Change
→ Theme Trigger
→ Theme Hypothesis
→ Evidence
→ Industry Mapping
→ Related Entities
→ Supporting Evidence
→ Counter Evidence
→ Lifecycle
→ Invalidating Conditions
→ Open Questions
```

Lifecycle 只能是：

```text
forming / supported / weakening / invalidated / uncertain
```

禁止：

```text
emerging / growing / maturing / declining / dormant / unknown
```

Theme Hypothesis 必须承载：

```text
supporting_evidence_ids / counter_evidence_ids
supporting_factors / counter_evidence
industry_mapping / related_entity_ids
invalidating_conditions / open_questions
uncertainty
```

counter_evidence_ids 必须指向合法 Evidence。trigger 数量少 / strength 偏低 / 缺少更多 trigger 不是 counter_evidence（只能叫 limitation / uncertainty / weak signal）。

evidence_driven / peer_diffusion 无公共接口时：`status = degraded`，`limitation = public interface unavailable`。不能伪装成 `insufficient_evidence`。

### 5.5 Stable IDs

每个 `ThemeTrigger.trigger_id` 和 `ThemeHypothesis.hypothesis_id` 必须 non-empty / unique / stable within run。

### 5.6 Artifact naming

正式文件必须是：

```text
theme_discovery_request.json
theme_discovery_run.json
```

不得使用 `run.json`。

### 5.7 S2 acceptance

至少：

```text
21 dimensions all produce output
Graph FACT requires Evidence reload (authoritative + eligible + as_of-safe)
MODEL_INFERENCE never FACT
Graph-only context → NON-EVIDENTIARY, not FACT
theme single model / single lifecycle vocabulary
theme Trigger/Hypothesis unique IDs
theme counter_evidence is real Evidence
theme evidence_driven/peer_diffusion → degraded when no public API
theme report rendered AFTER themes+metrics written to result
Request + Run both Pydantic→Schema validation fail-closed
as_of historical attack tests
no raw Graph SQL / no JSON mirror authority / no private Graph API
Graph write = NONE
Phase4 Evidence regression
Phase5 Graph/query/context/history regression
full pytest
schema validation
compileall
diff-check
Offline CI
```

之后：independent acceptance → merge master → remove S2 worktree → 授权 S3。

---

## 6. P6-S3 — Earnings Expectation

**状态：NOT_AUTHORIZED（需要 S2 PASS + MERGED）**

### 6.1 场景

- earnings_expectation

### 6.2 正式定义

earnings_expectation 是 **FORECAST / HYPOTHESIS**，永远不是 FACT / Graph FACT / trading signal。

必须记录：

```text
as_of
historical_input_periods
forecast_period
evidence_ids
assumptions
method
scenario
uncertainty
calculation_version
generated_by
```

三时间严格：

```text
as_of（研究时点）
historical_input_period（历史输入期间）
forecast_period（预测期间）
```

### 6.3 确定性分工

代码负责：

```text
period alignment / YoY / QoQ / growth / margin / aggregation
scenario arithmetic / sensitivity / rounding
unit normalization / formula evaluation / derived series
```

LLM 禁止计算：YoY/QoQ / ratio / margin / series / valuation formulas / mechanical forecast arithmetic。

LLM 只负责：drivers / assumptions / scenario semantics / risks / uncertainty。

任何 LLM 给出的数字不得直接进入最终 forecast（必须由代码重建）。

### 6.4 复用

必须复用 Phase4：

```text
financial facts / metrics / forecast primitives / valuation primitives
Evidence / model routing
```

不得创建第二套财务引擎。

### 6.5 S3 acceptance

- as_of / historical_input / forecast period governance
- future leakage attacks（forecast period 不得使用未来已知数据）
- 确定性与 LLM 计算边界
- Phase4 / Phase5 / Phase6A regression
- full pytest / schema / compileall / diff-check / Offline CI

之后：independent acceptance → merge master。

---

## 7. P6-S4 — First Coverage

**状态：NOT_AUTHORIZED（需要 S3 PASS + MERGED）**

### 7.1 场景

- first_coverage

### 7.2 编排层

first_coverage 是 **composition / orchestration**，不是第二套研报系统：

```text
Company / Security Profile
→ Phase4 Equity Research
→ accepted Phase6A Industry Research
→ Peer Context
→ P6-S3 Earnings Expectation
→ Valuation Applicability
→ Catalysts
→ Risks
→ Counter Evidence
→ Open Questions
→ First Coverage Report
```

### 7.3 必须调用已进入 master 的

```text
Phase4 public capabilities
Phase6A accepted industry interface
P6-S3 accepted earnings expectation
```

不得：

```text
复制 Phase4 report engine / financial engine / valuation engine
复制 Evidence engine / LLM routing
```

### 7.4 永久禁止

```text
目标价 / 买入/卖出评级 / overweight/underweight
position sizing / next-day trade
```

估值允许：

```text
method applicability / historical percentile
peer context / market-implied assumptions / sensitivity
```

不得输出目标价。

### 7.5 S4 acceptance

- 全链路编排验证
- Phase4 / Phase5 / Phase6A / P6-S3 regression
- full pytest / schema / compileall / diff-check / Offline CI

之后：independent acceptance → merge master。

---

## 8. P6-S5 — Central Enablement + Cross-Scenario Acceptance

**状态：NOT_AUTHORIZED（需要 S1—S4 全部 PASS + MERGED）**

这是唯一允许修改 shared control plane 的 Phase 6 阶段。

### 8.1 必须使默认 Registry/Orchestrator/CLI 可执行全部七个场景

```text
industry_research / theme_discovery
evening_brief / daily_review / stock_review
earnings_expectation / first_coverage
```

### 8.2 统一

```text
Request artifact naming / Run artifact naming
ScenarioExecutionResult / Task ID lineage
RunDirectory / validation / audit
schema registry 最终收敛
runner registration
CLI public route
control-plane integration
```

不得在 S1-S4 提前中央 enable。

### 8.3 跨场景验收

至少覆盖：

```text
morning → evening parity
daily review historical replay
stock review incremental evidence
industry historical as_of
theme Graph/Evidence separation
earnings future leakage
first coverage reuse chain
```

及：

```text
Phase2 / Phase3 / Phase4 / Phase5 全量回归
七个 Phase 6 scenario public entry 可运行
```

### 8.4 S5 acceptance

- 全量回归（Phase2—Phase5）
- 七场景全部通过
- full pytest / schema / compileall / diff-check / Offline CI

之后：merge master。

---

## 9. P6-S6 — Governance Closeout

**状态：NOT_AUTHORIZED（需要 S5 PASS + MERGED）**

同步所有治理文档到 terminal state。必须区分：

```text
research capability（PASS）
central enablement（PASS）
candidate integration（DEFERRED）
```

Phase 6 research completion 不自动意味着 Research→GraphChange Candidate enabled。

---

## 10. 全 Phase 永久输出安全

全部七场景永久禁止：

```text
目标价 / 买入评级 / 卖出评级 / 增持 / 减持
仓位建议 / 明日交易建议 / 自动荐股 / 诱导性交易语言
```

明确：

```text
theme_discovery != stock picking
earnings_expectation != trading signal
first_coverage != brokerage rating
daily_review != next-day trading plan
```

---

## 11. 数据库 / 本体 / 来源

全 Phase 6 默认：

```text
DB = v6
NO migration（各 milestone 独立验证）
NO ontology expansion（new node_type / relation / semantics → architecture review）
NO source whitelist expansion（走 source-governance 独立流程）
```

---

## 12. Schema 原则

```text
JSON Schema = authoritative
Pydantic = constructor
model_dump → Schema validation → fail closed
```

禁止：绝对总数断言（`len(SCHEMA_NAMES) == N`），改为语义检查（required subset exists, all loadable）。

---

## 13. Candidate Integration

全部 Research→GraphChange Candidate integration：

```text
DEFERRED
```

另立 Phase 6.1 任务书。

---

## 14. 授权状态

```text
P6-S0: AUTHORIZED（当前）
P6-S1—P6-S6: NOT_AUTHORIZED
```

任务书 approved 不得被解释成整个 Phase 6 已授权开发。

下一 milestone 只有在前一 milestone PASS + MERGED + workspace cleaned 后才能开始。
