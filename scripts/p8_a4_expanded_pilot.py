"""P8-A4 expanded Hybrid Agent Runtime pilot entry point.

Real Harness/provider execution is delegated to the already governed P8-A3-R1
runner after rebinding its task/report identifiers. When provider credentials
are unavailable, this script emits an explicit DATA_DEGRADED report and never
substitutes offline results for real-run evidence.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVAL_ENV = "P8_A4_HYBRID_PILOT_EVAL"
REPORT_PATH = ROOT / "reports" / "p8_a4_expanded_pilot.json"
HUMAN_EVALUATION_PATH = ROOT / "reports" / "p8_a4_human_evaluation.json"
TASK_ID = "P8-A4-HYBRID-AGENT-RUNTIME-EXPANDED-PILOT"


def _iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_pilot_module():
    source = ROOT / "scripts" / "p8_a3_pilot_evaluation.py"
    spec = importlib.util.spec_from_file_location("p8_a3_pilot_evaluation_for_a4", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to load governed pilot evaluator")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_human_template(exploration_ids: list[str]) -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_evaluation import build_human_evaluation_template

    HUMAN_EVALUATION_PATH.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_EVALUATION_PATH.write_text(
        json.dumps(build_human_evaluation_template(exploration_ids), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _degraded_report() -> dict:
    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_audit import PilotAuditRecorder, RuntimeLineage
    from research_os.agent_runtime.pilot_corpus import PilotCorpus
    from research_os.agent_runtime.runtime_router import RuntimePolicy, RuntimeRouter, RuntimeSelection

    corpus = PilotCorpus()
    router = RuntimeRouter(RuntimePolicy.load())
    audit = PilotAuditRecorder(audit_dir=ROOT / "reports" / "pilot_audit")
    cases = []
    for case in corpus.exploration_cases():
        decision = router.route(case.profile())
        audit.record(RuntimeLineage(
            task_id=case.id,
            runtime_selection=decision.selection.value,
            runtime_selection_reason=decision.reason,
            final_artifact_source="harness_exploration",
            policy_version=decision.policy_version,
            status="not_attempted_provider_unavailable",
        ))
        cases.append({
            "case_id": case.id,
            "category": case.category,
            "expected": case.expected,
            "decision": decision.selection.value,
            "runtime_used": "harness",
            "status": "not_attempted",
            "error": "PROVIDER_AUTH_MISSING",
        })
    for case in corpus.control_cases():
        decision = router.route(case.profile())
        audit.record(RuntimeLineage(
            task_id=case.id,
            runtime_selection=decision.selection.value,
            runtime_selection_reason=decision.reason,
            final_artifact_source="legacy",
            policy_version=decision.policy_version,
            status="routed_legacy",
        ))
        cases.append({
            "case_id": case.id,
            "category": case.category,
            "expected": case.expected,
            "decision": decision.selection.value,
            "runtime_used": "legacy",
            "status": "routed_legacy",
        })
    records = audit.records()
    return {
        "task": TASK_ID,
        "status": "PARTIAL",
        "degradation": "DATA_DEGRADED",
        "degradation_reason": "PROVIDER_AUTH_MISSING",
        "eval_run_id": f"a4-degraded-{uuid.uuid4().hex[:12]}",
        "started_at": _iso(),
        "ended_at": _iso(),
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
        "corpus": {"total": len(corpus.all()), "exploration": len(corpus.exploration_cases()),
                   "controls": len(corpus.control_cases())},
        "cases": cases,
        "reliability": {
            "session_success_rate": None,
            "session_attempted": 0,
            "session_completed": 0,
            "continuity_rate": None,
            "timeout_count": 0,
            "cleanup_status": {},
            "note": "No provider-backed session was attempted; offline results are not substituted.",
        },
        "governance": {
            "audit_completeness": 1.0 if records else 0.0,
            "audit_records": len(records),
            "corpus_cases": len(cases),
            "unauthorized_tool": 0,
            "authority_drift": 0,
            "secret_leak": 0,
            "validator_bypass": 0,
            "strict_schema_entered_harness": 0,
        },
        "value": {"status": "PENDING_REVIEW", "note": "No real run; human review remains pending."},
        "cost": {"provider_calls": 0, "tool_calls": 0, "latency_ms": {}, "token_usage": {},
                 "note": "No provider-backed execution; no cost inferred."},
        "audit_records": records,
        "risks": [{"kind": "provider_unavailable", "message": "Real Harness run not executed."}],
    }


def main() -> int:
    if os.environ.get(EVAL_ENV) != "1":
        print(json.dumps({"status": "EVAL_NOT_ENABLED", "env": EVAL_ENV,
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2

    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_corpus import PilotCorpus

    corpus = PilotCorpus()
    _write_human_template([case.id for case in corpus.exploration_cases()])
    if not os.environ.get("DEEPSEEK_API_KEY"):
        report = _degraded_report()
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": report["status"], "degradation": report["degradation"],
                          "corpus": report["corpus"]}, ensure_ascii=False, indent=2))
        return 0

    module = _load_pilot_module()
    module.EVAL_ENV = EVAL_ENV
    module.REPORT_PATH = REPORT_PATH
    module.EVAL_TASK_ID = TASK_ID
    result = module.main()
    if REPORT_PATH.exists():
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        report["corpus"] = {
            "total": len(corpus.all()),
            "exploration": len(corpus.exploration_cases()),
            "controls": len(corpus.control_cases()),
        }
        report["human_evaluation_path"] = str(HUMAN_EVALUATION_PATH.relative_to(ROOT))
        REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
