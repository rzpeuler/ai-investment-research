# P8-A4-R1 Real Provider-backed Harness Validation Design

## Goal

Execute the existing P8-A4 expanded pilot corpus against the pinned Harness
runtime and the currently available DeepSeek provider credential, without
changing Hybrid Runtime policy or granting Harness access to structured
research assets. Produce evidence that distinguishes real execution from
offline tests and unavailable provider data.

## Scope and invariants

The implementation is isolated to the task branch, scripts, tests, evaluation
helpers, and documentation. It reuses the existing Runtime Router, Permission
Policy, Exploration Contract, Harness adapter, MCP namespace, and corpus.

`HARNESS_ALLOWED` cases may enter the path:

`Request -> Runtime Router -> Permission Policy -> Exploration Contract -> Harness -> MCP -> Audit`

Structured research artifacts remain Legacy-owned. Harness must not enter
FinancialFact, ResearchFinding, FinalReport, Validator, Graph Write Authority,
or any strict-schema production asset path. `LEGACY_ONLY` corpus cases are
negative controls and must never enter Harness.

## Runner design

Add a separate real-run entry point rather than extending the existing offline
pilot script. The runner will:

1. load `config/harness_pilot_corpus.yaml`;
2. classify cases by the existing router/policy decision;
3. run only `HARNESS_ALLOWED` cases through the real pinned Harness provider
   path, using the existing exploration controller and bounded contract;
4. execute `LEGACY_ONLY` cases through the legacy path as negative controls;
5. capture sanitized aggregate metrics and bounded case evidence;
6. emit a human-review template without automated usefulness scoring; and
7. write the final report with independent sections for `REAL_RUN`,
   `OFFLINE_TEST`, and `DATA_UNAVAILABLE`.

The provider key is read from the existing process environment only. It is
never written, logged, persisted, or included in the report. A missing or
rejected credential produces a typed `DATA_UNAVAILABLE` result and does not
pretend that a provider-backed run occurred.

## Metrics and evidence

The real-run summary will include:

- reliability: session success rate, continuity rate, timeout count, and failed cases;
- cost: provider call count, accepted runtime token usage fields, and latency;
- governance: audit completeness, unauthorized tools, authority drift, validator
  bypass, secret leaks, and strict-schema entry count;
- value: a human review template only, with no model-generated score.

Each case records only bounded identifiers, policy decision, runtime/profile
identity, typed outcome, latency, provider usage availability, audit references,
and failure classification. Full prompts, full responses, credentials, private
reasoning, and raw provider logs are excluded.

## Failure handling

Provider failures are classified separately from Harness startup failures and
offline test results. A bounded provider timeout, missing credential, or
insufficient corpus completion makes the real-run result `PARTIAL` or
`DATA_UNAVAILABLE`; it cannot become PASS through retries or inferred metrics.
Unknown exceptions are recorded as `UNCLASSIFIED_RUNTIME_FAILURE` and keep the
acceptance result non-passing.

Negative-control failures, unauthorized tools, authority drift, validator
bypass, strict-schema entry, or secret leakage are governance failures even if
the provider call itself succeeds.

## Validation

Add offline tests for corpus classification, credential gating, metric
aggregation, human-review-only output, no-secret evidence, and strict-schema
exclusion. Run the existing full pytest suite, 86/86 Schema validation,
compileall, and diff check. The report will explicitly record which checks are
`OFFLINE_TEST`, which are `REAL_RUN`, and which are `DATA_UNAVAILABLE`.

## Handoff

Update `CURRENT_STATE.md`, `NEXT_PHASE.md`, `KNOWN_LIMITATIONS.md`, and
`DECISIONS.md` with the P8-A4-R1 evidence. Do not authorize P8-A5, Production
Adoption, default Harness routing, or any new capability based solely on this
validation task.
