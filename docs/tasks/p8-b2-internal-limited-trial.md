# P8-B2 DeepSeek Harness Internal Limited Trial

STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

This is the authoritative task-level entry for the internal-only P8-B2 trial.
P8-B1 is closed and independently accepted at merge commit
`e64249e9eb99a395ebaa63308d0d72ad1d3a7a74`. The P8-B2 implementation is based
on that new `master` and remains non-production.

## Invariants

- `P8_B2_INTERNAL_TRIAL=1` is required; the default is disabled.
- Client requests cannot select Harness or enable this trial.
- Default production runtime remains `legacy`.
- Provider network is enabled only by the explicit trial runner; Research data
  network remains off.
- The catalog is exactly `get_company_profile` and `check_data_readiness`.
- No frontend, public API, Scenario Tool, collector, source registry, graph
  write, schema, database, migration, Data Layer, Financial, or Orchestrator
  change is part of B2.

## Required evidence

The bounded corpus targets ten independent Harness sessions and twenty
provider-backed turns across at least `600519.SH` and `300750.SZ`. Each session
has identity/profile plus readiness on turn one and a fresh readiness call on
turn two. Evidence includes session opacity, authority references, cross-session
isolation, typed provider failures, latency, token/cost availability, budgets,
rollback latch, owned-process crash/restart, secret scan, and process hygiene.

The execution result is only `PASS CANDIDATE`, `PARTIAL`, or `FAIL`; independent
acceptance is required. Production adoption and P8-B3 remain
`NOT_AUTHORIZED`.
