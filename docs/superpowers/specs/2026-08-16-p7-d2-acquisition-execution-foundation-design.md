# P7-D2 Acquisition Execution Foundation — Design

**Date:** 2026-08-16  
**Status:** APPROVED DESIGN / IMPLEMENTATION NOT AUTHORIZED  
**Parent baseline:** P7-D1 accepted implementation head `bc277817ee419410803f5541d74be75a330e9713`  
**Scope:** execution foundation with injected fakes; every real source remains disabled

## 1. Context and authority

P7-D1 established the deterministic, read-only control plane:

```text
ScenarioDataRequirement
→ DataReadiness before
→ DataGap
→ AcquisitionPlan
```

Decision #48.11 authorizes P7-D2 taskbook drafting and architecture design only. It does not
authorize implementation, live acquisition, a specific external source, a new Collector, source
expansion, a database migration, Graph write, Phase 6.1, or any LLM/provider call.

This design adds the missing execution shape without claiming that any real adapter is business
sufficient. The first implementation must prove the complete path with injected fakes while the
production path remains fail-closed.

## 2. Goals

P7-D2 will define one controlled path:

```text
DataReadiness before
→ AcquisitionPlan
→ execution gate
→ existing Router
→ Collector bridge
→ normalize + Schema validation
→ atomic idempotent persistence
→ DataReadiness after
→ existing Runner
```

The design must:

1. keep the existing `src/research_os/routing/router.py` as the only source Router;
2. execute only `route_existing_sources` steps;
3. require an explicit live gate and `BUSINESS_SUFFICIENT` capability;
4. preserve P7-D1 requirement, binding, projector, time, provenance, coverage, and freshness
   authorities during recheck;
5. record honest execution and failure audit data;
6. make RawItem persistence atomic and idempotent;
7. leave all existing Runner business success semantics unchanged;
8. use zero LLM calls.

## 3. Non-goals

P7-D2 Foundation does not:

- promote `cls`, `cninfo`, `nbs`, `sina_quote`, or any other adapter to
  `BUSINESS_SUFFICIENT`;
- modify source status or verification evidence in `registry/sources.yaml`;
- add or expand a Collector, endpoint, API, selector, login flow, or source whitelist;
- implement automatic financial statements, historical daily bars, attention monitoring,
  Heat Ranking, scheduling, queues, background workers, concurrency, or continuous scans;
- execute `derive_existing`, manual input, human review, governed workflow, or unavailable steps;
- convert a RawItem directly into Evidence, Claim, Event, Finding, or Graph state;
- modify report conclusions, Runner status, exit code, or existing missing-data semantics;
- write Graph state, authorize Phase 6.1, or call DeepSeek/another provider;
- change DB v6 or add a migration.

Fake end-to-end tests prove only the foundation. They do not prove a real source usable.

## 4. Considered approaches

### 4.1 Selected: execution kernel with injected fakes

Build the full execution kernel, production gate, backward-compatible Router extension,
transactional writer, recheck, artifacts, and tests. The production Collector bridge has no
eligible real registrations because no capability is `BUSINESS_SUFFICIENT`.

This approach gives a testable architecture without silently authorizing network behavior.

### 4.2 Rejected: shadow live execution

Real Router/Collector calls with persistence disabled would test external behavior, but they would
still perform unauthorized networking and source execution.

### 4.3 Rejected: immediate single-source vertical slice

Wiring a real source such as CNINFO would require separate source-specific authorization, live
acceptance, time-window proof, field sufficiency proof, and capability promotion.

## 5. Components

### 5.1 `DataAcquisitionCoordinator`

The Coordinator owns the pre-Runner sequence:

```text
preflight before → optional execute → recheck → existing Runner
```

It accepts the existing P7-D1 bundle, immutable `AcquisitionPlan`, normalized request, task
identity, project/run paths, database handle, and system-controlled execution gates. It does not
select sources, normalize provider payloads, or determine readiness itself.

When acquisition is disabled, its output must be observationally equivalent to P7-D1 except for an
explicit `NOT_EXECUTABLE` execution audit in non-dry-run mode. It must not call Router, Collector,
network, or business-data persistence.

### 5.2 `AcquisitionExecutionService`

The service validates and executes the plan. It accepts only `route_existing_sources`; every other
action is recorded as `skipped` with an explicit reason. It never mutates the original plan or its
step status.

Gate order is fixed:

1. `dry_run == false`;
2. `config/data_acquisition_execution.yaml` has `enabled: true`;
3. the system-controlled `live_authorized` invocation argument is true;
4. plan Schema valid;
5. task/scenario/as_of match the authoritative invocation context;
6. action belongs to the exact allowlist;
7. requirement exists in the same Scenario Requirement Registry;
8. data type matches that requirement;
9. capability exists and equals `BUSINESS_SUFFICIENT`;
10. existing Router may be called.

Failure at any gate produces `NOT_EXECUTABLE` before network or DB mutation.

The checked-in `config/data_acquisition_execution.yaml` is strict and starts as:

```yaml
enabled: false
allowed_actions:
  - route_existing_sources
production_collector_ids: []
```

