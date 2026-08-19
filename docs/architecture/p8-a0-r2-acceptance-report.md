# P8-A0-R2 Acceptance Report

**Base:** `3957be9e251ffc20972a53fd6061ff0a9d2dceeb`  
**Date:** 2026-08-19  
**Harness:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**Status:** **PARTIAL**  
**Production adoption:** `NOT_AUTHORIZED`  
**P8-B:** `NOT_AUTHORIZED`

## Gate results

| Gate | Result | Evidence |
|---|---|---|
| Exact runtime/version pin | PASS | isolated `runtime-spike`; `dsh --version` = `0.1.0-rc.7` |
| Research-only profile | PASS | composed profile disables public bash/pwsh/filesystem/editor/web tools; MCP only advertises two read capabilities |
| Provider credential preflight | PASS | missing key returns `PROVIDER_AUTH_MISSING` before boot; no secret in output |
| Provider-backed session | PASS | live run completed with exit 0 in ~16 seconds; final assistant response present |
| Model-facing `stock-research` skill | PASS | custom skill root configured through official filesystem provider; live response names and follows skill |
| Real process/MCP tool call | PASS | stdio MCP server event evidence shows live `get_company_profile` and `check_data_readiness` calls |
| `get_company_profile` authority | PASS / PARTIAL DATA | SQLite read-only authority returned `partial_success`, entity `company:maotai`, symbol `600519.SH`, profile missing |
| `check_data_readiness` authority | PASS / DATA NOT READY | existing `DataPreflightService`; `requirement_count=7`, `missing_count=7` |
| Source direct access | DENIED | no source/collector tools advertised or implemented |
| Graph write/apply | DENIED | no graph mutation tools advertised or implemented |
| Tool result bound | PASS | hard 64 KiB fail-closed bound |
| Session credential scan | PASS | launcher output and event evidence contain no API key/header/cookie |
| Same-session continuation | NOT VERIFIED | official `headless` runner creates a fresh UUID session per invocation; no continuation run claimed |
| Full regression | NOT VERIFIED | offline `python -m pytest` exceeded 300 seconds without a completion result |
| Schema/database/migrations/core | PASS | no schema or DB migration; core authority unchanged |

## Live run evidence

The successful live run used the user-provided prompt for 贵州茅台 with the
explicit security identifier `600519.SH` for authority resolution. The model
called, through the official MCP client bridge:

1. `get_company_profile` → `partial_success`; `company:maotai` and
   `security:600519.SH`; `company_profile_missing`.
2. `check_data_readiness` → `partial_success`; seven requirements, seven
   missing; data acquisition disabled and no external source network.

The returned structured result was bounded and the model did not invent missing
financial, document, industry, peer, or valuation facts. No Research external
data network was enabled.

## Known limitations

- `research-headless` is the smallest official process-backed profile available
  in rc.7; same-session continuation needs a separate programmatic/Web session
  driver and was not falsely inferred from two one-shot runs.
- The current governed database has a security identity but no qualifying
  company profile, so the live demo correctly remains `partial_success` and
  does not begin a formal research report.
- Full project regression remains unresolved because the suite did not complete
  within the permitted 300-second observation window.

**Decision:** technical boundary is viable for further review, but R2 is not a
full acceptance candidate and does not authorize P8-B or production adoption.
