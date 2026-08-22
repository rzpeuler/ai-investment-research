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

## P8-B2-LIVE-01-REPAIR-02 — Usage Evidence Extraction Fixed（2026-08-21）

根因与修复（详见 `docs/tasks/p8-b2-live-01-repair-02-usage-evidence.md`）：

```text
ROOT CAUSE: accepted runtime（dsh rc.7）在 projections.values.tokenUsage 以
  camelCase 键名报告 usage（uncachedInputTokens / outputTokens /
  cacheReadTokens / cacheWriteTokens），_extract_usage 未识别 →
  total_tokens = NOT_REPORTED → provider_tokens = 0 → PASS gate 未过。
FIX（最小，已实施）: _extract_usage 增加 dsh 字段映射 —
  input_tokens = uncached + cacheRead + cacheWrite；output_tokens = output；
  cached_tokens = cacheRead + cacheWrite；cache_read/write_tokens 单独暴露；
  total_tokens = uncached + output + cacheRead + cacheWrite。
  仅使用 provider-reported 值，无推断/估算/硬编码；9 个离线回归测试。
VALIDATION（真实运行时，有界单 turn）: 修复后 EXTRACTED_USAGE =
  {input 23201, output 587, cached 10624, cache_read 10624, cache_write 0,
  total 23788} → provider_tokens > 0 = TRUE。
GOVERNANCE FINDING（需 Sol 决策）: 实测每 turn 用量 ~24-44k tokens；
  20 turns ≈ 480-880k，超过冻结的 max_provider_tokens = 200,000 →
  下一次正式 trial 将在约第 5-9 turn 如实触发 RESOURCE_BUDGET_EXCEEDED。
  budget 属冻结 cost control，本任务未修改；Sol 需在重新执行前就
  max_provider_tokens 作出治理决定。
NEXT: Sol 验收 REPAIR-02 + budget 决策 → 按 LIVE-00 边界重新执行正式 trial
  （新 RESUME taskbook）。P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-LIVE-01-BUDGET-DECISION-01 — Token Budget Boundary Decided（2026-08-21）

治理决策（详见 `docs/tasks/p8-b2-live-01-budget-decision.md`）：

```text
OBSERVED: 每 provider-backed turn 23.8k–44.3k tokens（dsh rc.7 tokenUsage，
  provider-reported；REPAIR-02 / RESUME-03 真实观测）
DERIVED: 20 turns ≈ 476k–886k tokens
CURRENT: max_provider_tokens = 200,000（LIVE-00 §5.6，设计期无真实证据设定）
OPTIONS:
  A（保持 200k）: 第 5–9 turn 触发 RESOURCE_BUDGET_EXCEEDED → corpus 无法完成
    → 正式 acceptance 物理不可达；拒绝
  B（提高）: 评估 500k（高端不足）/ 1,000,000（高端 +13% 余量，推荐）/
    2,000,000（余量过大，削弱有限预算意图）
  C（减少 turn）: 改变已验收 acceptance corpus = 降低标准；决策规则禁止；拒绝
DECISION: Option B — max_provider_tokens 200,000 → 1,000,000
  （warning 0.8 → 800k；最大成本有界 ≤1M tokens；仅 provider-reported；
  acceptance gate / failure semantics / retry / timeout / concurrency 不变）
IMPLEMENTATION: TrialBudget 值变更 = ARCHITECTURE_DECISION_REQUIRED →
  后续授权 taskbook（BUDGET-IMPL）实施，本任务无代码修改
NEXT: Sol 验收本决策 → BUDGET-IMPL taskbook → 按 LIVE-00 边界重新执行正式 trial
  （新 RESUME）。P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-LIVE-01-BUDGET-IMPL-01 — Budget Value Implemented（2026-08-21）

