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
