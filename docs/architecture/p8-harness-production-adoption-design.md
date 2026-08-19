# P8 Harness Production Adoption Architecture

**STATUS:** DESIGN COMPLETE / AWAITING INDEPENDENT ACCEPTANCE  
**BASE:** `b048f65`  
**RUNTIME CANDIDATE:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**IMPLEMENTATION:** NOT AUTHORIZED

## 1. Target topology

```text
User / Frontend
       |
       v
Agent Runtime Gateway (Python/backend control plane)
       |
       +--------------------------+
       |                          |
       v                          v
Persistent isolated Node       P7-UX1 legacy Chat path
Harness service (opt-in)       (default and fallback)
       |
       v
Research Skills
       |
       v
Versioned Research OS MCP surface: research-os-mcp/v1
       |
       v
Python Research OS authority
       |
       +-- Orchestrator / Scenario Registry / Runner
       +-- DataPreflight / Acquisition / Source Router
       +-- Documents / Financial / Evidence / PIT
       +-- Graph Query / Validators / Report artifacts
       |
       v
SQLite + governed sources
```

The Node service is a separately managed process. It is not embedded in Python,
vendored into `src/research_os`, or deployed by copying `runtime-spike`. The gateway
owns admission, feature flags, authentication context, timeout budgets, and fallback.
The Harness service owns only agent sessions and agent-facing execution.

## 2. Ownership matrix

| Concern | Owner | Harness access |
|---|---|---|
| Conversation messages and bounded session context | Harness | owner |
| Agent loop, Skill loading, tool selection | Harness | owner |
| Formal Task / Plan / Request / Run | Research OS | through approved scenario tools |
| Entity and security identity | Research OS | read capability only |
| Data readiness, gaps, acquisition plan | Research OS | read capability only |
| Source selection and collector routing | Research OS | never exposed directly |
| RawItem / Document / Evidence / Claim | Research OS | bounded references/results |
| Financial facts and deterministic calculations | Research OS | structured read results |
| PIT / as-of eligibility | Research OS | every relevant tool validates it |
| Graph query | Research OS | read-only capability |
| Graph proposal/review/apply | Research OS governance | not in initial production catalog |
| Report artifacts and idempotency | Research OS | reference/result only |
| Audit event stream | split: gateway correlation + Research OS authority audit | metadata only |

Harness session memory is never promoted to Research State or Knowledge Memory. A
follow-up question that needs current facts must re-run the Research OS tool; cached
conversation text is not authoritative.

## 3. Runtime placement and lifecycle

The recommended production shape is one persistent isolated service per deployment
unit, with bounded concurrent sessions. Each session is identified by a gateway-owned
opaque ID mapped to the Harness session ID. A process supervisor owns startup and
restart; the gateway owns readiness and graceful drain.

Lifecycle states:

```text
STARTING -> READY -> DRAINING -> STOPPED
    |         |          |
    +------> FAILED <----+
```

- `STARTING`: compose exact profile, verify version and deny-list, bind loopback or
  private service address, start MCP bridge, and pass health checks.
- `READY`: accept only admitted sessions and approved tool catalog calls.
- `DRAINING`: reject new sessions, finish bounded turns, cancel after deadline, and
  persist only permitted public session metadata.
- `FAILED`: expose a typed failure to the gateway; gateway selects P7-UX1.
- Restart never implies Research OS workflow replay.

Windows cleanup must terminate only the process tree created by the service instance.
Global `taskkill /F` or global Python/Node termination is prohibited. Linux/CI uses a
service manager or scoped process group with the same ownership rule.

## 4. Session and memory policy

### Conversation Memory — Harness

May contain user messages, public assistant answers, active goal/context, bounded tool
metadata, and Research OS object/evidence references. It must exclude credentials,
Authorization headers, cookies, private chain-of-thought, raw full documents, and
unbounded source payloads.

### Research State — Research OS

Task, Plan, Request, Run, readiness, acquisition execution, structured results,
report artifacts, status, and audit state remain in the existing Research OS paths.

### Knowledge Memory — Research OS

SQLite, Evidence, and versioned Graph remain canonical. A session reference is not a
fact. Session expiry, deletion, corruption, compaction, and retention are operational
events, not authority mutations.

Initial design limits: 20 turns per session, 128 active sessions per service unit,
bounded tool results, idle expiry, explicit deletion, and fail-closed corrupted-session
handling. Exact retention duration and encryption mechanism require P8-B1 security
acceptance.

## 5. Versioned MCP boundary

The production namespace is `research-os-mcp/v1`. Every tool definition contains:

- name and description;
- input and output schema identifiers;
- authority owner;
- network and write policy;
- PIT/as-of semantics;
- bounded result size;
- stable failure codes;
- evidence/object reference semantics.

Initial read-only catalog design:

| Class | Candidate tools | Policy |
|---|---|---|
| Capability | `get_company_profile`, `check_data_readiness`, `lookup_evidence`, `query_industry_graph`, `analyze_financials`, `get_research_artifact` | Research OS authority, read-only |
| Scenario | `run_stock_research`, `run_industry_research`, `run_daily_brief`, `run_abnormal_move_analysis` | formal Research OS workflow only |

The first production foundation may expose only the two A0-verified tools until each
additional tool passes its own capability acceptance. The following are prohibited:
`cninfo_fetch`, `nbs_fetch`, `sina_fetch`, `collector_execute`, `sql_query`,
`graph_apply`, and `graph_approve`. `propose_graph_change` requires a separate
taskbook and is not part of B1.

Tool failures are structured and bounded: `MCP_UNAVAILABLE`, `MCP_TOOL_FAILED`,
`RUNTIME_VERSION_MISMATCH`, `PROVIDER_TIMEOUT`, or a domain-specific Research OS
status. The Harness must not reinterpret `partial_success`, `degraded`, or
`insufficient_evidence` as success.

## 6. Security profile

Production composition is deny-by-default:

```text
bash OFF
filesystem write OFF
editor OFF
arbitrary subprocess OFF
coding tools OFF
direct internet OFF
source direct access OFF
graph write/approve/apply OFF
research MCP ON
```

The gateway must verify the composed profile at boot, not rely on prompt text. A
profile mismatch prevents readiness. Research external network access can occur only
inside an explicitly governed Research OS acquisition workflow; Harness provider
network is a separate gate.

## 7. Frontend boundary

Frontend never calls Harness internal API, MCP, or Research OS SQLite. The backend
gateway contract is:

```text
create_session(input) -> { session_id, runtime_mode, status }
send_message(session_id, content) -> { accepted, request_id }
resume_session(session_id) -> { session_id, status }
cancel_turn(session_id, request_id) -> { cancelled }
get_business_progress(session_id) -> progress projection
get_research_result(session_id, result_ref) -> bounded result projection
get_tool_evidence_refs(session_id) -> metadata/reference projection
```

These are design contracts only. They do not authorize frontend code, public API
implementation, or UI capability claims. `runtime_mode` defaults to `legacy` and
must be server-controlled.
