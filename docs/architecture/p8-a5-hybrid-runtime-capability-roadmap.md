# P8-A5 Hybrid Agent Runtime Capability Roadmap

**Date:** 2026-08-23
**Status:** ROADMAP ONLY / NOT IMPLEMENTED / PRODUCTION NOT AUTHORIZED
**Scope:** Architecture planning after the P8-A0~P8-A4 evidence baseline

## 1. Purpose and evidence boundary

P8-A5 defines the next capability direction for the Hybrid Agent Runtime. It
does not change the Runtime Router, the Legacy default runtime, permission
policy, schemas, validators, or any Financial, Evidence, or Graph authority.
It does not authorize production adoption.

The roadmap is based on the following evidence:

- P8-A0 verified the Harness + MCP + Research OS tool boundary.
- P8-A2 implemented the governed router, permission surface, and audit
  lineage.
- P8-A3 bounded the exploration loop with turn, tool, completion, and empty
  data controls.
- P8-A4-R1 completed 20/20 provider-backed `HARNESS_ALLOWED` cases and kept
  5/5 `LEGACY_ONLY` controls outside Harness. The pinned Harness version was
  `0.1.0-rc.7`; session success and continuity were `1.00`, timeout count was
  `0`, and audit completeness was `25/25`.
- P8-A4-R4 retained raw outputs, events, tool traces, audit lineage, metrics,
  and file hashes for 20/20 cases in the evaluation artifact layer.
- P8-A4-R5 provides a reviewer-owned Excel interface, but the human value
  evaluation remains deferred and has no automatic score.

These results support one bounded conclusion: Harness is suitable as an
opt-in Exploration Agent Runtime. They do not establish that Harness produces
useful formal research artifacts, strict-schema objects, or production-ready
research conclusions.

## 2. Responsibility matrix

| Responsibility | Harness / Skills | Research OS / Legacy workflow |
|---|---|---|
| Conversation and session lifecycle | Owns conversation state, continuation, bounded stop/resume, and user-facing exploration context under the existing contract. | Owns durable research task state and workflow handoff. |
| Planning and exploration | Generates bounded plans, questions, hypotheses, and next-step candidates. | Supplies governed data, readiness status, evidence context, and deterministic execution results. |
| Tool orchestration | Selects only tools allowed by the task contract and permission policy; every call is auditable. | Exposes the MCP facade and enforces authority, validation, source lineage, and failure states. |
| Facts and structured data | May read and discuss returned data; must treat missing or degraded data explicitly. | Owns facts, entity mapping, dates, units, data readiness, and all structured data contracts. |
| Evidence | May inspect evidence availability and identify review questions. | Owns evidence acquisition, provenance, quality, independence, conflict handling, and mutation. |
| Validation | May request preparation or explain validation feedback. | Owns schema validation, report validation, deterministic checks, and fail-closed status. |
| Research artifacts | Must not create or approve `FinancialFact`, `ResearchFinding`, `FinalReport`, or equivalent formal artifacts. | Legacy workflow owns artifact construction, validation, approval, and persistence. |
| Graph and source state | No direct graph write, source mutation, collector routing, or database access. | Existing authorities own graph writes, source registry, collectors, and persistence. |
| Audit and governance | Emits session/tool context needed for lineage. | Owns authoritative audit records, policy decisions, and authority boundaries. |

The dividing line is intentional: Harness can help decide what to investigate;
Research OS decides what is a fact, what is evidence, what validates, and what
becomes a durable research artifact.

## 3. Capability priorities

### P0 — Close human value evidence

Complete the existing 20-case human review using the retained raw artifacts and
the P8-A4-R5 workbook. This is the next evidence gate, not a runtime feature.
No model-generated score, summary, or proxy may replace a human reviewer.

### P1 — Contextual exploration corpus

