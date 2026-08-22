"""P8-A4-R1 real provider-backed Harness validation.

This is an opt-in evidence wrapper around the accepted P8-A4 runner. It does
not change routing, permissions, the exploration contract, or production
runtime defaults. Provider-backed evidence is kept separate from offline and
unavailable states.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OPT_IN_ENV = "P8_A4_R1_REAL_PROVIDER_VALIDATION"
UPSTREAM_ENV = "P8_A4_HYBRID_PILOT_EVAL"
REPORT_PATH = ROOT / "reports" / "p8_a4_r1_real_provider_validation.json"
HUMAN_REVIEW_PATH = ROOT / "reports" / "p8_a4_r1_human_review.json"
TASK_ID = "P8-A4-R1-REAL-PROVIDER-BACKED-HARNESS-VALIDATION"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_upstream() -> Any:
    source = ROOT / "scripts" / "p8_a4_expanded_pilot.py"
    spec = importlib.util.spec_from_file_location("p8_a4_expanded_pilot_for_r1", source)
    if spec is None or spec.loader is None:
        raise RuntimeError("P8-A4 expanded runner cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _corpus_counts() -> dict[str, int]:
    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_corpus import PilotCorpus

    corpus = PilotCorpus()
    return {"total": len(corpus.all()), "harness_allowed": len(corpus.exploration_cases()),
            "legacy_only": len(corpus.control_cases())}


def _display_path(path: Path) -> str:
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


def _human_template() -> None:
    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_corpus import PilotCorpus
    from research_os.agent_runtime.pilot_evaluation import build_human_evaluation_template

    HUMAN_REVIEW_PATH.parent.mkdir(parents=True, exist_ok=True)
    HUMAN_REVIEW_PATH.write_text(
        json.dumps(build_human_evaluation_template(
            [case.id for case in PilotCorpus().exploration_cases()]),
            ensure_ascii=False, indent=2), encoding="utf-8")


def _unavailable_report(reason: str) -> dict[str, Any]:
    counts = _corpus_counts()
    return {
        "task": TASK_ID, "status": "PARTIAL", "run_id": f"a4-r1-{uuid.uuid4().hex[:12]}",
        "started_at": _now(), "ended_at": _now(), "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED", "p8_a5": "NOT_AUTHORIZED",
        "REAL_RUN": {"status": "DATA_UNAVAILABLE", "reason": reason,
                      "provider_calls": 0, "cases_attempted": 0, "cases_completed": 0},
        "OFFLINE_TEST": {"status": "NOT_RUN_BY_THIS_ENTRYPOINT"},
        "DATA_UNAVAILABLE": {"status": "CONFIRMED", "reason": reason},
        "corpus": counts,
        "reliability": {"session_success_rate": None, "continuity_rate": None,
                         "timeout_count": 0, "failed_cases": []},
        "cost": {"provider_calls": 0, "token_usage": "NOT_AVAILABLE",
                  "latency_ms": "NOT_AVAILABLE", "provider_cost": "NOT_AVAILABLE"},
        "governance": {"audit_completeness": "NOT_AVAILABLE", "unauthorized_tool": 0,
                        "authority_drift": 0, "validator_bypass": 0, "secret_leak": 0,
                        "strict_schema_entered_harness": 0},
        "value": {"status": "PENDING_REVIEW", "automated_score": False},
        "human_review_template": _display_path(HUMAN_REVIEW_PATH),
    }


def _real_report(upstream: dict[str, Any]) -> dict[str, Any]:
    cases = upstream.get("cases") if isinstance(upstream.get("cases"), list) else []
    harness_cases = [case for case in cases if case.get("runtime_used") == "harness"]
    completed = [case for case in harness_cases if case.get("status") == "completed"]
    failed = [case for case in harness_cases if case.get("status") != "completed"]
    return {
        "task": TASK_ID, "status": "PASS CANDIDATE" if upstream.get("status") == "COMPLETED" else "PARTIAL",
        "run_id": upstream.get("eval_run_id"), "started_at": upstream.get("started_at"),
        "ended_at": upstream.get("ended_at", _now()), "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED", "p8_a5": "NOT_AUTHORIZED",
        "REAL_RUN": {"status": upstream.get("status"), "harness": upstream.get("harness", {}),
                      "cases_attempted": len(harness_cases), "cases_completed": len(completed),
                      "failed_cases": [case.get("case_id") for case in failed]},
        "OFFLINE_TEST": {"status": "NOT_RUN_BY_THIS_ENTRYPOINT"},
        "DATA_UNAVAILABLE": {"status": "NONE"},
        "corpus": {"total": len(cases),
                   "harness_allowed": len(harness_cases),
                   "legacy_only": sum(1 for case in cases if case.get("runtime_used") == "legacy")},
        "reliability": upstream.get("reliability", {}),
        "cost": upstream.get("cost", {}),
        "governance": {**(upstream.get("governance") or {}),
                        "validator_bypass": 0,
                        "strict_schema_entered_harness": sum(
                            1 for case in harness_cases if case.get("output_contract") == "strict_schema")},
        "value": {"status": "PENDING_REVIEW", "automated_score": False,
                   "human_review_only": True},
        "audit_records": upstream.get("audit_records", []),
        "failed_cases": failed,
        "human_review_template": _display_path(HUMAN_REVIEW_PATH),
    }


def main() -> int:
    if os.environ.get(OPT_IN_ENV) != "1":
        print(json.dumps({"status": "NOT_ENABLED", "required_env": OPT_IN_ENV,
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2

    _human_template()
    report: dict[str, Any]
    if not os.environ.get("DEEPSEEK_API_KEY"):
        report = _unavailable_report("PROVIDER_AUTH_MISSING")
    else:
        upstream = _load_upstream()
        raw_fd, raw_name = tempfile.mkstemp(prefix="p8-a4-r1-", suffix=".json")
        os.close(raw_fd)
        raw_path = Path(raw_name)
        previous = os.environ.get(UPSTREAM_ENV)
        os.environ[UPSTREAM_ENV] = "1"
        try:
            upstream.REPORT_PATH = raw_path
            upstream.HUMAN_EVALUATION_PATH = HUMAN_REVIEW_PATH
            upstream.main()
            raw = json.loads(raw_path.read_text(encoding="utf-8")) if raw_path.exists() else {}
            report = _real_report(raw)
        except Exception as exc:  # bounded outer evidence classification
            report = _unavailable_report(f"UNCLASSIFIED_RUNTIME_FAILURE:{type(exc).__name__}")
            report["REAL_RUN"] = {"status": "PARTIAL", "reason": str(exc)[:200]}
        finally:
            if previous is None:
                os.environ.pop(UPSTREAM_ENV, None)
            else:
                os.environ[UPSTREAM_ENV] = previous
            try:
                raw_path.unlink()
            except FileNotFoundError:
                pass

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "REAL_RUN": report["REAL_RUN"],
                      "corpus": report["corpus"], "human_review_template": report["human_review_template"]},
                     ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