```text
IMPLEMENTED: TrialBudget.max_provider_tokens 200,000 → 1,000,000
  （src/research_os/agent_runtime/trial.py；依据 BUDGET-DECISION-01 Option B）
SYNCED: docs/tasks/p8-b2-live-00-trial-boundary-design.md §5.6（1,000,000 +
  decision 依据）；test_trial_budget_is_explicit_and_bounded 增加 1,000,000 断言
UNCHANGED: max_sessions 10 / max_turns 20 / max_tool_calls 60 / max_retries 0 /
  turn_timeout 300s / warning_ratio 0.8 / concurrency 1 / failure semantics /
  acceptance gate / provider boundary
NEXT: Sol 验收 BUDGET-DECISION + BUDGET-IMPL → 按 LIVE-00 边界重新执行正式 trial
  （新 RESUME taskbook）。P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-INTERNAL-TRIAL-001 — Harness 内部试运行验证（2026-08-21）

```text
AUDIT: 唯一 AI 入口 = LlmClient；无第二套 AI 路径；默认 provider = legacy 直连
  （冻结）；evening_brief/stock_review/industry_research 无 LLM（llm_called:false 诚实标记）
IMPLEMENTED: HarnessLlmProvider（opt-in P8_B2_SCENARIO_TRIAL=1，LlmClient 后置
  控制面，默认不变）+ provider_factory harness= opt-in + 5 场景验证脚本 +
  14 个离线测试 + CI workflow
VERIFICATION: 5 场景验证（first_coverage/earnings_expectation 真实
  EquityLlmTasks→Harness→DeepSeek；3 个确定性场景诚实 no-LLM）— 结果见验收报告
RISKS: 默认 runtime 未切换（P8-B3 未授权）；Harness 模型路由粒度受限；
  确定性场景语义模块未连接（未来 taskbook）
NEXT: Sol 验收本任务 → Production Adoption 决策（P8-B3）另行授权。
  P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R1 — Harness 输出契约稳定化（2026-08-21）

```text
PROBLEM: Harness 输出与 Sol 严格 schema 不匹配 → schema-valid success = 0/6
FIX: Deterministic Output Normalizer（unwrap / key conformance / prune；
  不发明字段、不改值、不降标准）+ Harness 路径 prompt 指令强化 +
  audit 新增 resolved_model_id（observed profile model: deepseek-v4-flash）
VERIFICATION（run 32440917679, SUCCESS）: schema-valid success = 1 > 0 ✓
  - earnings_expectation:catalyst_candidates 经真实 Harness 通过严格
    catalyst schema（errs=0）
  - 其余任务诚实回退（值级 UNKNOWN / 无 JSON / 预算耗尽），无伪造
  - 27 个离线测试；full pytest / schema / compileall / CI 全绿
REMAINING RISK（更新）: 多数任务仍因值级问题或无语义 JSON 回退（模型行为
  问题，非适配层缺陷）；默认 runtime 仍 legacy；P8-B3 未授权
NEXT: Sol 验收 R1 → Production Adoption 决策另行授权。
  P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-EVAL-001 — Harness Quality Benchmark 建立（2026-08-21）

```text
BUILT: benchmark corpus（13 cases：5 equity + 5 research + 3 failure，
  与 LIVE-01 完全解耦）+ runner（scripts/run_harness_benchmark.py）+
  metrics collector + 阈值评估 + reports/harness_benchmark_latest.json
FIRST RUN（run 32444324435, SUCCESS）:
  schema_valid_rate = 0.10（1/10）— 未达 0.70 门槛（NOT_MET）
  legacy reference = 0.80（同 cases）→ 客观量化 harness 与 legacy 差距
  其余阈值全 MET（fake MODEL_INFERENCE=0 / validator bypass=0 /
  audit completeness=1.0 / budget violation=0 / secret leakage=0 /
  silent retry=0）
  failure cases 3/3 诚实回退；full pytest 3824 passed / 0 failed
P8-B3 建议: 暂不进入 — schema_valid_rate 未达门槛；需 harness 输出符合率
  专项提升后重跑 benchmark；判断规则 = Benchmark PASS + LIVE-01 PASS +
  成本评估 + 人工体验确认 → P8-B3 Decision
NEXT: Sol 验收 EVAL-001 → harness 输出符合率专项 → 重跑 benchmark。
  P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R3 — Harness Agent 输出优化（2026-08-21）