Design a new, separately authorized corpus with realistic research context:
entity mapping, as-of date, available sources, evidence excerpts or references,
known data gaps, and a concrete analyst question. The corpus should test
whether exploration produces substantive hypotheses and useful next actions,
not only whether governance controls fire.

### P2 — Skill contract expansion

Strengthen the existing `stock-research` skill first. Treat the additional
skills in Section 4 as candidates that require their own contracts, tests, and
taskbook authorization before implementation or enablement.

### P3 — Read-only MCP context surface

Add context only where a separate taskbook demonstrates a real exploration
need. Candidate tools must be deterministic at the boundary, source-aware,
audited, and read-only. They must return explicit `UNKNOWN`,
`INSUFFICIENT_EVIDENCE`, `DATA_DEGRADED`, or `SOURCE_CONFLICT` states where
appropriate.

### P4 — Opt-in frontend exploration experience

Design a frontend handoff that exposes session progress, tool results, data
gaps, audit lineage, and the handoff to the Legacy workflow. It must not expose
private chain-of-thought, invent capability status, or imply that exploration
output is a validated research artifact.

### P5 — Operational evidence observability

Continue retaining raw evaluation evidence and measure session success,
continuity, timeout, provider calls, token usage, latency, cleanup, and audit
completeness. These metrics support review and diagnosis; they are not by
themselves a production adoption gate.

## 4. Skill roadmap

All skills below are roadmap candidates. Until separately authorized, only the
existing governed skill surface is enabled.

| Skill | Purpose | Allowed tools / behavior | Forbidden actions |
|---|---|---|---|
| `stock-research` | Frame a company question, identify missing context, and organize bounded exploration. | Company profile, data readiness, governed research-scenario preparation, and other approved read-only MCP tools. | Creating formal facts/findings/reports; source or graph mutation; validator bypass; investment or trading advice. |
| `financial-analysis` | Prepare financial questions, identify metric gaps, and compare returned structured context. | Read-only company/financial context, data readiness, deterministic analysis-preparation tools. | Creating `FinancialFact`; changing financial data; emitting strict-schema artifacts; target prices or buy/sell/position recommendations. |
| `industry-analysis` | Explore industry structure, supply-chain questions, competitors, risks, and hypotheses. | Read-only industry graph/context, company profile, readiness, and scenario preparation. | Graph writes, source-specific collection, altering the source registry, or producing approved findings. |
| `evidence-review` | Inspect evidence coverage, provenance, conflicts, and questions requiring analyst review. | Evidence summaries, candidate/evidence reads, readiness, and audit lineage reads. | Evidence mutation or approval, provenance fabrication, validator bypass, or upgrading a lead into a fact. |
| `earnings-analysis` | Prepare earnings-focused questions, timing context, missing-data checks, and analyst follow-ups. | Read-only earnings/company context, readiness, and research-scenario preparation. | Ingestion, `FinancialFact` creation, source mutation, formal earnings artifacts, or unsupported conclusions. |
| `competitor-analysis` | Explore peer context and comparison hypotheses for analyst follow-up. | Read-only peer/company/industry context and readiness tools. | Mutating peer masters or graph state, inventing peer mappings, or writing a final comparison artifact. |

Every future skill must declare its objective, allowed tools, forbidden actions,
turn/tool budget, completion rule, empty-data behavior, and audit metadata. A
missing or invalid contract remains fail-closed.

## 5. MCP tool roadmap

### Existing governed surface

The current exploration boundary includes the existing Research OS facade,
including `get_company_profile`, `check_data_readiness`, and
`run_research_scenario` as verified in the P8-A0~P8-A4 work. These tools remain
behind the Runtime Router, permission policy, exploration contract, and audit
lineage.

### Candidate read-only tools

The following names describe future design candidates only; they are not
implemented or enabled by this document:

- `get_evidence_summary`: read evidence coverage, provenance, dates, and
  conflicts without changing evidence state.
- `list_evidence_candidates`: list governed candidates for analyst review,
  preserving source and independence metadata.
