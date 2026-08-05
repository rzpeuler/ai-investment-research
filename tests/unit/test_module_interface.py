"""ResearchModule 抽象接口契约测试（工程指南 13 节）。"""
from __future__ import annotations

from research_os.models import ModuleResult
from research_os.modules import ModulePlan, ResearchModule, ValidationResult
from tests.fixtures import samples


class DummyModule(ResearchModule):
    """最小实现：覆盖抽象接口的可测试样例。"""

    name = "dummy"
    version = "1.0.0"

    def validate_input(self, payload):
        return ValidationResult.success()

    def plan(self, payload, context):
        return ModulePlan(module=self.name, steps=["step1"])

    def run(self, payload, context):
        return ModuleResult(**samples.valid_module_result(module=self.name))

    def validate_output(self, result):
        return ValidationResult.success()


def test_module_has_name_and_version():
    m = DummyModule()
    assert m.name == "dummy"
    assert m.version == "1.0.0"


def test_module_validate_input_returns_result():
    m = DummyModule()
    result = m.validate_input({})
    assert isinstance(result, ValidationResult)
    assert result.ok is True
    assert result.errors == []


def test_module_plan_returns_plan():
    m = DummyModule()
    plan = m.plan({}, {})
    assert isinstance(plan, ModulePlan)
    assert plan.module == "dummy"
    assert plan.steps == ["step1"]


def test_module_run_returns_schema_valid_module_result():
    m = DummyModule()
    result = m.run({}, {})
    assert isinstance(result, ModuleResult)
    from research_os.validators.schema_validator import validate_model

    assert validate_model(result) == []


def test_module_validate_output():
    m = DummyModule()
    result = m.run({}, {})
    assert m.validate_output(result).ok is True


def test_validation_result_failure_explicit():
    v = ValidationResult.failure(["缺字段: x"])
    assert v.ok is False
    assert v.errors == ["缺字段: x"]


def test_abstract_methods_cannot_instantiate():
    """抽象接口不可直接实例化（强制实现）。"""
    import pytest

    with pytest.raises(TypeError):
        ResearchModule()  # type: ignore[abstract]
