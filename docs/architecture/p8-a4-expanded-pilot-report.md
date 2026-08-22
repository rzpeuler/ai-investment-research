# P8-A4 Expanded Exploration Pilot Report

Task: `P8-A4-HYBRID-AGENT-RUNTIME-EXPANDED-PILOT`
Date: 2026-08-22
Status: `PARTIAL / DATA_DEGRADED`

## 1. Expanded corpus

The corpus contains 25 cases:

| group | count | scope |
|---|---:|---|
| Industry exploration | 4 | competition landscape, upstream/downstream relationships, risk-factor exploration, general industry exploration |
| Research preparation | 4 | first coverage, earnings preparation, data-gap analysis, general preparation |
| Evidence discovery assistance | 4 | verification questions, evidence requirements, source conflicts, general evidence discovery |
| Analyst assistant | 4 | research framework, comparison dimensions, peer-comparison axes, general analyst assistance |
| Hypothesis generation | 4 | investment, risk, catalyst, and general hypothesis exploration |
| Legacy negative controls | 5 | FinancialFact, ResearchFinding, FinalReport, graph write, transaction-oriented output |

No case asks Harness to generate a formal ResearchFinding, FinancialFact, FinalReport,
or active graph change. The 20 exploration cases have 20 corresponding contracts;
the 5 controls intentionally have no exploration contract and remain Legacy-only.

## 2. Exploration contracts

`config/exploration_policy.yaml` contains 20 contracts. Every contract includes
`objective`, `allowed_tools`, `max_turns`, `max_tool_calls`,
`completion_rule`, `empty_data_policy`, `turn_timeout_seconds`, and
`failure_condition`. Contract tool sets are subsets of the Harness permission
allowlist. Missing contracts fail closed.

## 3. Harness execution result

### Offline governance execution

- 20/20 exploration cases completed through the offline bounded adapter;
- 5/5 negative controls routed to Legacy-only;
- corpus size: 25;
- no offline result is used as evidence of real provider reliability or value.

### Provider-backed execution

The opt-in runner `scripts/p8_a4_expanded_pilot.py` was invoked. The current
environment has no `DEEPSEEK_API_KEY`, so no provider-backed session was
attempted. The runner wrote an explicit `DATA_DEGRADED / PROVIDER_AUTH_MISSING`
result and did not substitute the offline run.

The bounded report is written to the gitignored path
`reports/p8_a4_expanded_pilot.json`. The human-review template is written to
`reports/p8_a4_human_evaluation.json`.

## 4. Reliability

| metric | result | interpretation |
|---|---:|---|
| session_success_rate | `NOT_AVAILABLE` | no provider-backed session attempted |
| timeout_count | `0 observed` | no provider-backed session attempted |
| continuity_rate | `NOT_AVAILABLE` | no provider-backed session attempted |
| cleanup_status | `NOT_AVAILABLE` | no Harness process started |

The offline adapter completed all 20 cases, but this is a deterministic
governance regression only and does not satisfy the real-run reliability gate
of `session_success_rate >= 0.95`.

## 5. Governance

| metric | result |
|---|---:|
| audit completeness | 100% (25/25 routing records) |
| unauthorized tool | 0 |
| authority drift | 0 |
| secret leak | 0 |
| validator bypass | 0 |
| strict-schema entered Harness | 0 |

The negative controls remained `LEGACY_ONLY`; no Harness output was admitted to
FinancialFact, ResearchFinding, FinalReport, or Graph authority.

## 6. Value evaluation

The human evaluation interface is implemented but remains `PENDING_REVIEW`.
It exposes per-case fields for research usefulness, exploration quality,
actionability, noise rate, reviewer, review time, and notes. No score was
invented because no provider-backed output was available.

Automated value proxies are therefore `NOT_AVAILABLE`. The pilot cannot yet
claim reduced research preparation cost or analyst usefulness.

## 7. Cost

| metric | result |
|---|---:|
| provider calls | 0 |
| tool calls | 0 provider-backed |
| latency | `NOT_AVAILABLE` |
| token usage | `NOT_AVAILABLE` |

No cost baseline is inferred from offline execution.

## 8. Acceptance and P8-A5 recommendation

P8-A4 is implemented and governance-validated, but the evaluation result is
`PARTIAL / DATA_DEGRADED`. P8-A5 is **not recommended yet**. A provider-backed
expanded run and Sol's completed human evaluation are required before deciding
whether the pilot has demonstrated stable reliability, research usefulness,
actionability, acceptable noise, and a meaningful cost baseline.

Harness remains opt-in; Legacy remains the default runtime; production adoption
and structured artifact replacement remain unauthorized.
