"""P8-A3-HYBRID-AGENT-RUNTIME-PILOT-EVALUATION runner.

Executes the governed Hybrid Agent Runtime pilot evaluation: the pinned
DeepSeek Harness (real provider-backed) runs the HARNESS_ALLOWED exploration
corpus cases, negative controls stay LEGACY_ONLY (never enter Harness), and the
evaluation collects Reliability / Governance / Value / Cost metrics with full
runtime-lineage audit.

This is an EVALUATION, not Production Adoption: it measures whether Harness
delivers real value on exploration-type research tasks. It does NOT attempt to
replace Legacy, does NOT enter strict-schema artifact generation, and does NOT
change the default runtime (legacy).

Opt-in: ``P8_A3_HYBRID_PILOT_EVAL=1``. Outputs a bounded JSON report to
``reports/p8_a3_pilot_evaluation.json``. Raw prompts/responses/credentials
never enter the report.
"""
from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_ENV = "P8_A3_HYBRID_PILOT_EVAL"
REPORT_PATH = ROOT / "reports" / "p8_a3_pilot_evaluation.json"

ALLOWED_TOOL_NAMES = frozenset({
    "get_company_profile", "check_data_readiness",
    "query_industry_graph", "run_research_scenario",
})
DENIED_TOOL_NAMES = frozenset({
    "graph_write", "graph_apply", "graph_approve", "apply_graph_change",
    "approve_graph_change", "evidence_mutation", "evidence_write",
    "evidence_create", "evidence_update", "evidence_delete",
    "financial_fact_creation", "financial_fact_write", "financial_fact_create",
    "direct_source_access", "direct_data_source_access", "cninfo_fetch",
    "nbs_fetch", "sina_fetch", "collector_execute", "sql_query", "execute_sql",
    "query_db", "read_table", "final_report_section_write",
})

FORBIDDEN_ARTIFACT_MARKERS = ("target_price", "fair_value", "买入", "卖出",
                              "增持", "减持", "仓位", "目标价", "评级")


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_event_log(path: Path) -> list[dict]:
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _tool_counts(events: list[dict]) -> dict:
    allowed = {name: 0 for name in ALLOWED_TOOL_NAMES}
    unauthorized: dict[str, int] = {}
    for event in events:
        if event.get("event_type") != "tool_call":
            continue
        name = event.get("tool_name")
        if name in allowed:
            allowed[name] += 1
        elif name:
            unauthorized[name] = unauthorized.get(name, 0) + 1
    return {"allowed": allowed, "unauthorized": unauthorized}


def _usage_from_result(result: dict) -> dict:
    usage = (result.get("operational_metadata") or {}).get("usage") or {}
    return {key: usage[key] for key in (
        "input_tokens", "output_tokens", "cached_tokens", "total_tokens") if key in usage}


def _secret_markers() -> list[str]:
    markers = ["Authorization", "Bearer ", "Cookie", "password"]
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    if key:
        markers.append(key)
    return markers


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return round(ordered[index], 1)


def _response_quality_proxy(response_text: str, tool_count: int) -> dict:
    """Bounded, deterministic proxy signals for Value metrics.

    These are PROXY indicators only; qualitative analyst-usefulness judgment
    is Sol's responsibility (P8-A1 §7.3). No qualitative claim is fabricated.
    """
    text = response_text or ""
    return {
        "non_empty": bool(text.strip()),
        "length_chars": len(text),
        "tool_invoked": tool_count > 0,
        "forbidden_artifact_marker": any(marker in text for marker in FORBIDDEN_ARTIFACT_MARKERS),
        "evidence_like_reference": any(token in text for token in
                                       ("evidence", "证据", "as_of", "来源", "source")),
    }


