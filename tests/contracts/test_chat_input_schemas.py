"""Phase 7 UX1 chat semantic-contract tests."""
from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft7Validator

from research_os.llm.validation import LlmOutputValidator
from research_os.orchestrator.runners import DEFAULT_SCENARIOS
from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    load_schema,
    schema_dir,
    validate_instance,
)


SCENARIO_SCHEMA_NAMES = {
    scenario: f"chat_{scenario}_input" for scenario in DEFAULT_SCENARIOS
}
CHAT_SCHEMA_NAMES = ("chat_route", *SCENARIO_SCHEMA_NAMES.values())

FORBIDDEN_FIELDS = {
    "task_id",
    "request_id",
    "requested_at",
    "created_at",
    "as_of",
    "timezone",
    "status",
    "version",
    "rule_versions",
    "idempotency_key",
    "run_id",
    "validation_status",
    "symbol",
    "company_entity_id",
    "security_entity_id",
    "industry_id",
    "phase4_result_id",
    "previous_cutoff",
    "manifest_id",
    "financial_manifest_id",
    "market_manifest_id",
}


VALID_PAYLOADS = {
    "morning_brief": {
        "entity_mentions": [], "industry_mentions": [],
        "report_date_expression": "今天", "research_focus": [],
        "complete": True, "clarification_question": None,
    },
    "evening_brief": {
        "entity_mentions": [], "industry_mentions": [],
        "report_date_expression": "今天", "research_focus": [],
        "complete": True, "clarification_question": None,
    },
    "daily_review": {
        "entity_mentions": [], "industry_mentions": [],
        "temporal_expression": "今天", "research_focus": [],
        "complete": True, "clarification_question": None,
    },
    "abnormal_move_analysis": {
        "entity_mentions": ["贵州茅台"], "temporal_expression": "今天下午",
        "research_question": "为什么突然下跌", "metric_expressions": ["跌幅"],
        "complete": True, "clarification_question": None,
    },
    "stock_research_report": {
        "company_mentions": ["贵州茅台"], "temporal_expression": None,
        "research_question": "核心竞争力是什么", "research_focus": ["财务"],
        "depth_hint": "deep", "complete": True, "clarification_question": None,
    },
    "stock_review": {
        "company_mentions": ["贵州茅台"], "temporal_expression": "最近一个月",
        "research_question": None, "research_focus": [], "depth_hint": None,
        "complete": True, "clarification_question": None,
    },
    "industry_research": {
        "industry_mentions": ["半导体"], "company_mentions": [],
        "temporal_expression": None, "research_question": "供需格局如何",
        "research_focus": ["供需"], "depth_hint": "standard",
        "complete": True, "clarification_question": None,
    },
    "theme_discovery": {
        "theme_keywords": ["AI 眼镜"], "industry_mentions": [],
        "temporal_expression": "最近一个月", "research_question": None,
        "research_focus": [], "depth_hint": None,
        "complete": True, "clarification_question": None,
    },
    "earnings_expectation": {
        "company_mentions": ["贵州茅台"], "forecast_period_expression": "FY2027",
        "metric_expressions": ["营业收入"], "scenario_expressions": ["基准情景"],
        "explicit_assumptions": [{
            "statement": "销量同比增长 5%", "metric_expression": "销量",
            "value_expression": "同比增长 5%", "period_expression": "FY2027",
        }],
        "complete": True, "clarification_question": None,
    },
    "first_coverage": {
        "company_mentions": ["贵州茅台"], "industry_mentions": ["白酒"],
        "temporal_expression": None, "research_question": None,
        "research_focus": [], "depth_hint": "deep",
        "complete": True, "clarification_question": None,
    },
}


def _property_names(node):
    if isinstance(node, dict):
        yield from node.get("properties", {}).keys()
        for value in node.values():
            yield from _property_names(value)
    elif isinstance(node, list):
        for value in node:
            yield from _property_names(value)


def _is_forbidden_property(name):
    return (
        name in FORBIDDEN_FIELDS
        or name.endswith("_manifest_id")
        or name.endswith("_manifest_ids")
    )


def _object_schemas(node):
    if isinstance(node, dict):
        if node.get("type") == "object":
            yield node
        for value in node.values():
            yield from _object_schemas(value)
    elif isinstance(node, list):
        for value in node:
            yield from _object_schemas(value)


def _valid_payload_for(schema_name):
    if schema_name == "chat_route":
        return {
            "scenario": None,
            "confidence": 0,
            "needs_clarification": True,
            "clarification_question": "请选择研究场景。",
        }
    scenario = schema_name.removeprefix("chat_").removesuffix("_input")
    return VALID_PAYLOADS[scenario]


