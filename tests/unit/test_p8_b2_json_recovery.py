from __future__ import annotations

from research_os.llm.json_recovery import recover_json_boundary
from research_os.llm.providers.harness import HarnessLlmProvider


def test_markdown_fence_is_recovered_without_mutation():
    result = recover_json_boundary('```json\n{"ok": true, "n": 1}\n```')
    assert result["recovered"] is True
    assert result["recovery_type"] == "markdown_fence"
    assert result["json_text"] == '{"ok": true, "n": 1}'


def test_surrounding_text_recovers_one_object():
    result = recover_json_boundary("Answer:\n{\"ok\": true}\nEnd.")
    assert result["recovered"] is True
    assert result["recovery_type"] == "surrounding_text"
    assert result["json_text"] == '{"ok": true}'


def test_whitespace_only_boundary_is_recovered():
    result = recover_json_boundary("  \ufeff {\"ok\": true}  ")
    assert result["recovered"] is True
    assert result["recovery_type"] == "whitespace"


def test_malformed_json_fails_closed():
    result = recover_json_boundary("Answer: {\"ok\": true,}")
    assert result["recovered"] is False
    assert result["failure_type"] == "strict_parse_error"
    assert result["json_text"] is None


def test_multiple_objects_are_not_guessed():
    result = recover_json_boundary('{"ok": true} and {"ok": false}')
    assert result["recovered"] is False
    assert result["failure_type"] == "ambiguous_multiple_objects"


def test_duplicate_keys_are_rejected():
    result = recover_json_boundary('{"ok": true, "ok": false}')
    assert result["recovered"] is False
    assert result["failure_type"] == "strict_parse_error"


def test_provider_exposes_recovery_audit_metadata():
    class Adapter:
        def create_session(self, metadata=None):
            return object()

        def send_message(self, session, message):
            return {"response": "Answer: {\"ok\": true}"}

        def close_session(self, session):
            return {}

    from tests.unit.test_p8_b2_harness_llm_entry import _request

    provider = HarnessLlmProvider(Adapter())
    result = provider.complete_json(_request(), {
        "type": "object", "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"], "additionalProperties": False,
    })
    assert result["ok"] is True
    assert result["output"] == {"ok": True}
    assert result["usage"]["json_recovery_attempted"] is True
    assert result["usage"]["json_recovery_type"] == "surrounding_text"
    assert result["usage"]["json_recovery_success"] is True


def test_recovery_does_not_bypass_validator():
    class Adapter:
        def create_session(self, metadata=None):
            return object()

        def send_message(self, session, message):
            return {"response": "Answer: {\"ok\": true}"}

        def close_session(self, session):
            return {}

    from research_os.llm.client import LlmClient
    from tests.unit.test_p8_b2_harness_llm_entry import _request
    from research_os.validators.schema_validator import load_schema

    provider = HarnessLlmProvider(Adapter())
    response = LlmClient(provider=provider, configured=True).generate_json(
        _request(output_schema_name="research_finding"), load_schema("research_finding"))
    assert response.status == "fallback"
    assert response.schema_valid is False
    assert response.output is None
