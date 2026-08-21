"""Offline capability/probe regression tests for P8-B2-R5-B."""
from __future__ import annotations

from research_os.llm.models import LlmRequest
from research_os.llm.providers.harness import HarnessLlmProvider
from research_os.llm.structured_output import detect_structured_output_capability


SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _request() -> LlmRequest:
    return LlmRequest(
        call_id="probe-call", task_id="probe-task", module="probe.test",
        prompt="return the structured object", prompt_hash="probe-hash",
        requested_model_class="flash", provider="deepseek-harness",
        output_schema_name="probe", timeout_seconds=60,
    )


class _NormalOnlyAdapter:
    def create_session(self, metadata=None):
        return object()

    def send_message(self, session, message):
        return {"status": "completed", "response": '{"ok": true}',
                "operational_metadata": {"usage": {"total_tokens": 7}}}

    def close_session(self, session):
        return {"status": "closed"}


class _StructuredAdapter(_NormalOnlyAdapter):
    def __init__(self):
        self.schemas: list[dict] = []

    def send_structured_message(self, session, message, output_schema):
        self.schemas.append(output_schema)
        return {"status": "completed", "response": '{"ok": true}',
                "operational_metadata": {"usage": {"total_tokens": 8}}}


def test_capability_detector_requires_explicit_adapter_method():
    unsupported = HarnessLlmProvider(_NormalOnlyAdapter())
    supported_adapter = _StructuredAdapter()
    supported = HarnessLlmProvider(supported_adapter, structured_output=True)

    assert detect_structured_output_capability(unsupported).status == "UNSUPPORTED"
    assert detect_structured_output_capability(supported).status == "SUPPORTED"
    assert unsupported.capability()["status"] == "NOT_REQUESTED"
    assert supported.capability()["structured_output_supported"] is True


def test_structured_mode_passes_schema_and_keeps_provider_usage():
    adapter = _StructuredAdapter()
    provider = HarnessLlmProvider(adapter, structured_output=True)
    result = provider.complete_json(_request(), SCHEMA)

    assert result["ok"] is True
    assert result["output"] == {"ok": True}
    assert result["usage"]["total_tokens"] == 8
    assert adapter.schemas == [SCHEMA]
    assert provider.calls[-1]["status"] == "completed"


def test_structured_mode_does_not_fallback_to_prompt_only_transport():
    adapter = _NormalOnlyAdapter()
    provider = HarnessLlmProvider(adapter, structured_output=True)
    result = provider.complete_json(_request(), SCHEMA)

    assert result["ok"] is False
    assert result["error_type"] == "structured_output_unsupported"
    assert provider.calls[-1]["status"] == "unsupported"