@pytest.mark.parametrize("schema_name", CHAT_SCHEMA_NAMES)
def test_chat_schema_is_registered_draft7_strict_and_llm_loadable(schema_name):
    assert schema_name in SCHEMA_NAMES
    schema = load_schema(schema_name)
    Draft7Validator.check_schema(schema)
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False

    payload = _valid_payload_for(schema_name)
    valid, parsed, errors = LlmOutputValidator().validate(payload, schema_name)
    assert valid, errors
    assert parsed == payload


def test_scenario_contracts_have_dynamic_parity():
    task_scenarios = set(load_schema("task")["properties"]["scenario"]["enum"])
    route_scenarios = set(
        load_schema("chat_route")["properties"]["scenario"]["enum"]
    ) - {None}
    runtime_scenarios = set(DEFAULT_SCENARIOS)
    discovered_schema_names = {
        path.name.removesuffix(".schema.json")
        for path in schema_dir().glob("chat_*_input.schema.json")
    }
    schema_scenarios = {
        name.removeprefix("chat_").removesuffix("_input")
        for name in discovered_schema_names
    }
    assert runtime_scenarios == task_scenarios == route_scenarios == schema_scenarios
    assert discovered_schema_names.issubset(SCHEMA_NAMES)


def test_route_contains_only_frozen_semantic_fields():
    schema = load_schema("chat_route")
    expected = {
        "scenario", "confidence", "needs_clarification", "clarification_question"
    }
    assert set(schema["properties"]) == expected
    assert set(schema["required"]) == expected


def test_route_rejects_unknown_scenario_and_authority_field():
    invalid_scenario = {
        "scenario": "not_a_scenario", "confidence": 1,
        "needs_clarification": False, "clarification_question": None,
    }
    assert validate_instance(invalid_scenario, "chat_route")
    with_authority = {
        "scenario": None, "confidence": 0,
        "needs_clarification": True,
        "clarification_question": "请选择研究场景。",
        "task_id": "forbidden",
    }
    assert validate_instance(with_authority, "chat_route")


@pytest.mark.parametrize("schema_name", CHAT_SCHEMA_NAMES)
def test_forbidden_authority_and_system_fields_are_absent_recursively(schema_name):
    assert not any(
        _is_forbidden_property(name)
        for name in _property_names(load_schema(schema_name))
    )


@pytest.mark.parametrize("schema_name", CHAT_SCHEMA_NAMES)
def test_every_object_schema_is_strict_recursively(schema_name):
    object_schemas = list(_object_schemas(load_schema(schema_name)))
    assert object_schemas
    assert all(node.get("additionalProperties") is False for node in object_schemas)


@pytest.mark.parametrize(
    "forbidden_field",
    ["task_id", "as_of", "company_entity_id", "financial_manifest_id"],
)
def test_nested_semantic_object_rejects_authority_and_system_fields(forbidden_field):
    payload = deepcopy(VALID_PAYLOADS["earnings_expectation"])
    payload["explicit_assumptions"][0][forbidden_field] = "forbidden"
    assert validate_instance(payload, "chat_earnings_expectation_input")


@pytest.mark.parametrize("scenario,payload", VALID_PAYLOADS.items())
def test_chat_input_normal_sample_is_valid(scenario, payload):
    assert validate_instance(payload, SCENARIO_SCHEMA_NAMES[scenario]) == []


@pytest.mark.parametrize("scenario,payload", VALID_PAYLOADS.items())
def test_chat_input_boundary_incomplete_sample_is_valid(scenario, payload):
    boundary = deepcopy(payload)
    for key, value in boundary.items():
        if isinstance(value, list):
            boundary[key] = []
        elif key not in {"complete", "clarification_question"}:
            boundary[key] = None
    boundary["complete"] = False
    boundary["clarification_question"] = "请补充必要信息。"
    assert validate_instance(boundary, SCENARIO_SCHEMA_NAMES[scenario]) == []


@pytest.mark.parametrize("scenario,payload", VALID_PAYLOADS.items())
@pytest.mark.parametrize("forbidden_field", sorted(FORBIDDEN_FIELDS))
def test_chat_input_rejects_extra_authority_fields(scenario, payload, forbidden_field):
    invalid = {**payload, forbidden_field: "forbidden"}
    assert validate_instance(invalid, SCENARIO_SCHEMA_NAMES[scenario])


@pytest.mark.parametrize("schema_name", CHAT_SCHEMA_NAMES)
def test_chat_schema_rejects_each_missing_required_semantic_field(schema_name):
    schema = load_schema(schema_name)
    property_names = set(schema["properties"])
    required_names = set(schema["required"])
    assert required_names == property_names

    payload = _valid_payload_for(schema_name)
    assert set(payload) == property_names
    for property_name in sorted(required_names):
        invalid = deepcopy(payload)
        invalid.pop(property_name)
        assert validate_instance(invalid, schema_name), property_name
