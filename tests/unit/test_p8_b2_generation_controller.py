"""P8-B2-R5-A: GenerationControlledProvider offline regression tests.

Deterministic fake providers drive the generate-validate-repair loop. The
schema, validator, normalizer and LlmClient are untouched; the validator stays
the only quality judgment source.
"""
from __future__ import annotations

import json

from research_os.agent_runtime.errors import RuntimeNotReady
from research_os.llm.client import LlmClient
from research_os.llm.providers.generation_controller import (
    GenerationControlledProvider,
    GenerationState,
)
from research_os.llm.repair import build_repair_prompt, extract_field_errors
from research_os.validators.schema_validator import load_schema

SIMPLE = {"type": "object",
          "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
          "required": ["id", "name"], "additionalProperties": False}


class FakeBaseProvider:
    """Scripted provider: returns a queue of responses (dicts)."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def complete_json(self, request, output_schema):
        self.calls += 1
        return dict(self.responses[min(self.calls - 1, len(self.responses) - 1)])


def _request():
    from research_os.llm.models import LlmRequest
    return LlmRequest(call_id="c1", task_id="t1", module="equity_research.test",
                      prompt="Return JSON", prompt_hash="h1", output_schema_name="test",
                      timeout_seconds=60)


class _DictValidator:
    """Test double: validates against a plain dict schema (jsonschema)."""

    def __init__(self, schema):
        self.schema = schema

    def validate(self, raw_output, schema_name):
        import jsonschema
        try:
            jsonschema.validate(instance=raw_output, schema=self.schema)
            return True, raw_output, []
        except jsonschema.ValidationError as exc:
            message = f"{'.'.join(str(p) for p in exc.path) or '<root>'}: {exc.message}"
            return False, None, [message]


def _controller(base, max_repair_passes=2):
    return GenerationControlledProvider(base, max_repair_passes=max_repair_passes,
                                        validator=_DictValidator(SIMPLE))


def _ok(output):
    return {"ok": True, "provider": "fake", "model_id": "fake/flash",
            "output": output, "error": None, "error_type": None,
            "retryable": False, "usage": {"total_tokens": 10}}


def _err(error_type="PROVIDER_TIMEOUT", retryable=True):
    return {"ok": False, "provider": "fake", "model_id": None, "output": None,
            "error": error_type, "error_type": error_type,
            "retryable": retryable, "usage": {}}


def _controller(base, max_repair_passes=2):
    return GenerationControlledProvider(base, max_repair_passes=max_repair_passes,
                                        validator=_DictValidator(SIMPLE))


def test_controller_works_with_real_registered_validator():
    # With the REAL LlmOutputValidator (registered schema name), invalid
    # outputs drive repair; exhaustion yields a typed honest error.
    from research_os.llm.validation import LlmOutputValidator
    base = FakeBaseProvider([_ok({"id": "x"}), _ok({"id": "x"}), _ok({"id": "x"})])
    controller = GenerationControlledProvider(base, max_repair_passes=2,
                                              validator=LlmOutputValidator())
    request = _request()
    request.output_schema_name = "research_finding"
    result = controller.complete_json(request, load_schema("research_finding"))
    assert result["ok"] is False
    assert result["error_type"] == "repair_exhausted"
    assert result["output"] is None


def test_first_pass_success_no_repair():
    base = FakeBaseProvider([_ok({"id": "x", "name": "n"})])
    controller = _controller(base)
    result = controller.complete_json(_request(), SIMPLE)
    assert result["ok"] is True
    assert result["output"] == {"id": "x", "name": "n"}
    assert base.calls == 1  # no repair
    assert result["usage"]["repair_round"] == 0
    assert result["usage"]["provider_calls"] == 1


def test_repair_success_after_missing_field():
    # Pass 1 output misses "name"; repair returns the complete object.
    base = FakeBaseProvider([_ok({"id": "x"}),
                             _ok({"id": "x", "name": "repaired"})])
    controller = _controller(base)
    result = controller.complete_json(_request(), SIMPLE)
    assert result["ok"] is True
    assert result["output"] == {"id": "x", "name": "repaired"}
    assert base.calls == 2
    assert result["usage"]["repair_round"] == 1
    assert result["usage"]["validation_error_summary"]  # audit carrier populated


def test_repair_exhaustion_is_honest_fallback():
    base = FakeBaseProvider([_ok({"id": "x"}), _ok({"id": "x"}), _ok({"id": "x"})])
    controller = _controller(base, max_repair_passes=2)
    result = controller.complete_json(_request(), SIMPLE)
    assert result["ok"] is False
    assert result["error_type"] == "repair_exhausted"
    assert result["output"] is None  # never becomes a Research object
    assert base.calls == 3  # 1 + 2 repair passes
    assert result["usage"]["repair_round"] == 2


def test_provider_error_passthrough():
    base = FakeBaseProvider([_err("PROVIDER_TIMEOUT", retryable=True)])
    controller = _controller(base)
    result = controller.complete_json(_request(), SIMPLE)
    assert result["ok"] is False
    assert result["error_type"] == "PROVIDER_TIMEOUT"
    assert result["retryable"] is True
    assert base.calls == 1  # no hidden retry by the controller


def test_no_fake_model_inference_through_llmclient():
    from research_os.validators.schema_validator import load_schema as ls
    base = FakeBaseProvider([_ok({"id": "x"}), _ok({"id": "x"}), _ok({"id": "x"})])
    client = LlmClient(provider=_controller(base), configured=True)
    resp = client.generate_json(_request(), SIMPLE)
    assert resp.status == "fallback"
    assert resp.schema_valid is False
    assert resp.output is None  # no MODEL_INFERENCE from a failed generation


def test_repair_prompt_builder_mentions_only_error_fields():
    errors = ["<root>: 'name' is a required property", "id: 'x' is not of type 'integer'"]
    prompt = build_repair_prompt(_request(), {"id": "x"}, errors, "test", evidence="- 证据")
    assert "name" in prompt
    assert "只修复" in prompt or "仅修复" in prompt
    assert "禁止虚构" in prompt
    assert "证据" in prompt


def test_field_error_extraction_categories():
    fields = extract_field_errors([
        "<root>: 'finding_id' is a required property",
        "<root>: 'as_of' is a required property",
        "catalyst_type: 'x' is not one of ['earnings', 'project']",
        "company_entity_id: 'v' does not match '^company:'",
        "invalid_response: Harness 响应缺少有效 JSON content",
        "unrelated message",
    ])
    assert fields["missing_required"] == ["as_of", "finding_id"]
    assert fields["enum_error"] == ["catalyst_type"]
    assert fields["value_format"] == ["company_entity_id"]
    assert len(fields["json_format"]) == 1
    assert len(fields["other"]) == 1


def test_state_is_per_task_and_in_memory():
    base = FakeBaseProvider([_ok({"id": "x", "name": "n"})])
    controller = _controller(base)
    controller.complete_json(_request(), SIMPLE)
    assert len(controller.states) == 1
    assert isinstance(controller.states[0], GenerationState)
    assert controller.states[0].repair_round == 0