```text
FAILURE ANALYSIS（EVAL-001 artifact）: 9/10 失败 = 5 json_format_failure +
  4 missing_required_field；根因在 Harness Agent Output Layer
OPTIMIZATION: Schema-aware Context Injection（JSON-only 指令强化 + 必填字段
  清单 + 字段约束摘要 + 确定性合法示例 + 任务/证据上下文）—
  schema_context.py + harness provider 接入；Schema/Validator/Normalizer/
  threshold 未变
FAILURE CLASSIFICATION: json_format_failure / missing_required_field /
  enum_violation / value_format_violation 加入 benchmark
BENCHMARK BEFORE/AFTER（run 32447199752）:
  schema_valid_rate 0.10 → 0.50（5/10）— 阶段目标 ≥0.30 达成 ✓
  legacy 对照 0.90；其他阈值全 MET（无伪造/无旁路/审计完整/预算/secret/
  silent retry）
  remaining: 4 missing_required_field + 1 json_format → P8-B3 门槛 0.70 未达
P8-B3 建议: 暂不进入 — 下一轮优化（必填字段强制/示例对齐）后重跑 benchmark
NEXT: Sol 验收 R3 → 下一轮输出优化 → 重跑 → 达 0.70 后再评估 P8-B3。
  P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R4 — Harness Schema Adherence Optimization（2026-08-21）

```text
IMPLEMENTED: task schema slice + required completion checklist + self-validation
  instruction + field-level missing stats（benchmark 增强）
EMPIRICAL ITERATION（同 corpus 13 cases, 4 runs）:
  R3 结构（完整 schema+约束+示例）: 0.5 / 0.4（测量最优）
  R4 slice-only: 0.3
  R4 组合（+checklist+自检）: 0.2 / 0.2（系统性回归，已回退）
RESULT: schema_valid_rate 0.50 → 0.40（R3 结构重测）；目标 ≥0.70 未达成
FAILURE FIELD STATS: finding_id 等 20 个必填字段各缺失 ×5 cases —
  系统性字段完成度问题，prompt 级指令无法修复
P8-B3 建议: 暂不进入 — 允许的 prompt 杠杆已到测量上限；0.70 需超出本任务
  范围的杠杆（profile/模型策略、结构化输出强制、测量方法治理 — 均属治理/
  架构决策）
NEXT: Sol 验收 R4 → 治理决策下一杠杆方向。P8-B2 保持
  IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R5 — Harness Generation Control 架构设计（2026-08-21）

```text
DESIGN（无代码实现）: 下一代 Generation Control 架构 —
  Generation Controller（provider 包装层，预算/审计/降级单入口保持）
  + Validation Layer（既有 Validator 不变，字段级错误作为修复输入）
  + Repair Layer（有界修复轮次，证据锚定）
  + Provider Adapter（Harness/legacy；JSON-mode 探测互补）
方案: B Validator-driven repair loop（推荐，核心）+ C structured-output
  探测（互补）+ A multi-pass（备选）
阶段: R5-A controller+repair 实现 → R5-B JSON-mode 探测 → R5-C multi-pass
  备选 → R5-D benchmark 重跑 + P8-B3 评估
NEXT: Sol 验收设计 → R5-A 实现 taskbook。P8-B2 保持
  IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R5-B probe result (2026-08-21)

The structured-output capability probe did not establish provider support: the
pinned Harness adapter has no provider-level structured-output method, and the
bounded real probe timed out before the normal/structured comparison. Keep
structured mode probe-only. R5-C is not recommended until the provider exposes
and documents a supported structured transport.

## P8-B2-R5-D — Harness Benchmark Reevaluation (2026-08-21)

The 13-case fixed corpus completed with benchmark-only case timeout 20s and
global timeout 900s. Preflight/health passed, cleanup passed with no process
residue, and report `reports/harness_benchmark_r5d.json` records:
schema_valid_rate `0.10` vs R3 `0.50`, JSON format failures `6` vs R3 `1`,
recovery success `1/10`, repair success `1.0` for one repaired case, provider
calls `15`, token usage `0`, and latency p50 `19.656s`. The `0.70` P8-B3 gate
is `NOT_MET`; fake inference, validator bypass, audit, budget and secret gates
passed. Do not enter P8-B3; no corpus or threshold changes are authorized.

## P8-B2-R5-C — JSON Boundary Recovery Implementation (2026-08-21)

Implemented as a bounded deterministic adapter. Recovery supports whitespace /
BOM, one Markdown JSON fence, and one unique surrounding JSON object. It does
not perform syntax repair, field completion, value conversion, or validator
bypass. Targeted tests and schema/compile validation passed. Full Windows
pytest timed out at 10 minutes, and the live Harness benchmark was blocked;
therefore no live before/after claim is made.

Next: run the same fixed benchmark in an environment with a bounded provider
credential/runtime, then decide R5-D. R5-D is not entered by this commit.
P8-B2 remains `IMPLEMENTED / PARTIAL / NOT ACCEPTED`; P8-B3 remains
`NOT_AUTHORIZED`.

R5-C design is complete, but no code implementation is authorized in this
task. The recommended next implementation, if separately approved, is a pure
bounded recovery adapter between raw provider output and the unchanged
Validator. It must only recover an unambiguous strict JSON boundary, preserve
all values and fields, and record recovery outcomes in audit. No schema,
validator, threshold, provider routing, or default runtime change is planned.

R5-D is not entered. Next action requires a separate implementation task with
taxonomy tests, fixed-subset comparison, and a benchmark artifact reporting
format failures separately from schema validity. P8-B2 remains
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`; P8-B3 remains `NOT_AUTHORIZED`.

