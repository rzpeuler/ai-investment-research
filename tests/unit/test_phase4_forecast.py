"""情景预测测试（任务书 3.25 预测节，Commit 12）。

覆盖：默认关闭（include_forecast=false 语义由 CLI 处理，此处验证对象）；仅显式情景；
假设来源；预测期间；驱动；敏感性；置信度；失效条件；预测不是 FACT（claim_type 白名单）；
model_generated 必须有实际模型调用；无 Provider 不伪造模型假设；不产生目标价格。
"""
from __future__ import annotations

import pytest

from research_os.equity_research.forecast import (
    ALLOWED_CLAIM_TYPES,
    AssumptionInput,
    ScenarioInput,
    build_scenario,
    deterministic_projection,
    validate_assumption,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"


def _assumption(**overrides) -> AssumptionInput:
    base = dict(
        driver="收入增速", value="0.1", unit="ratio", period="2026FY",
        source_type="user_input", source_ref_ids=[], evidence_ids=[],
        confidence=0.6, invalidates_when="增速低于 0",
    )
    base.update(overrides)
    return AssumptionInput(**base)


def _scenario(**overrides) -> ScenarioInput:
    base = dict(
        request_id="req-1", company_entity_id=COMPANY, name="用户悲观假设",
        scenario_type="user_assumption", forecast_start="2026-01-01",
        forecast_end="2026-12-31", periods=["2026FY"],
        assumptions=[_assumption()], llm_called=False, model_route=None,
        sensitivity_axes=[{"axis": "收入增速", "range": [-0.1, 0.2]}],
    )
    base.update(overrides)
    return ScenarioInput(**base)


class TestAssumptionValidation:
    def test_valid_assumption(self):
        assert validate_assumption(_assumption()) == []

    def test_illegal_source_type(self):
        issues = validate_assumption(_assumption(source_type="guessed"))
        assert issues

    def test_model_generated_requires_refs(self):
        issues = validate_assumption(_assumption(source_type="model_generated"))
        assert any("source_ref_ids" in i for i in issues)

    def test_confidence_range(self):
        assert validate_assumption(_assumption(confidence=1.5))


class TestScenarioBuild:
    def test_user_input_hypothesis(self):
        s = build_scenario(_scenario())
        assert s.status == "valid"
        assert s.assumptions[0].claim_type == "HYPOTHESIS"
        assert validate_model(s) == []

    def test_company_guidance_source_opinion(self):
        s = build_scenario(_scenario(assumptions=[
            _assumption(source_type="company_guidance", source_ref_ids=["doc-1"]),
        ]))
        assert s.assumptions[0].claim_type == "SOURCE_OPINION"

    def test_claim_type_never_fact(self):
        """预测假设不得为 FACT。"""
        s = build_scenario(_scenario())
        for a in s.assumptions:
            assert a.claim_type in ALLOWED_CLAIM_TYPES
            assert a.claim_type != "FACT"

    def test_model_generated_without_call_skipped(self):
        """无 Provider/无调用：model_generated 假设被跳过，不伪造模型假设。"""
        s = build_scenario(_scenario(
            assumptions=[_assumption(source_type="model_generated", source_ref_ids=["llm-1"])],
            llm_called=False,
        ))
        assert s.assumptions == []
        assert s.status == "invalid"
        assert any("未伴随实际模型调用" in w for w in s.warnings)

    def test_model_generated_with_call_kept(self):
        s = build_scenario(_scenario(
            assumptions=[_assumption(source_type="model_generated", source_ref_ids=["llm-1"])],
            llm_called=True, model_route={"mode": "flash", "llm_called": True},
        ))
        assert len(s.assumptions) == 1
        assert s.assumptions[0].claim_type == "MODEL_INFERENCE"

    def test_invalidation_conditions_preserved(self):
        s = build_scenario(_scenario())
        assert s.assumptions[0].invalidates_when == "增速低于 0"

    def test_confidence_aggregated(self):
        s = build_scenario(_scenario())
        assert 0 <= s.confidence <= 1

    def test_sensitivity_axes_preserved(self):
        s = build_scenario(_scenario())
        assert s.sensitivity_axes == [{"axis": "收入增速", "range": [-0.1, 0.2]}]

    def test_partial_when_some_assumptions_invalid(self):
        s = build_scenario(_scenario(assumptions=[
            _assumption(),
            _assumption(driver="坏假设", source_type="bogus"),
        ]))
        assert s.status == "partial"


class TestDeterministicProjection:
    def test_projection_compounds(self):
        out = deterministic_projection("100", "0.1", 3)
        assert [o.value for o in out] == ["110", "121", "133.1"]

    def test_negative_base_no_projection(self):
        assert deterministic_projection("-100", "0.1", 3) == []

    def test_zero_base_no_projection(self):
        assert deterministic_projection("0", "0.1", 3) == []

    def test_outputs_formula_version(self):
        out = deterministic_projection("100", "0.05", 2)
        for o in out:
            assert o.formula_version


class TestNoTargetPrice:
    def test_scenario_has_no_target_price(self):
        s = build_scenario(_scenario())
        # 对象无目标价字段（结构检查）
        fields = type(s).model_fields.keys()
        for forbidden in ("target_price", "fair_value"):
            assert forbidden not in fields
