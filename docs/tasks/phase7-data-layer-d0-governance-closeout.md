# P7-D0-GC：Governance Closeout after Independent Acceptance

**TASKBOOK_STATUS: AUTHORIZED — GOVERNANCE CLOSEOUT ONLY**
**MILESTONE: P7-D0-GC**
**START_HEAD: `d06d8d714958f58d44fb130f8fb30a3aff7e4a7a`**
**SCOPE: governance-only**
**P7-D0: PASS / INDEPENDENTLY ACCEPTED**
**P7-D1: NOT AUTHORIZED**
**PHASE6.1: NOT AUTHORIZED**
**GRAPH_WRITE: NONE**
**DB: v6**
**MIGRATIONS: NONE**
**SCHEMAS: 85**

> 独立架构验收已完成（P7-D0: PASS / INDEPENDENTLY ACCEPTED），本任务只把这一
> 已发生事实写回治理面。不得实现任何新功能；唯一允许修改的 Python 文件是
> `tests/unit/test_document_governance.py`。

## 1. 权威验收事实

```text
P7-D0_IMPLEMENTATION_HEAD: d06d8d714958f58d44fb130f8fb30a3aff7e4a7a
P7-D0-R1: PASS
INDEPENDENT_ACCEPTANCE: PASS
P7-D0: PASS / INDEPENDENTLY ACCEPTED

ACCEPTANCE_CI: 31501777548
PYTEST: 3019 passed / 6 skipped / 0 failed
SCHEMAS: 85/85 PASS
```

accepted code baseline = `d06d8d7`；本 governance-only closeout commit 不建立新的
accepted code baseline（与 Phase 6 / P7-UX1 治理 closeout 原则一致）。

## 2. 治理写入范围

- Decision #47 追加 47.8 Independent Acceptance + 47.9 Terminal Boundary（不改写
  47.1–47.7 冻结设计）。
- CURRENT_STATE → `P7-D0: PASS / INDEPENDENTLY ACCEPTED` + accepted head。
- NEXT_PHASE → `P7-D0: CLOSED / PASS / INDEPENDENTLY ACCEPTED`；
  `NEXT ELIGIBLE MILESTONE: P7-D1（NOT AUTHORIZED）`。eligible ≠ authorized。
- KNOWN_LIMITATIONS 只更新状态为 PASS，保留全部真实能力限制
  （DataReadinessService / GapClassifier / AcquisitionPlanner / AcquisitionExecutor /
  brief_event_content / brief_attention_content 自动源 / Heat Ranking / 历史日线 /
  财务自动源均未实现）。
- README 仅更新 living status，不得写成 "P7 Data Acquisition completed"。
- d0 / r1 taskbook 追加 terminal record；新增 governance-closeout taskbook。
- engineering-guide 保持 V1.5（无 awaiting acceptance 状态文本）。

## 3. Governance Test

唯一允许修改的 Python 文件：`tests/unit/test_document_governance.py`。

```text
AWAITING INDEPENDENT RE-ACCEPTANCE → PASS / INDEPENDENTLY ACCEPTED
新增/保留机械断言：d06d8d7、P7-D1: NOT AUTHORIZED、PHASE6.1: NOT_AUTHORIZED、
GRAPH_WRITE: NONE、DB: v6、MIGRATIONS: NONE、SCHEMAS: 85
```

## 4. 完成定义

```text
Decision #47 写入独立验收 PASS
accepted implementation head = d06d8d7
CURRENT_STATE = PASS / INDEPENDENTLY ACCEPTED
NEXT_PHASE 不再等待 D0 验收
P7-D1 仍 NOT AUTHORIZED
KNOWN_LIMITATIONS 不夸大数据采集能力
README 状态一致
Schema 仍 85 / DB v6 / 无 migration
无生产 Python 修改 / 无 Registry / Source / Router / Collector / Brief Pipeline 修改
Governance test 与新 terminal state 一致
pytest 0 failed / 85/85 Schema PASS / compileall PASS / diff check PASS
Offline CI SUCCESS
PR #24 仍 open / not merged
```

完成后等待最终独立核对；不得自行 merge。
