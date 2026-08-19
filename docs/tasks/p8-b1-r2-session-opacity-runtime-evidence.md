# P8-B1-R2 Session Opacity, Fail-Closed Runtime Evidence & Acceptance Integrity

**TASKBOOK_STATUS:** IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

**BASE:** `96ea74a163170b5026a3cde63468753517fb0ba2`

**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`

**MCP:** `research-os-mcp/v1`

## Scope result

R2 closes only the three findings from the prior acceptance: internal Harness
session opacity, fabricated runtime denial evidence, and non-mechanical live
same-session/authority evidence. No Tool, Skill, Scenario, frontend, production
traffic, schema, database, migration, source, Graph, ChatService, Orchestrator,
or P8-B2 change was added.

## Implemented gates

- Public response is allowlisted and recursively strips internal session fields.
- Resume/cancel/Gateway responses do not expose the Harness internal session ID.
- Runtime evidence records observed, disabled, enabled, and verified-absent IDs.
- `arbitrary_subprocess` is never promoted from policy-only evidence.
- Enabled or incomplete forbidden-component evidence fails closed.
- Same-session continuity is mechanically compared and emitted only as a boolean.
- Live Tool evidence comes from the MCP event log, not MCP startup probing.
- Turn 1 observes both allowed Tools; Turn 2 observes a new readiness event.
- stdout, event log, and bounded operational output receive secret scanning.
- Current governance state is `IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE`.

## Acceptance evidence

- Live provider run: PASS
- Same internal session: PASS
- Turn 1 Tool evidence: PASS
- Turn 2 new readiness event: PASS
- Authority re-read: PASS
- Secret scan: PASS
- Provider network: ON only for explicit acceptance
- Research data network: OFF
- Production adoption: NOT_AUTHORIZED
- P8-B2: NOT_AUTHORIZED
