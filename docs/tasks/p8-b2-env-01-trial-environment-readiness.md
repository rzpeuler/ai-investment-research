# P8-B2-ENV-01 — Provider-Backed Internal Trial Environment Readiness

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE (Sol)

This taskbook establishes and mechanically verifies the controlled runtime
environment required to execute the formal P8-B2 provider-backed bounded
internal trial (P8-B2-LIVE-01). It is an environment-readiness task, not the
formal acceptance trial: **no formal corpus session or turn was executed**.

## Authorization

- P8-B2 LIVE acceptance corpus (P8-B2-LIVE-01): NOT AUTHORIZED in this task
- P8-B3: NOT AUTHORIZED
- Production adoption: NOT AUTHORIZED
- Master merge: NOT AUTHORIZED

## Baseline verification

- `origin/master` = `e64249e9eb99a395ebaa63308d0d72ad1d3a7a74` (matches expected)
- `origin/feature/p8-b2-internal-trial` = `35a315cc54c7f9d2644f62fb8fc1f9f045f6918c` (matches expected)
- No baseline drift; no silent rebase.

## Workspace

- Isolated Git worktree: `ai-investment-research-env01`
- Branch: `task/P8-B2-ENV-01-trial-readiness` (based exactly on
  `feature/p8-b2-internal-trial` @ `35a315c`)
- No shared writable P8-B2 feature worktree.

## Frozen runtime contract (unchanged)

| Item | Value |
|---|---|
| Harness package | `@deepseek-ai/dsh` |
| Pinned version | `0.1.0-rc.7` (never `latest`, never silently upgraded) |
| MCP namespace | `research-os-mcp/v1` |
| Authorized MCP tools (exactly) | `get_company_profile`, `check_data_readiness` |
| MCP tool count | 2 |
| Default Research OS runtime | `legacy` |
| Production adoption | `NOT_AUTHORIZED` |

## Dependency strategy (fresh worktree → deterministic Harness)

- `agent_runtime/package.json` + `agent_runtime/package-lock.json` are committed
  and pin `@deepseek-ai/dsh` exactly to `0.1.0-rc.7` (lockfile v3, resolved npm
  tarball).
- Bootstrap: `cd agent_runtime && npm ci` (node >= 24 required). `npm ci`
  installs exactly the locked tree; `node_modules/` and `.dsh-home/` stay
  outside Git (`agent_runtime/.gitignore`).
- Verified in the fresh isolated worktree: `npm ci` → 528 packages →
  `dsh --version` → `0.1.0-rc.7`.
- No global-machine dependency, no reliance on another worktree's `node_modules`.

## Readiness probe design

New minimal module `src/research_os/agent_runtime/environment_readiness.py`
plus entry script `scripts/p8_b2_env_readiness.py` (opt-in
`P8_B2_ENV_READINESS=1`). It reuses the accepted P8-B2 infrastructure —
`ProductionEvidenceProbe`, `HarnessProcessFactory`, `HarnessRuntimeSupervisor`,
the owned process-tree cleanup mechanism, and the R2 evidence vocabulary —
instead of introducing another runtime, MCP server, provider SDK,
orchestration layer or acceptance engine.

Ten gates, each with an explicit evidence basis
(`OBSERVED` / `DERIVED_FROM_OBSERVED_RUNTIME` / `POLICY_INVARIANT` /
`NOT_AVAILABLE` / `NOT_VERIFIED`):

1. `HARNESS_AVAILABLE` — pinned binary + node present
2. `HARNESS_VERSION_VERIFIED` — `dsh --version` + committed package/lockfile pins
3. `PROVIDER_CREDENTIAL_PRESENT` — `DEEPSEEK_API_KEY` presence only (value never exposed)
4. `PROVIDER_CONNECTIVITY_VERIFIED` — one bounded provider probe (probe-only marker)
5. `MCP_SERVER_BOOT_VERIFIED` — stdio Research OS MCP server handshake
6. `MCP_NAMESPACE_VERIFIED` — namespace `research-os-mcp/v1`
7. `MCP_TOOLSET_VERIFIED` — exactly two tools, no unauthorized tool, in-process handshake
8. `RUNTIME_PROFILE_VERIFIED` — observed version/profile match the frozen contract
9. `PROCESS_CLEANUP_VERIFIED` — accepted owned-process cleanup mechanism; fail-closed on NOT_VERIFIED
10. `SECRET_HYGIENE_VERIFIED` — no secret markers in any bounded probe evidence

Result model: `READY` | `BLOCKED` | `FAIL`; cleanup that cannot be mechanically
proven is `FAIL_CLOSED` (a `FAIL` classification with `fail_closed: true`).

Formal-trial separation is structural: the probe holds no metrics recorder and
no counters, cannot admit a session or turn, and marks every provider call
`ENVIRONMENT_READINESS_PROBE_ONLY` / `FORMAL_ACCEPTANCE_TURN = NO`. It is proven
by offline test `test_probe_cannot_increment_formal_acceptance_counters`.

## Provider connectivity probe

- One tiny bounded request via the existing `DeepSeekChatCompletionsProvider`
  (flash model, `max_output_tokens=256`, `timeout_seconds=30`, no retries).
- Observed usage on this host: 191 total tokens (153 prompt incl. 128 cached,
  38 completion incl. 32 reasoning).
