"""P8-B2-INTERNAL-TRIAL-001: Harness LLM entry offline regression tests.

These tests are fully offline and deterministic: the external boundary (the
Harness adapter) is a fake, so no real provider or Harness process is needed.
They lock: provider mapping, failure degradation, budget governance, audit
recording and the no-fake-MODEL_INFERENCE rule for the opt-in harness LLM
entry (default runtime remains legacy).
"""
from __future__ import annotations

import json
import sqlite3

from research_os.agent_runtime.errors import RuntimeNotReady
from research_os.llm.client import LlmClient
from research_os.llm.equity_tasks import EquityLlmTasks
from research_os.llm.providers.harness import HarnessLlmProvider, _extract_json_object
from research_os.validators.schema_validator import load_schema


class FakeHarnessAdapter:
    """Deterministic Harness adapter stand-in (session lifecycle + behavior)."""

    def __init__(self, response_text: str = "", error: Exception | None = None,
                 usage: dict | None = None):
        self.response_text = response_text
        self.error = error
        self.usage = usage or {"total_tokens": 1234, "input_tokens": 1000, "output_tokens": 234}
        self.created = 0
        self.closed = 0
        self.messages: list[str] = []

    def create_session(self, metadata=None):
        self.created += 1
        return object()

    def send_message(self, session, message: str) -> dict:
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        result = {"status": "completed", "response": self.response_text}
        if self.usage:
            result["operational_metadata"] = {"usage": dict(self.usage)}
        return result

    def close_session(self, session) -> dict:
        self.closed += 1
        return {"status": "closed"}


def _request(**overrides):
    from research_os.llm.models import LlmRequest
    overrides.pop("prompt", None)  # prompt is fixed by the helper
    overrides.setdefault("output_schema_name", "test")
    return LlmRequest(
        call_id="call-1", task_id="task-1", module="equity_research.test",
        prompt='Return JSON: {"ok": true}', prompt_hash="h1",
        requested_model_class="flash", timeout_seconds=60, **overrides)


SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}},
          "required": ["ok"], "additionalProperties": False}


# ---------------------------------------------------------------------------
# Provider mapping
# ---------------------------------------------------------------------------

def test_successful_call_returns_structured_output():
    adapter = FakeHarnessAdapter(response_text='{"ok": true}')
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["ok"] is True
    assert result["output"] == {"ok": True}
    assert result["model_id"] == "deepseek-harness/flash"
    assert result["usage"]["total_tokens"] == 1234
    assert adapter.created == 1 and adapter.closed == 1


def test_json_embedded_in_markdown_is_extracted():
    adapter = FakeHarnessAdapter(response_text='```json\n{"ok": true}\n```')
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["ok"] is True and result["output"] == {"ok": True}


def test_prose_response_is_invalid_response():
    adapter = FakeHarnessAdapter(response_text="I cannot comply with that request.")
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["ok"] is False
    assert result["error_type"] == "invalid_response"
    assert result["retryable"] is False


def test_provider_timeout_is_typed_and_retryable():
    adapter = FakeHarnessAdapter(error=RuntimeNotReady("PROVIDER_TIMEOUT", "harness api failed"))
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["ok"] is False
    assert result["error_type"] == "PROVIDER_TIMEOUT"
    assert result["retryable"] is True


def test_harness_boot_failure_is_typed_and_retryable():
    adapter = FakeHarnessAdapter(error=RuntimeNotReady("HARNESS_BOOT_FAILED", "dsh exited"))
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["error_type"] == "HARNESS_BOOT_FAILED"
    assert result["retryable"] is True


def test_unexpected_adapter_error_is_network_error():
    adapter = FakeHarnessAdapter(error=RuntimeError("boom"))
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    assert result["error_type"] == "network_error"
    assert result["retryable"] is False


def test_oversized_prompt_rejected_before_harness():
    adapter = FakeHarnessAdapter(response_text='{"ok": true}')
    provider = HarnessLlmProvider(adapter, max_input_chars=10)
    result = provider.complete_json(_request(prompt="x" * 100), SCHEMA)
    assert result["ok"] is False and result["error_type"] == "invalid_response"
    assert adapter.created == 0  # never reached the harness


# ---------------------------------------------------------------------------
# Budget governance + no fake MODEL_INFERENCE through the unified LlmClient
# ---------------------------------------------------------------------------

def _client(provider, configured=True):
    return LlmClient(provider=provider, configured=configured)


FIXTURE_EXCERPTS = {
    "risk_candidates": "行业波动带来不确定压力，需求下降风险",
    "catalyst_candidates": "新产品产能投产与业绩公告",
    "research_questions": "公司收入增长与经营业绩",
}


def _evidence(task: str):
    return {"excerpts": [FIXTURE_EXCERPTS.get(task, "公司收入增长业绩公告"), "第二条证据"],
            "ids": ["e1", "e2"],
            "types": ["official_disclosure", "official_disclosure"],
            "cutoff": "2026-08-01T00:00:00+08:00"}


