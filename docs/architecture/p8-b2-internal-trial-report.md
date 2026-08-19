# P8-B2 Internal Trial Report

STATUS: PARTIAL / NOT ACCEPTED

## Run

- Trial run: `b2-216970a3586047af96011f3fd4355c97`
- Runtime: `@deepseek-ai/dsh` `0.1.0-rc.7`
- Provider network: `ON` for explicit trial only
- Research data network: `OFF`
- Default runtime: `legacy`
- Production adoption: `NOT_AUTHORIZED`
- P8-B3: `NOT_AUTHORIZED`
- B2 base: `e64249e9eb99a395ebaa63308d0d72ad1d3a7a74`
- B2 implementation head at initial report: `0ecd8c1`

## Evidence

| Gate | Result |
|---|---|
| Local cold boot | PASS 3/3; 2.157–3.109 seconds; exact version/profile/MCP catalog |
| Boot failure classification | None in 3 cold boots; prior failure class was `HTTP_NOT_READY_TIMEOUT` |
| Runtime admission | PASS; restart re-verification PASS |
| Session establishment | PARTIAL: 1 Harness session established; provider timeout before corpus progress |
| Live model/skill invocation | NOT VERIFIED |
| Research OS tool invocation | NOT VERIFIED |
| Authority drift | 0 observed in available evidence |
| Unauthorized tools | 0 observed |
| Research source network | OFF |
| Rollback latch | PASS |
| Owned-process crash/restart | PASS |
| Process residue | NO |
| Provider failures | 2 `PROVIDER_TIMEOUT`; 1 `HARNESS_BOOT_FAILED` during the run lifecycle |
| Fallback | PASS; 1 real legacy adapter route with `MCP_UNAVAILABLE` reason |
| Rollback | PASS; latch denied new Harness admission after controlled trip |
| Sessions / turns | 0 completed / 1 attempted turn in the final provider run |
| Token usage | `NOT_REPORTED` |
| Monetary cost | `NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME` |
| Latency baseline | NOT_AVAILABLE: no completed provider-backed turn |
| Budget utilization | sessions 0.10; turns 0.00; tools 0.00; provider tokens 0.00 |
| Process hygiene | PASS; owned root and descendants gone after stop; process leak count 0 |
| Full pytest | NOT_VERIFIED: prior full run timed out; targeted offline tests pass |

## Decision

The execution evidence is insufficient for a full demo or P8-B2 acceptance.
The result is intentionally `PARTIAL`; no production adoption, default runtime
change, frontend exposure, or P8-B3 authorization follows from this report.
