# P8-A4 Expanded Exploration Pilot Design

## Scope

P8-A4 expands the existing P8-A3-R1 governed Harness pilot to a 25-case
corpus: 20 exploration cases and 5 Legacy negative controls. The work remains
an evaluation pilot. It does not adopt Harness as the default runtime, replace
Legacy, or allow Harness output to become a formal research artifact.

Real Harness/provider execution is the source of reliability, value, and cost
claims. Offline execution is test-only and must never fill missing real-run
results.

## Architecture and data flow

The existing governed path remains unchanged:

```text
Pilot case
  -> Runtime Router
  -> Permission Policy
  -> Exploration Contract
  -> Real Harness + Research OS MCP
  -> bounded exploration output
  -> Pilot Audit Lineage
```

The corpus contains four cases for each exploration class:

- industry exploration;
- research preparation;
- evidence discovery assistance;
- analyst assistant;
- hypothesis generation.

Five negative controls remain Legacy-only and cover strict-schema or authority
boundaries, including FinancialFact, ResearchFinding, FinalReport, Graph write,
and transaction-oriented output. Each Harness case must have a contract in
`config/exploration_policy.yaml`; missing contracts fail closed.

Harness output is bounded exploration assistance only. It cannot write
FinancialFact, ResearchFinding, FinalReport, or active Graph authority. Formal
artifacts still require the Legacy workflow and existing validators.

## Evaluation and failure handling

The pilot adds a structured human-evaluation template with one pending record
per executed exploration case. Sol may score research usefulness, exploration
quality, actionability, and noise rate on documented scales; the system does
not prefill those scores.

Automated metrics are defined as follows:

- `session_success_rate = completed_sessions / attempted_sessions`;
- `timeout_count` counts typed timeout failures only;
- `continuity_rate` measures same-case session continuity;
- `cleanup_status` preserves root/tree/residue status;
- audit completeness requires a complete lineage record per executed case;
- unauthorized tool, authority drift, secret leak, validator bypass, and
  strict-schema-entered-Harness are zero-tolerance governance failures;
- provider calls, tool calls, latency, and token usage are recorded per case,
  with aggregate mean/median cost baselines.

Provider or Harness unavailability produces an explicit `DATA_DEGRADED` or
`insufficient_evidence` result. Typed failures are preserved, with no automatic
retry and no offline substitution. Forbidden Artifact or transaction-oriented
output is detected and marked failed; it is never admitted to the research
artifact chain.

## Testing and acceptance

Tests cover corpus size and category coverage, unique IDs, complete contracts,
contract tool subsets, fail-closed missing-contract behavior, permission
enforcement, audit completeness, forbidden-artifact detection, human-evaluation
record validation, and offline full-corpus execution.

Validation runs in this order:

1. `python -m pytest`;
2. schema validation, retaining `86/86 PASS`;
3. compile/import checks;
4. offline expanded-corpus execution;
5. opt-in real Harness expanded-corpus execution.

The report records whether the real run was complete or degraded. Acceptance
may be `PASS / READY_FOR_P8_A5_REVIEW`, `PARTIAL / VALUE_INCONCLUSIVE`,
`PARTIAL / DATA_DEGRADED`, or `NOT_READY`; no automatic production-adoption
decision is made.

## Documentation outputs

The implementation updates:

- `docs/architecture/p8-a4-expanded-pilot-report.md`;
- `docs/project-state/CURRENT_STATE.md`;
- `docs/project-state/NEXT_PHASE.md`;
- `docs/project-state/KNOWN_LIMITATIONS.md`;
- `docs/project-state/DECISIONS.md`.

No LlmClient, Provider Factory, Schema, Validator, Financial Authority,
Evidence Authority, Graph Write Authority, or default Runtime changes are in
scope.
