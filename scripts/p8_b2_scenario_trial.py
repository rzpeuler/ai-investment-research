"""P8-B2-INTERNAL-TRIAL-001 scenario verification through the Harness control plane.

Opt-in (`P8_B2_SCENARIO_TRIAL=1`); never the default. Boots the pinned
Harness once, routes the equity-family scenarios' real LLM task sets
(EquityLlmTasks) through the unified LlmClient -> Harness -> DeepSeek path,
and verifies the deterministic (non-LLM) scenarios' honesty markers
(llm_called: false). Outputs a bounded JSON summary; never prints credentials,
prompts or raw responses.

Bounded by design: each task runs at depth "fast" (flash_max=2, pro_max=0),
so the whole verification makes at most 16 harness-backed provider calls.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_os.llm.client import LlmClient  # noqa: E402
from research_os.llm.equity_tasks import EquityLlmTasks  # noqa: E402
from research_os.llm.providers.harness import HarnessLlmProvider  # noqa: E402

SCENARIO_TRIAL_ENV = "P8_B2_SCENARIO_TRIAL"

# Canonical LLM task sets executed by the equity-family scenarios.
SCENARIO_LLM_TASKS = {
    "first_coverage": [
        "research_questions", "business_description_normalization",
        "catalyst_candidates", "risk_candidates", "competitive_factor_candidates",
    ],
    "earnings_expectation": [
        "research_questions", "catalyst_candidates", "risk_candidates",
    ],
}
# Deterministic (non-LLM) scenarios: verify the honesty markers only.
NON_LLM_SCENARIOS = ("evening_brief", "stock_review", "industry_research")

FIXTURE_EXCERPTS = {
    "risk_candidates": "行业波动带来不确定压力，需求下降风险",
    "catalyst_candidates": "新产品产能投产与业绩公告",
    "competitive_factor_candidates": "公司产品竞争力与市场份额业绩公告",
    "business_description_normalization": "公司主营业务收入增长与经营业绩",
    "research_questions": "公司收入增长与经营业绩",
}


def _evidence(task: str) -> dict:
    return {"excerpts": [FIXTURE_EXCERPTS.get(task, "公司收入增长业绩公告"), "第二条证据"],
            "ids": ["e1", "e2"], "types": ["official_disclosure", "official_disclosure"],
            "cutoff": "2026-08-01T00:00:00+08:00"}


def _check_non_llm_honesty() -> dict:
    """Verify deterministic scenarios emit no fake LLM usage."""
    markers = {
        "evening_brief": ("src/research_os/brief/renderer.py", "llm_called: false",
                          "semantic_llm_modules_not_connected"),
        "stock_review": ("src/research_os/review/stock.py", "llm_called: false", None),
        "industry_research": ("src/research_os/orchestrator/runners/industry_research.py",
                              "deterministic_fallback", "llm_called"),
    }
    result = {}
    for scenario, (path, marker, extra) in markers.items():
        text = (Path(__file__).resolve().parents[1] / path).read_text(encoding="utf-8")
        ok = marker in text and (extra is None or extra in text)
        result[scenario] = {"honest_no_llm_marker": "PASS" if ok else "FAIL",
                            "marker": marker, "extra": extra}
    return result


def main() -> int:
    if os.environ.get(SCENARIO_TRIAL_ENV) != "1":
        print(json.dumps({"status": "SCENARIO_TRIAL_NOT_ENABLED",
                          "default_runtime": "legacy"}, ensure_ascii=False, indent=2))
        return 2
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "BLOCKED_CREDENTIAL_UNAVAILABLE"}, ensure_ascii=False))
        return 1

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE llm_call_records (call_id TEXT, payload TEXT, task_id TEXT,"
                 " module TEXT, status TEXT, called_at TEXT)")
    adapter = HarnessLlmProvider()
    client = LlmClient(provider=adapter, configured=True, db=_Db(conn))

    summary: dict = {"scenarios": {}, "harness_calls": 0, "total_tokens": 0}
    try:
        for scenario, tasks in SCENARIO_LLM_TASKS.items():
            runner = EquityLlmTasks(client, depth="fast")  # flash_max=2, pro_max=0
            scenario_result = {"tasks": {}}
            for task in tasks:
                ev = _evidence(task)
                resp = runner.run_task(task, task_id=f"{scenario}:{task}",
                                       evidence_excerpts=ev["excerpts"],
                                       evidence_ids=ev["ids"],
                                       evidence_types=ev["types"], cutoff=ev["cutoff"])
                scenario_result["tasks"][task] = {
                    "called": resp.called, "status": resp.status,
                    "schema_valid": resp.schema_valid,
                    "model_id": resp.model_id,
                    "flash_used": runner.budget.flash_used,
                    "pro_used": runner.budget.pro_used,
                }
            calls = len(adapter.calls)
            scenario_result["harness_calls"] = calls
            scenario_result["flash_used"] = runner.budget.flash_used
            summary["harness_calls"] += calls
            summary["scenarios"][scenario] = scenario_result
            print(f"SCENARIO {scenario}: tasks={len(tasks)} harness_calls={calls} "
                  f"flash_used={runner.budget.flash_used}", flush=True)

        summary["non_llm_scenarios"] = _check_non_llm_honesty()
        summary["audit_rows"] = conn.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0]
        summary["default_runtime"] = "legacy"
        summary["status"] = "COMPLETED"
    finally:
        adapter.adapter.supervisor.stop()

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


class _Db:
    def __init__(self, conn):
        self._conn = conn


if __name__ == "__main__":
    raise SystemExit(main())
