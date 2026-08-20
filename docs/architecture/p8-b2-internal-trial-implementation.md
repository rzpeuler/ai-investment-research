# P8-B2 Internal Trial Implementation

The implementation is isolated to the P8-B2 trial controller, runner, tests,
provider usage extraction, and the existing P8-B1 MCP boundary's handshake and
safe event evidence. The controller uses the already accepted production
Harness adapter and never changes Research OS authority.

The event log is process-local and temporary. It records tool name, typed status,
bounded target/authority references, and aggregate counters only. Failed provider
or MCP calls remain typed failures; they are not converted into successful tool
evidence. The controller fails closed when budgets, the safety latch, session
continuity, authority evidence, or process ownership checks fail.

The monetary cost field is deliberately reported as
`NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME` unless the accepted runtime supplies it.
No token or cost value is inferred from text.

## P8-B2-ENV-01 Environment Readiness (2026-08-20)

A minimal environment-readiness layer (`src/research_os/agent_runtime/
environment_readiness.py`, entry script `scripts/p8_b2_env_readiness.py`,
opt-in `P8_B2_ENV_READINESS=1`) mechanically verifies that the formal trial's
prerequisites hold before any acceptance corpus is authorized. It is not
another runtime, agent abstraction, MCP server, provider SDK, orchestration
framework or acceptance engine: it reuses `ProductionEvidenceProbe`,
`HarnessProcessFactory`, `HarnessRuntimeSupervisor` and the accepted owned
process-tree cleanup mechanism, and it shares the R2 evidence vocabulary.

Architecture boundary (unchanged):

```
Research OS
    ↓
existing P8-B2 trial controller
    ↓
approved Harness launcher (HarnessProcessFactory / supervisor)
    ↓
pinned DeepSeek Harness (@deepseek-ai/dsh 0.1.0-rc.7)
    ↓
approved provider connection (bounded probe only)
```

Ten readiness gates produce `READY` / `BLOCKED` / `FAIL` with per-gate evidence
basis; cleanup that cannot be mechanically proven is `FAIL_CLOSED`. The probe
holds no metrics recorder and no counters, cannot admit a session or turn, and
marks every provider call `ENVIRONMENT_READINESS_PROBE_ONLY` /
`FORMAL_ACCEPTANCE_TURN = NO`, so a readiness probe can never be mistaken for
or counted toward the formal corpus.

Deterministic Harness bootstrap for a fresh isolated worktree:
`cd agent_runtime && npm ci` from the committed `package-lock.json`
(`@deepseek-ai/dsh` exactly `0.1.0-rc.7`; `node_modules/` and `.dsh-home/`
remain outside Git). Verified on this host: fresh worktree → `npm ci` → 528
packages → `dsh --version` = `0.1.0-rc.7`.

See `docs/tasks/p8-b2-env-01-trial-environment-readiness.md` for the probe
design, the live gate results and the formal-trial separation evidence.
