# P8-B1 DeepSeek Harness Production Foundation

**TASKBOOK_STATUS:** IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE  
**TYPE:** Production foundation implementation; non-production-default; feature-flagged  
**BASE:** `a2b984bd61b57f8e7a50985c1a9e5c7d451b45a0`  
**BRANCH:** `feature/p8-b1-production-foundation`  
**IMPLEMENTATION_HEAD:** `600b24292a73009e0765bdadf49865b3e2bc24c2`  
**P8-B:** PASS / INDEPENDENTLY ACCEPTED  
**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**UPSTREAM:** Developer Preview  

## Authorization and boundaries

This taskbook implements only the P8-B1 production foundation. The default
runtime remains `legacy`; Harness is explicit server-side opt-in and is never
selected by client payload. `runtime-spike/` remains an acceptance reference
and is not imported by production code.

Allowed implementation areas are `src/research_os/agent_runtime/**`,
`agent_runtime/**` runtime/profile assets, `scripts/p8_b1_*`, tests, and the
P8-B1 documentation. No frontend, production traffic, schema, DB migration,
source expansion, Graph write, ChatService, LlmClient, Orchestrator, or P8-B2
work is authorized.

## Foundation deliverables

- `AgentRuntimeGateway` with session lifecycle operations and legacy adapter.
- `HarnessRuntimeSupervisor` with owned-process lifecycle and fail-closed READY.
- Exact version gate for `0.1.0-rc.7` and `research-headless` profile verification.
- Versioned `research-os-mcp/v1` boundary with exactly two read Tools:
  `get_company_profile` and `check_data_readiness`.
- Secret redaction, typed failures, session quotas, result bound, fallback and
  rollback/crash lifecycle foundations.
- Reproducible runtime package/profile metadata independent of `runtime-spike`.

## Acceptance gates

Offline acceptance must use zero provider, source, CNINFO, NBS, and live Harness
network. It must cover default legacy mode, client override rejection, exact
version/profile gates, MCP handshake, Tool allowlist, denied capabilities,
opaque sessions, secret redaction, scoped cleanup, fallback, crash recovery,
rollback, resource admission, compileall, schema validation, and regression.

Live provider acceptance is separate and explicit. If enabled, Research data
network remains OFF and the report must redact credentials and internal session
identifiers.

## Terminal state

Implementation completion must be recorded as:

```text
P8-B1: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
P8-B2: NOT_AUTHORIZED
DEFAULT_RUNTIME: legacy
PRODUCTION_ADOPTION: NOT_AUTHORIZED
SCHEMA: 86/86 PASS
DB: v6
MIGRATIONS: NONE
```
