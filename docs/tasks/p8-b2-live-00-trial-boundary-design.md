# P8-B2-LIVE-00 — Formal Trial Execution Boundary Design

STATUS: DESIGNED / AWAITING INDEPENDENT ACCEPTANCE (Sol)

本任务为未来的 P8-B2-LIVE-01 Formal Internal Trial 定义并冻结执行边界。本任务
**不执行**正式 trial：未产生 10 sessions / 20 provider-backed turns，未消耗任何
acceptance corpus。

## 0. 现状基线（2026-08-20）

| Item | State |
|---|---|
| P8-B2 | IMPLEMENTED / PARTIAL / NOT ACCEPTED |
| P8-B2-R2 | PASS（evidence-integrity repair） |
| P8-B2-R2 integration | PASS（feature/p8-b2-internal-trial @ 35a315c） |
| P8-B2-ENV-02 | PASS（Linux environment validation：GitHub Actions Ubuntu 24.04.4 LTS，PROCESS_CLEANUP_VERIFIED=YES / PROCESS_RESIDUE=NO） |
| Harness | `@deepseek-ai/dsh` `0.1.0-rc.7`（pinned） |
| MCP | `research-os-mcp/v1`；恰好 `get_company_profile` / `check_data_readiness` |
| Default runtime | legacy |
| 唯一 blocker | Formal provider-backed internal trial execution |

## 5.1 Execution Environment

**选择：GitHub Actions Ubuntu runner（`ubuntu-latest`）作为正式 trial 执行环境。**

理由：

- **与已验证环境一致**：P8-B2-ENV-02 已在 `ubuntu-latest`（Ubuntu 24.04.4 LTS，
  kernel 6.17.0-1022-azure，x86_64，Python 3.12.14，Node v24.19.0）机械验证
  `PROCESS_CLEANUP_VERIFIED=YES` / `PROCESS_RESIDUE=NO` — 正式 trial 的
  `process residue = NO` 硬 gate 在 Linux 上可满足，Windows 宿主无法提供该证据
  （ENV-01 CLOSED，fail-closed）。这是 Decision #61 的延续。
- **reproducible**：GitHub-hosted Ubuntu 固定镜像语义，任何会话可在同一环境复现；
  `npm ci`（committed `agent_runtime/package-lock.json`）确定性安装 pinned Harness。
- **auditable**：workflow run、日志、artifact 均可审计；与生产 Offline CI 同一
  执行环境语义。
- **limitations**：
  - 该环境本身不持有 approved provider credential（CI 无 secrets 策略）—
    凭证注入必须通过 5.2 定义的 approved secret mechanism，且其配置须由
    LIVE-01 授权流程显式批准；
  - GitHub job 时长上限（6 小时）远大于 trial 预期耗时（~1–2 小时），不构成限制；
  - 不允许并行 job（concurrency = 1），避免多 run 混淆计数。

## 5.2 Credential Boundary

Provider credential：`DEEPSEEK_API_KEY`。

**禁止**（任何形式）：

- 进入 repository / git history；
- 进入 logs（含 workflow 日志、应用日志、探针输出）；
- 进入 artifacts（含 evidence snapshot、event log、报告）；
- 进入 reports / task 文档；
- 以 key value、prefix、suffix、长度指纹（length-derived fingerprint）形式被记录
  或报告。

**注入机制（approved secret mechanism）**：

- 正式 trial 运行时，`DEEPSEEK_API_KEY` 只通过 GitHub Actions secret 注入：
  workflow 中仅以 `env: DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}`
  引用（GitHub 自动 masking）；该 secret 的创建/更新属于 LIVE-01 授权操作，
  由 authorized operator 执行，且不写入任何文档或聊天记录。
- 执行 Agent 不得要求用户在 chat 中粘贴 key、不得把 key 放入 CLI 参数、文件、
  fixture、task 文档或测试。