Unknown configuration fields or actions are a control-plane configuration error. Tests construct
an in-memory enabled policy and Fake Collector registry; they do not rewrite production config.

### 5.3 Backward-compatible Router evolution

The existing Router remains the sole routing authority. It receives one internal implementation
that returns both the `DataRoute` audit and normalized items. Public behavior is:

- existing `Router.resolve(...) -> DataRoute` remains unchanged;
- new `Router.resolve_with_items(...) -> RoutedDataBatch` exposes the same route decision plus
  normalized items;
- both methods call the same internal routing algorithm;
- source ordering, primary/secondary/fallback semantics, missing-field checks, empty-result
  warning, and DataRoute Schema validation remain identical.

`RoutedDataBatch` is an internal typed value, not a second Router and not a new persisted authority.

### 5.4 `CollectorFetcherBridge`

The bridge adapts an injected `source_id -> CollectorAdapter` registry to the Router fetcher
protocol. For one source attempt it performs:

```text
discover(query, time_window)
→ fetch(each ItemRef)
→ normalize(each RawPayload)
→ RawItem Schema validation
→ normalized items + fields_present
```

The bridge preserves the adapter's source ID, rate-limit policy, failure reason, and normalization
version boundary. It does not contain platform-specific selectors or credentials. The production
registry remains empty for the foundation milestone; tests inject Fake Collectors.

### 5.5 `AcquisitionWriteRepository`

Network work happens before opening the write transaction. The repository validates the complete
batch, assigns stable RawItem identities, resolves replays, then atomically persists the DataRoute
and all new RawItems in one SQLite transaction.

It uses a dedicated batch method rather than `Database.upsert()` because the current generic
method commits individual DataRoute and RawItem writes. No migration is needed because DB v6
already contains `data_routes` and `raw_items`.

## 6. Contracts

### 6.1 Immutable input

`AcquisitionPlan` remains the immutable P7-D1 plan. Execution must not add `source_id`,
`selected_source`, or provider fields to plan steps. Source disclosure belongs only in the
post-routing `DataRoute` inside the execution result.

### 6.2 New `AcquisitionExecutionResult`

One new strict JSON Schema and Pydantic model are introduced, increasing the Schema registry from
85 to 86. The object contains:

- `execution_id`: deterministic UUID5 over task ID and canonical plan hash;
- `task_id`, `scenario`, `as_of`, `plan_sha256`;
- `started_at`, `finished_at`;
- overall `status`;
- ordered step results in original plan order;
- `readiness_before_requirement_ids` and `readiness_after_requirement_ids`, each in central
  Requirement Registry order;
- warnings and normalized error records.

Each step result contains:

- original `step_id`, `requirement_id`, `data_type`, and action;
- status and reason code;
- optional `DataRoute`;
- inserted and reused RawItem IDs/counts;
- rejected future-item count;
- warnings and sanitized error detail.

Overall statuses are exactly:

```text
not_executable | completed | partial_success | failed
```

Step statuses are exactly:

```text
not_executable | skipped | completed | partial_success | failed
```

### 6.3 Stable RawItem identity

Before persistence the writer replaces adapter-generated random IDs with UUID5 identities:

```text
external_id present:
  source_id + external_id + content_hash

external_id absent:
  source_id + canonical_http_url + content_hash
```

Canonical URL normalization is deterministic and limited to scheme/host case normalization,
default-port removal, fragment removal, and stable query ordering. It must not discard arbitrary
query parameters.

An identical identity reuses the first persisted RawItem and does not overwrite its original
`retrieved_at`. The same external ID with a different content hash becomes a distinct content
version. A UUID collision with incompatible source/content identity fails closed.

## 7. Time and point-in-time rules

- The Router time window is derived deterministically from the requirement context and ends at the
  authoritative task `as_of`.
- Date-time parsing uses the existing timezone-aware utilities; lexical comparison is prohibited.
- A normalized item with `published_at > as_of` is rejected as `FUTURE_ITEM_REJECTED` before
  persistence.
- Empty or malformed publication time cannot prove eligibility and is rejected.
- `retrieved_at` records actual retrieval time and may be later than `as_of`; it never substitutes
  for publication/effective-time authority.
- Historical acquisition is not PIT-safe merely because an endpoint returns an old document.
  A real source may be promoted only after it proves the required historical/version semantics.
- Readiness recheck reuses the same `task_as_of`, Requirement Binding, canonical projector,
  provenance, coverage, freshness, and source-tier authorities used before execution.

## 8. Atomicity and replay behavior

For each executable step:

1. route and collect outside a DB transaction;
2. validate every normalized RawItem and the DataRoute;
3. calculate stable identities and split the batch into inserted/reused sets;
4. begin one SQLite transaction;
5. insert the DataRoute audit and all new RawItems;
6. commit, or roll back the whole step on any persistence failure;
7. run readiness recheck only after commit.

Re-running the same task and content may append a new DataRoute attempt audit but must not increase
RawItem count. Step results report inserted and reused counts honestly.

## 9. Error semantics

Normalized reason codes include:

```text
EXECUTION_DISABLED
LIVE_GATE_DISABLED
DRY_RUN_PROHIBITS_EXECUTION
PLAN_CONTEXT_MISMATCH
ACTION_NOT_ALLOWED
REQUIREMENT_NOT_FOUND
DATA_TYPE_MISMATCH
CAPABILITY_NOT_BUSINESS_SUFFICIENT
ROUTE_UNAVAILABLE
FETCH_FAILED
NORMALIZATION_FAILED
RAW_ITEM_SCHEMA_INVALID
FUTURE_ITEM_REJECTED
EMPTY_RESULT
PERSIST_FAILED
RECHECK_FAILED
CONTROL_PLANE_CONFIGURATION_ERROR
```

Rules:

- `NOT_EXECUTABLE` means a pre-network gate was not satisfied.
- No route or an ineligible route is `ROUTE_UNAVAILABLE`.
- Empty response is `EMPTY_RESULT`; it never means no event, no change, or no attention.
- An empty response persists only its DataRoute audit, writes zero RawItems, produces a
  `partial_success` step with `EMPTY_RESULT`, and leaves readiness MISSING/STALE.
- Any invalid item prevents the whole step from being persisted.
- Persistence failure rolls back the step and records `PERSIST_FAILED`.
- If persistence commits but recheck encounters a control-plane failure, the execution is
  `partial_success`; persisted facts remain recorded and readiness is not invented.
- Error detail is sanitized and must not include credentials, cookies, request headers, full
  payloads, or full page content.

Ordinary acquisition failure does not overwrite Runner status, exit code, or missing-data fields.
Only an invalid control-plane contract/configuration fails the coordinator before Runner execution.

## 10. Orchestrator integration and artifacts

The production order is:

```text
existing request validation
→ P7-D1 preflight before
→ P7-D2 coordinator
→ optional execution
→ readiness recheck after committed writes
→ existing Runner.execute
```

The live acquisition gate is system-controlled, separate from the Research Live gate and Chat LLM
gate. P7-D2 Foundation does not expose a CLI or dashboard switch: the production factory always
passes `live_authorized=false`. Tests inject `live_authorized=true`; a later real-source milestone
must separately authorize any public runtime surface. The gate never enters business request
Schemas or persisted user-semantic request fields.

Non-dry-run run directories add:

```text
acquisition_execution.json
data_readiness_after.jsonl
```

Existing artifacts remain unchanged:

```text
data_readiness_before.jsonl
data_gaps.jsonl
acquisition_plan.json
```

Dry-run remains zero network, zero DB write, and zero artifact write.

## 11. Test strategy

### 11.1 Contract tests

- normal, boundary, and failure cases for `AcquisitionExecutionResult`;
- unknown fields/statuses rejected;
- model dump passes the new Schema;
- plan continues to reject source/provider leakage;
- Schema registry count is exactly 86.

### 11.2 Unit tests

- every execution gate and its zero-network/zero-write proof;
- old `Router.resolve()` compatibility and new method decision parity;
- Collector bridge discover/fetch/normalize sequencing and error propagation;
- exact action allowlist;
- stable identity, replay reuse, content-version separation, and collision rejection;
- future/malformed item rejection;
- full-batch validation before transaction;
- atomic insert and rollback;
- error sanitization;
- no LLM/provider call.

### 11.3 Integration tests with fakes

- `MISSING → fake route/fetch/normalize/persist → READY`;
- stale input → new content version → freshness becomes READY;
- primary failure and secondary success preserve attempted/selected/fallback audit;
- empty result keeps readiness MISSING/STALE;
- replay keeps RawItem count stable and increments reused count;
- one invalid item rolls back the whole step;
- committed persistence plus recheck failure returns `partial_success` without inventing readiness;
- Coordinator disabled path matches P7-D1 Runner behavior;
- all ten existing Runners retain status/exit/missing-data semantics.

### 11.4 Repository gates

```text
python -m pytest
python -m research_os.cli.main validate      # 86/86
python -m compileall -q src tests
git diff --check
Offline CI SUCCESS
```

All default tests remain offline. No real source acceptance is part of P7-D2 Foundation.

## 12. Acceptance boundary

P7-D2 Foundation may be accepted only if:

- the full fake execution path and all failure attacks pass;
- old Router and all ten Runners remain backward compatible;
- production config is disabled by default;
- no real capability is `BUSINESS_SUFFICIENT`;
- no real Collector is invoked in ordinary or CI runs;
- DB remains v6 with six migrations;
- Schema registry is 86;
- LLM/provider calls are zero;
- Graph writes are zero;
- source registry and Collector inventory are unchanged;
- docs state that P7 data acquisition is foundation-only, not operational coverage.

Completion permits independent acceptance of the foundation only. It does not authorize a real
source vertical slice. Each real source/data-type pairing requires a separate taskbook or explicit
scope, verified source governance, live acceptance, and capability promotion approval.

## 13. Implementation authorization gate

This approved design is not implementation authority. Before code changes, the repository must
contain an approved P7-D2 taskbook and detailed implementation plan, followed by explicit user
authorization for P7-D2 implementation.
