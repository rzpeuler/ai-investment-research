# P8-B1-R3 Public Session Contract & Final Acceptance Closure

**TASKBOOK_STATUS:** PASS / INDEPENDENTLY ACCEPTED

**BASE:** `de9a5e3b3cbe93fe1c17abdc3281738fe1dbea4f`

**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`

**MCP:** `research-os-mcp/v1`

## Result

R3 closes only the public session contract finding. Internal `GatewaySession`
records remain available to Gateway/Adapter mappings, while callers receive the
allowlist-based `PublicGatewaySession` DTO. Legacy and Harness create-session
paths now return the same public type. `resume_session()` returns the same type
with a stable resumed status.

## Acceptance evidence

- Public create session contains no Harness internal ID: PASS
- Public DTO has no `harness_session_id` field: PASS
- Internal adapter mapping retains Harness ID: PASS
- Legacy/Harness public contract consistency: PASS
- send/resume/cancel/close recursive opacity: PASS
- R2 fail-closed evidence unchanged: PASS
- Live same-session and Tool event evidence: PASS
- Authority re-read and secret scan: PASS
- Research data network: OFF
- Default runtime: legacy
- Production adoption: NOT_AUTHORIZED
- P8-B2: NOT_AUTHORIZED

Execution status is `PASS / INDEPENDENTLY ACCEPTED` under the P8-B2 M0 closeout.
