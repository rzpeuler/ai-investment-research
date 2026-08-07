"""情景预测（Phase 4 任务书 3.17/Commit 12）。

- 默认关闭（include_forecast=false）；仅显式情景；
- 假设来源：company_guidance / external_opinion / user_input /
  deterministic_extrapolation / model_generated；
- claim_type 只允许 SOURCE_OPINION / MODEL_INFERENCE / HYPOTHESIS（不得为 FACT）；
- model_generated 必须有实际模型调用（llm_called=true）；无 Provider 时禁用；
- 不得产生目标价格。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional

from research_os.models.valuation import ForecastAssumption, ForecastOutput, ForecastScenario
from research_os.utils.time import now_iso

FORECAST_RULES_VERSION = "1.0.0"

# claim_type 白名单（非 FACT）
ALLOWED_CLAIM_TYPES = {"SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS"}

# source_type → 默认 claim_type 映射
SOURCE_CLAIM_MAP = {
    "company_guidance": "SOURCE_OPINION",
    "external_opinion": "SOURCE_OPINION",
    "user_input": "HYPOTHESIS",
    "deterministic_extrapolation": "HYPOTHESIS",
    "model_generated": "MODEL_INFERENCE",
}


def _dec(value: Any) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _fmt(d: Optional[Decimal]) -> Optional[str]:
    if d is None:
        return None
    s = format(d, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in ("", "-"):
        s = "0"
    return s


@dataclass
class AssumptionInput:
    """情景假设输入。"""
    driver: str
    value: Any
    unit: str
    period: str
    source_type: str
    source_ref_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    confidence: float = 0.5
    invalidates_when: str = ""


@dataclass
class ScenarioInput:
    """情景输入。"""
    request_id: str
    company_entity_id: str
    name: str
    scenario_type: str
    forecast_start: str
    forecast_end: str
    periods: List[str]
    assumptions: List[AssumptionInput]
    llm_called: bool = False
    model_route: Optional[dict] = None
    sensitivity_axes: List[dict] = field(default_factory=list)


def validate_assumption(ai: AssumptionInput) -> List[str]:
    """假设合法性检查（确定性）。"""
    issues: List[str] = []
    if ai.source_type not in SOURCE_CLAIM_MAP:
        issues.append(f"非法 source_type: {ai.source_type!r}")
    if ai.source_type == "model_generated" and not ai.source_ref_ids:
        issues.append("model_generated 假设必须有 source_ref_ids（模型调用记录）")
    if not (0 <= ai.confidence <= 1):
        issues.append("confidence 必须在 0..1")
    return issues


def build_scenario(si: ScenarioInput) -> ForecastScenario:
    """构造情景对象；model_generated 无调用记录时拒绝（不伪造模型假设）。"""
    warnings: List[str] = []
    assumptions: List[ForecastAssumption] = []
    for ai in si.assumptions:
        issues = validate_assumption(ai)
        if issues:
            warnings.extend(issues)
            continue
        claim_type = SOURCE_CLAIM_MAP[ai.source_type]
        # 无 Provider：model_generated 假设禁用（诚实回退，不得伪造）
        if ai.source_type == "model_generated" and not si.llm_called:
            warnings.append("model_generated 假设未伴随实际模型调用（llm_called=false），已跳过")
            continue
        assumptions.append(ForecastAssumption(
            assumption_id=str(uuid.uuid4()),
            driver=ai.driver,
            value=ai.value,
            unit=ai.unit,
            period=ai.period,
            source_type=ai.source_type,  # type: ignore[arg-type]
            source_ref_ids=ai.source_ref_ids,
            evidence_ids=ai.evidence_ids,
            claim_type=claim_type,  # type: ignore[arg-type]
            confidence=ai.confidence,
            invalidates_when=ai.invalidates_when,
        ))

    status = "valid"
    if warnings:
        status = "partial"
    if not assumptions:
        status = "invalid"

    return ForecastScenario(
        scenario_id=str(uuid.uuid4()),
        request_id=si.request_id,
        company_entity_id=si.company_entity_id,
        name=si.name,
        scenario_type=si.scenario_type,  # type: ignore[arg-type]
        enabled=True,
        forecast_start=si.forecast_start,
        forecast_end=si.forecast_end,
        periods=si.periods,
        assumptions=assumptions,
        outputs=[],
        sensitivity_axes=si.sensitivity_axes,
        confidence=min(1.0, max(0.0, sum(a.confidence for a in assumptions) / max(len(assumptions), 1))),
        status=status,  # type: ignore[arg-type]
        llm_called=si.llm_called,
        model_route=si.model_route,
        warnings=warnings,
        version=1,
        created_at=now_iso(),
    )


def deterministic_projection(
    base_value: str,
    growth_rate: str,
    periods: int,
    unit: str = "yuan",
    metric_code: str = "revenue",
) -> List[ForecastOutput]:
    """确定性外推：value × (1+g)^n；仅正基数（负基数外推无意义）。"""
    d_base, d_g = _dec(base_value), _dec(growth_rate)
    if d_base is None or d_g is None:
        return []
    if d_base <= 0:
        return []
    outputs: List[ForecastOutput] = []
    current = d_base
    for n in range(1, periods + 1):
        current = current * (1 + d_g)
        outputs.append(ForecastOutput(
            metric_code=metric_code,
            period=f"FY{n}",
            value=_fmt(current),
            unit=unit,
            formula_version=FORECAST_RULES_VERSION,
            status="valid",
        ))
    return outputs
