# P8-A0-R1 Acceptance Report

**Base:** `84e515045e833579706ddd53fe111db82a64f32e`  
**Date:** 2026-08-19  
**Status:** **INDEPENDENTLY REVIEWED — PARTIAL / FAIL FOR FULL DEMO**  
**Decision:** `P8-B: NOT AUTHORIZED`

## Independent review disposition

| Gate | Reviewed result |
|---|---|
| Runtime installation | PASS |
| Version pin | PASS |
| Web runtime | PASS |
| Boundary fixture | PASS |
| Research OS authority | PASS |
| Live provider session | FAIL / NOT COMPLETED |
| Live model skill invocation | NOT VERIFIED |
| Live Research OS tool invocation | NOT VERIFIED |
| Full regression | NOT VERIFIED |
| Overall | PARTIAL / FAIL FOR FULL DEMO |

`P8-B` remains **NOT AUTHORIZED**. No follow-on implementation or production
adoption is implied by this report.

## Results

| Area | Result | Evidence |
|---|---|---|
| Runtime installation | PASS | `runtime-spike/package-lock.json`; full optional dependency install completed |
| Version pin | PASS | `dsh --version` → `0.1.0-rc.7` |
| Node runtime | PASS | Node `v24.16.0` |
| CLI/process boundary | PASS | `dsh web --host 127.0.0.1 --port 0` stayed alive and returned HTTP 200 |
| Session startup | PARTIAL | headless profile created a session directory, but the task did not complete within 30 seconds without a configured provider key |
| Skill loading | PARTIAL | official filesystem skill layout accepted; local `stock-research` loaded by the boundary registry; model-facing live load not completed |
| Tool invocation | PASS (boundary fixture) | facade invoked profile → readiness → scenario in order; no collector or graph write entrypoint exists |
| 贵州茅台 demo | PARTIAL | structured three-call fixture response produced; no live provider/data claim made |
| Research OS authority | PASS | no core/data/schema/orchestrator/source/graph changes |
| Regression | PARTIAL | P8-A0 tests 5 passed; compileall passed; full pytest exceeded 300 seconds |

## Installation record

The isolated environment is `runtime-spike/`. It pins:

```json
"@deepseek-ai/dsh": "0.1.0-rc.7"
```

The generated lockfile and complete `npm ls --all --json` dependency tree are
kept in that directory. Optional/native dependencies must not be omitted: an
`--omit=optional` install failed during boot because the Koffi native module was
missing. A full install completed with 528 packages.

## Runtime evidence

The official web profile started successfully at an OS-selected loopback port:

```text
dsh web: http://127.0.0.1:58440
HTTP status: 200
```

The process was stopped after verification. The headless profile created a
persistent session directory, but could not finish the requested research task
in the isolated environment without a configured DeepSeek provider. Its output
is therefore not treated as a successful research result.

## Boundary demo

The reproducible `runtime-spike/verify_demo.py` calls exactly:

1. `get_company_profile`
2. `check_data_readiness`
3. `run_research_scenario`

The output is explicitly marked `fixture_success`. It validates the process
boundary and structured contract, not external facts or live source coverage.
