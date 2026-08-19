# P8 Agent Runtime Operational Contract

**STATUS:** DESIGN ONLY / P8-B1 NOT AUTHORIZED  
**RUNTIME:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**UPSTREAM:** Developer Preview

## 1. Health and lifecycle contract

The gateway consumes three independent signals:

```text
process_alive -> profile_verified -> ready
```

`process_alive` alone is never readiness. Readiness requires exact runtime version,
deny-list verification, MCP handshake, bounded tool catalog, provider configuration
presence (without exposing its value), and a successful no-write authority probe.

Required failure codes:

```text
HARNESS_BOOT_FAILED
PROVIDER_AUTH_FAILED
PROVIDER_TIMEOUT
MCP_UNAVAILABLE
MCP_TOOL_FAILED
SESSION_CORRUPTED
RUNTIME_VERSION_MISMATCH
PROFILE_POLICY_MISMATCH
RESOURCE_BUDGET_EXCEEDED
```

Startup, health, ready, shutdown, restart, timeout, crash recovery, port binding,
MCP reconnect, provider failure, and session recovery must each emit bounded metadata.
Shutdown is graceful first, then scoped process-tree termination for the service-owned
root only.

## 2. Credential lifecycle

Provider credentials are injected by the deployment secret mechanism into the Harness
process environment or secret handle. They are never passed through Frontend,
session content, tool arguments, Research OS objects, SQLite, reports, or logs.

The design requires:

- startup secret presence check with redacted result;
- rotation without writing the new value to session history;
- child-process inheritance limited to the service-owned tree;
- log and error redaction for key/header/cookie/password patterns;
- crash dump and diagnostic artifact exclusion;
- explicit revocation and restart behavior.

Provider credentials authorize model calls only. They do not authorize Research OS
source acquisition, collector routing, graph writes, or database access.

## 3. Security assertions

The runtime must fail closed if any of these are enabled or mounted unexpectedly:

```text
bash, pwsh, filesystem write, editor, arbitrary subprocess, coding tools,
direct internet, source-specific tools, SQL, graph approve, graph apply
```

Research OS MCP is the only agent-facing capability surface. The profile is verified
at composition/startup and periodically on restart, not inferred from model text.

## 4. Observability contract

Allowed fields:

- opaque session ID and request ID;
- runtime/profile version;
- Skill name;
- Tool name and status;
- duration and bounded token usage;
- provider status and typed failure code;
- Research artifact/evidence references;
- fallback decision and rollout cohort.

Forbidden fields:

- private chain-of-thought;
- provider credentials or raw Authorization;
- complete sensitive tool payloads;
- full source documents or transient PDF bytes;
- unbounded user content in operational logs.

Metrics are split into runtime health, provider health, MCP health, gateway fallback,
session lifecycle, quota/cost, and Research OS business outcomes. A provider failure
must not be mislabeled as a Research OS data failure.

## 5. Resource and cost controls

The service must enforce, before production foundation acceptance:

- maximum concurrent sessions per service and per user;
- idle session expiry and maximum turns/history;
- per-turn provider timeout;
- maximum tool calls per turn;
- maximum tool payload/result size;
- token budget and maximum response size;
- bounded retry count with no autonomous infinite loop;
- provider cost telemetry and budget alarm;
- drain deadline and process-child limit.

Retries are classified: transport retry may be safe for an idempotent read; formal
Research OS workflow retry requires its own idempotency key and must not be silently
duplicated by fallback.

## 6. Developer Preview risk register

| Risk | Control | Release gate |
|---|---|---|
| API compatibility break | exact pin and compatibility probes | upgrade acceptance |
| profile format change | composed deny-list snapshot | profile verification |
| session API change | continuation and recovery tests | session acceptance |
| MCP behavior change | versioned contract and negative tools | boundary acceptance |
| npm/native dependency volatility | lockfile, supported Node version, isolated build | reproducible install |
| credential/security assumption drift | secret scan and profile deny assertions | security acceptance |
| Node/native Windows/Linux difference | OS-specific lifecycle tests | process gate |
| cost or concurrency expansion | quotas, budgets, alerts | resource acceptance |
| upstream preview abandonment | retained legacy path and rollback artifact | governance review |

## 7. Incident and fallback contract

On any critical violation, the gateway:

1. stops admitting new Harness sessions;
2. switches new requests to P7-UX1;
3. drains or cancels owned Harness turns within the deadline;
4. preserves bounded audit metadata and Research OS run state;
5. emits one typed incident/fallback code;
6. prevents automatic re-enable until an operator/governance decision.

There is no silent duplicate execution. A user may explicitly retry a failed request;
the Research OS idempotency contract decides whether a formal run is reused or rebuilt.

## 8. Acceptance evidence required for P8-B1

P8-B1 must provide evidence for all controls in this document, plus a separate
security review, deployment-specific secret handling, OS process tests, load/cost
boundaries, and a rollback drill. This design document is not that evidence and does
not authorize implementation.
