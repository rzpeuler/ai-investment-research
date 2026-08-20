# P8-B2-LIVE-01-BUDGET-DECISION-01 — Formal Trial Token Budget Boundary Decision

STATUS: DECIDED / AWAITING INDEPENDENT ACCEPTANCE (Sol)

本任务基于真实 provider usage evidence 重新评估正式 Trial 的 token budget
设计。纯治理/文档任务：**无代码修改**；budget 值的实现变更（如需）属后续
授权 taskbook（本任务按要求停止并标注 ARCHITECTURE_DECISION_REQUIRED）。

## 1. Observed / Derived / Policy 区分

### 1.1 Observed（真实 provider usage，非估算）

| 来源 | 场景 | total_tokens（provider-reported） | 组成 |
|---|---|---|---|
| REPAIR-02 有界单 turn 诊断（真实运行时） | turn 1（profile + readiness） | **23,788** | uncached 23,201 + output 587 + cacheRead 10,624 + cacheWrite 0 |
| RESUME-03 usage-shape 诊断（真实运行时） | turn 1（profile + readiness） | **44,296** | uncached 27,672 + output 1,264 + cacheRead 15,360 + cacheWrite 0 |
| RESUME-03 正式 trial | 20 个 completed turns（usage 当时未提取） | —（latency p50 6,218ms / p95 8,767ms） | — |

观测范围：**每 provider-backed turn 约 23.8k–44.3k tokens**（差异来自 prompt /
缓存命中 / 工具上下文变化；均为 dsh rc.7 `projections.values.tokenUsage`
provider-reported 值，经 REPAIR-02 映射）。

### 1.2 Derived（基于 observed 的合理预测）

- 20 turns 预测总用量：
  - 低端：23.8k × 20 ≈ **476k tokens**；
  - 高端：44.3k × 20 ≈ **886k tokens**；
  - 中位（~34k/turn）：≈ **680k tokens**。
- 结论：20-turn corpus 的真实用量**显著超过当前冻结的 200,000 上限**（约
  2.4–4.4 倍）。

### 1.3 Policy（治理选择）

- 当前冻结：`max_provider_tokens = 200,000`（LIVE-00 §5.6 / TrialBudget，
  RESUME-03 / REPAIR-02 taskbook 均重申）。
- 200k 是在**无真实 usage evidence** 时设定的设计期上限（意图：
  "prevent uncontrolled provider usage"，LIVE-00 §5.6）。

## 2. 当前 token accounting 方式

- 每 turn：`_extract_usage` → `operational_metadata.usage` →
  `_usage_from_result`（total_tokens，int ≥ 0）→ `counters.provider_tokens +=`；
- `_admit_turn` / `_budget_check`：`provider_tokens / max_provider_tokens`，
  比率 ≥ 1 → `RESOURCE_BUDGET_EXCEEDED`（fail-closed）；≥ 0.8 → warning；
- 只接受 provider-reported 值；无推断/估算（REPAIR-02 后已正确映射）。

## 3. 决策选项评估

### Option A — 保持 max_provider_tokens = 200,000

- 成本：上限 200k tokens（最低；但这是被截断成本，非完整 corpus 成本）。
- 完成率：**无法完成 20-turn corpus** — 约第 5–9 turn 触发
  `RESOURCE_BUDGET_EXCEEDED` → fail-closed PARTIAL；
- failure semantics：budget exhaustion 是如实 typed 结果，机制正确，但
  **使正式 acceptance 在物理上不可达**（corpus 无法完成 → PASS CANDIDATE
  不可能）。
- 结论：A 与"完成 10 sessions / 20 turns"的正式 contract 不兼容。

### Option B — 提高预算

评估值：

| 值 | 对 886k（高端预测）余量 | 对 476k（低端预测）余量 | 评价 |
|---|---|---|---|
| 500,000 | −44%（不足） | +5%（过紧） | 不足以覆盖观测高端，方差风险高 |
| **1,000,000** | **+13%** | **+110%** | 覆盖观测范围并保留合理余量 |
| 2,000,000 | +126% | +320% | 余量过大，削弱"有限预算"意图 |

**推荐：1,000,000**。

理由：

- 基于 observed 证据（非估算）：覆盖 20-turn 预测高端 886k 并保留 ~13%
  余量（缓存命中率、turn 2 fresh readiness、provider 延迟波动）；
- 保持"防止失控 provider usage"的有限预算意图：1M 仍是硬上限，
  超出即 fail-closed；warning 比率不变（0.8 → 800k 预警）；
- 成本透明：只计 provider-reported 值；最大成本 = 1M tokens（flash 模型，
  有界且可预期）；
- 不改变 acceptance gate / failure semantics / retry / timeout / concurrency。

### Option C — 调整 Trial contract（如减少 turn 数）

- 10 sessions / 20 provider-backed turns 是已验收的 acceptance corpus
  （600519.SH ×5 + 300750.SZ ×5，每 session 2 turns），不是预算问题的产物；
- 减少 turn 数 = 降低 acceptance 标准 = 为获得 PASS 而降低标准 —
  **被决策规则明确禁止**；
- 结论：拒绝。预算与 contract 是独立维度；问题应通过预算解决，而非缩水
  corpus。

## 4. Decision

**采用 Option B：将 `max_provider_tokens` 从 200,000 调整为 1,000,000。**

- Observed：23.8k–44.3k tokens/turn（真实 provider 报告）。
- Derived：20 turns ≈ 476k–886k。
- Policy：上限 1,000,000（观测高端的 +13% 余量；warning 0.8 → 800k）。
- Impact：正式 trial 可在预算内完成完整 corpus；budget exhaustion 仍
  fail-closed；最大成本有界（1M tokens）；cost transparency 保持
  （provider-reported only）。

## 5. ARCHITECTURE_DECISION_REQUIRED（实现变更，本任务不实施）

本任务禁止代码修改。`TrialBudget.max_provider_tokens` 的默认值（
`src/research_os/agent_runtime/trial.py:86`，当前 200_000）与
`docs/tasks/p8-b2-live-00-trial-boundary-design.md` §5.6 的变更，需要：

1. Sol 独立验收本 BUDGET-DECISION；
2. 后续授权实现 taskbook（例如 P8-B2-BUDGET-IMPL-01）：把
   `max_provider_tokens` 更新为 1,000,000 + 同步 LIVE-00 边界文档 +
   更新 budget 相关测试断言（如有）＋ 回归测试；
3. 然后按 LIVE-00 边界重新执行正式 trial（新 RESUME taskbook）。

不得在本任务中实现该值变更。

## 6. 状态

- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不写 `P8-B2 ACCEPTED`。
- 本任务未执行 trial、未改代码、未改 acceptance criteria。
