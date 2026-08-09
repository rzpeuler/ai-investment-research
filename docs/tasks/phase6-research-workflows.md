# Phase 6：研究工作流 — 串行恢复任务书

**TASKBOOK_STATUS: APPROVED**
**SERIAL_EXECUTION: REQUIRED**
**PARALLEL_PHASE6_BUSINESS_DEVELOPMENT: CANCELLED**
**CURRENT_MILESTONE: P6-S0**

---

## 里程碑概览

| Milestone | 内容 | 状态 |
|---|---|---|
| P6-G0 | 顶层设计治理冻结 | PASS / MERGED |
| P6-F0 | 共享契约冻结 | PASS / MERGED |
| P6-S0 | Serial Governance Reset (governance-only) | AUTHORIZED |
| P6-S1 | 6B Final Closure + Acceptance + Merge | NOT_AUTHORIZED |
| P6-S2 | 6A Final Closure + Acceptance + Merge | NOT_AUTHORIZED |
| P6-S3 | Earnings Expectation | NOT_AUTHORIZED |
| P6-S4 | First Coverage | NOT_AUTHORIZED |
| P6-S5 | Central Enablement + Cross-Scenario Acceptance | NOT_AUTHORIZED |
| P6-S6 | Governance Closeout | NOT_AUTHORIZED |

## 串行规则

- MAX_ACTIVE_PHASE6_BUSINESS_BRANCHES = 1
- 上一 milestone 未 PASS+MERGED → 下一 milestone NOT_AUTHORIZED
- 每个 milestone 从最新 accepted master 创建 clean branch
- 禁止并行 6A/6B/6C、禁止跨 track cherry-pick、禁止复用旧 worktree

## evening_brief 重新定义

- evening_brief = morning_brief 同构复用（同一 BriefPipeline）
- 唯一差异：时间窗口（morning: [D-1 20:00, D 08:00); evening: [D 08:00, D 20:00)）
- 旧 evening incremental methodology 正式废止

## Candidate Integration

- 所有 Research→GraphChange Candidate integration: DEFERRED
- 另立 Phase 6.1 任务书

## 任务书 approved 不得被解释成整个 Phase 6 已授权开发

当前仅 P6-S0 AUTHORIZED。所有业务里程碑（S1-S6）NOT_AUTHORIZED。
