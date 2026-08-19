# P8 Agent Runtime Migration and Rollback Plan

**STATUS:** DESIGN ONLY / NO IMPLEMENTATION AUTHORIZED  
**DEFAULT:** `agent_runtime_mode=legacy`  
**LEGACY PATH:** P7-UX1  
**HARNESS VERSION:** `0.1.0-rc.7`

## 1. Migration rule

This is a dual-path migration, not a big-bang replacement. P7-UX1 remains the
production and fallback path until a later independent acceptance explicitly retires
it. Harness traffic is opt-in, bounded, observable, and reversible.

The flag is server-side and has at least these values:

```text
legacy   # default; current behavior
harness  # explicit opt-in; only accepted profiles and scenarios
```

No client-supplied flag may enable Harness for another user or bypass gateway policy.

## 2. Phases

| Phase | Scope | Exit gate |
|---|---|---|
| P8-B1 Production Foundation | isolated runtime, gateway, profile, two read-only tools; flag OFF | boot/security/lifecycle/contract acceptance |
| P8-B2 Internal limited trial | explicit internal opt-in, legacy fallback active | session reliability, cost, security, no authority drift |
| P8-B3 Controlled research rollout | selected scenario/tenant cohort | scenario parity, evidence quality, rollback drill |
| P8-B4 Default-runtime evaluation | evaluate Harness as default candidate | independent acceptance and explicit governance decision |

Each phase has a separate taskbook and accepted commit. Passing a phase does not
authorize the next phase automatically.

## 3. Request routing

```text
request
  -> gateway validates identity, runtime flag, scenario, quotas
  -> legacy: P7-UX1 control path
  -> harness: isolated Harness session
  -> Research OS capability/workflow tools
  -> structured result / business progress projection
```

If Harness has not reached READY, the gateway returns a typed fallback decision and
routes the request to P7-UX1. If a formal Research OS workflow has already started,
the gateway does not silently start a second workflow on the fallback path; it returns
the existing run status or requires an explicit user retry policy.

## 4. Rollback triggers

Immediate rollback to `legacy` occurs for:

- runtime version mismatch or profile drift;
- boot/readiness failure;
- MCP unavailable or unauthorized tool observed;
- credential exposure or private-reasoning logging;
- session corruption or cross-session target contamination;
- Research OS authority mismatch, direct source access, or graph mutation attempt;
- provider timeout/error rate or cost budget breach;
- process-tree leak, unbounded child process, or failed drain;
- material output safety regression.

Rollback is a gateway flag change plus session drain. It does not delete Research OS
records, rewrite reports, or globally terminate unrelated Node/Python processes.

## 5. Upgrade and compatibility policy

`0.1.0-rc.7` is an exact production candidate pin. No `^0.1`, `latest`, floating tag,
or automatic npm update is permitted. Any newer Harness version requires a new
isolated acceptance run covering:

1. runtime boot and profile deny-list;
2. provider-backed session;
3. Skill discovery/loading;
4. MCP tool invocation and bounds;
5. same-session continuation and authority re-read;
6. security negative tests and process cleanup;
7. full offline regression.

The old version remains the rollback artifact until the new version is independently
accepted. A failed compatibility probe blocks the upgrade.

## 6. No retirement condition yet

P7-UX1 may be retired only after a separate acceptance proves equivalent or better
session reliability, business progress semantics, Research OS authority preservation,
security, cost, observability, and all accepted scenario contracts. P8-B design does
not grant retirement or production adoption.