## P8-B2-R5-A — Generation Controller 实现（2026-08-21）

```text
IMPLEMENTED: GenerationControlledProvider（provider 包装层，有界
  generate-validate-repair loop，max_repair_passes=2）+ repair.py（字段级
  错误提取 + 修复 prompt）+ audit 扩展（generation_pass/repair_round/
  provider_calls/validation_error_summary）+ benchmark repair metrics
TESTS: 9 个 fake-provider 测试；run 内 full pytest 3840 passed / 0 failed；
  schema 86/86
BENCHMARK（run 32460687556）: schema_valid_rate 0.3（方差带内）；
  missing_required_field 3-5 → 0（repair 完全消除该类失败）；json_format
  5（fallback 类）；repair metrics: success 0.333 / avg rounds 1.67 /
  added calls 10；0.70 未达（本任务不要求）
NEXT: Sol 验收 → R5-B（Harness JSON-mode 探测，针对 json_format 主导失败）
  → R5-D benchmark 重跑。P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-B2-R6 — Harness Generation Strategy Evaluation（2026-08-21）

```text
EVALUATION/DESIGN（只设计，不实现；无 runtime 切换）:
  任务级 Runtime Selection Strategy — 从 R5-D 证据（harness 0.10 vs legacy
  0.90 schema_valid_rate）出发，按任务类型（extraction / normalization /
  reasoning / generation）给出 runtime 建议：
  - strict_schema 输出 → LEGACY_ONLY（legacy 0.90；harness json_format 主导）
  - 工具 / 多轮 / 开放探索 → HARNESS_CANDIDATE（governance 白名单；LIVE-01
    20/20 会话可靠；需独立评估指标，不套用 schema_valid_rate）
  - HYBRID = Harness 探索 + Legacy 成稿（两阶段，各 phase 单独走规则）
  Task Runtime Router 已设计（确定性、默认 legacy、audit runtime_selection、
  治理策略表配置工件），未实现。
NEXT: Sol 验收 R6 → 若认可 HARNESS_CANDIDATE 领域，另立独立 taskbook 建立
  "Harness 探索能力评估"（新指标 + 新 corpus，与 EVAL-001 解耦）。
  P8-B3 结构化生成默认路径维持 legacy；P8-B3 保持 NOT_AUTHORIZED。
  P8-B2 保持 IMPLEMENTED / PARTIAL / NOT ACCEPTED。
```

## P8-ARCH-001 — Harness Hybrid Runtime Architecture Freeze（2026-08-21）

```text
GOVERNANCE FREEZE（只改文档；production code 0 changes）:
  DeepSeek Harness Hybrid Runtime Architecture 正式冻结
  （DECISIONS #80；docs/architecture/harness-hybrid-runtime-architecture.md；
  engineering-guide V1.9 §0.9）。
  - Harness = Agent Orchestration Runtime（Conversation / Durable Session /
    Goal Management / Skill Loading / Tool Scheduling / Exploration Workflow）；
    不是默认严格结构化生成 runtime（benchmark harness 0.10 vs legacy 0.90）
  - Research OS = Research Intelligence Authority（身份/就绪/采集/证据/PIT/
    图谱/工作流/Validator/报告）
  - LLM: 保留 research_os.llm；禁止因接入 Harness 重写 LlmClient
  - MCP: Harness → MCP → Research OS Tools；禁止直连 Data Source/Collector/
    DB/Graph Write
  - Skill = 能力说明+工作方法+routing metadata；Tool = 受治理可执行接口
  - 状态: HARNESS_ARCHITECTURE=DESIGN_FROZEN / HARNESS_IMPLEMENTATION=
    NOT_IMPLEMENTED / PRODUCTION_ACCEPTANCE=NO
