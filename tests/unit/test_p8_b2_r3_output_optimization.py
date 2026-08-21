"""P8-B2-R3: harness agent output optimization regression tests.

Locks the schema-aware context injection (required list + constraint summary +
deterministic example) and the benchmark failure classification. The schema,
validator and normalizer are never modified; the example is a context hint
only and never fabricates the model's output.
"""
from __future__ import annotations

from research_os.llm.schema_context import (
    build_harness_prompt,
    build_schema_example,
    describe_schema,
)
from research_os.validators.schema_validator import load_schema, validate_instance

SIMPLE = {"type": "object",
          "properties": {"id": {"type": "string"}, "name": {"type": "string"},
                         "kind": {"type": "string", "enum": ["a", "b"]},
                         "company_entity_id": {"type": "string", "pattern": "^company:"},
                         "tags": {"type": "array", "items": {"type": "string"}}},
          "required": ["id", "name", "kind", "company_entity_id", "tags"],
          "additionalProperties": False}


def test_describe_schema_lists_required_and_constraints():
    described = describe_schema(SIMPLE)
    assert described["required"] == ["id", "name", "kind", "company_entity_id", "tags"]
    assert any("enum: a, b" in c for c in described["constraints"])
    assert any("pattern: ^company:" in c for c in described["constraints"])


def test_example_is_schema_valid_and_deterministic():
    example = build_schema_example(SIMPLE)
    import jsonschema
    jsonschema.validate(instance=example, schema=SIMPLE)  # must be valid
    assert build_schema_example(SIMPLE) == example  # deterministic


def test_example_for_real_equity_schema_is_valid():
    schema = load_schema("catalyst")
    example = build_schema_example(schema)
    errors = validate_instance(example, "catalyst")
    assert not errors, errors[:3]


def test_prompt_contains_json_only_and_required_fields():
    prompt = build_harness_prompt(None, SIMPLE, task_name="test_task",
                                  evidence="- 证据一")
    assert "只输出一个 JSON 对象" in prompt
    assert "禁止调用任何工具" in prompt
    assert "必填字段" in prompt
    assert "company_entity_id" in prompt
    assert "完整合法示例" in prompt
    assert "任务：test_task" in prompt


def test_prompt_keeps_user_request_and_evidence():
    class _Req:
        prompt = "请基于证据分析"
        module = "equity_research.catalyst_candidates"
        input_evidence_ids = ["e1"]

    prompt = build_harness_prompt(_Req(), SIMPLE)
    assert "用户要求" in prompt and "请基于证据分析" in prompt


# ---------------------------------------------------------------------------
# Failure classification (benchmark runner)
# ---------------------------------------------------------------------------

def _classify(error: str) -> str:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "run_harness_benchmark", "scripts/run_harness_benchmark.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._classify_failure(error)


def test_failure_classification_categories():
    assert _classify("invalid_response: Harness 响应缺少有效 JSON content") == "json_format_failure"
    assert _classify("JSON 解析失败: Expecting value") == "json_format_failure"
    assert _classify("<root>: 'finding_id' is a required property") == "missing_required_field"
    assert _classify("catalyst_type: 'x' is not one of ['earnings', 'project']") == "enum_violation"
    assert _classify("company_entity_id: 'v' does not match '^company:'") == "value_format_violation"
    assert _classify("confidence: 'v' is not of type 'number'") == "value_format_violation"
    assert _classify("version: 0 is less than the minimum of 1") == "value_format_violation"
    assert _classify("") == "none"
    assert _classify("something else") == "other"


def test_prompt_uses_measured_best_structure():
    # R4-R1 empirical finding: the completion checklist / self-validation
    # instructions systematically reduced schema-valid rate (0.2/0.2 across
    # two runs) vs the R3 structure (0.5). The prompt therefore keeps the
    # full schema + required constraints + example WITHOUT the checklist.
    prompt = build_harness_prompt(None, SIMPLE, task_name="catalyst_candidates")
    assert "必填字段（必须全部出现在输出中，不得缺失）" in prompt
    assert "company_entity_id" in prompt
    assert "完整合法示例" in prompt
    assert "JSON Schema" in prompt and "additionalProperties" in prompt
    assert "必填字段完成清单" not in prompt  # checklist removed (empirical regression)
    assert "输出前自检" not in prompt
