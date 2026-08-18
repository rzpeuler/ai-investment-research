# P7-D2 Acquisition Execution Foundation — Implementation Plan

> Taskbook: `docs/tasks/phase7-data-layer-d2.md`
> Design: `docs/superpowers/specs/2026-08-16-p7-d2-acquisition-execution-foundation-design.md`
> Current status: planning complete / implementation not authorized
> Method: one milestone at a time, test-first, one Git commit per milestone

## Precondition

Do not execute this plan until the user explicitly authorizes
`P7-D2 FOUNDATION IMPLEMENTATION`. Authorization covers only Fake-proven infrastructure; it does
not authorize a real source or capability promotion.

Before every milestone:

```text
git status --short
git diff --check
```

After every milestone, run its targeted tests and commit only that milestone.

## Milestone 0 — Governance and frozen contracts

### Files

Create:

```text
config/data_acquisition_execution.yaml
schemas/acquisition_execution_result.schema.json
tests/contracts/test_data_acquisition_execution_contract.py
tests/unit/test_data_acquisition_execution_policy.py
src/research_os/data_layer/execution_policy.py
```

Modify:

```text
src/research_os/models/data_acquisition.py
src/research_os/models/__init__.py
src/research_os/validators/schema_validator.py
docs/engineering-guide.md
docs/project-state/DECISIONS.md
docs/tasks/phase7-data-layer-d2.md
tests/unit/test_document_governance.py
```

### Test-first sequence

1. Add failing contract tests for strict ExecutionResult model/Schema, exact enums, UUID/time
   validation, nested step results, DataRoute, errors, and additionalProperties=false.
2. Add failing policy tests for strict YAML, default disabled, exact allowlist, empty production
   collectors, unknown-field rejection, and zero I/O policy loading.
3. Add the Schema/model and register it in `SCHEMA_NAMES` / `validate_model`.
4. Implement `ExecutionPolicyRegistry`; no network and no runtime mutation.
5. Record Decision #49 and engineering-guide V1.7 using the approved design verbatim in substance.

### Verify

```text
python -m pytest tests/contracts/test_data_acquisition_execution_contract.py -q
python -m pytest tests/unit/test_data_acquisition_execution_policy.py -q
python -m pytest tests/unit/test_document_governance.py -q
python -m research_os.cli.main validate
git diff --check
```

Expected: targeted tests pass; 86/86 schemas; DB v6; migrations remain six.

### Commit

```text
feat: freeze P7-D2 execution contracts
```

## Milestone 1 — Existing Router batch return and Fake Collector bridge

### Files

Create:

```text
src/research_os/data_layer/collector_bridge.py
tests/unit/test_data_acquisition_router.py
```

Modify:

```text
src/research_os/routing/router.py
src/research_os/data_layer/__init__.py
```

### Test-first sequence

1. Freeze existing `Router.resolve()` outputs for success, primary failure/secondary success,
   fallback, missing fields, empty items, missing fetcher, and all-source failure.
2. Add failing parity tests requiring `resolve_with_items()` to return the exact same DataRoute as
   `resolve()` under equivalent injected fetchers.
3. Add Fake Collector tests for discover → fetch → normalize order, source identity, field union,
   multiple ItemRefs, partial fetch failure, invalid RawItem, and sanitized errors.
4. Refactor Router to one private algorithm returning `RoutedDataBatch`; keep `resolve()` as a
   compatibility projection.
5. Implement the bridge with injected adapters only. Do not import or register real adapters.

### Verify

```text
python -m pytest tests/unit/test_sources.py tests/unit/test_collector_interface.py -q
python -m pytest tests/unit/test_data_acquisition_router.py -q
python -m pytest tests/integration/test_data_layer_preflight.py -q
git diff --check
```

### Commit

```text
feat: expose routed data batches through existing router
```

## Milestone 2 — Fail-closed execution service

### Files

Create:

```text
src/research_os/data_layer/execution.py
tests/unit/test_data_acquisition_execution.py
```

Modify:

```text
src/research_os/data_layer/__init__.py
```

### Test-first sequence

1. Parameterize every gate: dry-run, config disabled, live gate disabled, invalid plan, task /
   scenario / as_of mismatch, Schema-invalid action, unknown requirement, data-type mismatch, capability
   missing, and capability below BUSINESS_SUFFICIENT.
2. For every rejected gate, monkeypatch Router/Collector/repository to raise if called; assert zero
   calls and `not_executable` audit.
3. Test plan immutability and stable execution UUID5/plan SHA256.
4. Test non-executable Plan actions are `skipped`, not silently dropped.
5. Test exact status/reason aggregation and error sanitization.
6. Implement `AcquisitionExecutionService` only after the failures demonstrate every gate.

### Verify

```text
python -m pytest tests/unit/test_data_acquisition_execution.py -q
python -m pytest tests/unit/test_data_layer_control_plane.py -q
python -m pytest tests/unit/test_data_layer_r3_runtime.py -q
python -m pytest tests/unit/test_data_layer_r3_1_final_runtime.py -q
git diff --check
```

### Commit

```text
feat: add fail-closed acquisition execution service
```

## Milestone 3 — Atomic idempotent persistence

### Files

Create:

```text
src/research_os/data_layer/acquisition_repository.py
tests/unit/test_data_acquisition_repository.py
```

`src/research_os/storage/db.py` remains unchanged. The repository uses the existing
`Database.transaction()` context, which yields the parameterized SQLite connection needed for the
single batch transaction.