NEXT: D4 已完成（ACCEPTED / MERGED 2026-08-19，范围不变）→ 后续独立授权
  P8-A0 Hybrid Agent Runtime Spike（最小范围，另行 taskbook）→ 独立架构验收
  → 再决定 Harness production adoption。默认 runtime 保持 legacy；
  P8-B3 / production adoption 保持 NOT_AUTHORIZED。
```

## P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE — Hybrid Runtime Spike（2026-08-21）

```text
SPIKE EXECUTED（最小 Hybrid Runtime Spike；Harness + Skills + MCP + Research
  OS Tools 形成完整研究闭环）:
  - Harness runtime: pinned @deepseek-ai/dsh@0.1.0-rc.7 启动/session create/
    resume 验证通过（宿主 Windows；Node 24；DEEPSEEK_API_KEY 可用）
  - MCP facade: 4-tool spike surface（get_company_profile / check_data_readiness
    / query_industry_graph / run_research_scenario）；冻结 2-tool 契约为默认，
    spike 为 env-gated opt-in（P8_A0_HYBRID_SPIKE=1）
  - Skills: stock-research / financial-analysis / industry-graph-research 可发现
    并加载（使用场景 + Tool 选择 + 工作方法；无业务代码）
  - Session: 真实连续 4-turn 会话执行（研究宁德时代 → 现金流 → 产业链风险 →
    比较亿纬锂能）；session continuity / tool invocation chain / audit 记录
  - Authority: 无 source 直连 / 无 graph write / 无 evidence 修改 /
    无 validator bypass；secret scan 0
  - 测试: tests/unit/test_p8_a0_hybrid_spike.py；full pytest 2828 passed /
    4 skipped / 0 failed；schema 86/86
  - 报告: docs/architecture/p8-a0-hybrid-runtime-spike-report.md +
    reports/p8_a0_hybrid_spike.json
NEXT: Sol 独立验收 spike（MCP 4-tool 表面 / Skill 定义 / Session 结果 /
  Authority）→ 在 POSIX CI（ubuntu）重跑取得 process_residue=NO 的机械证据
  → 若通过，独立 taskbook 授权 P8-A1（Hybrid Agent Runtime 正式设计/实施
  评估；范围仍保持 legacy 默认，Harness 仅限白名单探索类任务；不将 Harness
  作为默认严格结构化生成 runtime）。默认 runtime 保持 legacy；
  P8-B3 / production adoption 保持 NOT_AUTHORIZED。
```

## P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN — Hybrid Agent Runtime Pilot Design（2026-08-22）

```text
DESIGN COMPLETE（设计任务；production code 0 changes；默认 runtime 保持
  legacy；Harness 保持 opt-in）:
  Hybrid Agent Runtime 生产试点设计（DECISIONS #82；
  docs/architecture/p8-a1-hybrid-pilot-design.md）:
  - 核心原则: Exploration → Harness；Structured Research Output → Legacy
  - Task Classification: HARNESS_ALLOWED（industry exploration / research
    preparation / evidence discovery assistance / multi-turn analyst
    assistant / hypothesis generation；输出不直接成为正式 Research Artifact）
    vs LEGACY_REQUIRED（FinancialFact / ResearchFinding / Catalyst / Risk /
    Evidence binding / Final report sections；需严格 Validator）
  - Runtime Router: 确定性（非 LLM 决策）；输入 task_type / output_contract /
    risk_level / authority_requirement → LEGACY_ONLY / HARNESS_ALLOWED /
    HYBRID；默认 LEGACY_ONLY；白名单为配置工件
  - Permission Model: ALLOW（company profile / graph query / data readiness /
    bounded scenario trigger）vs DENY（graph write / evidence mutation /
    financial fact creation / datasource direct access）
  - Session Governance: session lifetime 有界；区分 LLM request 60s / agent
    turn 300s（P8-A0 实测 180s 不足）/ tool 30s；token budget provider-reported
    ≤ 治理上限（如 1M/会话）
  - Audit Boundary: runtime_selection / harness_session_id / skill_used /
    tools_called / authority_checks / final_artifact_source
  - Pilot Acceptance Criteria: Reliability / Governance / Value / Cost
