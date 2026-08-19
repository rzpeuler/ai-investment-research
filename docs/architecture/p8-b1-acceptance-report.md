# P8-B1 Acceptance Report

**STATUS:** IMPLEMENTED / AWAITING INDEPENDENT ACCEPTANCE

**BASE:** `a2b984bd61b57f8e7a50985c1a9e5c7d451b45a0`

**IMPLEMENTATION_HEAD:** `600b24292a73009e0765bdadf49865b3e2bc24c2`

**HARNESS:** `@deepseek-ai/dsh@0.1.0-rc.7`

## Scope

P8-B1 implements the feature-flagged, non-production-default Agent Runtime
foundation. The default path remains P7-UX1 / `legacy`. No frontend, production
traffic, schema, DB migration, source acquisition, Graph write, or P8-B2 work
was performed.

## Initial verification

| Gate | Result |
| --- | --- |
| Agent Runtime Gateway | PASS |
| Legacy adapter preserved | PASS |
| Harness Supervisor lifecycle | PASS |
| Exact version gate | PASS |
| Research profile verification | PASS |
| MCP namespace | `research-os-mcp/v1` |
| MCP Tool catalog | exactly `get_company_profile`, `check_data_readiness` |
| Source / SQL / Graph Tools | DENIED |
| 64 KiB result bound | PASS |
| Opaque gateway session | PASS |
| Typed failures | PASS |
| Secret redaction | PASS |
| Default runtime | `legacy` |
| Provider network | OFF |
| Research data network | OFF |
| Schema / DB / migrations | 86 / v6 / NONE |

## Offline regression result

`python -m pytest -q`: **3699 passed / 6 skipped / 0 failed / 1 warning**  
`python -m research_os.cli.main validate`: **86/86 PASS**  
`python -m compileall -q src scripts tests`: **PASS**  
`git diff --check`: **PASS**

## Pending terminal verification

The full offline regression, independent security review, rollback drill,
crash-recovery drill, and any separately authorized provider-backed live
acceptance must be recorded before changing this report to PASS. Production
adoption and default Harness switching remain not authorized.
