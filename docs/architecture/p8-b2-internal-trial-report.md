# P8-B2 Internal Trial Report

STATUS: PARTIAL / NOT ACCEPTED

## Run

- Official post-fix trial run: `P8_B2_TRIAL_STATUS = PARTIAL`
- Runtime: `@deepseek-ai/dsh` `0.1.0-rc.7` (pinned; not executed this run)
- Provider network: `ON` for explicit trial only
- Research data network: `OFF`
- Default runtime: `legacy`
- Production adoption: `NOT_AUTHORIZED`
- P8-B3: `NOT_AUTHORIZED`
- B2 base: `e64249e9eb99a395ebaa63308d0d72ad1d3a7a74`
- Repair base: `afb12724213095b36b7524b176af6a05d7970dbd` (P8-B2 R1 head)
- P8-B2-R2 repair branch: `task/P8-B2-R2-trial-evidence-integrity`

## This run's outcome

The official post-fix live trial was attempted with `P8_B2_INTERNAL_TRIAL=1`.
The approved environment mechanism exposed no `DEEPSEEK_API_KEY`, and the
isolated worktree carried no installed pinned Harness binary
(`agent_runtime/node_modules`), so cold boot failed with
`HARNESS_BOOT_FAILED` before any provider-backed turn could run.

This is the truthful trial outcome and is intentionally **not** converted into
a PASS. `PARTIAL` does not authorize production adoption, a default runtime
change, frontend exposure, or P8-B3.

## Evidence Integrity Repair (P8-B2-R2)

The earlier `PARTIAL` run's evidence path has been repaired so the next real
trial can be independently reviewed:

| Finding | Repair |
|---|---|
| R2-01 failure double count | single-owner counting at the corpus level |
| R2-02 CLI process-residue overwrite | constant overwrite removed; frozen snapshot consumed |
| R2-03 secret evidence erasable | secret count is monotonic across scans |
| R2-04 tree cleanup not mechanical | owned process-group + `cleanup_status` + fail-closed residue |
| R2-05 no evidence provenance | `evidence_basis` mapping on critical fields |

Final closeout status: provenance coverage is complete for the authoritative
acceptance/scope snapshot; `P8_AUTHORITY_DB_PATH` runtime support is removed
and the deterministic authority fixture is test-only; and the owned-process
drain-thread lifecycle warning is covered by regression testing. P8-B2 remains
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`; independent Sol acceptance is pending.

## Evidence

| Gate | Result |
|---|---|
| Local cold boot | PARTIAL: `HARNESS_BOOT_FAILED` (Harness binary absent in isolated worktree; no provider credential in approved mechanism) |
| Runtime admission | NOT EXECUTED |
| Session establishment | 0 |
| Live model/skill invocation | NOT VERIFIED |
| Research OS tool invocation | NOT VERIFIED |
| Authority drift | 0 observed in available evidence |
| Unauthorized tools | 0 observed |
| Research source network | OFF |
| Rollback latch | NOT RUN |
| Owned-process crash/restart | NOT RUN |
| Process residue | NOT_VERIFIED (mechanically fail-closed) |
| Provider failures | 0 (no provider-backed turn attempted) |
| Fallback | NOT RUN |
| Sessions / turns | 0 completed / 0 attempted |
| Token usage | `NOT_REPORTED` |
| Monetary cost | `NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME` |
| Latency baseline | NOT_AVAILABLE: no completed provider-backed turn |
| Budget utilization | sessions 0.00; turns 0.00; tools 0.00; provider tokens 0.00 |
| Full offline validation | PASS (see acceptance report for exact pytest/schema counts) |

## Decision

The execution evidence is insufficient for a full demo or P8-B2 acceptance
because no provider-backed turn could be executed: provider credential and
installed Harness runtime were unavailable to this isolated trial. The result
is intentionally `PARTIAL`; no production adoption, default runtime change,
frontend exposure, or P8-B3 authorization follows.

Non-blocking repository hygiene: PR #26 remains stale (based on an obsolete
P7-D4/P8-A0 worldview) and must not be merged.

## P8-B2-ENV-01 Environment Readiness (2026-08-20)

The P8-B2-ENV-01 environment readiness probe was implemented and executed from
the isolated worktree `ai-investment-research-env01`
(branch `task/P8-B2-ENV-01-trial-readiness`, based on `35a315c`). It verifies
prerequisites only; it is not the formal acceptance corpus and executed
**0 sessions / 0 turns**.

Live gate results on this host (Windows):

| Prerequisite | Result |
|---|---|
| Pinned Harness `@deepseek-ai/dsh@0.1.0-rc.7` installed (fresh `npm ci`) | YES |
| Harness executable boot (real bounded invocation) | YES |
| Provider credential present (never exposed) | YES |
| Provider-backed connectivity (one bounded probe call, flash, 191 tokens) | YES |
| Runtime / profile observed (`research-headless`, denied components exact) | YES |
| MCP server boot + namespace `research-os-mcp/v1` | YES |
| Exactly two tools, 0 unauthorized, in-process handshake | YES |
| Owned process root terminated, no OS residue | YES |
| Owned process **tree** cleanup evidence | NOT_VERIFIED (Windows; accepted fail-closed model) |
| Secret hygiene | YES (0 markers) |

Overall readiness on this host: **FAIL (fail-closed)** — the only blocker is
`PROCESS_CLEANUP_VERIFIED = NOT_VERIFIED`: the accepted R2 cleanup evidence
model cannot enumerate the owned process tree on Windows, so the formal
`process residue = NO` gate cannot be proven on this host. The same mechanism
is proven `VERIFIED` on POSIX by the accepted Linux process-group tests in the
GitHub Offline CI. `FORMAL_TRIAL_READY = NO` on this host.

The previous PARTIAL run's environment blockers are closed: the pinned Harness
now boots in an isolated worktree, and the approved credential is present and
provider connectivity is verified. P8-B2 remains
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`.