NEXT: Sol 验收 P8-A1 设计 → POSIX CI（ubuntu）重跑 P8-A0 spike 取得
  process_residue=NO 的机械证据 → 独立 taskbook 授权 P8-A2（生产试点实施：
  Runtime Router 配置工件 + 权限表落地 + audit 字段扩展 + 试点 corpus）。
  P8-A2 不切换默认 runtime；不删除 Legacy；不改 LlmClient / Schema /
  Validator。P8-B3 / production adoption 保持 NOT_AUTHORIZED。
```

## P8-A2-HYBRID-AGENT-RUNTIME-PILOT-IMPLEMENTATION — Hybrid Agent Runtime Pilot（2026-08-22）

```text
IMPLEMENTED（生产试点基础设施；默认 runtime 保持 legacy；Harness 仅白名单
  opt-in；DECISIONS #83）:
  - Runtime Router（agent_runtime/runtime_router.py）：确定性、无 LLM；
    task_type/output_contract/risk_level/authority_requirement →
    LEGACY_ONLY/HARNESS_ALLOWED/HYBRID；strict_schema 强制 legacy；未列入
    白名单默认 legacy（fail-closed）
  - Runtime Policy（config/runtime_policy.yaml v1.0.0）：配置驱动；exploration
    白名单 5 项；default/strict_schema 均强制 legacy；LEGACY_REQUIRED 禁止入白名单
  - Permission Policy（agent_runtime/permission_policy.py）：fail-closed；
    ALLOW 4 探索工具；DENY graph_write/evidence_mutation/
    financial_fact_creation/direct_source_access
  - Audit Extension（agent_runtime/pilot_audit.py）：runtime lineage 7 字段 +
    artifact_source() 回答"哪个 runtime 产生该 Artifact"
  - Harness Pilot Entry（agent_runtime/pilot_adapter.py）：Router → Permission
    → Runtime → Audit；opt-in P8_A2_HYBRID_PILOT=1
  - Pilot Corpus（config/harness_pilot_corpus.yaml）：8 cases（5 exploration
    + 3 negative controls）；不含 FinancialFact/ResearchFinding/final report
    的 Harness 任务
  - POSIX 验证（scripts/p8_a2_posix_validation.py + workflow
    p8-a2-posix-validation.yml）：Ubuntu CI 验证 process_residue=NO
  - 测试: tests/unit/test_p8_a2_hybrid_pilot.py（29 offline）；full pytest 绿；
    schema 86/86；Legacy 既有测试全过
NEXT: Sol 独立验收 P8-A2（Router 决策 / Policy 配置 / Permission / Audit /
  corpus / POSIX CI 结果）→ 若通过，独立 taskbook 授权 P8-A3（生产试点运行：
  在受治理环境用真实 Harness 执行 corpus 探索任务，采集 Reliability /
  Governance / Value / Cost 四类指标）。P8-A3 不切换默认 runtime；不删除
  Legacy；不改 LlmClient / Schema / Validator。P8-B3 / production adoption
  保持 NOT_AUTHORIZED。
