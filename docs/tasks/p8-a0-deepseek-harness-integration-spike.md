# P8-A0 DeepSeek Harness Integration Spike

**STATUS:** IMPLEMENTATION AUTHORIZED — SPIKE ONLY  
**Authorization:** user authorization received 2026-08-19  
**Base:** P7-D4 accepted baseline  
**Branch:** `feature/p8-a0-harness-spike`

## Scope

This spike validates a research-only agent boundary. It does not replace
`ChatService`, `LlmClient`, `Orchestrator`, the data layer, source registry,
collectors, graph schema, frontend, or production runtime.

## Findings

1. The official upstream artifact is the npm package `@deepseek-ai/dsh`, not a
   Python SDK. The pinned candidate is `0.1.0-rc.7`, matching tag
   `dsh-v0.1.0-rc.7`.
2. Python therefore remains the Research OS control-plane adapter; the Harness
   process boundary is the `dsh` CLI. No fake Python package or API was added.
3. The spike implements durable conversation memory, skill discovery/loading,
   a fail-closed research profile, and a four-tool Research OS facade.
4. The actual npm runtime is not installed in the repository environment. The
   probe reports this as `installed_without_network: false`; no live Harness or
   external source call is claimed.

## Acceptance state

| Check | Result |
|---|---|
| Harness dependency version recorded | PASS |
| Python control-plane boundary starts | PASS |
| Durable session preserves bounded context | PASS |
| Skill discovery/loading | PASS |
| Structured Research OS facade | PASS |
| Source bypass / graph direct write | PASS — denied |
| Official `dsh` runtime installed and live-started | NOT VERIFIED |
| Research OS core authority changed | PASS — unchanged |
| Schema/database/production migration | PASS — none |

The spike is **PARTIAL / NOT READY FOR PRODUCTION ADOPTION** until the pinned
official runtime is installed in an isolated environment and its MCP/session
startup is independently accepted.
