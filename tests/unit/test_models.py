"""Python 数据模型测试：正常、边界、失败，以及与 JSON Schema 的一致性。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_os.models import (
    Claim,
    Entity,
    Event,
    Evidence,
    GraphChange,
    ModuleResult,
    Opinion,
    RawItem,
    Task,
)
from research_os.validators.schema_validator import validate_model
from tests.fixtures import samples


MODEL_FACTORIES = [
    (Task, samples.valid_task),
    (Entity, samples.valid_entity),
    (RawItem, samples.valid_raw_item),
    (Event, samples.valid_event),
    (Opinion, samples.valid_opinion),
    (Claim, samples.valid_claim),
    (Evidence, samples.valid_evidence),
    (ModuleResult, samples.valid_module_result),
    (GraphChange, samples.valid_graph_change),
]


@pytest.mark.parametrize("model_cls,factory", MODEL_FACTORIES)
def test_model_valid_and_matches_schema(model_cls, factory):
    """正常实例化，且 dump 结果通过对应 Schema 校验（模型与契约一致）。"""
    model = model_cls(**factory())
    errors = validate_model(model)
    assert errors == [], f"{model_cls.__name__} 与 Schema 不一致: {errors}"


@pytest.mark.parametrize("model_cls,factory", MODEL_FACTORIES)
def test_model_missing_required_fails(model_cls, factory):
    """缺少必需字段必须抛出 ValidationError。"""
    data = factory()
    required = {
        Task: "task_id", Entity: "entity_id", RawItem: "raw_item_id",
        Event: "event_id", Opinion: "opinion_id", Claim: "claim_id",
        Evidence: "evidence_id", ModuleResult: "module", GraphChange: "graph_change_id",
    }[model_cls]
    del data[required]
    with pytest.raises(ValidationError):
        model_cls(**data)


@pytest.mark.parametrize("model_cls,factory", MODEL_FACTORIES)
def test_model_extra_field_fails(model_cls, factory):
    """extra=forbid：额外字段必须失败。"""
    with pytest.raises(ValidationError):
        model_cls(**samples.invalid_extra_field(factory()))


def test_model_invalid_enum_fails():
    with pytest.raises(ValidationError):
        Task(**samples.valid_task(depth="ultra"))
    with pytest.raises(ValidationError):
        Event(**samples.valid_event(impact_direction="super_positive"))
    with pytest.raises(ValidationError):
        ModuleResult(**samples.valid_module_result(status="maybe"))


def test_model_invalid_time_fails():
    with pytest.raises(ValidationError):
        Task(**samples.valid_task(requested_at="not-a-date"))
    with pytest.raises(ValidationError):
        Event(**samples.valid_event(event_time="08-05-2026"))


def test_model_numeric_bounds_fail():
    with pytest.raises(ValidationError):
        Claim(**samples.valid_claim(confidence=1.5))
    with pytest.raises(ValidationError):
        Opinion(**samples.valid_opinion(influence_score=101))
    with pytest.raises(ValidationError):
        Task(**samples.valid_task(max_runtime_seconds=0))


def test_model_timezone_enforced():
    """timezone 强制 Asia/Shanghai（工程指南时间口径）。"""
    with pytest.raises(ValidationError):
        Task(**samples.valid_task(timezone="UTC"))


def test_model_bounds_ok():
    """数值边界（0/1、空列表、null）可正常实例化。"""
    Task(**samples.valid_task(warnings=[], entities=[]))
    Event(**samples.valid_event(novelty=0.0, confidence=1.0))
    Entity(**samples.valid_entity(valid_from=None, valid_to=None, aliases=[]))
    Claim(**samples.valid_claim(confidence=0.0, evidence_ids=[]))