- `get_financial_context`: read already-authorized structured financial context
  with units, period, as-of date, and data-quality status.
- `get_earnings_context`: read governed earnings timing and available context.
- `get_peer_context`: read existing peer mappings and their confidence/status.
- `get_industry_context`: read industry or supply-chain context without graph
  mutation.

Each candidate requires a separate contract and tests for normal, empty,
degraded, conflict, authorization, and audit cases. A candidate must not
silently call a source-specific collector or expose an unvalidated raw store.

### Permanent negative boundaries

Harness and its skills must not receive tools for direct source mutation, graph
write, evidence mutation, artifact approval/apply, direct database or SQL
access, collector routing, schema bypass, validator bypass, or final report
write. No MCP expansion may weaken the existing Financial Authority, Evidence
Authority, or Graph Write Authority.

## 6. Frontend integration direction

The intended user path is:

```text
Frontend
    ↓
Harness session
    ↓
Skill contract
    ↓
Research OS MCP facade
    ↓
Existing Legacy workflow and validator
```

Harness should manage conversation, session continuation, bounded exploration,
tool-call progress, pause/stop, and an explicit handoff request. The Research
OS and Legacy workflow should manage entity resolution, source/evidence
lineage, data readiness, validation, formal artifact creation, approval, and
persistence.

The frontend may display the returned evidence context, data gaps, tool status,
audit lineage, and handoff state. It must not display private chain-of-thought,
claim that a Harness response is a validated artifact, or hard-code a
capability as available when the router or backend has not enabled it.

The first frontend milestone should be a design and contract taskbook, not a
production integration. The default entry point and default runtime remain
Legacy.

## 7. Deferred human value evaluation

Human value evaluation may be reopened only when all of the following are
available:

1. At least three realistic research scenarios, including a company question
   and at least one industry, earnings, or competitor context.
2. A context package for every case containing entity mapping, as-of date,
   available source/evidence references, data gaps, and the analyst question.
3. Substantive exploration output that can be judged for research usefulness,
   exploration quality, actionability, and noise; a governance-only trace is
   insufficient.
4. Immutable per-case evidence containing input, prompt, raw response, event
   snapshot, tool calls, audit lineage, and metrics.
5. A named human reviewer using the workbook/JSON workflow, with no automatic
   model score or summary substituted.

The review rubric remains reviewer-owned: 1–5 for research usefulness,
exploration quality, and actionability; 0–1 for noise rate; plus notes and
review time. Qualitative severe-negative patterns must be recorded. Aggregate
thresholds may help structure a human decision, but they do not convert the
evaluation into an automated acceptance gate.

## 8. Sequencing and exit conditions

| Phase | Deliverable | Exit condition |
|---|---|---|
| A | Complete current P8-A4 human review | 20/20 cases reviewed and independently checked; outcome recorded as human evidence. |
| B | Design contextual corpus | Cases have realistic inputs, evidence context, data gaps, and substantive expected review questions. |
| C | Authorize skill/tool taskbooks | Each enabled addition has a contract, negative controls, tests, and audit evidence. |
| D | Design frontend handoff | Session, evidence display, and Legacy handoff contracts are defined without exposing private reasoning or artifact authority. |
| E | Independent reassessment | Reliability, governance, cost, cleanup, and human value are reviewed together; any adoption decision requires a new explicit authorization. |

No phase in this roadmap changes the default runtime or grants Harness access
to formal research authorities. No phase is a production adoption declaration.

## 9. Non-goals and frozen decisions

P8-A5 does not modify production runtime code, Runtime Router policy, Legacy
default routing, `LlmClient`, schemas, validators, source registry, Financial
Authority, Evidence Authority, or Graph Write Authority. It does not move
`FinancialFact`, `ResearchFinding`, `FinalReport`, or equivalent structured
research artifacts into Harness. It does not permit graph writes, evidence
mutation, source mutation, or automatic human-value scoring.
