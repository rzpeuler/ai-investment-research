# P8-B1-R1 DeepSeek Harness Production Runtime Binding & Terminal Acceptance

**TASKBOOK_STATUS:** PASS / INDEPENDENTLY ACCEPTED

**BASE:** `1b6b3e37efb159542e78e7e10a9408d66b73617e`

**FINAL_HEAD:** `86070d4`

**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`

**MCP:** `research-os-mcp/v1`

## Terminal result

R1 closed the runtime-binding findings without adding Tools, Skills, Scenarios,
frontend, production traffic, or B2 rollout. The foundation now binds the
official pinned package, an observed production profile, an actual stdio MCP
surface, the real P7-UX1 legacy seam, and an owned process-tree lifecycle.

## Acceptance gates

- Legacy P7-UX1 binding: PASS
- Official Harness client: PASS
- Production process factory: PASS
- Clean npm install and exact version: PASS
- Observed profile composition: PASS
- Actual stdio handshake and exact two-tool discovery: PASS
- Tool loop through Research OS authority: PASS
- Process cleanup and crash recovery: PASS
- Rollback and session quota release: PASS
- Security review and secret scan: PASS
- Live provider session and same-session continuation: PASS
- Research data network: OFF
- Full regression: 3704 passed / 6 skipped / 0 failed / 1 warning
- Schema / DB / migrations: 86 / v6 / NONE

Production adoption remains `NOT_AUTHORIZED`; default runtime remains `legacy`;
P8-B2 remains `NOT_AUTHORIZED`.
