# GOV-STATE-SYNC-P7D4-01 — P7-D4 Terminal State Consistency Repair

**TASKBOOK_STATUS: IMPLEMENTED / AWAITING SOL INDEPENDENT ACCEPTANCE（2026-08-19）**
**TASK_ID: GOV-STATE-SYNC-P7D4-01**
**TASK_TYPE: GOVERNANCE / DOCUMENTATION CONSISTENCY REPAIR**
**BASE_BRANCH: master**
**BASE_COMMIT: `829f5da42785bab4ebe3afa8751b6479471235b6`**
**WORK_BRANCH: `task/GOV-STATE-SYNC-P7D4-01-state-consistency`**

## 1. 任务目的

消除 living-state 文档之间的 P7-D4 状态漂移，使新 Sol / Agent 只读取当前仓库即可恢复
项目状态，不再误判：

- P7-D4 仍在开发或等待验收（实际 = IMPLEMENTED / ACCEPTED）；
- PR #25 尚未合并（实际 = MERGED）；
- DeepSeek Harness 已经实现（实际 = NOT IMPLEMENTED）；
- 下一步应先直接 coding（实际 = 先做 P8-A0 taskbook）。

## 2. 事实基线

```text
P7-D4: IMPLEMENTED / ACCEPTED
Independent acceptance: PASS（2026-08-19）
Implementation head: 7c2791b2b854b88279c4c3126f7b1b2f8e861460
Accepted merge baseline: 8b153b3c8f6daf50fe30787535eb3132088da99d
P7-D4 merged into master: YES
PR #25: MERGED
P7-D2: PASS / INDEPENDENTLY ACCEPTED
P7-D3: PASS / INDEPENDENTLY ACCEPTED
CURRENT CHAT RUNTIME: P7-UX1
DEEPSEEK HARNESS: DESIGN FROZEN / SELECTED CANDIDATE / NOT IMPLEMENTED
NEXT ENGINEERING MILESTONE: P8-A0 DeepSeek Harness Integration Spike TASKBOOK
P8-A0 IMPLEMENTATION: NOT AUTHORIZED
PHASE 6.1: DEFERRED / NOT AUTHORIZED
SCHEMA: 86 / DB: v6 / MIGRATIONS: NONE
```

能力边界保持：company_document / financial_statement_data = WORKFLOW_WIRED；
BUSINESS_SUFFICIENT 与 deterministic_derivation=true 不因本任务自动晋级。

## 3. 允许修改范围

```text
README.md
AGENTS.md
docs/project-state/CURRENT_STATE.md
docs/project-state/NEXT_PHASE.md
docs/project-state/KNOWN_LIMITATIONS.md
docs/tasks/gov-state-sync-p7d4-01.md
tests/unit/test_document_governance.py
```

## 4. 禁止范围

```text
src/**、schemas/**、registry/**、config/**、knowledge/**、data/**、.github/**、
pyproject.toml、docs/project-state/DECISIONS.md、docs/engineering-guide.md、
docs/architecture/**、docs/contracts/**、既有历史 taskbook、既有 acceptance/baseline
文档、migration 文件
```

禁止：P8-A0 / Harness / MCP / Frontend / 数据源扩展 / BUSINESS_SUFFICIENT 晋级 /
deterministic_derivation 修改 / Schema / DB / migration / CI / 模型路由 / API 改动；
禁止顺手修 bug；禁止大规模重写历史文档。

## 5. 需要清理的 stale state

- P7-D4 `AWAITING INDEPENDENT ACCEPTANCE` / `IMPLEMENTATION IN PROGRESS` /
  `TEMPORARILY PAUSED` / `PAUSED_HEAD` / `online acceptance NOT_RUN`
- "D4 尚未独立验收" / "D4 恢复后继续"
- README 中 D2/D3 已 PASS 后仍写"当前不是 PASS / CLOSED"
- PR #25 已 merge 后仍写 `OPEN / NOT MERGED` / `merge authorized / not merged`
- KNOWN_LIMITATIONS 顶部总结日期与 P7-D4 财务能力旧描述

区分：明确的历史 snapshot / frozen decision（如 DECISIONS.md、architecture 文档、
历史 taskbook 中的当时状态）保持原样，不做机械替换。

## 6. 测试要求

```text
python -m pytest tests/unit/test_document_governance.py -q   # PASS
python -m pytest                                              # 0 failed（online 按默认 gate skip）
python -m research_os.cli.main validate                       # 86/86 PASS
python -m compileall -q src tests                             # PASS
git diff --check                                              # PASS
```

加强 governance regression tests（positive + negative assertions），防止 stale phrase
回归。禁止删除测试、把断言改恒真、跳过/ xfail / monkeypatch。

## 7. Definition of Done

- [ ] 基于 base `829f5da` 的独立 worktree + task branch
- [ ] 本 taskbook 已新增
- [ ] 全部 living-state stale audit 完成
- [ ] P7-D4 所有 current-state = ACCEPTED（accepted baseline `8b153b3`）
- [ ] PR #25 current-state = MERGED
- [ ] README D2/D3 acceptance 矛盾清除；P7-D4 terminal summary 已增加
- [ ] KNOWN_LIMITATIONS stale state 清除；Harness/Frontend 限制保留
- [ ] AGENTS active D4-resume instruction 清除
- [ ] P8-A0 明确仍为 taskbook / NOT AUTHORIZED；Harness / Frontend 明确 NOT IMPLEMENTED
- [ ] capability 边界未被夸大
- [ ] governance regression tests 已加强；targeted + full pytest PASS
- [ ] 86/86 Schema PASS；compileall PASS；diff-check PASS
- [ ] production / schema / registry / config / DB / migration / collector / source /
      graph / harness / frontend delta 全 0
- [ ] branch 已 commit + push；PR 已创建（环境支持时）；未 merge

## 8. 完成状态

完成后本任务状态为：`IMPLEMENTED / AWAITING SOL INDEPENDENT ACCEPTANCE`。
不得自行 merge 到 master。Sol 验收 PASS 后再处理 merge。

当前下一里程碑 = **P8-A0 DeepSeek Harness Integration Spike taskbook**；
P8-A0 implementation = **NOT AUTHORIZED**。
