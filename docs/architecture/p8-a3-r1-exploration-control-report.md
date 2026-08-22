# P8-A3-R1 Exploration Control Evaluation Report

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

Task: P8-A3-R1-HARNESS-EXPLORATION-CONTROL
（修复 P8-A3 发现的开放式 Exploration Agent Loop 不可控问题；建立 Exploration
Execution Contract）

## 1. 目标与背景

P8-A3 实证：5/5 HARNESS_ALLOWED 探索任务在 300s/600s turn 预算下全部
TURN_TIMEOUT（agentic loop），而定向 prompt 约 10s 完成。根因是开放式 Agent
Loop 缺少 Exploration Boundary。本任务建立 Exploration Execution Contract，
使 Harness Exploration Task 具备：明确目标 / 工具预算 / 最大回合 / 完成条件 /
失败退出条件。

## 2. Exploration Contract 设计

### 2.1 配置工件（config-driven，禁止硬编码）

`config/exploration_policy.yaml`（version 1.0.0），每 HARNESS_ALLOWED 任务
必须含：

| 字段 | 说明 |
|---|---|
| objective | 有界探索目标（必须输出 findings / unanswered_questions / next_actions） |
| allowed_tools | 本任务的 Harness ALLOW 工具子集（≤ 权限表） |
| max_turns | 硬回合预算（agent turn 数） |
| max_tool_calls | 硬工具调用预算（跨任务累计） |
| turn_timeout_seconds | 每回合墙钟预算（禁止无限等待） |
| completion_rule.required_fields | 确定性完成标记（findings / unanswered_questions / next_actions） |
| empty_data_policy | 空/不足数据策略（record_data_gap_and_stop，不重试） |
| failure_condition | 预算耗尽 → exploration_incomplete |

### 2.2 契约执行（ExplorationController）

```text
contract-bounded prompt（含 objective/allowed_tools/budgets/stop_condition）
  → turn 1（完整契约 prompt）
  → turn N>1（有界 follow-up：直接输出 required_fields 并结束）
  → 每回合计数 tool_calls（MCP event log，非 LLM 判定）
  → 确定性 completion 检测（子串标记，非 LLM 判定）
  → 空数据 → record data_gap 并结束（不自动重试）
  → 超 max_turns / max_tool_calls → exploration_incomplete（fail closed）
```

- Completion 检测**不使用 LLM 判断**：基于 required output fields 子串标记。
- 禁止无限 agent loop：turn 预算 + tool 预算 + 每回合墙钟三重硬边界。

## 3. 修改文件

