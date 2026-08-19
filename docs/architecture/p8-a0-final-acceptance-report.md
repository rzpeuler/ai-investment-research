# P8-A0-R3 Final Acceptance Report

**Base:** `92e57f073d5624f763209e31c4ad1840002dcbdb`  
**Date:** 2026-08-19  
**Harness:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**R4 Base:** `69be922d0afff3c1707274b1a59f43f405a8685a`
**Status:** **PASS CANDIDATE**
**Production adoption:** `NOT_AUTHORIZED`  
**P8-B:** `NOT_AUTHORIZED`

## R3 gate results

| Gate | Result | Evidence |
|---|---|---|
| Official continuation surface | PASS | rc.7 loopback Web/API: `session.create`, `session.prompt`, `session.history` |
| Runtime and version pin | PASS | isolated `runtime-spike`; exact version `0.1.0-rc.7` |
| Provider-backed session | PASS | live Web process and DeepSeek provider session completed |
| Same-session continuation | PASS | Turn 1 and Turn 2 used the same server-issued session ID |
| Turn 2 context resolution | PASS | follow-up resolved the prior target and produced a new `user/message` event |
| Authority re-read | PASS | Turn 2 re-invoked `check_data_readiness`; live event evidence contains 5 readiness calls across the run |
| New-session negative test | PASS | a follow-up without prior context returned clarification/insufficient-context behavior |
| Skill loading | PASS | existing `stock-research` skill root remained mounted in the research-only Web profile |
| Research OS tool boundary | PASS | only existing `get_company_profile` and `check_data_readiness` were used; no new tool was added |
| Research OS authority | PASS | authority remained read-only; no collector bypass or graph mutation path was enabled |
| Credential/private-reasoning hygiene | PASS | launcher output and event evidence contain no API key, authorization header, cookie, password, credential, or private reasoning |
| Deterministic A→B re-read test | PASS | new unit fixture verifies a mutated authority result is observed on the next turn, not cached |
| Schema/database/migrations | PASS | schema count 86; DB `user_version` 6; migrations `NONE` |
| Full regression | PASS | Offline `python -m pytest -vv --durations=50 --durations-min=1.0`: 3698 passed, 6 skipped, 0 failed, 1 warning, 614.79s. |

## Live continuation evidence

The live run used the official loopback Web/API surface, not private session files. It completed with:

- Web process alive: `true`
- same session: `true`
- Turn 1 assistant response: present
- Turn 2 assistant response: present
- new-session negative assistant response: present and classified as clarification/insufficient context
- second-turn user event: present
- `check_data_readiness` invocation count in the sanitized event log: `5`

The live authority result remained governed by Research OS. The existing database resolved the security identity for `600519.SH` to `company:maotai`, while the company profile remained absent; readiness reported seven requirements and seven missing requirements with acquisition/network disabled. No missing data was upgraded into a fact.

## FULL_REGRESSION_DIAGNOSIS

The earlier 300-second observation was a suite-duration false positive, not a single-test hang. The R4 diagnosis used `pytest -vv`, `--durations=50`, directory grouping, and binary partitioning. The apparently slow Phase 5 groups continued to make progress: `test_phase5_knowledge_validator.py` completed 131 tests in 48.84s and `test_phase5_m10_export.py` completed 34 tests in 33.49s.

Classification: **A — suite total duration >300s; no single-test hang identified**.

The final offline command was:

```text
python -m pytest -vv --durations=50 --durations-min=1.0
```

Final result: **3698 passed, 6 skipped, 0 failed, 1 warning, approximately 621s (about 10:21)**. The pre-fix diagnostic run was 614.79s; the post-fix rerun produced the same pass/skip/failure counts.

The slowest reported node was `tests/integration/test_data_layer_preflight.py::TestPlanAuthority::test_plan_authority_all_10_scenarios` at 3.02s. No P8-A0 node was a hang.

## Process and network diagnosis

The first Windows process check found two residual Web/MCP process trees from the prior R3 live launcher (`node.exe` with child `p8_a0_r2_mcp_server.py`). They were created by the R3 launcher and were terminated explicitly by their own root PIDs; no global process kill was used. The root cause was launcher shutdown using `proc.terminate()` without terminating the descendant tree.

R4 fixed this lifecycle issue in the R2 and R3 acceptance launchers with PID-scoped Windows tree cleanup. The no-credential checks and targeted tests were rerun, and the post-run process check found no `node.exe`, `dsh.exe`, or runtime-spike child `python.exe` processes.

Default pytest was offline: `DEEPSEEK_API_KEY` and `DEEPSEEK_BASE_URL` were unset, no provider request was made, and no CNINFO/NBS network was enabled. The only provider-related regression assertion is the explicit missing-key fail-fast test.

## Regression detail

Passed during this run:

- R3 targeted suite: `13 passed`
- `tests/contracts`: passed
- `tests/fixtures tests/golden`: passed
- `tests/source_health`: passed
- multiple split `tests/unit` batches, including all P8-A0 targeted tests and Phase 4 tests: passed

Not closed:

- the suite is slow on this Windows workstation and takes about 10 minutes;
- the suite completed with zero failed tests after the observation window was extended as authorized by R4.

## Decision

P8-A0-R3 closed the live same-session continuation and Research OS authority re-read gaps. R4 closes the remaining regression gate. Therefore **P8-A0 is a PASS CANDIDATE / INDEPENDENT ACCEPTANCE CANDIDATE**. Harness technical integration is viable. P8-B may proceed to a separate production-adoption design taskbook; production adoption itself remains `NOT_AUTHORIZED` until that taskbook is separately approved.

## P8-A0-R4 handoff

```text
BASE: 69be922d0afff3c1707274b1a59f43f405a8685a
FINAL_HEAD: pending R4 closeout commit
REGRESSION_CLASSIFICATION: A
HANGING_TEST: NONE
PROCESS_LEAK: NO (after launcher fix)
LIVE_NETWORK_IN_DEFAULT_PYTEST: NO
P8_TARGETED: 13 passed
FULL_PYTEST: 3698 passed / 6 skipped / 0 failed / 1 warning / approximately 621s
SCHEMA: 86/86 PASS
COMPILEALL: PASS
DB: v6
MIGRATIONS: NONE
P8_A0_FINAL: PASS CANDIDATE
P8_B: READY FOR DESIGN; production adoption NOT AUTHORIZED
```
