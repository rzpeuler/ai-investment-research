# P8-B1-R1 Security Review

**STATUS:** PASS

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
| arbitrary subprocess | no agent-facing Tool; process service is supervisor-owned |
| source Tools | absent from actual MCP discovery |
| SQL Tools | absent from actual MCP discovery |
| Graph mutation Tools | absent from actual MCP discovery |
| cross-session target access | gateway mapping is opaque and session-scoped |
| process cleanup | owned root tree only; unrelated processes untouched |

## Boundary conclusion

Research OS remains the authority for identity and readiness. The Harness
client does not read the Research OS database, choose sources, execute
collectors, or mutate Graph state. The default runtime remains legacy and
production adoption remains unauthorized.
