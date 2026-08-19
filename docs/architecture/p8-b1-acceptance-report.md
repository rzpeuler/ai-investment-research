# P8-B1 Acceptance Report

**STATUS:** IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

**BASE:** `a2b984bd61b57f8e7a50985c1a9e5c7d451b45a0`

**IMPLEMENTATION_HEAD:** `600b24292a73009e0765bdadf49865b3e2bc24c2`

**R1_FINAL_HEAD:** `86070d4`

**R3_FINAL_HEAD:** `caf7289`

**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`

## Scope

P8-B1 implements the feature-flagged, non-production-default Agent Runtime
foundation. The default path remains P7-UX1 / `legacy`. No frontend, production
traffic, schema, DB migration, source acquisition, Graph write, or P8-B2 work
was performed.

## R2 acceptance gates

| Gate | Result |
| --- | --- |
| Agent Runtime Gateway | PASS |
| Legacy adapter preserved | PASS |
| Harness Supervisor lifecycle | PASS |
| Exact version gate | PASS |
| Research profile verification | PASS |
| MCP namespace | `research-os-mcp/v1` |
| MCP Tool catalog | exactly `get_company_profile`, `check_data_readiness` |
| Source / SQL / Graph Tools | DENIED |
| 64 KiB result bound | PASS |
| Opaque gateway session | PASS |
| Typed failures | PASS |
| Secret redaction | PASS |
| Default runtime | `legacy` |
| Provider network | OFF |
| Research data network | OFF |
| Schema / DB / migrations | 86 / v6 / NONE |
| Legacy P7-UX1 real binding | PASS |
| Official Harness client | PASS |
| Production process factory | PASS |
| Clean npm install | PASS; 528 packages; 0 vulnerabilities |
| Actual composed profile evidence | PASS |
| Actual stdio MCP handshake/discovery | PASS |
| Owned process-tree cleanup | PASS |
| Crash recovery | PASS |
| Rollback drill | PASS |
| Session quota release | PASS |
| Live provider acceptance | PASS |
| Same-session continuation | PASS |
| Authority re-read | PASS |
| Security review | PASS |
| Internal Harness session ID public leak | NOT EXPOSED |
| Runtime evidence fabricated PASS | REMOVED |
| Runtime evidence fail-closed mutation tests | PASS |
| Live same-session evidence | PASS; boolean only |
| Live Tool event evidence | PASS; MCP event log |
| Live authority re-read | PASS; new readiness event |
| Live secret scan | PASS |
| Public create session contract | PASS |
| Public session DTO has no internal ID | PASS |
| Legacy / Harness public contract | CONSISTENT |
| Resume public contract | PASS |

## Offline regression result

`python -m pytest -q`: **3712 passed / 6 skipped / 0 failed / 1 warning**
`python -m research_os.cli.main validate`: **86/86 PASS**  
`python -m compileall -q src scripts tests`: **PASS**  
`git diff --check`: **PASS**

## Live provider acceptance

Provider network was explicitly enabled for one acceptance run. Research data
network remained OFF. The actual session completed two turns through the
pinned rc.7 process, actual profile, and stdio MCP. The MCP event log observed
both allowed Tools in Turn 1 and a new `check_data_readiness` event in Turn 2.
Same-session continuity was computed internally and emitted only as a boolean;
no internal Harness ID was recorded. Research data network remained OFF and the
secret scan passed.

Production adoption and default Harness switching remain not authorized.
