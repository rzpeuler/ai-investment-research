# Phase 6：研究型工作流（6A / 6B / 6C）——正式工程任务书

**TASKBOOK_STATUS: APPROVED**
**IMPLEMENTATION_STATUS: IN_PROGRESS（P6-F0 IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE）**
**CURRENT_MILESTONE: P6-F0**
**NEXT_MILESTONE: 6A / 6B / 6C-PREP（待 F0 独立验收 PASS 后另行授权）**

**P6-F0: IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE**
**P6-A: NOT_AUTHORIZED**
**P6-B: NOT_AUTHORIZED**
**P6-C: NOT_AUTHORIZED**

> 正式设计决策：`DECISIONS.md` #41（Phase 6 Top-Level Design Decision，2026-08-09）。
> 工程指南：`docs/engineering-guide.md` V1.2（第 69 节）。
> 共享契约：`docs/contracts/phase6-shared-contract.md`（P6-F0 冻结）。
> **任务书 approved 不得被解释成整个 Phase 6 已授权开发。**
> P6-G0 已通过独立验收（PR #13，G0 FINAL MASTER `9e5c894`）。
> 当前只允许执行 P6-F0；F0 验收 PASS 前 6A / 6B / 6C-PREP 均不得开始。

**任务书创建基线：**

```text
repository:
rzpeuler/ai-investment-research

base_branch:
master

base_sha:
0cebf03eae40cb29d39f987154b014fb89a08787
（PHASE5_FINAL_MASTER，Phase 5 CLOSED / PASS 的 terminal state）

schemas:
55/55

DB:
v6

production_phase6_files_changed:
NONE（本任务书创建时）
```

---

# 1. Phase 6 目标

在 Phase 2/3/4/5 已验收能力之上，完成七个研究型工作流场景，并首次在受控边界内
启用 Graph→Research（只读）。Phase 6 不改变输出政策、不改变 Graph 写入权威链路、
不扩张本体与来源白名单。

```text
6A：industry_research（行业研究）、theme_discovery（主题挖掘）
6B：evening_brief（每日晚报）、daily_review（每日复盘）、stock_review（个股复盘）
6C：first_coverage（首次覆盖）、earnings_expectation（财报预期）
```

# 2. Phase 6 非目标

- 目标价、买入/卖出评级、增持/减持建议、仓位建议、明日交易建议、自动荐股；
- Scenario → active GraphNode / GraphEdge；
- 自动 ontology expansion、新增 node_type / relation / relation semantic change；
- 顺手扩张 source whitelist；
- 复制第二套 financial / valuation / evidence / LLM engine；
- 重构 Phase 2/3/4/5 已验收行为；
- 把 theme_discovery 做成自动荐股、first_coverage 做成券商评级、
  earnings_expectation 做成交易信号、daily_review 做成次日交易计划。

# 3. 并行治理拓扑（FROZEN，见 DECISIONS #41.2）

```text
P6-G0 顶层设计治理冻结（串行）
  ↓
P6-F0 Shared Contract Freeze（串行）
  ↓
F0 PASS 后：6A + 6B + 6C-PREP 可并行
  ↓
6A dependency gate PASS
  ↓
6C real first_coverage integration
```

依赖规则：

1. P6-G0 串行；
2. P6-F0 串行；
3. F0 PASS 后 6A + 6B + 6C-PREP 可并行；
4. 6C real first_coverage integration 依赖 6A stable industry interface
   （hard dependency）；
5. 6B 不 hard-depend on 6A；
6. 6A 不依赖 6B；
7. 6C 不 hard-depend on 6B；
8. shared control-plane enablement 必须串行。

# 4. 里程碑定义

## 4.0 P6-G0 —— Phase 6 Top-Level Design Governance Freeze（当前）

design/governance-only。交付：

- 工程指南升级 V1.2（第 69 节 6A/6B/6C 完整结构）；
- DECISIONS.md #41 正式设计决策；
- 本任务书创建（APPROVED / NOT_STARTED）；
- CURRENT_STATE / NEXT_PHASE / README / governance test 同步；
- 不实现任何 Phase 6 production scenario。

## 4.1 P6-F0 —— Shared Contract Freeze

**IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE（2026-08-09）**

共享契约冻结里程碑，串行执行。**已交付（2026-08-09）**：

- 七场景注册契约（scenario id / 输入输出 Schema / 报告 Front Matter / 运行记录）→ 冻结
  于 `docs/contracts/phase6-shared-contract.md` §2/§8/§20；
- Task 契约与 as_of 治理契约（Graph→Research 强制 as_of；6C forecast 三时间治理）→ §10/§11/§13；
- Graph→Research 只读接口契约（GraphQueryService / KnowledgeContextBuilder / read-only）→ §15/§18；
- KnowledgeContext != Evidence 血缘契约（evidence_ids → Evidence reload → validation）→ §14/§15/§16；
- 输出边界与禁止项校验契约（七场景统一）→ §23；
- 共享控制面修改清单（串行 enablement）→ §3/§7/§27；
- 机械保护测试 → `tests/unit/test_document_governance.py::test_phase6_shared_contract_frozen`。

F0 实现内容为契约文档 + 机械测试 + 状态同步，无业务代码、无中央 enable、无 migration。