## P8-B2-LIVE-01 Formal Trial Attempt (2026-08-20)

STATUS: **BLOCKED**

The formal provider-backed trial was attempted under the frozen P8-B2-LIVE-00
execution boundary (GitHub Actions `ubuntu-latest` + GitHub Actions secret
credential injection). The approved execution environment has **no
`DEEPSEEK_API_KEY` secret** — mechanical evidence: `gh secret list` is empty,
repo `actions/secrets` total_count = 0, no environment secrets, no org secrets.
Per the LIVE-01 taskbook mandate (credential absent → immediate BLOCKED; no
provider substitution, no mock, no acceptance-gate change, no faked success),
the trial did not start.

| Item | Result |
|---|---|
| Sessions | 0 / 10 |
| Turns | 0 / 20 |
| Provider-backed turns | 0 |
| Provider calls | 0 |
| FORMAL_CORPUS_EXECUTED | NO |
| Blocker | approved credential execution boundary not provisioned (GitHub Actions secret missing) |
| Evidence snapshot | NOT GENERATED (no trial evidence existed to freeze) |
| Next action | authorized operator provisions `DEEPSEEK_API_KEY` secret, then re-run LIVE-01 |

P8-B2 remains `IMPLEMENTED / PARTIAL / NOT ACCEPTED`; this BLOCKED outcome is
truthful and is not converted into any form of PASS.

## P8-B2-LIVE-01 Formal Trial Execution — PARTIAL (2026-08-20, RESUME-02)

STATUS: **PARTIAL**（fail-closed evidence snapshot generated; frozen）

Environment: GitHub Actions `ubuntu-latest` — Ubuntu 24.04.4 LTS, kernel
6.17.0-1022-azure, x86_64, Python 3.12.14, Node v24.19.0; Harness
`@deepseek-ai/dsh` `0.1.0-rc.7` (npm ci); authority DB provisioned
deterministically (v6 + corpus security profiles; self-check PASS).
Workflow run `32385207624` (head `e8ccff0`), all steps SUCCESS.

Pre-trial readiness probe: **READY** — `approved_credential_present=YES`,
`connectivity_verified=YES` (bounded provider call), `owned_tree_cleanup=VERIFIED`,
`process_residue=NO`, `secret_hygiene=YES`.

Trial evidence snapshot (artifact `p8-b2-live-01-evidence/trial-evidence.json`):

