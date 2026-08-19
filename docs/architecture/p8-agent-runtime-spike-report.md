# P8-A0 Agent Runtime Spike Report

**Date:** 2026-08-19  
**Status:** PARTIAL — boundary validated, upstream runtime not installed  
**Decision:** Continue to P8-B only after independent acceptance and isolated
runtime installation review.

## Version and dependency record

- Upstream: `deepseek-ai/deepseek-harness`
- Official package: `@deepseek-ai/dsh`
- Pinned version: `0.1.0-rc.7`
- Immutable tag observed: `dsh-v0.1.0-rc.7`
- Node/npm environment: Node `v24.16.0`, npm `11.13.0`
- Python SDK: **not published/verified** for this upstream; the taskbook's
  Python SDK assumption is incompatible with the official distribution.
- Direct dependency tree: recorded from npm metadata in the acceptance work;
  the package depends on `@deepseek-ai/cordis@^4.0.1` and version-matched
  `@deepseek-ai/dsh-*` packages, plus CLI/runtime support packages.
- Installation policy: no automatic `latest`; SDK/runtime must be pinned and
  upgraded only with a compatibility test.

## Boundary

```text
User
  -> Harness session / agent loop (upstream runtime, future isolated process)
  -> Python control-plane boundary
  -> Research OS facade
  -> existing Research OS services and authority
```

The implemented facade exposes only:

- `get_company_profile`
- `check_data_readiness`
- `query_industry_graph`
- `run_research_scenario`

Collector calls, source selection, graph write/apply, and arbitrary network or
filesystem operations are denied. Tool results must be structured objects.

## Session and skills

`DurableSession` stores bounded conversation turns and object references only.
Credential-like values are rejected. It is not Research State or Knowledge
Memory. `SkillRegistry` discovers the three spike skills from `SKILL.md` files;
skills do not own data, routing, workflows, or graph writes.

## Compatibility and limitations

- Upstream remains a developer preview with compatibility-breaking changes.
- The official runtime is npm/Node-based, so a future integration needs an
  isolated Node runtime and a versioned process/JSON-RPC contract; it must not
  be silently embedded into the Python package.
- MCP server wiring is represented by the facade contract only; a production
  MCP server was not introduced in this spike.
- No live API key, direct network call, source collector, graph write, schema
  change, database migration, or frontend change was made.

## Verification

- `tests/unit/test_p8_a0_agent_runtime.py`: 5 passed
- `python scripts/p8_a0_probe.py`: Node/npm available; pinned runtime not
  installed without network
- `python -m compileall -q src scripts`: PASS
- Full regression remains required before independent acceptance.
