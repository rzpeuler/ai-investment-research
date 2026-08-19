# P8-B1-R2 Runtime Integrity Design

## Scope

Close only the three R2 findings on the existing `feature/p8-b1-production-foundation`
branch: internal Harness session opacity, fail-closed runtime composition evidence, and
mechanically observed live acceptance evidence. No new Tool, Skill, Scenario, frontend,
production traffic, schema, database, migration, or P8-B2 capability is included.

## Design

`OfficialHarnessClient` will expose an allowlisted public result containing status,
response, and bounded operational metadata. Harness raw payloads and internal session
identifiers remain private to the adapter/client boundary. Gateway responses will be
sanitized recursively as a defense in depth measure.

Runtime evidence will distinguish observed, disabled, enabled, and verified-absent
component IDs. A forbidden capability passes only when the observed runtime proves it is
disabled or a complete pinned-version inventory proves the component is absent. Missing,
ambiguous, or policy-only evidence fails closed. `arbitrary_subprocess` will never be
promoted from a policy expectation to observed evidence.

Live acceptance will derive same-session continuity from internal comparisons but emit
only a boolean. The MCP stdio server event log will be the source of live Tool evidence;
the startup probe will not count as a model Tool call. Turn 1 must observe both allowed
Tools, Turn 2 must observe a new `check_data_readiness` event, and the report will emit
only counts and PASS/FAIL fields. stdout, event log, and bounded operational output will
be scanned for credentials and sensitive fields.

The branch will explicitly return P8-B1 to `IMPLEMENTED / AWAITING INDEPENDENT
ACCEPTANCE`; execution must not self-assign independent acceptance.

## Failure handling

Any sanitizer ambiguity, incomplete component inventory, missing MCP event evidence,
session discontinuity, authority re-read failure, or secret-scan match returns a typed
failure and prevents a PASS acceptance result.

## Verification

Add unit tests for recursive opacity and each evidence state, integration tests for the
real profile, and live acceptance assertions for same-session continuity, Tool event
counts, authority re-read, and secret scanning. Run targeted tests, full `pytest`,
`compileall`, Schema validation, and `git diff --check`.