| Item | Result |
|---|---|
| Trial status | PARTIAL |
| Sessions completed | 0 / 10 (session_create_attempts=2, success=1) |
| Turns completed | 0 / 20 (turn_attempts=1) |
| Provider-backed turn | 1 attempted → `PROVIDER_TIMEOUT` (typed, counted once, no retry) |
| Second session create | `HARNESS_BOOT_FAILED` (Harness process not READY after timeout; adapter.admit) → latch tripped → fail-closed stop |
| Typed failures | `{PROVIDER_TIMEOUT: 1, HARNESS_BOOT_FAILED: 1}` |
| Runtime / MCP | 0.1.0-rc.7 / research-headless; `research-os-mcp/v1`; exactly 2 tools; 0 unauthorized; 0 authority drift |
| Process cleanup | root TERMINATED / owned tree VERIFIED / residue NO / leak 0 |
| Secret scan | PASS (secret_leak_count=0) |
| Drills | rollback PASS / crash-restart PASS / legacy fallback PASS |
| Budget utilization | sessions 0.1; turns 0.0; tool_calls 0.0; provider_tokens 0.0 |
| Tokens | NOT_REPORTED (no completed provider turn) |

Interpretation: the frozen failure semantics worked as designed — a real
provider-backed turn was attempted, the timeout was recorded exactly once with
no hidden retry, the Harness process loss was fail-closed, cleanup was
mechanically verified on Linux, and no secret leaked. The 10-session / 20-turn
corpus did not complete; the result is a truthful `PARTIAL`, not converted into
any form of PASS.

Next action: Sol independent verification of this evidence; investigate the
first-turn provider timeout and post-timeout Harness process recovery; then
re-run LIVE-01 under the frozen LIVE-00 boundary. P8-B2 remains
`IMPLEMENTED / PARTIAL / NOT ACCEPTED`.

## P8-B2-LIVE-01-REPAIR-01 Root Cause Diagnosis (2026-08-20)

STATUS: COMPLETE / AWAITING INDEPENDENT ACCEPTANCE
（详细分析：`docs/tasks/p8-b2-live-01-repair-01-timeout-diagnosis.md`）

**PROVIDER_TIMEOUT root cause — Adapter/configuration defect (our side), NOT
provider latency.** The formal trial's first provider-backed turn failed because
the pinned Harness process crashed: our stdio MCP server
(`scripts/p8_b1_mcp_server.py`) replied `protocolVersion: "1"` to the Harness's
MCP client (`@deepseek-ai/dsh-mcp-client` on `@modelcontextprotocol/sdk`
1.30.0), which only supports `2025-11-25 / 2025-06-18 / 2025-03-26 /
2024-11-05 / 2024-10-07` → "Server's protocol version is not supported: 1" →
`failOnStartupError: true` → dsh process exited (code 1) → the turn's HTTP
requests failed (mapped to `PROVIDER_TIMEOUT` by `_rpc`) → supervisor FAILED →
`HARNESS_BOOT_FAILED` on the next session create. The fail-closed machinery
(typed single-count failures, no retry, latch, process cleanup VERIFIED, secret
scan PASS) worked as designed; the defect was the protocol negotiation.

Reproduction (bounded single-turn diagnostic, real provider, not corpus):

| | Before fix | After fix |
|---|---|---|
| Turn | `TURN_FAILED PROVIDER_TIMEOUT 2.6s` | `TURN_COMPLETED 22.7s "completed"` |
| Process | exit code 1 (crash; SDK version error in stderr) | alive (`poll()=None`) |
| Supervisor | FAILED | READY |

Minimal fix applied (no acceptance/trial-contract/security changes):
`negotiate_mcp_protocol_version` added to `mcp/contracts.py` (echoes supported
client versions, falls back to `2024-11-05`), used by the stdio server's
initialize reply; 5 offline unit tests added. Namespace `research-os-mcp/v1`,
tools, failure semantics, budgets unchanged. Re-run condition for LIVE-01 is
met; the formal 10-session / 20-turn corpus has NOT been re-executed. P8-B2
remains `IMPLEMENTED / PARTIAL / NOT ACCEPTED`.