| 文件 | 变更 |
|---|---|
| config/exploration_policy.yaml | 新增（5 个 HARNESS_ALLOWED 任务契约） |
| src/research_os/agent_runtime/exploration_contract.py | 新增（契约加载器，严格校验，缺失契约拒绝执行） |
| src/research_os/agent_runtime/exploration_controller.py | 新增（有界执行：turn/tool 预算、确定性完成、空数据停止） |
| src/research_os/agent_runtime/pilot_adapter.py | 集成契约强制（HARNESS_ALLOWED 必须先有契约） |
| src/research_os/agent_runtime/pilot_audit.py | +exploration control lineage 字段 |
| scripts/p8_a3_pilot_evaluation.py | 契约有界 prompt + 每回合 tool 计数 + 控制 lineage |
| scripts/p8_a2_hybrid_pilot.py | offline runner 返回契约完成标记 |
| agent_runtime_skills/*/SKILL.md | +Exploration Execution Contract 元数据 |
| tests/unit/test_p8_a3_r1_exploration_control.py | 新增（18 offline tests） |
| tests/unit/test_p8_a2_hybrid_pilot.py | 适配契约强制 + 缺失契约拒绝测试 |

## 4. Harness 执行结果

（`scripts/p8_a3_pilot_evaluation.py`，真实 pinned Harness rc.7；完整数据
`reports/p8_a3_pilot_evaluation.json`）

| case | expected | decision | P8-A3 (300s/600s) | P8-A3-R1（契约强制） |
|---|---|---|---|---|
| industry_exploration | HARNESS_ALLOWED | HARNESS_ALLOWED | timeout | **completed（completion=completed）** |
| research_preparation | HARNESS_ALLOWED | HARNESS_ALLOWED | timeout | **completed** |
| evidence_discovery_assistance | HARNESS_ALLOWED | HARNESS_ALLOWED | timeout | **completed** |
| analyst_assistant | HARNESS_ALLOWED | HARNESS_ALLOWED | timeout | **completed** |
| hypothesis_generation | HARNESS_ALLOWED | HARNESS_ALLOWED | timeout | **completed** |
| financial_fact_generation | LEGACY_ONLY | LEGACY_ONLY | routed_legacy | routed_legacy ✓ |
| research_finding_generation | LEGACY_ONLY | LEGACY_ONLY | routed_legacy | routed_legacy ✓ |
| final_report_section | LEGACY_ONLY | LEGACY_ONLY | routed_legacy | routed_legacy ✓ |

逐 case 契约执行（run `a3-eval-d2dce46d8644`）：turns 1-2 / max 2-3；tools
0-4 / max 4-6（全部在预算内；`industry_exploration` 本次直接按契约 objective
作答未调用工具，属 agent 行为方差）；数据缺口按 empty_data_rule 记录并停止
（不重试，诊断实测：图谱空 → 记录 data_gap → 主动终止，5 次工具调用 ≤ 6）。

## 5. Timeout 变化

- P8-A3：5/5 timeout（300s 与 600s 均无法收敛；agentic loop）
- P8-A3-R1：**timeout_count = 0**（契约 prompt + turn/tool 预算消除无限循环）；
  每回合 turn_timeout 120s × max_turns（2-3）→ 总墙钟有界（≤6 分钟/任务）。

## 6. Reliability 指标

| 指标 | 目标 | P8-A3 | P8-A3-R1 |
|---|---|---|---|
| session_success_rate | ≥0.95 | 0.0（5/5 timeout） | **1.0（5/5 completed）** ✅ |
| continuity_rate | — | 1.0 | 1.0 |
| timeout_count | 可控 | 5 | **0** |
| cleanup_status | NO（POSIX） | NOT_VERIFIED（Win）/ NO（CI） | 同左 |

## 7. Governance 指标（保持全过）

| 指标 | 要求 | P8-A3 | P8-A3-R1 |
|---|---|---|---|
| audit_completeness | 100% | 100% | **100%（8/8）** |
| unauthorized_tool | 0 | 0 | **0** |
| authority_drift | 0 | 0 | **0** |
| secret_leak | 0 | 0 | **0** |
| validator_bypass | 0 | 0 | **0** |
| strict_schema_entered_harness | 0 | 0 | **0** |

## 8. Value 指标

- 契约强制后 5/5 探索任务产生含 findings / unanswered_questions /
  next_actions 的输出（非空输出率 1.0）；工具调用率受 agent 行为影响
  （run 间方差；诊断实测工具调用 5 次/任务 ≤ 预算）。
- 如实声明：Value 为确定性代理；定性分析师有用性由 Sol 评估（P8-A1 §7.3）。

## 9. Cost 指标

- latency：每任务 ≤ max_turns × turn_timeout（120s × 2-3 = 240-360s 上限）；
  实际 1-2 回合完成，远低于上限。
- token usage：provider-reported（见报告 JSON；部分 run timeout 前无 usage
  返回，如实记录）。
- provider calls：≤ max_tool_calls（4-6/任务，诊断实测 5；见报告 JSON）。

## 10. 结论与 Recommendation

- **Exploration Execution Contract 有效控制 agentic loop**：turn / tool / 墙钟
  三重硬边界 + 确定性完成检测 + 空数据停止，消除"无限探索"（timeout 5 → 0，
  session_success 0 → 1.0）。
- Governance 保持全过；Negative controls 继续 LEGACY_ONLY。
- **Reliability 目标达成**（≥0.95 达成：1.0）。
- 建议：Sol 验收本任务（契约设计 / 预算执行 / 测试 / 真实执行结果）→ 可授权
  P8-A4（生产试点运行，采集 Reliability / Governance / Value / Cost 正式基线）。
- 默认 runtime 保持 legacy；P8-B3 / production adoption 保持 NOT_AUTHORIZED。

## 11. 状态

- P8-A3-R1 为修复任务；Agent 不得 self-accept。
