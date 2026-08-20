# 下一阶段准入（NEXT PHASE）

## P8-B2-LIVE-01 Formal Trial — EXECUTED → PARTIAL（2026-08-20，RESUME-02）

正式 provider-backed trial 在 approved credential boundary（GitHub Actions
secret 已配置）下于 GitHub Actions `ubuntu-latest` 执行，结果 **PARTIAL**：

```text
TRIAL: P8-B2-LIVE-01（RESUME-02）
STATUS: PARTIAL（fail-closed evidence snapshot 已生成）
READINESS PROBE（trial 前）: READY — credential YES / connectivity YES / process cleanup VERIFIED
SESSIONS: completed 0 / 10（session_create_attempts=2, success=1）
TURNS: completed 0 / 20（turn_attempts=1）
PROVIDER_CALLS: 1 attempted（首次 provider-backed turn → PROVIDER_TIMEOUT，typed 单次计数，无重试）
TYPED_FAILURES: {PROVIDER_TIMEOUT: 1, HARNESS_BOOT_FAILED: 1}
  - 第 1 turn：session.prompt 未在 300s turn timeout 内完成 → PROVIDER_TIMEOUT
  - 第 2 session create：Harness 进程不再 READY（adapter.admit → HARNESS_BOOT_FAILED）→ latch 触发 → fail-closed 停止
PROCESS: root TERMINATED / owned tree VERIFIED / residue NO / leak 0
SECRET: secret_scan PASS（0 markers）；artifact/log/diff 三扫描 CLEAN
DRILLS: rollback PASS / crash-restart PASS / legacy fallback PASS
MCP: research-os-mcp/v1；恰好 2 tools；0 unauthorized；0 authority drift
FORMAL_CORPUS_EXECUTED: YES（bounded、provider-backed、20-turn corpus 未完成）
```

NEXT ACTION：

```text
1. Sol 独立验证 LIVE-01 PARTIAL evidence（frozen snapshot + artifact + 本报告）；
2. 调查首次 provider-backed turn 的 PROVIDER_TIMEOUT（DeepSeek 响应延迟 vs dsh 进程稳定性），
   以及 timeout 后 Harness 进程未恢复 READY 的行为；
3. 依据调查结果按 LIVE-00 边界重新执行 LIVE-01（不修改 acceptance criteria / trial contract）；
4. 在正式 corpus 完成并经独立验收前，P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-LIVE-01-REPAIR-01 — 根因已定位并修复（2026-08-20）

调查结论（详见 `docs/tasks/p8-b2-live-01-repair-01-timeout-diagnosis.md`）：

```text
ROOT CAUSE: 我方 stdio MCP server（scripts/p8_b1_mcp_server.py）initialize 回复
  protocolVersion "1"；pinned Harness 的 MCP SDK（@deepseek-ai/dsh-mcp-client，
  @modelcontextprotocol/sdk 1.30.0）只接受日期版协议
  （2025-11-25 / 2025-06-18 / 2025-03-26 / 2024-11-05 / 2024-10-07）
  → "Server's protocol version is not supported: 1" → failOnStartupError
  → dsh 进程以 exit code 1 崩溃 → turn 失败（被 _rpc 映射为 PROVIDER_TIMEOUT）
  → supervisor FAILED → HARNESS_BOOT_FAILED。
  NOT provider latency：修复后完整 tool-calling turn 仅 22.7s。
HARNESS_RECOVERY: HARNESS_BOOT_FAILED 是预期 fail-closed 行为（进程死亡检测 →
  admit 拒绝 → latch），机制正确；缺陷在协议协商（上述）。
FIX（最小，已实施）: contracts.py 新增 negotiate_mcp_protocol_version（echo 受支持
  版本，否则回退 2024-11-05）；stdio server initialize 使用协商结果；
  新增 5 个离线单元测试。namespace / tools / failure semantics / budgets 不变。
VALIDATION: 有界单 turn 诊断（真实 provider，非 corpus）修复前 TURN_FAILED 2.6s +
  进程 exit 1；修复后 TURN_COMPLETED 22.7s + 进程存活 + supervisor READY。
