# P8-B2 DeepSeek Harness Internal Limited Trial

STATUS: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

P8-B1 is closed and independently accepted at the no-squash merge baseline
`e64249e9eb99a395ebaa63308d0d72ad1d3a7a74`. P8-B2 is an internal, explicit-opt-in
trial only. It is not production adoption.

## Guardrails

- The trial starts only when `P8_B2_INTERNAL_TRIAL=1` is explicitly set.
- The default runtime remains legacy; there is no public HTTP, frontend, daemon,
  or normal-user route to this trial.
- The provider network is enabled only by the trial process. Research data/source
  network access remains off.
- Only `get_company_profile` and `check_data_readiness` are admitted.
- The controller records bounded aggregate evidence and safe authority references;
  prompts, raw responses, credentials, and reasoning are not recorded.
- A tripped `TrialSafetyLatch` requires operator reset. Session, turn, tool-call,
  token, retry, and timeout budgets are finite.
- No graph write, schema, source registry, collector, frontend, ChatService,
  Orchestrator, or Data Layer changes are included.

## Acceptance scope

The trial corpus contains ten independent two-turn sessions across `600519.SH`
and `300750.SZ`. Turn one requires profile plus readiness evidence; turn two
requires a fresh readiness call in the same session. The runner also performs an
owned-process crash/restart drill and a latch rollback drill.

Execution agents may report `PASS CANDIDATE` or `PARTIAL`; only an independent
reviewer may accept the result. P8-B3 and production adoption remain
`NOT_AUTHORIZED`.
