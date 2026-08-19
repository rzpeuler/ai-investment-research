# P8-B2 Internal Trial Report

STATUS: PARTIAL / NOT ACCEPTED

## Run

- Trial run: `b2-77ee3b4e52a54f6d97f042f74f4766bd`
- Runtime: `@deepseek-ai/dsh` `0.1.0-rc.7`
- Provider network: `ON` for explicit trial only
- Research data network: `OFF`
- Default runtime: `legacy`
- Production adoption: `NOT_AUTHORIZED`
- P8-B3: `NOT_AUTHORIZED`

## Evidence

| Gate | Result |
|---|---|
| Runtime admission | PASS for the attempted run; restart re-verification PASS |
| Session establishment | NOT COMPLETED: provider timeout before corpus progress |
| Live model/skill invocation | NOT VERIFIED |
| Research OS tool invocation | NOT VERIFIED |
| Authority drift | 0 observed in available evidence |
| Unauthorized tools | 0 observed |
| Research source network | OFF |
| Rollback latch | PASS |
| Owned-process crash/restart | PASS |
| Process residue | NO |
| Provider failures | 2 `PROVIDER_TIMEOUT`; 1 `HARNESS_BOOT_FAILED` during the run lifecycle |
| Sessions / turns | 0 / 0 completed in the final run |
| Token usage | `NOT_REPORTED` |
| Monetary cost | `NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME` |

## Decision

The execution evidence is insufficient for a full demo or P8-B2 acceptance.
The result is intentionally `PARTIAL`; no production adoption, default runtime
change, frontend exposure, or P8-B3 authorization follows from this report.