- 若 approved credential 在 trial 环境不可用：**不得伪造、不得替换 provider、
  不得修改 acceptance 逻辑**；返回 `CREDENTIAL_PRESENT = NO` → `BLOCKED`。

**观察规则**：

- 只允许：`CREDENTIAL_PRESENT = YES` / `NO`（布尔存在性）。
- 禁止：key value、prefix、suffix、长度指纹、partial token。

**验证检查**（trial 前后）：

1. git diff secret scan（commit 前）；
2. artifact inspection（evidence snapshot / event log 不含 secret markers）；
3. log inspection（workflow 与运行时日志不含 secret markers）。

## 5.3 Trial Execution Contract

正式 trial（P8-B2-LIVE-01）契约：

- **10 sessions**：`ENTITY_CORPUS` =（600519.SH, Kweichow Moutai）×5 +
  （300750.SZ, CATL）×5（与 accepted trial 实现一致）；
- **20 provider-backed turns**：每 session 2 turns —
  - turn 1：`get_company_profile` 一次 + `check_data_readiness` 一次；
  - turn 2：同一 session 内重新 `check_data_readiness` 一次（fresh readiness，
    禁止使用缓存结果）；
- 每个 turn 必须产生 evidence：
  - session id（public session hash，不记录内部 harness session id）；
  - turn id（1 | 2）；
  - timestamp（事件时间与文章/数据时间分离）；
  - runtime evidence（version / profile / MCP namespace，bounded）；
  - tool evidence（tool name、typed status、bounded authority reference）；
  - failure evidence（如失败：typed failure code，单次计数 R2-01）。
- session/turn 计数由 accepted `TrialMetricsRecorder` 单一权威维护；
  readiness probe 与 trial 计数器严格分离（probe 不触碰任何计数器）。

## 5.4 Evidence Model

证据捕获结构（每个 evidence item 必须包含：source、timestamp、evidence basis、
observed / derived / policy invariant 分类）：

```text
Trial Evidence
├── Environment      （OS/kernel/arch/python/node/harness version；source=observed runtime）
├── Runtime          （profile/version/mcp namespace；basis=DERIVED_FROM_OBSERVED_RUNTIME）
├── Provider         （CREDENTIAL_PRESENT、connectivity、usage 仅 provider-reported；basis=OBSERVED）
├── Session          （public hash、entity、internal mapping presence；basis=OBSERVED）
├── Turn             （turn id、timestamp、latency、same_session、provider_status；basis=OBSERVED）
├── Tool Invocation  （tool name、typed status、bounded authority ref、unauthorized count；basis=OBSERVED）
├── Failure          （typed code、provider/mcp 分类、单次计数；basis=OBSERVED）
└── Cleanup          （root_cleanup、owned_tree_cleanup、process_residue；basis=OBSERVED / NOT_VERIFIED fail-closed）
```

证据词汇（与 accepted R2 一致）：

- `OBSERVED` — 实际记录的运行证据；
- `DERIVED_FROM_OBSERVED_RUNTIME` — 从本次 trial 观察到的运行 Harness 推导；
- `POLICY_INVARIANT` — 静态策略/授权常量（如 default_runtime=legacy、
  production_adoption=NOT_AUTHORIZED），从不声称是观察值；
- `NOT_AVAILABLE` / `NOT_VERIFIED` — 证据不存在/无法机械验证（fail-closed）。

**证据保留策略**：

- 只保留 bounded aggregate evidence（trial report 的 frozen snapshot）；
- 原始 prompts、raw responses、reasoning、credentials、内部 session id
  一律不保留；
- 临时 event log 为进程本地文件，trial 结束后删除（snapshot 冻结之后）；
- evidence snapshot 冻结后不可被 CLI/report 层改写（R2-02）。

## 5.5 Failure Handling