```

## P8-A3-HYBRID-AGENT-RUNTIME-PILOT-EVALUATION — Hybrid Agent Runtime Pilot Evaluation（2026-08-22）

```text
EVALUATED（受治理试点评估；验证 Harness 在探索型任务中的真实价值；不是
  Production Adoption；DECISIONS #84）:
  - 运行器: scripts/p8_a3_pilot_evaluation.py（opt-in P8_A3_HYBRID_PILOT_EVAL=1）；
    真实 pinned Harness（rc.7）provider-backed；corpus 8 cases（5 exploration
    + 3 negative controls）
  - Governance 全过: audit_completeness=100%（8/8）/ unauthorized_tool=0 /
    authority_drift=0 / secret_leak=0 / strict_schema_entered_harness=0 /
    graph_write_attempted=false
  - 关键实证发现（如实）: 300s 和 600s turn 预算下 5 个开放探索 turn 全部
    TURN_TIMEOUT（5/5，无改善）→ 不是预算问题；诊断证明简单定向 turn 9.5s
    完成（含工具调用）→ 根因是开放探索 prompt 触发 agentic 循环（多工具/
    多轮/空图重试），是生产试点前的可靠性门槛
  - POSIX 验证: 首次 CI（run 32512091426）FAILED（PROFILE_POLICY_MISMATCH:
    stdio MCP 需 P8_A0_HYBRID_SPIKE=1，已修复）；p8-a3-pilot-evaluation.yml
    workflow 就绪，push 到本分支触发重跑取得 process_residue=NO
  - 测试: tests/unit/test_p8_a3_pilot_evaluation.py（11 offline）；full pytest 绿；
    schema 86/86；未改 LlmClient/Schema/Validator/Authority；默认 runtime legacy
NEXT: Sol 独立验收 P8-A3 评估（Governance 全过 / agentic 循环发现 / POSIX CI
  重跑证据）→ **P8-A4 前置条件**：先将探索 prompt 改为有界定向形态（单次工具
  调用 / 明确结束条件）、处理空图重试，修复后重跑本评估；再独立 taskbook 授权
  P8-A4（生产试点运行）。P8-A4 不切换默认 runtime；不删除 Legacy；不改
  LlmClient / Schema / Validator。P8-B3 / production adoption 保持
  NOT_AUTHORIZED。
```

## P8-A3-R1-HARNESS-EXPLORATION-CONTROL — Exploration Execution Contract（2026-08-22）

```text
IMPLEMENTED（修复 P8-A3 开放式 agent loop；DECISIONS #85）:
  - Exploration Execution Contract（config/exploration_policy.yaml v1.0.0，
    config-driven）: 每 HARNESS_ALLOWED 任务含 objective / allowed_tools /
    max_turns / max_tool_calls / turn_timeout_seconds /
    completion_rule.required_fields / empty_data_policy / failure_condition
  - 契约强制（agent_runtime/exploration_controller.py）: turn 1 完整契约
    prompt；turn N>1 有界 follow-up；每回合 MCP event log 计数 tool_calls；
    确定性 completion 检测（非 LLM）；空数据 record data_gap 并停止；
    超预算 → exploration_incomplete（fail closed）
  - Adapter 强制契约（缺失契约拒绝执行）；audit +exploration control lineage；
    skills +契约元数据
  - 实测: timeout_count 5 → 0；governance 全过；Negative controls 保持
    LEGACY_ONLY
  - 测试: tests/unit/test_p8_a3_r1_exploration_control.py（18 offline）；
    full pytest 绿；schema 86/86；未改 Router 核心/Legacy/LlmClient/Schema/
    Validator/Authority
NEXT: Sol 独立验收 P8-A3-R1（契约设计 / 预算执行 / 测试 / 真实执行结果）→
  若 Reliability ≥0.95 达成，独立 taskbook 授权 P8-A4（生产试点运行：采集
  Reliability / Governance / Value / Cost 正式基线）。P8-A4 不切换默认
  runtime；不删除 Legacy；不改 LlmClient / Schema / Validator。P8-B3 /
  production adoption 保持 NOT_AUTHORIZED。
```
## P8-A4 follow-up gate (2026-08-22)

P8-A4 implementation is complete but evaluation is `PARTIAL / DATA_DEGRADED`.
Before P8-A5, run the opt-in expanded corpus with approved provider
credentials, preserve provider-reported calls/latency/token usage, and have Sol
complete the human evaluation template. Do not treat the offline 20/20 result
as real Harness reliability or value evidence. Keep Legacy as the default and
do not route structured research artifacts through Harness.

## P8-A4-R1 follow-up gate (2026-08-22)

The real provider-backed run is complete as `PASS CANDIDATE`, not independently
accepted. Next actions are independent review of the 25-case evidence,
completion of the human usefulness template, and process-tree cleanup
verification if required by acceptance. P8-A5 and production adoption remain
`NOT_AUTHORIZED` until those gates close.