def test_flash_attempts_are_bounded_and_failure_is_honest_fallback():
    # Schema-invalid output (ok=True) drives the flash retry path; a
    # non-retryable provider error would stop after one attempt (max_retries=0).
    adapter = FakeHarnessAdapter(response_text='{"invalid": true}')
    provider = HarnessLlmProvider(adapter)
    tasks = EquityLlmTasks(_client(provider), depth="fast")  # flash_max=2, pro_max=0
    ev = _evidence("research_questions")
    resp = tasks.run_task("research_questions", task_id="t1",
                          evidence_excerpts=ev["excerpts"], evidence_ids=ev["ids"],
                          evidence_types=ev["types"], cutoff=ev["cutoff"])
    assert tasks.budget.flash_used == 2  # both flash attempts consumed
    assert resp.called is True  # calls were attempted
    assert resp.status == "fallback"  # honest degradation
    assert resp.output is None
    assert resp.schema_valid is False
    assert adapter.created == 2  # exactly two harness calls, no hidden retries


def test_pro_upgrade_after_two_flash_failures():
    adapter = FakeHarnessAdapter(response_text='{"invalid": true}')
    provider = HarnessLlmProvider(adapter)
    tasks = EquityLlmTasks(_client(provider), depth="standard")  # flash_max=5, pro_max=1
    ev = _evidence("catalyst_candidates")
    resp = tasks.run_task("catalyst_candidates", task_id="t1",
                          evidence_excerpts=ev["excerpts"], evidence_ids=ev["ids"],
                          evidence_types=ev["types"], cutoff=ev["cutoff"])
    # 2 flash failures -> 1 pro attempt -> all fail -> honest fallback.
    assert tasks.budget.flash_used == 2
    assert tasks.budget.pro_used == 1
    assert resp.status == "fallback"
    assert adapter.created == 3


def test_shared_budget_exhaustion_skips_without_harness_call():
    adapter = FakeHarnessAdapter(response_text='{"invalid": true}')
    provider = HarnessLlmProvider(adapter)
    tasks = EquityLlmTasks(_client(provider), depth="fast")  # flash_max=2
    ev = _evidence("risk_candidates")
    for index in range(3):
        tasks.run_task("risk_candidates", task_id=f"t{index}",
                       evidence_excerpts=ev["excerpts"], evidence_ids=ev["ids"],
                       evidence_types=ev["types"], cutoff=ev["cutoff"])
    # First task consumes both flash attempts; later tasks are budget-denied
    # before any provider call.
    assert tasks.budget.flash_used == 2
    assert adapter.created == 2


def test_harness_output_never_bypasses_the_validator():
    # Even a structurally parsed output is validated against the real project
    # schema; an invalid output yields an honest fallback, never MODEL_INFERENCE.
    adapter = FakeHarnessAdapter(response_text='{"invalid": true}')
    provider = HarnessLlmProvider(adapter)
    tasks = EquityLlmTasks(_client(provider), depth="fast")
    ev = _evidence("risk_candidates")
    resp = tasks.run_task("risk_candidates", task_id="t1",
                          evidence_excerpts=ev["excerpts"], evidence_ids=ev["ids"],
                          evidence_types=ev["types"], cutoff=ev["cutoff"])
    assert resp.called is True
    assert resp.status == "fallback"
    assert resp.schema_valid is False
    assert resp.output is None


# ---------------------------------------------------------------------------
# Audit completeness
# ---------------------------------------------------------------------------

def test_audit_record_contains_required_fields():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE llm_call_records (call_id TEXT, payload TEXT, task_id TEXT,"
                 " module TEXT, status TEXT, called_at TEXT)")
    provider = HarnessLlmProvider(FakeHarnessAdapter(response_text='{"invalid": true}'))
    client = LlmClient(provider=provider, configured=True, db=_FakeDb(conn))
    resp = client.generate_json(_request(output_schema_name="research_finding",
                                         provider="deepseek-harness"),
                                load_schema("research_finding"))
    row = conn.execute("SELECT call_id, task_id, module, status FROM llm_call_records").fetchone()
    assert row is not None
    call_id, task_id, module, status = row
    assert call_id == "call-1"
    assert task_id == "task-1"
    assert module == "equity_research.test"
    assert status == "fallback"  # honest degradation recorded
    payload = json.loads(conn.execute("SELECT payload FROM llm_call_records").fetchone()[0])
    assert payload["called"] is True
    assert payload["provider"] == "deepseek-harness"
    assert "model_id" in payload
    assert "latency_seconds" in payload
    assert "usage_metadata" in payload
    assert resp.called is True


class _FakeDb:
    def __init__(self, conn):
        self._conn = conn


# ---------------------------------------------------------------------------
# Security: no secret exposure through the harness entry
# ---------------------------------------------------------------------------

def test_secret_marker_never_enters_usage_or_output():
    adapter = FakeHarnessAdapter(response_text='{"ok": true}',
                                 usage={"total_tokens": 5, "raw": "Bearer SECRET-123"})
    provider = HarnessLlmProvider(adapter)
    result = provider.complete_json(_request(), SCHEMA)
    rendered = json.dumps(result)
    assert "SECRET-123" not in rendered
    assert "Bearer" not in rendered


def test_json_extraction_is_deterministic_and_safe():
    assert _extract_json_object('prefix {"a": 1} suffix') == {"a": 1}
    assert _extract_json_object('{"a": {"b": [1, 2]}}') == {"a": {"b": [1, 2]}}
    assert _extract_json_object('{"a": "brace } inside"}') == {"a": "brace } inside"}
    assert _extract_json_object("no braces here") is None
    assert _extract_json_object('{"a": 1') is None  # unbalanced -> None
