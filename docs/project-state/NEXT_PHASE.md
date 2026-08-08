# 下一阶段准入（NEXT PHASE）

## 当前结论

- **Phase 4 engineering foundation：PASS**
- **Phase 4 full research capability：PASS（独立验收 SHA `9506f6a`）**
- **Pre-Phase-5 Offline CI Gate：PASS**
- **Phase 5 taskbook：APPROVED**
  - 任务书路径：`docs/tasks/phase5-industry-knowledge-graph.md`
  - 正式设计决策：`DECISIONS.md` #30
- **Phase 5 implementation：IN_PROGRESS**
  - M0：PASS（SHA `df358da`，M0 Offline CI `31159354574` PASS）
  - M1 Graph Contracts：PASS（SHA `b097996`，M1 CI `31165533237`：1281 passed / 5 skipped / 55/55 schemas）
  - M2 Persistence and ontology seed：PASS（SHA `565d500`，M2 CI `31171415215`：1351 passed / 5 skipped / 55/55 schemas）
  - M3 GraphChange Candidate Pipeline：PASS（SHA `242e039`，M3 CI `31240709634`：1480 passed / 5 skipped / 55/55 schemas）
  - M4 Knowledge Validator：PASS（SHA `20b7a15`，M4 CI `31241777234`：1611 passed / 5 skipped / 55/55 schemas）
  - M5 Human Review Workflow：PASS（SHA `92649a7`，M5 CI `31251491357`：1725 passed / 5 skipped / 0 xfail / 55/55 schemas）
  - M6 Deterministic Apply Engine：PASS（SHA `480b209`，CI `31257395650`，1809 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M7 Supersede / Expire / History：PASS（SHA `651e9a1`，CI `31262745492`，1911 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M8 Query + Knowledge Context Builder：PASS（SHA `eac18e2`，CI `31269460005`，2009 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M9-M10：NOT_AUTHORIZED

Phase 5 正式任务书已由用户批准。M1、M2、M3、M4、M5、M6、M7、M8 已通过独立架构验收。
**M7 验收通过不自动授权 M8。** M8 已由用户于 2026-08-08 另行明确授权并通过独立验收。

Phase 5 正式任务书已由用户批准。**任务书批准 ≠ 工程实施授权**。

## Phase 5 工程前置条件

| # | 条件 | 状态 | 证据 |
|---|---|---|---|
| 1 | 统一控制面、晨报 Evidence、Phase 4 完成定义和文档治理问题全部关闭 | SATISFIED | Phase 4.1 独立验收 PASS，统一 Orchestrator/ScenarioRegistry 已接入，晨报 Evidence 血缘完整 |
| 2 | 全量测试与已配置质量检查通过 | SATISFIED | 1133 passed / 5 skipped / 51/51 schemas / compileall PASS；Offline CI run 31154022296 通过 |
| 3 | Phase 4 核心语义模块达到最低覆盖，真实 Provider 状态如实记录 | SATISFIED | DeepSeek 真实 Provider 已验证；600519.SH / 300750.SZ 取得 SUCCESS；无 Provider 时如实回退 |
| 4 | Claim/Evidence Validator 无严重缺口，人工财务和派生事件血缘可反查 | SATISFIED | ERV-001—093 Validator 已实现；Document/checksum/数值/时间/实体校验全部在位 |
| 5 | README / CURRENT_STATE / NEXT_PHASE / KNOWN_LIMITATIONS / taskbook 状态一致 | SATISFIED | M0-R1 治理一致性修正已完成，全部文档反映真实能力边界（含 Offline CI 上线） |
| 6 | 正式 Phase 5 任务书存在且不改变工程指南既有边界 | SATISFIED | `docs/tasks/phase5-industry-knowledge-graph.md` 已批准；DECISIONS.md #30 已冻结 |

## Phase 5 实施授权门

**所有工程前置条件均已满足。用户已于 2026-08-07 明确授权开始 Phase 5 M1。**

```
Phase 5 implementation authorization gate: SATISFIED
```

当前准入：**PR5B CLOSEOUT**（不是 M9 AUTHORIZED）。

PR5B closeout 冻结流程（完成前禁止提前创建 PR5C）：

```text
PR5B 必须完成 closeout
→ 独立复核
→ 用户明确批准 merge
→ squash merge PR5B
→ 验证新的 master SHA
→ 才可从 master 创建 phase5/pipeline-integration
```

M9-M10 仍 NOT_AUTHORIZED。

```
当前状态：
M6 PASS（SHA 480b209，CI 31257395650）。
M7 PASS（SHA 651e9a1，CI 31262745492）。
M8 PASS（SHA eac18e2，CI 31269460005，2009 passed / 5 skipped / 0 xfail，
        55/55 schemas，DB v6）。
PR5B closeout in progress（PR #5 DRAFT）。

禁止：
M9 / M10 / PR5C 创建 / merge PR5B。
```

## Phase 4 独立验收记录

- 独立验收结论：`PASS`；验收 SHA：`9506f6a19ab60187d1ab0bc4991cfa427606ecae`；
- 600519.SH 与 300750.SZ 的 Task→Plan→Request→Run→Evidence→报告血缘通过复核；
- 688981.SH 受控缺失未被提升为 success；
- DeepSeek 间歇性超时仍按 8/1 共享预算降级，且日志无凭证泄漏；
- 保持分钟行情、自动历史日线、通用 OCR 和深度媒体等未验证能力为明确限制。