F0 未 PASS 前，任何 6A / 6B / 6C 业务实现均 NOT_AUTHORIZED。

## 4.2 Phase 6A —— industry_research / theme_discovery

| 里程碑 | 内容 | 状态 |
|---|---|---|
| P6-A0 | 6A 顶层设计与场景契约细化 | NOT_AUTHORIZED |
| P6-A1 | industry_research 场景实现（6A 方法论全维度） | NOT_AUTHORIZED |
| P6-A2 | theme_discovery 场景实现（Theme Hypothesis 流程） | NOT_AUTHORIZED |
| P6-A3 | Graph→Research 只读接入（as_of 强制） | NOT_AUTHORIZED |
| P6-A4 | Research Capability Acceptance（只读研究能力验收） | NOT_AUTHORIZED |
| P6-A5 | Candidate Integration Authorization | NOT_AUTHORIZED |
| P6-A6 | optional candidate integration（Research → GraphChange Candidate） | NOT_AUTHORIZED |

6A 交付 6A stable industry interface 供 6C real integration 依赖。

## 4.3 Phase 6B —— evening_brief / daily_review / stock_review

| 里程碑 | 内容 | 状态 |
|---|---|---|
| P6-B0 | 6B 顶层设计与场景契约细化 | NOT_AUTHORIZED |
| P6-B1 | evening_brief 场景实现（08:00 → 20:00 incremental research） | NOT_AUTHORIZED |
| P6-B2 | daily_review 场景实现（observed_fact / previous_research_view / new_evidence / updated_interpretation / remaining_unknown） | NOT_AUTHORIZED |
| P6-B3 | stock_review 场景实现（增量复盘，不重跑完整 Phase4 研报） | NOT_AUTHORIZED |
| P6-B4 | Research Capability Acceptance | NOT_AUTHORIZED |
| P6-B5 | Candidate Integration Authorization | NOT_AUTHORIZED |
| P6-B6 | optional candidate integration | NOT_AUTHORIZED |

6B 不 hard-depend on 6A。

## 4.4 Phase 6C —— first_coverage / earnings_expectation

| 里程碑 | 内容 | 状态 |
|---|---|---|
| P6-C0 | 6C 顶层设计与场景契约细化（含 forecast 三时间治理） | NOT_AUTHORIZED |
| P6-C1 | earnings_expectation 场景实现（HYPOTHESIS / FORECAST，确定性算术用代码） | NOT_AUTHORIZED |
| P6-C2 | first_coverage PREP（编排层骨架 + 复用 Phase4/6A 接口） | NOT_AUTHORIZED |
| P6-C3 | **dependency gate**：6A stable industry interface PASS | NOT_AUTHORIZED |
| P6-C4 | first_coverage real integration（依赖 6A stable interface） | NOT_AUTHORIZED |
| P6-C5 | Research Capability Acceptance | NOT_AUTHORIZED |
| P6-C6 | Candidate Integration Authorization | NOT_AUTHORIZED |
| P6-C7 | optional candidate integration | NOT_AUTHORIZED |

6C 不 hard-depend on 6B；first_coverage 不得复制第二套
financial / valuation / evidence / LLM engine。

## 4.5 收尾

| 里程碑 | 内容 |
|---|---|
| P6-I0 | cross-track integration acceptance（6A/6B/6C 全场景联合验收） |
| P6-I1 | governance closeout（文档、状态、测试、版本收口） |

# 5. 永久治理边界（承接 DECISIONS #41）

- Graph→Research：READ ONLY，as_of REQUIRED，SQLite 唯一 authority，
  JSON mirror 非权威 deterministic read-only export。
- KnowledgeContext != Evidence；Graph FACT 进报告事实链必须经
  evidence_ids → Evidence reload → validation → Claim/ResearchFinding → Markdown。
- Graph 写入：`LLM can propose / LLM cannot approve；human can approve /
  human cannot bypass validator`；Scenario 不得直接写 active GraphNode / GraphEdge。
- Candidate 顺序：Research Capability Acceptance → Candidate Integration
  Authorization → Research → GraphChange Candidate。
- 时间治理：禁止 future knowledge leakage；历史研究只看 as_of 时刻合法有效的知识状态。
- Ontology / source：NOT_AUTHORIZED / PROHIBITED（见 DECISIONS #41.11）。
- 输出安全：七场景统一禁止目标价/评级/仓位/交易建议/自动荐股。

# 6. 不变性约束

- 不修改 Phase 2/3/4/5 已验收运行时行为；
- 不修改 schemas（除非 F0 契约评审在 DECISIONS 记录后另行授权）；
- 不新增 DB migration（当前 v6）；
- 不修改 ontology / source whitelist / Graph runtime authority。

# 7. 验收标准（每个里程碑）

- 正常 / 边界 / 失败测试齐备；
- `python -m pytest` 0 failed；
- `python -m research_os.cli.main validate` 全部 Schema 有效；
- `python -m compileall -q src tests` 通过；
- `git diff --check` 通过；
- 独立验收签字后才能推进下一里程碑；
- P6-G0 验收通过前，P6-F0 及其后一切业务实现保持 NOT_AUTHORIZED。
