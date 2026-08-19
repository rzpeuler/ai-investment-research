# P8-B2 Internal Limited Trial Design

## Scope and governance

P8-B2 is an internal, explicit opt-in, non-production trial of the accepted
P8-B1 Harness foundation. It does not change the default `legacy` route, public
HTTP or Frontend surfaces, production traffic, Scenario rollout, P7-UX1
retirement, MCP Tool catalog, Research OS authority, schema, database, or
migrations. The trial starts only after the P8-B1 M0 closeout and no-squash merge.

## Trial architecture

`scripts/p8_b2_internal_trial.py` is the only entrypoint and refuses to run
unless `P8_B2_INTERNAL_TRIAL=1`. It creates an isolated `TrialController` with
an explicit budget, `TrialSafetyLatch`, bounded metrics recorder, and a
`HarnessProcessFactory`-backed adapter. The controller owns all trial sessions
and is not reachable from Gateway public routes or Frontend code.

Each session receives an opaque public gateway ID. The controller may inspect
its own adapter mapping for continuity verification, but reports only hashes and
booleans. Provider network is enabled only for the explicit trial process;
Research data network remains disabled. The existing two MCP Tools are reused.

## Corpus and metrics

The bounded corpus contains at least ten independent sessions, at least twenty
provider-backed turns, and at least two locally authoritative entities including
`600519.SH`. Each session has two turns: identity/profile plus readiness, then a
fresh readiness call. Session A and B use different entities and are checked for
cross-session contamination.

Per-turn metrics include trial ID, hashed public session ID, turn index, runtime
and profile, Tool counts, provider status, typed failure, bounded durations, same
session result, authority drift result, and budget counters. Full prompts,
responses, raw Tool payloads, credentials, and private reasoning are excluded.

## Budgets, rollback, and failure handling

The controller enforces maximum sessions, turns, Tool calls, provider tokens,
retries, and per-turn timeout. At 80% it records a warning; at 100% it denies
new admission with `RESOURCE_BUDGET_EXCEEDED`. No autonomous sampling expansion
or unlimited retry is allowed.

`TrialSafetyLatch` transitions ENABLED → TRIPPED on security/runtime incidents.
Once tripped, new Harness admission is denied until an explicit operator reset.
Rollback stops new Harness admission and routes subsequent eligible requests to
legacy; it never replays Research Tool work. Crash/restart drills re-observe
version, profile, MCP handshake, and Tool discovery before admitting a new
session. Owned process trees must be zero at completion.

## Acceptance

Hard gates are zero authority drift, zero cross-session contamination, zero
unauthorized Tool calls, zero secret leaks, zero process residue, and zero
Research source network. Successful continuations must have 100% same-session
and fresh-readiness evidence. Provider failures may exist only as bounded,
typed, recoverable failures and must be reported. The final report is PASS
CANDIDATE or PARTIAL; the execution agent never self-assigns independent
acceptance.
