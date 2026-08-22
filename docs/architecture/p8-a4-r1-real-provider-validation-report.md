# P8-A4-R1 Real Provider-backed Harness Validation Report

Task: `P8-A4-R1-REAL-PROVIDER-BACKED-HARNESS-VALIDATION`

Status: `PASS CANDIDATE / AWAITING INDEPENDENT ACCEPTANCE`

This report separates evidence sources. `REAL_RUN` is populated only by the
explicit provider-backed runner. `OFFLINE_TEST` contains deterministic test
and governance results. `DATA_UNAVAILABLE` is used when the provider
credential or provider-backed execution is unavailable. These categories are
never substituted for one another.

## Environment

- Harness: pinned existing runtime/profile from P8-A4
- Default runtime: `legacy`
- Provider network: only enabled for the explicit R1 runner
- Research/source network: unchanged and governed by existing policy
- Structured artifacts: remain Legacy + Validator owned
- P8-A5 / Production Adoption: `NOT_AUTHORIZED`

## Runner

```text
P8_A4_R1_REAL_PROVIDER_VALIDATION=1
python scripts/p8_a4_r1_real_provider_validation.py
```

The runner reuses `config/harness_pilot_corpus.yaml`, the Runtime Router,
Permission Policy, Exploration Contract, existing Harness adapter, MCP facade,
and Audit Lineage. It does not alter the production route or capability
catalog.

## Corpus

- 20 `HARNESS_ALLOWED` exploration cases
- 5 `LEGACY_ONLY` negative controls
- strict-schema controls never enter Harness

## REAL_RUN

Execution date: `2026-08-22` (Asia/Shanghai). The explicit opt-in run used the
existing provider credential and completed the expanded corpus:

- Run ID: `a3-eval-489d488fe0e5`
- Harness: `0.1.0-rc.7`, profile `research-headless`
- MCP namespace: `research-os-mcp/v1`
- 20/20 `HARNESS_ALLOWED` cases completed; failed cases: none
- 5/5 `LEGACY_ONLY` negative controls remained on Legacy
- Session success rate: `1.00`; continuity rate: `1.00`; timeout count: `0`
- Audit completeness: `1.00` (25/25 records)
- Unauthorized tool: `0`; authority drift: `0`; validator bypass: `0`;
  secret leak: `0`; strict-schema entered Harness: `0`; graph write attempted:
  `false`

Provider-reported cost and latency evidence:

- Provider calls: `24`
- Input/output/total tokens: `14,408,520 / 298,272 / 14,706,792`
- Cached tokens: `13,326,336`
- Latency: p50 `12,250 ms`, p95 `29,187 ms`, min `8,312 ms`, max `42,032 ms`

Cleanup evidence records the Harness root as terminated, but process-tree
verification is `NOT_VERIFIED`; this is retained as a limitation rather than
claimed as a clean process-tree result.

Value is `PENDING_REVIEW`. The run produced a human-review template only;
`automated_score=false`. The upstream deterministic safety signal recorded 9
forbidden-artifact markers, but this is not a usefulness score and is not
converted into an automatic human-value judgment.

## OFFLINE_TEST

The targeted R1 and expanded-pilot unit tests passed (`13 passed`),
`compileall` passed, and `git diff --check` passed. These checks validate the
runner and governance plumbing only; they are not substituted for REAL_RUN.

The missing-credential branch was also tested as typed `DATA_UNAVAILABLE`.

## DATA_UNAVAILABLE

No provider-unavailable condition occurred during the successful REAL_RUN.
The runner retains a fail-closed `PROVIDER_AUTH_MISSING` result when the
explicit existing credential is absent; it never fabricates provider metrics.

## Metrics

The generated bounded JSON artifact records reliability, provider calls,
accepted runtime token fields, latency, audit completeness, unauthorized tools,
authority drift, validator bypass, secret scan, and strict-schema boundary
results. Value remains a human-review template; no automated usefulness score is
generated.

## Acceptance

P8-A4-R1 must not be considered accepted unless the report contains a real
provider-backed result, complete corpus accounting, truthful cost/token
evidence, passing governance metrics, and the required offline validation
results. Missing credentials, provider failure, incomplete corpus execution, or
unverified full regression keep the result `PARTIAL` or `DATA_UNAVAILABLE`.
Because human review is pending and process-tree cleanup is not verified,
P8-A5 is **not recommended yet**; P8-A5 and production adoption remain
`NOT_AUTHORIZED`.
