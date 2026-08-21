"""P8-A2 Hybrid Agent Runtime Pilot runner.

Executes the pilot corpus through the governance execution layer
(Router -> Permission -> Runtime -> Audit) and prints a bounded summary. The
Harness path is exercised with a fake/offline runner by default; the real
Harness loop is validated separately by the P8-A0 spike and the P8-A2 POSIX
validation script. This runner is opt-in (``P8_A2_HYBRID_PILOT=1``) and never
changes the default runtime.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if os.environ.get("P8_A2_HYBRID_PILOT") != "1":
        print(json.dumps({"status": "PILOT_NOT_ENABLED", "env": "P8_A2_HYBRID_PILOT",
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2

    sys.path.insert(0, str(ROOT / "src"))
    pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + pythonpath if pythonpath else "")

    from research_os.agent_runtime.pilot_adapter import HarnessPilotAdapter
    from research_os.agent_runtime.pilot_audit import PilotAuditRecorder
    from research_os.agent_runtime.pilot_corpus import PilotCorpus
    from research_os.agent_runtime.runtime_router import RuntimePolicy

    corpus = PilotCorpus()
    audit = PilotAuditRecorder()
    policy = RuntimePolicy.load()

    def harness_runner(case_id: str, prompt: str) -> dict:
        # Offline harness runner for the pilot runner: bounded, no real LLM.
        # The real Harness loop is validated by P8-A0 spike + P8-A2 POSIX script.
        return {
            "status": "completed",
            "harness_session_id": f"pilot-{case_id}-offline",
            "skills_used": ["stock-research", "financial-analysis", "industry-graph-research"],
            "tools_called": ["get_company_profile", "check_data_readiness",
                             "query_industry_graph", "run_research_scenario"],
        }

    adapter = HarnessPilotAdapter(policy=policy, audit=audit,
                                  harness_runner=harness_runner)

    results = []
    for case in corpus.all():
        outcome = adapter.run_case(case)
        results.append(outcome.as_dict())

    report = {
        "task": "P8-A2-HYBRID-AGENT-RUNTIME-PILOT",
        "status": "COMPLETED",
        "policy_version": policy.version,
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
        "corpus_size": len(corpus.all()),
        "results": results,
        "audit_records": audit.records(),
        "artifact_source_examples": {
            "industry_exploration": audit.artifact_source("industry_exploration"),
            "financial_fact_generation": audit.artifact_source("financial_fact_generation"),
        },
    }
    out_path = ROOT / "reports" / "p8_a2_hybrid_pilot.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "corpus_size": report["corpus_size"],
        "results": report["results"],
        "artifact_source_examples": report["artifact_source_examples"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
