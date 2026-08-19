# P8-B1-R3 Public Session Contract Design

## Scope

Close only the R3 public-boundary finding: `GatewaySession` currently contains
`harness_session_id` and is returned to callers. Runtime architecture, MCP
transport, Tool catalog, Research OS authority, profile evidence, production
traffic, frontend, schema, database, and P8-B2 remain unchanged.

## Design

Add a frozen `PublicGatewaySession` DTO with only `gateway_session_id`,
`runtime_mode`, `status`, and explicitly allowlisted metadata. Keep the existing
`GatewaySession` as an internal session record containing the Harness ID. Add one
`to_public_session()` projector as the only conversion path across the Gateway
boundary.

`AgentRuntimeGateway.create_session()` will retain the internal record in its
mapping and return the public DTO. `resume_session()` will return the same DTO
shape with a resumed status. Legacy and Harness adapters will continue to use
internal records internally, while all Gateway methods expose stable public
types. Send/cancel/close payloads remain sanitized and contain no Harness ID.

The live acceptance launcher will use only the public session's gateway ID for
Gateway calls. Continuity checks may inspect the adapter mapping in acceptance
code, but no internal value will be serialized or reported.

## Failure handling and verification

The projector is allowlist-based, so adding an internal field cannot leak it by
default. Tests will cover create/send/resume/cancel/close recursively using
`repr`, `json.dumps`, and `dataclasses.asdict`, plus type consistency between
Legacy and Harness. R2 fail-closed evidence, MCP event evidence, secret scan,
full pytest, Schema validation, compileall, and governance state remain gates.
