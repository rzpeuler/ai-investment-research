# P8-A0-R3 Final Acceptance Report

**Base:** `92e57f073d5624f763209e31c4ad1840002dcbdb`  
**Date:** 2026-08-19  
**Harness:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**Status:** **PARTIAL / FAIL FOR FULL REGRESSION**  
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
| Full regression | NOT VERIFIED | `python -m pytest` exceeded 300 seconds; `tests/unit` also exceeded 180 seconds. Contracts, fixtures/golden, source_health, and most split unit batches passed. |

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

## Regression detail

Passed during this run:

- R3 targeted suite: `13 passed`
- `tests/contracts`: passed
- `tests/fixtures tests/golden`: passed
- `tests/source_health`: passed
- multiple split `tests/unit` batches, including all P8-A0 targeted tests and Phase 4 tests: passed

Not closed:

- the complete `python -m pytest` command did not finish within 300 seconds;
- `tests/unit` did not finish within 180 seconds, with the remaining Phase 5/6 grouping exceeding the observation window.

## Decision

P8-A0-R3 closes the live same-session continuation and Research OS authority re-read gaps. It does **not** satisfy the full acceptance bar because the complete regression suite did not complete. Therefore the overall decision remains **PARTIAL / FAIL FOR FULL DEMO**. Stop at R3 and perform the required GO/NO-GO review; do not enter P8-B and do not adopt Harness in production.
