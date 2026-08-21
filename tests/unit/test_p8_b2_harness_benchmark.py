"""P8-B2-EVAL-001: Harness benchmark offline regression tests.

Deterministic and fully offline: the live harness path is not exercised here
(that is the CI benchmark run); these tests lock the corpus definition, the
metrics derivation and the failure-case behavior (fallback / audit / no fake).
"""
from __future__ import annotations

import json

import pytest
import yaml

from research_os.agent_runtime.errors import RuntimeNotReady
from research_os.llm.client import LlmClient
from research_os.llm.providers.harness import HarnessLlmProvider


ROOT = None  # filled below
CORPUS = None


@pytest.fixture(scope="module", autouse=True)
def _load():
    global ROOT, CORPUS
    from pathlib import Path
    ROOT = Path(__file__).resolve().parents[2]
    CORPUS = yaml.safe_load((ROOT / "config" / "harness_benchmark" / "corpus.yaml").read_text(encoding="utf-8"))


def test_corpus_exists_and_has_expected_shape():
    cases = CORPUS["cases"]
    assert 10 <= len(cases) <= 15
    equity = [c for c in cases if c["category"] == "equity"]
    research = [c for c in cases if c["category"] == "research"]
    failure = [c for c in cases if c["category"] == "failure"]
    assert len(equity) >= 5
    assert len(research) >= 5
    assert len(failure) >= 3
    ids = [c["id"] for c in cases]
    assert len(ids) == len(set(ids))


def test_corpus_is_decoupled_from_live01_corpus():
    # The benchmark corpus must never reference LIVE-01 acceptance semantics.
    text = yaml.safe_dump(CORPUS, allow_unicode=True)
    assert "session" not in text
    assert "turn" not in text
    assert "PASS CANDIDATE" not in text


def test_equity_cases_reference_registered_tasks_or_prompt_level():
    from research_os.llm.equity_tasks import EQUITY_LLM_SCHEMAS
    for case in CORPUS["cases"]:
        if case["category"] == "equity" and case.get("task"):
            assert case["task"] in EQUITY_LLM_SCHEMAS
        assert case["schema_name"]  # schema never modified/removed


def test_failure_cases_define_expected_honest_fallback():
    for case in CORPUS["cases"]:
        if case["category"] == "failure":
            assert case["failure"] in {"invalid_json", "timeout", "schema_violation"}
            assert case["expected"] == "honest_fallback"


# ---------------------------------------------------------------------------
# Failure behavior through the real LlmClient path (deterministic fixtures)
# ---------------------------------------------------------------------------

class _FakeAdapter:
    def __init__(self, *, response_text: str = "", error: Exception | None = None):
        self.response_text = response_text
        self.error = error

    def create_session(self, metadata=None):
        return object()

    def send_message(self, session, message: str) -> dict:
        if self.error is not None:
            raise self.error
        return {"status": "completed", "response": self.response_text}

    def close_session(self, session) -> dict:
        return {"status": "closed"}


def _run(case: dict, adapter) -> dict:
    from research_os.validators.schema_validator import load_schema
    provider = HarnessLlmProvider(adapter)
    client = LlmClient(provider=provider, configured=True)
    request = _request(case["schema_name"])
    resp = client.generate_json(request, load_schema(case["schema_name"]))
    return {"called": resp.called, "status": resp.status, "schema_valid": resp.schema_valid,
            "output": resp.output, "errors": resp.validation_errors or []}


def _request(schema_name: str):
    from research_os.llm.models import LlmRequest
    return LlmRequest(call_id="bench-f", task_id="bench:f", module="harness_benchmark.failure",
                      prompt="Return JSON", prompt_hash="f", output_schema_name=schema_name,
                      timeout_seconds=60)


def test_invalid_json_failure_is_honest_fallback():
    case = next(c for c in CORPUS["cases"] if c["id"] == "fl_invalid_json")
    result = _run(case, _FakeAdapter(response_text="无法输出 JSON。"))
    assert result["status"] == "fallback"
    assert result["schema_valid"] is False
    assert result["output"] is None
    assert any("invalid_response" in e for e in result["errors"])


def test_timeout_failure_is_typed_and_honest():
    case = next(c for c in CORPUS["cases"] if c["id"] == "fl_timeout")
    result = _run(case, _FakeAdapter(error=RuntimeNotReady("PROVIDER_TIMEOUT", "harness failed")))
    assert result["status"] == "fallback"
    assert result["schema_valid"] is False
    assert result["output"] is None
    assert any("PROVIDER_TIMEOUT" in e for e in result["errors"])


def test_schema_violation_failure_is_honest_fallback():
    case = next(c for c in CORPUS["cases"] if c["id"] == "fl_schema_violation")
    result = _run(case, _FakeAdapter(response_text='{"invalid": true}'))
    assert result["status"] == "fallback"
    assert result["schema_valid"] is False
    assert result["output"] is None  # never becomes a Research object


def test_audit_records_are_written_for_failure_cases():
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE llm_call_records (call_id TEXT, payload TEXT, task_id TEXT,"
                 " module TEXT, status TEXT, called_at TEXT)")
    provider = HarnessLlmProvider(_FakeAdapter(response_text="无法输出 JSON。"))
    client = LlmClient(provider=provider, configured=True, db=_FakeDb(conn))
    client.generate_json(_request("research_finding"),
                         __import__("research_os.validators.schema_validator",
                                    fromlist=["load_schema"]).load_schema("research_finding"))
    row = conn.execute("SELECT call_id, status FROM llm_call_records").fetchone()
    assert row is not None
    assert row[0] == "bench-f"
    assert row[1] == "fallback"


class _FakeDb:
    def __init__(self, conn):
        self._conn = conn


def test_metrics_definition_matches_governance_thresholds():
    from scripts.run_harness_benchmark import SCHEMA_VALID_RATE_REQUIRED
    assert SCHEMA_VALID_RATE_REQUIRED == 0.70


def test_report_output_path_is_gitignored():
    import subprocess
    result = subprocess.run(["git", "check-ignore", "reports/harness_benchmark_latest.json"],
                            capture_output=True, text=True)
    assert result.returncode == 0  # reports/ is ignored: benchmark artifacts stay out of git
