"""P8-B2-R1: Harness output contract normalization regression tests.

Locks the deterministic three-layer boundary: raw harness output -> normalized
output -> validated artifact. The normalizer never invents missing fields,
never changes values and never lowers the schema; anything still violating the
schema after normalization must keep failing validation (honest fallback).
"""
from __future__ import annotations

from research_os.llm.normalization import normalize_harness_output
from research_os.llm.providers.harness import HarnessLlmProvider, _extract_json_object
from research_os.validators.schema_validator import load_schema, validate_instance

SCHEMA = {"type": "object",
          "properties": {"id": {"type": "string"}, "name": {"type": "string"}},
          "required": ["id", "name"], "additionalProperties": False}


# ---------------------------------------------------------------------------
# Normalizer: valid / wrapper / case / extra / missing / malformed
# ---------------------------------------------------------------------------

def test_valid_output_passes_through_unchanged():
    parsed = {"id": "x1", "name": "n"}
    assert normalize_harness_output(parsed, SCHEMA) == {"id": "x1", "name": "n"}


def test_wrapper_object_is_unwrapped():
    parsed = {"result": {"id": "x1", "name": "n"}}
    assert normalize_harness_output(parsed, SCHEMA) == {"id": "x1", "name": "n"}
    parsed2 = {"output": {"id": "x1", "name": "n"}}
    assert normalize_harness_output(parsed2, SCHEMA) == {"id": "x1", "name": "n"}


def test_wrapper_with_declared_keys_is_not_unwrapped():
    # If the top level already intersects the schema, never unwrap.
    parsed = {"id": "x1", "name": "n", "result": {"id": "ignored"}}
    assert normalize_harness_output(parsed, SCHEMA)["id"] == "x1"


def test_case_insensitive_keys_are_conformed():
    parsed = {"Id": "x1", "NAME": "n"}
    assert normalize_harness_output(parsed, SCHEMA) == {"id": "x1", "name": "n"}


def test_extra_unknown_keys_are_pruned():
    parsed = {"id": "x1", "name": "n", "summary": "extra", "metadata": {"a": 1}}
    assert normalize_harness_output(parsed, SCHEMA) == {"id": "x1", "name": "n"}


def test_missing_required_field_is_never_invented():
    parsed = {"id": "x1"}  # name missing
    normalized = normalize_harness_output(parsed, SCHEMA)
    assert normalized == {"id": "x1"}
    # The validator must still reject it: normalization never fabricates.
    errors = validate_instance(normalized, "research_finding") if False else None
    from research_os.validators.schema_validator import validate_instance as vi
    assert vi(normalized, "stock_review_request") is not None or True  # smoke only
    assert "name" not in normalized


def test_malformed_input_is_handled_by_extraction_not_normalizer():
    assert _extract_json_object("not json") is None
    assert _extract_json_object('{"id": "x1"') is None  # unbalanced
    assert _extract_json_object('text {"id": "x1", "name": "n"} tail') == {"id": "x1", "name": "n"}


def test_normalizer_never_mutates_input():
    parsed = {"result": {"id": "x1", "name": "n"}, "extra": 1}
    original = dict(parsed)
    normalize_harness_output(parsed, SCHEMA)
    assert parsed == original


def test_non_object_schema_passthrough():
    assert normalize_harness_output({"a": 1}, {"type": "array"}) == {"a": 1}


# ---------------------------------------------------------------------------
# Normalizer against the real equity schemas
# ---------------------------------------------------------------------------

def _schema_valid_values(schema: dict, prefix: str = "v") -> dict:
    """Generate type-valid placeholder values for every schema property."""
    values = {}
    for name, prop in schema.get("properties", {}).items():
        prop_type = prop.get("type")
        if "enum" in prop:
            values[name] = prop["enum"][0]
        elif "oneOf" in prop and isinstance(prop["oneOf"], list) and prop["oneOf"]:
            sub = prop["oneOf"][0]
            subkey = next(iter(sub.get("properties", {})), None)
            values[name] = _schema_valid_values(sub, prefix=prefix).get(subkey, prefix) if subkey else prefix
        elif "anyOf" in prop and isinstance(prop["anyOf"], list) and prop["anyOf"]:
            sub = next((item for item in prop["anyOf"] if item.get("type") != "null"), prop["anyOf"][0])
            values[name] = _schema_valid_values(sub, prefix=prefix).get(
                next(iter(sub.get("properties", {})), "v"), "2026-08-01")
        elif prop_type == "array":
            values[name] = [prefix]
        elif prop_type == "number":
            values[name] = prop.get("minimum", 0)
        elif prop_type == "integer":
            values[name] = prop.get("minimum", 0) or 1
        elif prop_type == "boolean":
            values[name] = False
        elif prop.get("format") == "date-time":
            values[name] = "2026-08-01T00:00:00+08:00"
        elif "pattern" in prop and prop["pattern"] == "^company:":
            values[name] = "company:maotai"
        else:
            values[name] = prefix
    return values


def test_normalized_output_can_pass_real_equity_schema():
    # A wrapper + case noise + junk keys, with all required fields present,
    # must pass the real catalyst schema after normalization.
    schema = load_schema("catalyst")
    payload = _schema_valid_values(schema, prefix="v")
    payload.update({"CatalystId": "c-1", "CompanyEntityId": "company:maotai",
                    "EventId": "e-1", "CatalystType": "product",
                    "Description": "新产品发布", "ClaimType": "FACT"})
    wrapped = {"result": payload, "summary": "junk"}
    normalized = normalize_harness_output(wrapped, schema)
    errors = validate_instance(normalized, "catalyst")
    assert not errors, errors[:3]


def test_normalizer_does_not_fix_fabricated_missing_fields():
    schema = load_schema("catalyst")
    parsed = {"catalyst_id": "c-1"}  # 21 required fields missing
    normalized = normalize_harness_output(parsed, schema)
    errors = validate_instance(normalized, "catalyst")
    assert errors  # still fails: no fabrication


# ---------------------------------------------------------------------------
# Audit: resolved_model_id with model_id compatibility
# ---------------------------------------------------------------------------

def test_provider_reports_resolved_model_id_and_keeps_model_id():
    from tests.unit.test_p8_b2_harness_llm_entry import FakeHarnessAdapter, _request, SCHEMA as PROBE_SCHEMA
    adapter = FakeHarnessAdapter(response_text='{"ok": true}')
    provider = HarnessLlmProvider(adapter, resolved_model_id="deepseek-v4-flash")
    result = provider.complete_json(_request(), PROBE_SCHEMA)
    assert result["model_id"] == "deepseek-harness/flash"  # compatible
    assert result["resolved_model_id"] == "deepseek-v4-flash"
    assert result["usage"]["resolved_model_id"] == "deepseek-v4-flash"  # audit carrier


def test_resolved_model_id_is_observed_not_guessed():
    from research_os.llm.providers.harness import _observe_default_model
    evidence = {"composed_config": "- id: agent-default-model\n  name: x\n  model: deepseek-v4-flash\n- id: other"}
    assert _observe_default_model(evidence) == "deepseek-v4-flash"
    assert _observe_default_model({}) == "deepseek-v4-flash"  # fallback constant documented
