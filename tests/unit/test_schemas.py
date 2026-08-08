"""Schema 校验测试：9 个核心 JSON Schema 的正常、边界与失败路径。

验收标准（工程指南 63 节）：所有 Schema 测试通过。
"""
from __future__ import annotations

import pytest

from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    validate_all_schemas,
    validate_instance,
)
from tests.fixtures import samples

# (schema_name, 有效样本工厂)
VALID_FACTORIES = [
    ("task", samples.valid_task),
    ("entity", samples.valid_entity),
    ("raw_item", samples.valid_raw_item),
    ("event", samples.valid_event),
    ("opinion", samples.valid_opinion),
    ("claim", samples.valid_claim),
    ("evidence", samples.valid_evidence),
    ("module_result", samples.valid_module_result),
    ("graph_change", samples.valid_graph_change),
]


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_schema_files_are_valid(name, factory):
    """所有 schema 文件本身合法。"""
    results = validate_all_schemas()
    assert results[name] == [], f"{name}.schema.json 非法: {results[name]}"


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_valid_instance_passes(name, factory):
    """正常样本必须通过校验。"""
    errors = validate_instance(factory(), name)
    assert errors == [], f"{name} 正常样本未通过: {errors}"


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_missing_required_field_fails(name, factory):
    """缺少必需字段必须失败。"""
    data = factory()
    required = {
        "task": "task_id", "entity": "entity_id", "raw_item": "raw_item_id",
        "event": "event_id", "opinion": "opinion_id", "claim": "claim_id",
        "evidence": "evidence_id", "module_result": "module",
        "graph_change": "graph_change_id",
    }[name]
    del data[required]
    errors = validate_instance(data, name)
    assert errors, f"{name} 缺少 {required} 应失败但通过了"


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_extra_field_fails(name, factory):
    """additionalProperties:false —— 额外字段必须失败。"""
    errors = validate_instance(samples.invalid_extra_field(factory()), name)
    assert errors, f"{name} 含额外字段应失败但通过了"


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_nullable_fields_accept_null(name, factory):
    """可选字段允许 null（边界）。"""
    data = factory()
    nullable_by_schema = {
        "task": ["time_window.start", "time_window.end"],
        "entity": ["valid_from", "valid_to"],
        "raw_item": ["author", "external_id", "raw_category"],
        "event": ["effective_at"],
        "opinion": ["time_horizon", "influence_score"],
        "claim": ["valid_until"],
        "graph_change": ["reviewed_at"],
    }.get(name, [])
    for path in nullable_by_schema:
        node = data
        parts = path.split(".")
        for p in parts[:-1]:
            node = node[p]
        node[parts[-1]] = None
    errors = validate_instance(data, name)
    assert errors == [], f"{name} null 边界未通过: {errors}"


@pytest.mark.parametrize("name,factory", VALID_FACTORIES)
def test_empty_collections_pass(name, factory):
    """空列表字段（边界）。"""
    data = factory()
    list_fields = {
        "task": ["entities", "warnings"],
        "entity": ["aliases", "industry_ids", "concept_ids", "source_ids"],
        "raw_item": ["entities"],
        "event": ["subject_entities", "object_entities", "industry_coordinates",
                  "evidence_ids", "conflicts"],
        "opinion": ["target_entities", "arguments", "predictions", "conditions",
                    "evidence_ids"],
        "claim": ["subject_entities", "evidence_ids"],
        "module_result": ["facts", "source_opinions", "analyses", "hypotheses",
                          "open_questions", "evidence_ids", "warnings",
                          "missing_data", "artifacts"],
        "graph_change": ["impact_scope", "conflicts",
                         "verification_points"],
    }.get(name, [])
    for f in list_fields:
        data[f] = []
    errors = validate_instance(data, name)
    assert errors == [], f"{name} 空列表边界未通过: {errors}"


def test_invalid_enum_fails():
    """错误枚举值必须失败（代表性覆盖各枚举字段）。"""
    cases = [
        ("task", samples.valid_task(status="unknown_status")),
        ("task", samples.valid_task(depth="ultra")),
        ("entity", samples.valid_entity(entity_type="alien")),
        ("event", samples.valid_event(impact_direction="super_positive")),
        ("opinion", samples.valid_opinion(stance="super_bullish")),
        ("claim", samples.valid_claim(claim_type="GUESS")),
        ("evidence", samples.valid_evidence(source_tier="Z")),
        ("module_result", samples.valid_module_result(status="maybe")),
        ("graph_change", samples.valid_graph_change(change_type="delete_everything")),
    ]
    for name, data in cases:
        errors = validate_instance(data, name)
        assert errors, f"{name} 非法枚举应失败但通过了"


def test_invalid_format_fails():
    """非法格式（时间/哈希/版本号）必须失败。"""
    cases = [
        ("task", samples.valid_task(requested_at="not-a-date")),
        ("entity", samples.valid_entity(valid_from="2026/08/05")),
        ("raw_item", samples.valid_raw_item(content_hash="xyz")),
        ("event", samples.valid_event(event_time="08-05-2026")),
        ("opinion", samples.valid_opinion(published_at="yesterday")),
        ("claim", samples.valid_claim(as_of=12345)),
        ("evidence", samples.valid_evidence(retrieved_at="now")),
        ("module_result", samples.valid_module_result(version="1.0")),
        ("graph_change", samples.valid_graph_change(created_at="later")),
    ]
    for name, data in cases:
        errors = validate_instance(data, name)
        assert errors, f"{name} 非法格式应失败但通过了"


def test_numeric_bounds_fail():
    """数值越界必须失败（置信度/新颖性/评分）。"""
    cases = [
        ("event", samples.valid_event(novelty=1.5)),
        ("event", samples.valid_event(confidence=-0.1)),
        ("opinion", samples.valid_opinion(influence_score=101)),
        ("claim", samples.valid_claim(confidence=2.0)),
        ("module_result", samples.valid_module_result(confidence=99)),
        ("task", samples.valid_task(max_runtime_seconds=0)),
    ]
    for name, data in cases:
        errors = validate_instance(data, name)
        assert errors, f"{name} 数值越界应失败但通过了"


def test_all_schema_files_present():
    """55 个 Schema 文件必须齐全（含 Phase 5 产业图谱 4 个）。"""
    from research_os.validators.schema_validator import schema_path

    for name in SCHEMA_NAMES:
        assert schema_path(name).exists(), f"缺少 {name}.schema.json"
    assert len(SCHEMA_NAMES) == 55
