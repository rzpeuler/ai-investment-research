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
