# P8-B1-R2 Security Review

**STATUS:** PASS / AWAITING INDEPENDENT ACCEPTANCE

## Observed runtime evidence

The review uses observed rc.7 composition and actual stdio MCP discovery, not
the JSON policy manifest alone.

- Installed binary: `@deepseek-ai/dsh@0.1.0-rc.7`
- Composed profile: `research-headless`
- MCP namespace: `research-os-mcp/v1`
- Advertised Tools: `get_company_profile`, `check_data_readiness`
- Research data network: OFF
- Provider credential: not present in session, Tool result, or acceptance output

## Denial checklist

| Capability | Observed result |
| --- | --- |
| bash / pwsh | unreachable; composition-disabled Tool entries |
| filesystem write/editor/search | unreachable; composition-disabled Tool entries |
| web / web search | Tool entries disabled; no direct source network |
| arbitrary subprocess | observed disabled Tool composition; no policy-only PASS |
| source Tools | absent from actual MCP discovery |
| SQL Tools | absent from actual MCP discovery |
| Graph mutation Tools | absent from actual MCP discovery |
| cross-session target access | gateway mapping is opaque and session-scoped |
| process cleanup | owned root tree only; unrelated processes untouched |

## Boundary conclusion

Internal Harness session IDs are retained only inside the adapter/client boundary
and are not present in send, resume, cancel, Gateway, event-log, or acceptance
outputs. Runtime evidence distinguishes observed, disabled, enabled, and verified
absent component IDs; incomplete or ambiguous evidence fails closed.

Research OS remains the authority for identity and readiness. The Harness
client does not read the Research OS database, choose sources, execute
collectors, or mutate Graph state. The default runtime remains legacy and
production adoption remains unauthorized.