NEXT: Sol 验证 REPAIR-01 后，重新执行 P8-B2-LIVE-01（10 sessions / 20 turns，
  同一 LIVE-00 边界；正式 corpus 尚未重新执行）。
```

## P7-D4 当前状态与后续顺序（2026-08-19）

P7-D4 已于 2026-08-19 完成独立验收并 no-squash 合并进 master（accepted baseline
`8b153b3`，GOV-MERGE-P7D4-01）。GOV-ARUX1 governance freeze（Decision #54 / #55）
已随同一 merge 进入 master。

后续顺序冻结：

```text
1. P8-B1 DeepSeek Harness Production Foundation
2. P8-B1 independent acceptance
3. P8-B2 is implemented but remains PARTIAL / NOT ACCEPTED (P8-B2-R2 evidence-integrity repair delivered)
5. D5 / 后续数据能力按新路线继续
```

明确：

```text
P8-A0: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P8-B1: CLOSED / PASS / INDEPENDENTLY ACCEPTED
PRODUCTION ADOPTION: NOT_AUTHORIZED
D5: 不得因为本次设计自动开始
FRONTEND IMPLEMENTATION: NOT_AUTHORIZED（后续须独立 frontend taskbook）
```

不得直接进入 Harness implementation。

可以记录：Frontend foundation 可在未来与部分数据阶段解耦实施，但 AI Research
session integration 必须兼容最终 Harness boundary。

## P8-B Design Handoff

P8-B design documents are independently accepted on `9aa7071`. The authorized
next task is the separate P8-B1 Production Foundation taskbook. P8-B2 remains
not authorized.

## 当前结论

- **Phase 4 engineering foundation：PASS**
- **Phase 4 full research capability：PASS（独立验收 SHA `9506f6a`）**
- **Pre-Phase-5 Offline CI Gate：PASS**
- **Phase 5 taskbook：APPROVED**
  - 任务书路径：`docs/tasks/phase5-industry-knowledge-graph.md`
  - 正式设计决策：`DECISIONS.md` #30
- **Phase 5 implementation：PASS**（terminal state，不重新打开）
  - M0：PASS（SHA `df358da`，M0 Offline CI `31159354574` PASS）
  - M1 Graph Contracts：PASS（SHA `b097996`，M1 CI `31165533237`：1281 passed / 5 skipped / 55/55 schemas）
  - M2 Persistence and ontology seed：PASS（SHA `565d500`，M2 CI `31171415215`：1351 passed / 5 skipped / 55/55 schemas）
  - M3 GraphChange Candidate Pipeline：PASS（SHA `242e039`，M3 CI `31240709634`：1480 passed / 5 skipped / 55/55 schemas）
  - M4 Knowledge Validator：PASS（SHA `20b7a15`，M4 CI `31241777234`：1611 passed / 5 skipped / 55/55 schemas）
  - M5 Human Review Workflow：PASS（SHA `92649a7`，M5 CI `31251491357`：1725 passed / 5 skipped / 0 xfail / 55/55 schemas）
  - M6 Deterministic Apply Engine：PASS（SHA `480b209`，CI `31257395650`，1809 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M7 Supersede / Expire / History：PASS（SHA `651e9a1`，CI `31262745492`，1911 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M8 Query + Knowledge Context Builder：PASS（SHA `eac18e2`，CI `31269460005`，2009 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M9 Structured Research Candidate Integration：**PASS**（SHA `d097ca8`，CI `31275096225`，2068 passed / 5 skipped / 0 xfail / 55/55 schemas，DB v6 不变）
  - M10 Deterministic JSON Mirror + E2E Acceptance：**PASS**（accepted SHA 156ea35, CI 31292861813, 2110/5/0/0）

Phase 5 正式任务书已由用户批准。M1-M9 全部通过独立架构验收。
PR5B 已 squash merge 进入 master（`cfdeeba7`）。

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

**PR5B 已 squash merge。用户已于 2026-08-09 明确授权 M9。M9 已通过独立验收（2026-08-09）。**

```
Phase 5 implementation authorization gate: SATISFIED
```

当前状态：**M10 PASS**。PR5C #6 MERGED / SQUASH。JSON Mirror Option A PASS。

PR5B closeout 已完成：

```text
PR5B closeout CI: 31270208169 PASS
→ 独立复核 → 用户批准 merge
→ squash merge PR5B → master cfdeeba7
→ 从 master 创建 PR5C phase5/pipeline-integration
```

M9 scope：existing structured research objects → GraphChange candidate。
Graph→Research NOT implemented in M9。

当前状态：
PR5B MERGED（master cfdeeba7）。
PR5C #6 MERGED。
M0-M10 PASS。
Phase 5: CLOSED / PASS

## Phase 6 terminal state and current limited authorization

- **Phase 6**: CLOSED / PASS
- **Phase 6 research capability**: PASS
- **Phase 6 central enablement**: PASS
- **USER_TRIAL_READY**: YES
- **CURRENT ENGINEERING MILESTONE**: P8-B DeepSeek Harness Production Adoption Design（P8-A0 independently accepted at `f16a3163814345e9aee2d00615a42dae57fd86fb`）
- **Phase 6.1 Research→GraphChange Candidate Integration**: DEFERRED / NOT_AUTHORIZED
- **Phase 7**: D0 CLOSED / PASS；D1 CLOSED / PASS；UX1 CLOSED / PASS；D2 Foundation PASS / INDEPENDENTLY ACCEPTED；D3 MVP PASS / INDEPENDENTLY ACCEPTED（Decision #52，accepted head `e8a4a9f`）
- **P7-UX1**: CLOSED / PASS / INDEPENDENTLY ACCEPTED（Decision #46.7；governance closeout 2026-08-10）
- **P7-D0**: CLOSED / PASS / INDEPENDENTLY ACCEPTED（Decision #47.8/#47.9；accepted head d06d8d7）
- **P7-D1**: CLOSED / PASS / INDEPENDENTLY ACCEPTED（Decision #48.10/#48.11；accepted head `bc27781`；CI `31899546501`）
- **P7-D2 FOUNDATION**: PASS / INDEPENDENTLY ACCEPTED（Decision #50；accepted head `55c4ba5`）
- **P7-D3 MVP**: PASS / INDEPENDENTLY ACCEPTED（Decision #52；accepted head `e8a4a9f`；已合并进 master）
- **REAL DATA ACQUISITION COVERAGE**: macro_data（nbs）/ company_announcement（cninfo）WORKFLOW_WIRED；BUSINESS_SUFFICIENT 待治理 closeout
- **Current Schema registry**: 86（Phase 6 terminal historical snapshot was 69）
- **DB / migrations**: v6 / NONE
- **FINAL IMPLEMENTATION / VALIDATION HEAD**: `84f70b5dec1a65c9842628c974e1693738ab9cca`（independent acceptance head `55c4ba5`）
- **OFFLINE CI**: SUCCESS — run `31945487755`（Ubuntu / Python 3.12.13）
- **NEXT WORK**: Implement P8-B1 foundation and independently accept it; keep P7-UX1 as the legacy fallback path
- **REAL-SOURCE AUTHORIZATION**: NONE

Phase 6 completion itself did not authorize Phase 6.1 or Phase 7。P7-UX1 is now separately
authorized by its approved taskbook and Decision #46, but that authorization is limited to the
local conversational control-plane adapter. It does not authorize P7 data acquisition, Phase 6.1,
Graph write, source expansion, collector work, or database migration.

P7-UX1 已通过独立验收并完成 governance closeout（PASS / INDEPENDENTLY ACCEPTED）。
该 terminal 状态不授权 P7 数据采集、Phase 6.1、Graph write、source expansion、collector
work 或 database migration。

P7-D1 已通过独立复验（Decision #48.10/#48.11），状态为 `CLOSED / PASS /
INDEPENDENTLY ACCEPTED`。accepted implementation head 为 `bc27781`，PR #25
已获 merge authorization，但当前仍 OPEN / NOT MERGED。

P7-D2 Foundation 已于 2026-08-18 通过独立验收（Decision #50，PASS / INDEPENDENTLY ACCEPTED，
accepted head `55c4ba5`）：

```text
P7-UX1: CLOSED / PASS
P7-D0: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P7-D1: CLOSED / PASS / INDEPENDENTLY ACCEPTED
P7-D2 FOUNDATION: PASS / INDEPENDENTLY ACCEPTED（2026-08-18）
REAL DATA ACQUISITION COVERAGE: NONE
→ D1（PR #25 已授权）与 D2 合并进 master
→ 从新 master 建立 P7-D3 工程基线（Free-Source Production MVP：nbs / cninfo）
→ real source execution / production collector IDs / capability promotion: 须 P7-D3 授权
→ Phase 6.1: NOT AUTHORIZED
```

Foundation 的独立验收不得自动授权真实来源。任何 real-source execution 仍须新的来源治理、
验证、taskbook、架构批准与显式 implementation authorization。

P7-D3 已于 2026-08-18 通过独立验收（Decision #52，PASS / INDEPENDENTLY ACCEPTED，
accepted head `e8a4a9f`，已合并进 master）：

```text
P7-D3 MVP: PASS / INDEPENDENTLY ACCEPTED（2026-08-18）
REAL_SOURCE_E2E: nbs → macro_data；cninfo → company_announcement（真实网络验收）
DEFAULT_NETWORK: OFF；LIVE_DATA_GATE: --live-data（dry-run 零落盘）
CAPABILITY: WORKFLOW_WIRED（BUSINESS_SUFFICIENT 待治理 closeout，NBS/CNINFO 分开）
→ 从新 master 建立 P7-D4 工程基线（CNINFO 年报 → company_document → derive_existing → 核心 FinancialFact）
→ Phase 6.1: NOT_AUTHORIZED
```

D3 验收 PASS 只授权合并与后续 P7-D4 实施；不授权新增来源、Collector、付费接口、
OCR、LLM 财务提取、Graph write、Phase 6.1、DB migration、新 Schema。

## Phase 4 独立验收记录

- 独立验收结论：`PASS`；验收 SHA：`9506f6a19ab60187d1ab0bc4991cfa427606ecae`；
- 600519.SH 与 300750.SZ 的 Task→Plan→Request→Run→Evidence→报告血缘通过复核；
- 688981.SH 受控缺失未被提升为 success；
- DeepSeek 间歇性超时仍按 8/1 共享预算降级，且日志无凭证泄漏；
- 保持分钟行情、自动历史日线、通用 OCR 和深度媒体等未验证能力为明确限制。

## P8-B2-LIVE-01-RESUME-03 — Corpus Completed; PARTIAL on usage evidence gate（2026-08-21）

REPAIR-01 修复后正式 trial 重新执行（run `32391248096`，GitHub Actions
ubuntu-latest，approved credential boundary）：

```text
CORPUS: COMPLETED — sessions 10/10，turns 20/20（turn_attempts=20, completed=20）
EVIDENCE: same_session_pass=20 / turn2_reread_pass=10 / turn1_evidence_pass=10
  authority_drift=0 / unauthorized=0 / secret_leak=0（secret_scan=PASS）
  provider_failures=0 / mcp_failures=0 / typed_failures={}
  process_residue=NO（root TERMINATED / tree VERIFIED）/ drills PASS
  latency p50=6218ms p95=8767ms / session_create 10/10
REPAIR-01 验证目标：全部达成（Harness 稳定、20/20 provider-backed turns 完成、
  session/turn evidence 完整、process cleanup VERIFIED、failure semantics 0 失败）
STATUS: PARTIAL — 唯一未过的 PASS gate：provider_tokens > 0
  （total_tokens=NOT_REPORTED：accepted runtime 在 projections.values.tokenUsage
  以 dsh 特有键名报告 usage — uncachedInputTokens/outputTokens/cacheReadTokens/
  cacheWriteTokens — 而 _extract_usage 未映射这些键；属 usage 提取映射缺口，
  与 REPAIR-01 同类，需 REPAIR-02 taskbook 最小修复；非 contract/推断问题）
NEXT ACTION:
  1. Sol 独立验证 RESUME-03 evidence（frozen snapshot + artifact）；
  2. REPAIR-02：扩展 _extract_usage 映射 dsh tokenUsage 键（provider-reported，
     非推断），新增离线测试；
  3. 修复后按 LIVE-00 边界重新执行 LIVE-01（RESUME-04）。
  4. 在正式 corpus 通过全部 gate 并经独立验收前，P8-B2 保持
     IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```
