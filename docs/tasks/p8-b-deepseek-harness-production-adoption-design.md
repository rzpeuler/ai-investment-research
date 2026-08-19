# P8-B DeepSeek Harness Production Adoption Design

**TASKBOOK_STATUS:** DESIGN COMPLETE / AWAITING INDEPENDENT ACCEPTANCE  
**TYPE:** Governance and architecture design only  
**BASE:** `b048f65`  
**P8-B_DESIGN_HEAD:** `cdb8510`  
**P8-A0_ACCEPTED_HEAD:** `f16a3163814345e9aee2d00615a42dae57fd86fb`  
**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`  
**UPSTREAM:** Developer Preview  
**IMPLEMENTATION:** NOT AUTHORIZED  
**PRODUCTION_ADOPTION:** NOT AUTHORIZED  
**SCHEMA_CHANGE:** NONE  
**DB_MIGRATION:** NONE

## 1. Purpose and authorization

P8-A0 proved that the pinned Harness runtime can execute a bounded, provider-backed,
same-session research loop through a Research OS boundary. P8-B answers how that
capability could be adopted safely and progressively. It does not replace P7-UX1,
ChatService, LlmClient, Orchestrator, or any Research OS authority.

This document authorizes design review only. A later P8-B1 taskbook is required for
any production foundation implementation. Frontend implementation requires its own
taskbook.

## 2. Accepted baseline

| Item | Accepted value |
|---|---|
| Runtime | `@deepseek-ai/dsh@0.1.0-rc.7` |
| Provider-backed session | PASS |
| Research-only profile | PASS |
| Stock-research Skill | PASS |
| MCP stdio boundary | PASS |
| Same-session continuation | PASS |
| Authority re-read | PASS |
| New-session negative behavior | PASS |
| Full regression | 3698 passed / 6 skipped / 0 failed / 1 warning |
| Schema / DB / migrations | 86 / v6 / NONE |
| Current production/fallback | P7-UX1 |

## 3. Design principles

1. Research OS remains the deterministic authority for facts, evidence, PIT, sources,
   acquisition, workflows, graph state, and reports.
2. Harness owns conversation and agent execution concerns only.
3. The default runtime remains `legacy`; Harness is opt-in behind one server-side
   `agent_runtime_mode` flag.
4. Harness provider network and Research OS data network are separate gates.
5. Tools expose business capabilities, never collectors, SQL, source routing, or
   graph mutation.
6. Every production phase must be reversible to P7-UX1 without replaying a formal
   Research OS workflow twice.
7. The pinned preview version is never upgraded in place.

## 4. M0–M8 design deliverables

| Milestone | Design answer |
|---|---|
| M0 | P8-A0 independently accepted and merged no-squash into master |
| M1 | Persistent isolated Node Harness service behind a backend gateway |
| M2 | Harness conversation memory separated from Research OS state and knowledge memory |
| M3 | Versioned `research-os-mcp/v1` catalog with read-only capability contracts |
| M4 | Scenario/Capability Skill boundary; Skills do not reproduce workflows |
| M5 | Harness owns agent-facing LLM; existing `research_os.llm` owns formal workflow LLM |
| M6 | Fail-closed production profile, credential lifecycle, and process security |
| M7 | Health, lifecycle, observability, quotas, preview risk, and upgrade controls |
| M8 | Feature-flagged dual path, staged rollout, rollback, and frontend backend contract |

Detailed design is recorded in:

- [P8 Harness Production Adoption Architecture](../architecture/p8-harness-production-adoption-design.md)
- [P8 Agent Runtime Migration Plan](../architecture/p8-agent-runtime-migration-plan.md)
- [P8 Agent Runtime Operational Contract](../architecture/p8-agent-runtime-operational-contract.md)

## 5. Independent acceptance questions

1. **Where does production Harness run?** A separate isolated Node service/process,
   never embedded in the Python interpreter or copied into Research OS.
2. **Who owns Session?** Harness owns conversation/session lifecycle; Research OS
   owns formal Task/Plan/Run and audit state.
3. **Who owns Research State?** Research OS.
4. **Who owns facts/evidence/PIT?** Research OS and its governed SQLite/evidence/graph
   services.
5. **How does Frontend access Agent?** Only through a backend Agent Runtime Gateway
   contract; it does not call MCP, Harness internals, or SQLite directly.
6. **How does Harness call Research OS?** Versioned MCP capability tools through the
   gateway-managed isolated runtime.
7. **How are tools versioned?** `research-os-mcp/v1`, with per-tool schemas,
   authority, network/write policy, PIT semantics, errors, bounds, and references.
8. **How does Harness failure fall back?** Boot, provider, MCP, session, timeout, or
   version failures select P7-UX1 and return a single controlled path.
9. **How does provider failure fall back?** Provider failure is recorded separately;
   it never triggers an ungoverned Research OS acquisition or duplicate workflow.
10. **How do coding/bash/fs/network remain off?** Composition-level deny profile,
    capability allowlist, process sandbox, and startup security assertions.
11. **How is Harness upgraded?** New version requires a new isolated acceptance run;
    no floating ranges, `latest`, or in-place npm update.
12. **How is rollback done?** Flip the server-side flag to `legacy`, drain Harness
    sessions, preserve Research OS audit records, and do not replay completed runs.
13. **When can legacy go away?** Only after a separate acceptance proves parity,
    reliability, security, cost, and scenario coverage; this design does not grant
    that authorization.
14. **How is Developer Preview risk controlled?** Pinning, risk register, canary
    scope, compatibility probes, kill switch, and explicit upgrade acceptance.

## 6. Definition of done for this design

- [x] P8-A0 accepted baseline merged into master
- [x] Production topology and authority ownership defined
- [x] Versioned MCP boundary defined
- [x] Skill / Tool / Workflow boundary defined
- [x] Model ownership defined
- [x] Security and credential lifecycle defined
- [x] Runtime lifecycle and observability defined
- [x] Dual-path migration and rollback defined
- [x] Feature flag defaults to legacy
- [x] Developer Preview risk and upgrade policy defined
- [x] Resource and cost controls defined
- [x] Frontend/backend contract defined without frontend implementation
- [x] No production adoption, schema change, migration, or Harness upgrade performed
- [ ] Independent P8-B design acceptance

**Next:** independent acceptance of P8-B design. Only after that acceptance may a
separate P8-B1 Production Foundation taskbook be considered.