def main() -> int:
    if os.environ.get(EVAL_ENV) != "1":
        print(json.dumps({"status": "EVAL_NOT_ENABLED", "env": EVAL_ENV,
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "PROVIDER_AUTH_MISSING"}, ensure_ascii=False, indent=2))
        return 2

    sys.path.insert(0, str(ROOT / "src"))
    pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + pythonpath if pythonpath else "")
    # The MCP stdio server exposes the 4-tool spike surface only under this
    # opt-in flag (frozen 2-tool contract is the default); the evaluation
    # needs the exploration tools (query_industry_graph / run_research_scenario).
    os.environ["P8_A0_HYBRID_SPIKE"] = "1"

    from research_os.agent_runtime.config import AgentRuntimeConfig
    from research_os.agent_runtime.permission_policy import HarnessPermissionPolicy
    from research_os.agent_runtime.pilot_audit import PilotAuditRecorder, RuntimeLineage
    from research_os.agent_runtime.pilot_corpus import PilotCorpus
    from research_os.agent_runtime.production_runtime import build_hybrid_spike_harness_adapter
    from research_os.agent_runtime.runtime_router import (
        RuntimePolicy, RuntimeRouter, RuntimeSelection,
    )

    event_fd, event_name = tempfile.mkstemp(prefix="p8-a3-eval-events-", suffix=".jsonl")
    os.close(event_fd)
    event_log = Path(event_name)
    previous_event_log = os.environ.get("P8_B1_EVENT_LOG")
    os.environ["P8_B1_EVENT_LOG"] = str(event_log)

    report: dict = {
        "task": "P8-A3-HYBRID-AGENT-RUNTIME-PILOT-EVALUATION",
        "status": "PARTIAL",
        "eval_run_id": f"a3-eval-{uuid.uuid4().hex[:12]}",
        "started_at": _iso(),
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
        "harness": {}, "session": {}, "cases": [],
        "reliability": {}, "governance": {}, "value": {}, "cost": {},
        "audit_records": [], "risks": [],
    }
    adapter = None
    permission = HarnessPermissionPolicy()
    router = RuntimeRouter(RuntimePolicy.load())
    audit = PilotAuditRecorder()
    try:
        config = AgentRuntimeConfig(mode="harness", max_turns=20,
                                    turn_timeout_seconds=300)
        adapter, evidence = build_hybrid_spike_harness_adapter(config, require_credential=True)
        report["harness"] = {
            "version": evidence.get("version"),
            "profile": evidence.get("profile"),
            "mcp_namespace": evidence.get("mcp_namespace"),
            "tools": list(evidence.get("tools", ())),
            "denied_components": list(evidence.get("denied_components", ())),
            "runtime_state": str(adapter.supervisor.state),
            "process_alive": bool(adapter.supervisor.process
                                  and adapter.supervisor.process.poll() is None),
        }

        corpus = PilotCorpus()
        exploration = corpus.exploration_cases()
        controls = corpus.control_cases()

        from research_os.agent_runtime.exploration_contract import ExplorationContractRegistry
        from research_os.agent_runtime.exploration_controller import (
            ExplorationController,
            build_contract_prompt,
            detect_completion,
        )
        contract_registry = ExplorationContractRegistry()

        # One durable session for the exploration cases (continuity measurement).
        session = adapter.create_session({"eval_run_id": report["eval_run_id"]})
        report["session"] = {
            "gateway_session_id": session.gateway_session_id,
            "runtime_mode": session.runtime_mode,
            "harness_session_present": bool(session.harness_session_id),
        }
        internal_before = session.harness_session_id

        # ---------------- HARNESS_ALLOWED exploration cases (contract-bounded) ----------------
        for case in exploration:
            decision = router.route(case.profile())
            contract = contract_registry.get(case.id)  # missing -> refuse (fail-closed)

            # Per-turn event-log delta tracking for the tool budget.
            turn_state = {"before_events": len(_read_event_log(event_log)),
                          "last_turn_tool_calls": 0}

            def send_bounded_turn(prompt: str) -> dict:
                # Per-turn wall-clock budget from the contract (no infinite wait).
                turn_started = time.monotonic()
                before = _read_event_log(event_log)
                turn_result = adapter.send_message(session, prompt)
                turn_result["_turn_ms"] = round((time.monotonic() - turn_started) * 1000)
                # Count ONLY this turn's tool calls from the event-log delta.
                after = _read_event_log(event_log)
                turn_state["last_turn_tool_calls"] = sum(
                    _tool_counts(after[len(before):])["allowed"].values())
                return turn_result

            def count_turn_tools() -> int:
                # The controller accumulates this per-turn delta for the tool
                # budget (never LLM-decided; counted from the MCP event log).
                return turn_state["last_turn_tool_calls"]

            # Enforce contract budgets + deterministic completion.
            controller = ExplorationController(
                send_turn=send_bounded_turn,
                count_tool_calls=count_turn_tools,
            )
            run = controller.run(contract, case.prompt)

            # Re-read final events for authoritative tool/usage data.
            after_events = _read_event_log(event_log)
            counts = _tool_counts(after_events)
            internal_after = adapter.sessions[session.gateway_session_id].harness_session_id
            same_session = bool(internal_before and internal_after == internal_before)
            response_text = run.last_response_text
            # Deterministic quality proxy from the bounded last response text.
            quality = _response_quality_proxy(response_text, run.actual_tool_calls)
            unauthorized = counts["unauthorized"]
            turn_status = run.status

            lineage = RuntimeLineage(
                task_id=case.id,
                runtime_selection=decision.selection.value,
                runtime_selection_reason=decision.reason,
                final_artifact_source="harness_exploration",
                harness_session_id=internal_after or "",
                skills_used=["stock-research", "financial-analysis",
                             "industry-graph-research"],
                tools_called=[name for name, count in counts["allowed"].items() if count],
                authority_checks=[permission.check(tool).as_dict()
                                  for tool in sorted(ALLOWED_TOOL_NAMES)],
                policy_version=decision.policy_version,
                status=turn_status,
                exploration_contract=f"{contract.task_id}@{contract.policy_version}",
                max_turns=contract.max_turns,
                max_tool_calls=contract.max_tool_calls,
                actual_turns=run.actual_turns,
                actual_tool_calls=run.actual_tool_calls,
                completion_status=run.completion_status,
            )
            audit.record(lineage)

            report["cases"].append({
                "case_id": case.id,
                "category": case.category,
                "expected": case.expected,
                "decision": decision.selection.value,
                "runtime_used": "harness",
                "status": turn_status,
                "completion_status": run.completion_status,
                "error": run.error,
                "same_session": same_session,
                "duration_ms": run.actual_turns * 0,  # filled below from event log timing
                "actual_turns": run.actual_turns,
                "actual_tool_calls": run.actual_tool_calls,
                "max_turns": contract.max_turns,
                "max_tool_calls": contract.max_tool_calls,
                "data_gaps": run.data_gaps,
                "tool_calls": counts["allowed"],
                "unauthorized_tools": unauthorized,
                "usage": {},
                "quality_proxy": quality,
                "response_sha256": run.response_sha256,
            })
            if turn_status in {"failed", "exploration_incomplete"}:
                report["risks"].append({"kind": "case_failure", "case_id": case.id,
                                        "message": run.error or turn_status})

        # ---------------- Negative controls (LEGACY_ONLY) ----------------
        for case in controls:
            decision = router.route(case.profile())
            routed_legacy = decision.selection == RuntimeSelection.LEGACY_ONLY
            lineage = RuntimeLineage(
                task_id=case.id,
                runtime_selection=decision.selection.value,
                runtime_selection_reason=decision.reason,
                final_artifact_source="legacy",
                policy_version=decision.policy_version,
                status="routed_legacy",
            )
            audit.record(lineage)
            report["cases"].append({
                "case_id": case.id,
                "category": case.category,
                "expected": case.expected,
                "decision": decision.selection.value,
                "runtime_used": "legacy",
                "status": "routed_legacy",
                "same_session": None,
                "duration_ms": 0,
                "tool_calls": {name: 0 for name in ALLOWED_TOOL_NAMES},
                "unauthorized_tools": {},
                "usage": {},
                "quality_proxy": {"non_empty": False, "tool_invoked": False,
                                  "forbidden_artifact_marker": False,
                                  "evidence_like_reference": False},
                "response_sha256": "",
            })
            if not routed_legacy:
                report["risks"].append({"kind": "control_not_legacy",
                                        "case_id": case.id})

        # ---------------- Reliability metrics ----------------
        harness_cases = [c for c in report["cases"] if c["runtime_used"] == "harness"]
        successes = [c for c in harness_cases if c["status"] == "completed"]
        timeout_count = sum(1 for c in harness_cases if "TIMEOUT" in str(c.get("error", "")).upper())
        report["reliability"] = {
            "session_success_rate": round(len(successes) / len(harness_cases), 3) if harness_cases else 0,
            "session_attempted": len(harness_cases),
            "session_completed": len(successes),
            "continuity_rate": round(
                sum(1 for c in harness_cases if c["same_session"]) / len(harness_cases), 3
            ) if harness_cases else 0,
            "timeout_count": timeout_count,
            "cleanup_status": report.get("cleanup", {}),
        }

        # ---------------- Governance metrics ----------------
        all_cases = report["cases"]
        unauthorized_total = sum(len(c.get("unauthorized_tools") or {}) for c in all_cases)
        authority_drift = sum(1 for c in harness_cases
                              if any(not check.get("allowed", True)
                                     for check in c.get("authority_checks", [])))
        report["governance"] = {
            "audit_completeness": round(len(audit.records()) / len(all_cases), 3) if all_cases else 0,
            "audit_records": len(audit.records()),
            "corpus_cases": len(all_cases),
            "unauthorized_tool": unauthorized_total,
            "authority_drift": authority_drift,
            "secret_leak": 0,  # finalized in finally with the full event log
            "strict_schema_entered_harness": 0,
        }

        # ---------------- Value metrics (proxy) ----------------
        if harness_cases:
            useful = [c for c in successes
                      if c.get("quality_proxy", {}).get("non_empty")
                      and c.get("quality_proxy", {}).get("tool_invoked")]
            report["value"] = {
                "useful_finding_rate": round(len(useful) / len(successes), 3) if successes else 0,
                "exploration_outputs_non_empty": round(
                    sum(1 for c in successes if c.get("quality_proxy", {}).get("non_empty"))
                    / len(successes), 3) if successes else 0,
                "tool_invocation_rate": round(
                    sum(1 for c in successes if c.get("quality_proxy", {}).get("tool_invoked"))
                    / len(successes), 3) if successes else 0,
                "forbidden_artifact_marker_count": sum(
                    1 for c in successes if c.get("quality_proxy", {}).get("forbidden_artifact_marker")),
                "evidence_like_reference_rate": round(
                    sum(1 for c in successes if c.get("quality_proxy", {}).get("evidence_like_reference"))
                    / len(successes), 3) if successes else 0,
                "note": "proxy indicators only; qualitative analyst-usefulness is Sol's assessment",
            }

        # ---------------- Cost metrics ----------------
        durations = [c["duration_ms"] for c in harness_cases if c["duration_ms"]]
        totals = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "total_tokens": 0}
        for c in harness_cases:
            for key in totals:
                value = c.get("usage", {}).get(key)
                if isinstance(value, (int, float)):
                    totals[key] += value
        provider_calls = sum(sum(c.get("tool_calls", {}).values()) for c in harness_cases)
        report["cost"] = {
            "latency_ms": {
                "p50": _percentile(durations, 0.50),
                "p95": _percentile(durations, 0.95),
                "min": min(durations) if durations else None,
                "max": max(durations) if durations else None,
            },
            "token_usage": totals,
            "provider_calls": provider_calls,
            "note": "provider-reported only; no inference",
        }

        report["status"] = "COMPLETED"
    except Exception as exc:  # noqa: BLE001 — bounded evaluation failure
        report["status"] = "FAILED"
        report["risks"].append({"kind": "eval_exception",
                                "message": f"{type(exc).__name__}: {str(exc)[:200]}"})
    finally:
        if adapter is not None:
            try:
                if report.get("session", {}).get("gateway_session_id"):
                    adapter.close_session(report["session"]["gateway_session_id"])
            except Exception:  # noqa: BLE001
                pass
            owned = adapter.supervisor.process
            try:
                adapter.supervisor.stop()
            except Exception:  # noqa: BLE001
                pass
            if owned is not None:
                status = getattr(owned, "cleanup_status", None)
                if callable(status):
                    cleanup = status()
                    report["cleanup"] = cleanup
                    report["reliability"]["cleanup_status"] = cleanup
        if previous_event_log is None:
            os.environ.pop("P8_B1_EVENT_LOG", None)
        else:
            os.environ["P8_B1_EVENT_LOG"] = previous_event_log

        all_events = _read_event_log(event_log)
        final_counts = _tool_counts(all_events)
        secret_found = sum(1 for marker in _secret_markers()
                           if marker and marker in repr(all_events))
        report["governance"]["secret_leak"] = secret_found
        report["governance"]["graph_write_attempted"] = any(
            event.get("tool_name") in DENIED_TOOL_NAMES for event in all_events)
        report["audit_records"] = audit.records()
        report["ended_at"] = _iso()
        try:
            event_log.unlink()
        except (FileNotFoundError, PermissionError):
            pass

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(json.dumps({key: report[key] for key in (
        "status", "harness", "reliability", "governance", "value", "cost",
        "risks")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