| 场景 | 分类 | 行为 |
|---|---|---|
| Provider failure | FAIL | typed failure 单次计数（R2-01）；不得转换为成功；trial 不能 PASS CANDIDATE |
| MCP failure | FAIL | typed failure 单次计数；`MCP_UNAVAILABLE` / `PROFILE_POLICY_MISMATCH` 触发 latch |
| Process cleanup failure | FAIL_CLOSED | `cleanup_status` tree=FAILED → residue=YES → FAIL；tree=NOT_VERIFIED → fail-closed |
| Credential unavailable | BLOCKED | 不启动 trial；如实报告；不伪造 |
| Budget exhausted / timeout | FAIL / PARTIAL | 按既有 budget 语义终止，禁止静默继续 |
| Harness boot failure | BLOCKED（环境） | 按 ENV-01 探针分类语义如实报告 |

**禁止自动 retry loops**：accepted `TrialBudget.max_retries = 0`；单次 causal
failure 只计数一次，不得通过重试掩盖失败。失败证据必须保留（typed code + count），
不得在后续成功后被清零（R2-03 单调语义适用于 secret 证据；failure 计数同样只增）。

## 5.6 Cost / Resource Boundary

| 项 | 值 | 说明 |
|---|---|---|
| max sessions | 10 | TrialBudget（accepted） |
| max turns | 20 | TrialBudget |
| max tool calls | 60 | TrialBudget |
| max provider tokens | 200,000 | TrialBudget；超出即终止 |
| turn timeout | 300s | TrialBudget.turn_timeout_seconds |
| provider timeout | 60s | AgentRuntimeConfig |
| max retries | 0 | 无自动重试 |
| concurrency | 1 | 顺序执行，单 workflow job |
| 成本控制 | usage 仅接受 provider-reported | 不推断 token/cost；cost 字段保持 NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME（除非 provider 报告） |
| 预期用量 | 20 turns × ~2k tokens ≈ 40k tokens | 远低于 200k 上限；单次 trial 预期成本极低 |

## 6. Security Requirements

- **PASS 标准：No secret exposure**（key value / prefix / suffix / length
  fingerprint 在任何 repository / history / logs / artifacts / reports 中为零）。
- 强制检查：
  1. git diff secret scan（commit 前，含 `DEEPSEEK_API_KEY` value 与
     `Authorization` / `Bearer ` / `Cookie` / `password` markers）；
  2. artifact inspection（frozen snapshot、event log、探针输出）；
  3. log inspection（workflow 日志、运行时 stdout/stderr tails）。
- secret 证据单调（R2-03）：任何一次扫描的 positive finding 不得因后续清理而
  归零；`secret_leak_count` 只取历史最大值。
- 探针与 trial 的 secret hygiene gate 复用同一 marker 词汇与单调计数语义。

## 7. Acceptance Workflow Design

未来 P8-B2-LIVE-01 的流程（本任务只定义，不执行）：

```text
Preparation                      （taskbook 授权、branch、workflow、budget 确认）
    ↓
Environment verification         （readiness probe on Ubuntu：HARNESS/RUNTIME/MCP/PROCESS/SECURITY gates）
    ↓
Credential verification          （approved secret mechanism：CREDENTIAL_PRESENT = YES；失败 → BLOCKED）
    ↓
Trial execution                  （10 sessions / 20 provider-backed turns，顺序执行）
    ↓
Evidence collection              （frozen snapshot：全部 gate 字段 + evidence basis；计数器单权威）
    ↓
Sol independent verification     （独立复核 evidence、secret scan、process hygiene、budget）
    ↓
PASS / REWORK_REQUIRED           （Agent 不得自验收；只有独立 reviewer 可接受）
```

明确：**执行 Agent 不能 self-accept P8-B2**。trial 输出只能是
`PASS CANDIDATE` / `PARTIAL` / `FAIL`；独立验收通过前，P8-B2 保持
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`。

## 8. 状态

- `FORMAL_CORPUS_EXECUTED = NO`（本任务与 LIVE-01 之前均未执行）。
- P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`；不记录 `P8-B2 ACCEPTED`。
- 本任务只改文档；无代码、无 runtime、无 acceptance 变更。
