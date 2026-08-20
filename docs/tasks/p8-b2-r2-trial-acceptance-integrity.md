# P8-B2-R2 — Internal Trial Acceptance Evidence Integrity Repair

> Status: IMPLEMENTED / PARTIAL / NOT ACCEPTED（awaiting independent Sol verification）
> Task authorization: AUTHORIZED · Merge authorization: NOT AUTHORIZED
> Repository: `rzpeuler/ai-investment-research`
> Work branch: `task/P8-B2-R2-trial-evidence-integrity`
> PR target: `feature/p8-b2-internal-trial`

## Purpose

Repair the P8-B2 internal trial acceptance evidence path so that the next real
trial can be independently reviewed. This task does **not** lower any P8-B2
acceptance gate and does **not** authorize production adoption, a default
runtime switch, frontend integration, or P8-B3.

## Findings Closed

- **R2-01 — RuntimeFailure counted twice.** `_run_turn` previously recorded a
  `metrics.failure(...)` and then `run_corpus` recorded it again for the same
  causal exception. Counting is now deferred to the single corpus-level owner;
  the turn layer records only bounded evidence and re-raises. Attempt counters
  (`turn_attempts`, `session_create_attempts`) remain separate metrics and are
  never hidden.
- **R2-02 — CLI overrode process residue.** The trial CLI unconditionally set
  `result["process_residue"] = "NO"`. This constant overwrite is removed; the
  CLI now consumes the frozen evidence snapshot and may only add
  non-authoritative metadata (`restart_drill_detail`, `rollback_drill_detail`).
- **R2-03 — Secret evidence erased during finalization.** `_scan_secrets`
  overwrote `secret_leak_count` on every scan, so a post-cleanup scan could
  turn an earlier positive into zero. Secret evidence is now monotonic
  (`max(scans)`); cleanup never erases an earlier positive result.
- **R2-04 — Process-tree cleanup not mechanically meaningful.** The harness is
  now spawned in its own POSIX session/process-group; shutdown targets only
  that owned group (`os.killpg` SIGTERM → bounded SIGKILL escalation) and the
  Windows owned-root `taskkill /T` path is retained. `BoundedOwnedProcess`
  exposes structured `cleanup_status` distinguishing root vs owned-tree
  verdicts. `process_residue = NO` only after owned-tree cleanup is
  mechanically verified; otherwise `YES` / `NOT_VERIFIED` and the gate stays
  closed (fail-closed).
- **R2-05 — No evidence provenance.** `evaluate_final_trial` now freezes a
  single evidence snapshot; critical acceptance fields carry an
  `evidence_basis` mapping (`OBSERVED` / `DERIVED_FROM_OBSERVED_RUNTIME` /
  `POLICY_INVARIANT` / `NOT_AVAILABLE` / `NOT_VERIFIED`).

## Implementation

- `src/research_os/agent_runtime/trial.py`:
  - Added `EvidenceBasis`, `PASS_CANDIDATE`, `PARTIAL`.
  - Single-owner failure accounting (corpus-level).
  - Monotonic secret scan.
  - `TrialController.evaluate_final_trial()` freezes a snapshot after
    collect → final secret scan → owned cleanup → observe → freeze → render.
  - `_process_residue()` mechanically sources the process gate; hard gate in
    `_render_summary` requires `process_residue == "NO"` for `PASS CANDIDATE`.
  - `restart_drill` uses `terminate_tree` and no longer double-counts a
    restart admission failure.
  - Fixed pre-existing `_budget_check` so the warning flag is read/written on
    `self.metrics` (otherwise a full 20-turn corpus would raise an
    `AttributeError` at the last turn).
- `src/research_os/agent_runtime/production_runtime.py`:
  - `HarnessProcessFactory.__call__` spawns the owned harness in a dedicated
    POSIX process-group (`start_new_session=True`).
  - `BoundedOwnedProcess` adds `terminate_tree()` and `cleanup_status()` with
    mechanical root/tree verdicts; uses `/proc` enumeration on Linux and
    returns `NOT_VERIFIED` where the group cannot be proven.
- `src/research_os/agent_runtime/runtime_supervisor.py`:
  - `_cleanup_owned_process` prefers `terminate_tree` when available.
- `scripts/p8_b2_internal_trial.py`:
  - Removes the constant `process_residue = "NO"` overwrite; consumes the
    frozen snapshot and attaches only non-authoritative drill metadata.
- `tests/unit/test_p8_b2_evidence_integrity.py`:
  - 14 offline regression tests covering the 12 required regression scenarios
    with deterministic fakes (no provider network).

## Regression Coverage (taskbook 12 scenarios)

1. one provider exception → one provider failure ✓
2. session-creation failure → one failure / zero turn attempts ✓
3. MCP failure counted exactly once ✓
4. secret finding survives final cleanup ✓
5. secret content redacted / not emitted ✓
6. CLI cannot overwrite mechanical process result ✓
7. simulated residue forces non-PASS ✓
8. `NOT_VERIFIED` cleanup forces non-PASS ✓
9. verified zero owned-process residue allows the process gate ✓
10. evidence-basis values explicit for critical gates ✓
11. PASS CANDIDATE blocked with fewer than 10 sessions / 20 turns ✓
12. PASS CANDIDATE blocked when any hard security/integrity gate fails ✓

## Offline Validation

- `python -m pytest`: full run (see report).
- `python -m research_os.cli.main validate`: `86/86 PASS`.
- `python -m compileall -q src scripts tests`: PASS.
- `git diff --check`: PASS.
- Schema count 86, DB v6, migrations NONE, MCP catalog unchanged
  (`get_company_profile`, `check_data_readiness`), default runtime `legacy`,
  production adoption `NOT_AUTHORIZED`.

## Live Trial Result

Official post-fix trial run:
- `P8_B2_TRIAL_STATUS = PARTIAL`
- Cause: the approved environment mechanism exposed no `DEEPSEEK_API_KEY`, and
  the isolated worktree carried no installed pinned Harness binary
  (`agent_runtime/node_modules`), so cold boot failed with
  `HARNESS_BOOT_FAILED`. No provider-backed turn could be executed.
- This is the truthful outcome; it is **not** converted into `PASS`.

## Documentation

- Created `docs/tasks/p8-b2-r2-trial-acceptance-integrity.md` (this file).
- Updated `docs/architecture/p8-b2-internal-trial-report.md`.
- Updated `docs/project-state/CURRENT_STATE.md`, `NEXT_PHASE.md`,
  `KNOWN_LIMITATIONS.md`.

## Final State

- P8-B2: IMPLEMENTED / PARTIAL / NOT ACCEPTED
- P8-B3: NOT_AUTHORIZED
- FRONTEND IMPLEMENTATION: NOT_AUTHORIZED
- PRODUCTION ADOPTION: NOT_AUTHORIZED
- No execution-agent self-acceptance; only independent Sol verification may
  convert an eligible `PASS CANDIDATE` into project acceptance.