- The initial 16-token budget mechanically truncated the flash model's JSON
  content (reasoning prefix); 256 tokens produces a clean `{"ok": true}`.
- Marked `ENVIRONMENT_READINESS_PROBE_ONLY`; never counted toward the formal
  10-session / 20-turn corpus.

## Live probe result (this host, 2026-08-20)

`P8_B2_ENV_READINESS=1 PYTHONPATH=src python scripts/p8_b2_env_readiness.py`

| Gate | Result | Evidence basis |
|---|---|---|
| HARNESS_AVAILABLE | YES | OBSERVED |
| HARNESS_VERSION_VERIFIED | YES (0.1.0-rc.7) | OBSERVED |
| PROVIDER_CREDENTIAL_PRESENT | YES | OBSERVED |
| PROVIDER_CONNECTIVITY_VERIFIED | YES (one bounded probe call) | OBSERVED |
| MCP_SERVER_BOOT_VERIFIED | YES | OBSERVED |
| MCP_NAMESPACE_VERIFIED | YES (research-os-mcp/v1) | OBSERVED |
| MCP_TOOLSET_VERIFIED | YES (2 tools, 0 unauthorized, in-process handshake) | OBSERVED |
| RUNTIME_PROFILE_VERIFIED | YES (0.1.0-rc.7 / research-headless) | DERIVED_FROM_OBSERVED_RUNTIME |
| PROCESS_CLEANUP_VERIFIED | NOT_VERIFIED → FAIL_CLOSED | NOT_VERIFIED |
| SECRET_HYGIENE_VERIFIED | YES (0 markers) | OBSERVED |

- Harness executable boot: verified (real pinned Harness process reached HTTP
  ready; root process terminated after probe; no OS process residue).
- Owned process tree: the accepted R2 evidence model cannot enumerate the owned
  tree on Windows (`cleanup_status` → `root=TERMINATED, tree=NOT_VERIFIED`),
  so this gate is mechanically `NOT_VERIFIED` → `FAIL_CLOSED`. This is the
  accepted fail-closed behavior, not a code defect: the same mechanism is
  proven `VERIFIED` on POSIX by the accepted Linux process-group regression
  tests (`tests/unit/test_p8_b2_process_ownership_linux.py`, exercised by the
  GitHub Offline CI on Ubuntu).
- Final result on this host: **FAIL** (fail-closed) — blocker:
  `PROCESS_CLEANUP_VERIFIED = NOT_VERIFIED`.
- `FORMAL_TRIAL_READY = NO` on this host (formal gate requires owned process
  cleanup verified and process residue = NO).

## Windows limitation and Linux validation (P8-B2-ENV-02)

- **Windows limitation（如实记录）**：本宿主为 Windows，accepted R2 清理证据模型
  无法枚举 owned process tree（`cleanup_status` = root TERMINATED / tree
  NOT_VERIFIED），因此 `PROCESS_CLEANUP_VERIFIED = NOT_VERIFIED`（fail-closed）。
  这是平台证据限制，不是代码缺陷；不得把 Windows 结果解释为 Linux 结果。
- **Linux validation**：`PROCESS_CLEANUP_VERIFIED = YES` / `PROCESS_RESIDUE = NO`
  的 POSIX 机械证明由 GitHub Actions `ubuntu-latest` 执行环境完成 — 详见
  `docs/tasks/p8-b2-env-02-linux-validation.md` 与 P8-B2-ENV-02 验收报告
  （workflow：`.github/workflows/p8-b2-env-02-linux-validation.yml`，不修改
  生产 Offline CI）。
- 不记录 `P8-B2 ACCEPTED`；P8-B2 保持 `IMPLEMENTED / PARTIAL / NOT ACCEPTED`。

## Offline tests

`tests/unit/test_p8_b2_env_readiness.py` — 15 deterministic tests covering the
12 required scenarios (harness missing → BLOCKED; wrong version → FAIL;
credential missing → BLOCKED; connectivity unavailable → BLOCKED; namespace
mismatch → FAIL; missing tool → FAIL; extra tool → FAIL; cleanup NOT_VERIFIED →
fail closed; residue YES → FAIL; secret evidence → FAIL; all gates verified →
READY; probe cannot increment acceptance counters) plus boot-failure and
evidence-basis completeness. Tests never require a real credential or real
Harness.

## Regression

- Targeted P8-B2 tests: 78 passed, 3 skipped (Linux-only process-group tests on
  Windows).
- Full `python -m pytest`, `research_os.cli.main validate` (86/86), compileall,
  `git diff --check`: see the acceptance report on the task branch head.
- SCHEMA: 86/86 (no schema change). DATABASE: v6 (no migration).
  DEFAULT_RUNTIME: legacy. MCP_TOOL_COUNT: 2.

## Project state

- `P8-B2: IMPLEMENTED / PARTIAL / NOT ACCEPTED` (unchanged; not self-accepted).
- `P8-B2 formal live trial environment` on this Windows host: `FAIL` (fail-closed
  on owned process-tree cleanup evidence). All other prerequisites (pinned
  Harness executable, credential, provider connectivity, runtime/profile, MCP
  boot/namespace/toolset, secret hygiene) are mechanically verified.
- The readiness probe itself is not an acceptance result and must not be read as
  one: the formal 10-session / 20-turn corpus was not executed
  (`FORMAL_CORPUS_EXECUTED = NO`).