### Test-first sequence

1. Test deterministic RawItem UUID5 for external-ID and URL fallback identities.
2. Test URL canonicalization exact allowed operations and preservation of query parameters.
3. Test replay reuse, first retrieved_at retention, changed-content new version, and collision
   fail-closed.
4. Test complete batch validation occurs before transaction/write.
5. Inject a failure on the second RawItem and prove both RawItems and DataRoute roll back.
6. Test empty batch persists only the DataRoute audit.
7. Implement direct parameterized SQLite statements inside one repository-owned transaction;
   never call per-object committing `Database.upsert()` inside the batch.

### Verify

```text
python -m pytest tests/unit/test_data_acquisition_repository.py -q
python -m pytest tests/unit/test_db.py tests/unit/test_sources.py -q
python -m pytest tests/integration/test_orchestrator_flow.py -q
git diff --check
```

### Commit

```text
feat: persist acquisition batches atomically
```

## Milestone 4 — Coordinator, recheck, and Orchestrator artifacts

### Files

Create:

```text
src/research_os/data_layer/coordinator.py
tests/integration/test_data_acquisition_foundation.py
```

Modify:

```text
src/research_os/data_layer/preflight.py
src/research_os/data_layer/__init__.py
src/research_os/orchestrator/orchestrator.py
tests/integration/test_data_layer_preflight.py
```

### Test-first sequence

1. Prove exact call order: preflight before → coordinator → optional execution → recheck → Runner.
2. Prove production default policy causes zero Router/Collector/network/business writes and leaves
   Runner status/exit/missing_data unchanged.
3. With in-memory enabled policy + BUSINESS_SUFFICIENT fake capability + Fake Collector, prove
   `MISSING → persist → READY`.
4. Prove STALE refresh, primary failure/secondary success, empty result, replay, atomic rollback,
   and committed-write/recheck-failure partial_success.
5. Recheck by calling the same `DataPreflightService` authority with the same task_as_of; do not
   implement a simplified checker path.
6. Persist `acquisition_execution.json` and `data_readiness_after.jsonl` atomically only for
   non-dry-run runs. Keep existing three P7-D1 artifacts unchanged.
7. Prove dry-run remains zero file/DB/network side effects.

### Verify

```text
python -m pytest tests/integration/test_data_acquisition_foundation.py -q
python -m pytest tests/integration/test_data_layer_preflight.py -q
python -m pytest tests/integration/test_orchestrator_flow.py -q
python -m pytest tests/integration/test_phase6_s5_central_enablement.py -q
git diff --check
```

### Commit

```text
feat: coordinate acquisition before scenario execution
```

## Milestone 5 — Attack matrix and ten-Runner regression

### Files

Modify tests only:

```text
tests/unit/test_data_acquisition_execution.py
tests/unit/test_data_acquisition_repository.py
tests/integration/test_data_acquisition_foundation.py
tests/integration/test_data_layer_preflight.py
```

### Required attacks

- source/provider leakage in Plan;
- task/scenario/as_of tampering;
- lexical datetime and cross-offset future item;
- malformed publication/retrieval timestamps;
- adapter source ID mismatch;
- duplicate ItemRefs and duplicate normalized items;
- stable-ID collision;
- one invalid item among valid items;
- transaction failure after DataRoute insert;
- empty source response;
- all sources fail vs missing fetcher distinction;
- error containing authorization header/cookie/token;
- recheck configuration failure after commit;
- fake capability accidentally entering production registry;
- real Collector import/call in default and CI paths;
- LLM/provider invocation;
- Graph write;
- Runner result mutation.

### Verify

```text
python -m pytest tests/unit/test_data_acquisition_execution_policy.py tests/unit/test_data_acquisition_router.py tests/unit/test_data_acquisition_repository.py tests/unit/test_data_acquisition_execution.py -q
python -m pytest tests/integration/test_data_acquisition_foundation.py -q
python -m pytest tests/integration/test_data_layer_preflight.py -q
python -m pytest tests/integration/test_phase6_s5_central_enablement.py -q
git diff --check
```

### Commit

```text
test: harden P7-D2 execution boundaries
```

## Milestone 6 — Full validation and governance handoff

### Files

Update only living governance surfaces and taskbook status to report actual results:

```text
docs/project-state/CURRENT_STATE.md
docs/project-state/NEXT_PHASE.md
docs/project-state/KNOWN_LIMITATIONS.md
README.md
docs/tasks/phase7-data-layer-d2.md
tests/unit/test_document_governance.py
```

Do not declare PASS. Record exact implementation head, tests, schemas, DB/migration count, zero
real sources, zero promoted capabilities, zero production collectors, zero LLM, and zero Graph
writes.

### Full verification

```text
python -m pytest --collect-only -q
python -m pytest
python -m research_os.cli.main validate
python -m compileall -q src tests
git diff --check
```

Also mechanically verify:

```text
schemas = 86
migrations = 6
production_collector_ids = []
BUSINESS_SUFFICIENT capabilities = 0
registry/sources.yaml unchanged
src/research_os/collectors/** unchanged
Graph write = 0
production LLM calls = 0
```

### Commit

```text
docs: hand off P7-D2 foundation for acceptance
```

### Terminal report

```text
P7-D2 FOUNDATION: IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE
REAL DATA ACQUISITION COVERAGE: NONE
```

Keep the PR open and unmerged until independent acceptance and explicit merge authorization.
