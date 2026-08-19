# P8-B1 DeepSeek Harness Production Foundation Implementation Design

Status: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

Base: `9aa707161b77a8ca6db1fd2f66b2fe7c6c1abfff`

Harness: `@deepseek-ai/dsh@0.1.0-rc.7`

## 1. Scope and invariants

P8-B1 builds a non-production-default, feature-flagged foundation for a future
Harness-backed Agent Runtime. The default runtime remains `legacy`, and the
Harness path requires explicit server-side opt-in. Client payloads cannot select
or override the runtime mode.

The implementation must not modify ChatService, Orchestrator, Data Layer,
Financial Extractor, Knowledge Graph, Source Registry, Frontend, schemas, the
database, or migrations. `runtime-spike/` remains an acceptance reference only
and is not a production dependency.

## 2. Runtime boundary

The backend boundary is:

```text
caller
  -> AgentRuntimeGateway
      -> LegacyAgentRuntimeAdapter       (default)
      -> HarnessAgentRuntimeAdapter      (explicit opt-in only)
          -> HarnessRuntimeSupervisor
              -> isolated Harness service
                  -> research-os-mcp/v1
                      -> existing Research OS authority
```

`AgentRuntimeGateway` owns the stable session operations:
`create_session`, `send_message`, `resume_session`, `cancel_turn`, and
`get_runtime_status`. Harness internal session identifiers are never exposed as
public identifiers; the gateway maintains an opaque ID mapping owned by the
Harness runtime while Research OS remains the owner of research state.

## 3. Supervisor and admission

`HarnessRuntimeSupervisor` models `STARTING`, `READY`, `DRAINING`, `STOPPED`,
and `FAILED`. Process liveness is separate from readiness. READY requires all of
the following:

- owned process is alive;
- exact runtime version is `0.1.0-rc.7`;
- production research profile verifies successfully;
- MCP namespace handshake succeeds;
- advertised Tool catalog exactly matches the two allowed Tools;
- required configuration and credential preflight pass.

Any version, profile, MCP, Tool, credential, or runtime failure is typed and
fail-closed. Process cleanup is limited to the supervisor-owned process tree;
global Node/Python termination is forbidden.

## 4. Production profile and MCP contract

The production profile denies shell, filesystem write/edit/search, jobs,
subagents, workflow coding tools, todo/goal tools, direct web/search, and
arbitrary subprocess capabilities. The only exposed MCP namespace is
`research-os-mcp/v1`, with exactly:

- `get_company_profile`
- `check_data_readiness`

Both Tools reuse existing Research OS entity/security and readiness authority.
`check_data_readiness` is dry-run and must not start CNINFO, NBS, or any source
refresh. No source-specific, SQL, Graph mutation, or scenario Tool is exposed.

Tool contracts include typed status/failure semantics, authority metadata,
network/write policy, point-in-time metadata, and a 64 KiB fail-closed result
bound. Missing data may return partial or insufficient status and must not be
upgraded to success.

## 5. Gateway behavior, fallback, and security

Legacy behavior remains unchanged behind `LegacyAgentRuntimeAdapter`. Before a
formal Harness research workflow begins, Harness admission failure may produce
a typed fallback to legacy with a recorded reason. After a Harness workflow
starts, the gateway must not silently duplicate the workflow through legacy.

`cancel_turn` cancels only the selected session turn. Supervisor drain handles
service shutdown. Session, request, runtime, profile, Tool, duration, bounded
token, typed failure, fallback, and Research OS reference metadata are
observable; secrets are redacted by field name and known secret value before
logs, session metadata, errors, or results are emitted.

Resource limits are explicit and validated, including the existing 20-turn,
128-active-session, and 64 KiB result limits plus bounded timeout, retry, token,
Tool-call, and response settings. Read retries are restricted to idempotent
operations. No new database persistence is introduced; Harness-owned isolated
runtime storage and bounded operational mapping remain distinct from Research
OS research truth.

## 6. Verification plan

Offline tests cover default legacy mode, client override rejection, exact
version gating, profile denial, MCP handshake, exact Tool allowlist, absent
source/SQL/Graph Tools, result bounds, opaque sessions, typed credential and
runtime failures, scoped process cleanup, fallback behavior, secret redaction,
rollback, crash recovery, and bounded admission. Offline tests use zero provider
network, zero Research data network, and zero live Harness calls.

Explicit live acceptance, if separately authorized, may enable only the DeepSeek
provider network. Research data network remains OFF. It must verify supervisor
boot, exact version, profile, MCP handshake, two allowed Tool calls, same-session
continuation, graceful drain, process cleanup, and secret scanning.

Acceptance documentation will report implementation as
`IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE`; it must not claim production
adoption or change the default runtime.

## 7. Explicit non-goals

This milestone does not implement frontend wiring, production traffic,
production-default Harness, P7-UX1 retirement, scenario Tools, provider/source
adapters, graph writes, database tables, schema changes, migrations, or P8-B2.
