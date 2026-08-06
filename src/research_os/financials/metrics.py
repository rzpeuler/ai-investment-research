"""财务指标计算服务（Phase 4 任务书 3.12/Commit 6）。

从 FinancialFact 输入构建 FinancialMetric；所有指标确定性计算，输入血缘完整
（input_fact_ids），公式版本进 formula_version；不输出研究结论。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from research_os.financials.formulas import (
    FORMULA_VERSION,
    METRIC_FUNCTIONS,
    MetricResult,
)
from research_os.models.financials import FinancialMetric, FinancialMetricInputBinding
from research_os.utils.time import now_iso


@dataclass(frozen=True)
class MetricParameterSpec:
    name: str
    taxonomy_code: str
    period_role: str
    required: bool = True


@dataclass(frozen=True)
class MetricFormulaSpec:
    """生成器和 Validator 共用的唯一公式契约。"""
    metric_code: str
    formula: Callable[..., MetricResult]
    parameters: Tuple[MetricParameterSpec, ...]
    unit: str
    precision: int
    formula_id: str
    formula_version: str
    zero_denominator_rule: str
    not_applicable_sectors: Tuple[str, ...] = ()


def _parameter(name: str, taxonomy: str, role: str = "current", required: bool = True) -> MetricParameterSpec:
    return MetricParameterSpec(name, taxonomy, role, required)


def _spec(code: str, unit: str, *parameters: MetricParameterSpec,
          zero_rule: str = "formula_defined", na_sectors: Tuple[str, ...] = ()) -> MetricFormulaSpec:
    return MetricFormulaSpec(code, METRIC_FUNCTIONS[code], parameters, unit, 8,
                             f"{code}_v1", FORMULA_VERSION, zero_rule, na_sectors)


_FINANCIAL_NA = ("financial",)
METRIC_FORMULA_REGISTRY: Dict[str, MetricFormulaSpec] = {
    "revenue_growth": _spec("revenue_growth", "ratio", _parameter("current", "revenue"), _parameter("comparable", "revenue", "comparable"), zero_rule="comparable_zero"),
    "net_profit_growth": _spec("net_profit_growth", "ratio", _parameter("current", "net_profit_attr"), _parameter("comparable", "net_profit_attr", "comparable"), zero_rule="comparable_zero"),
    "deducted_net_profit_growth": _spec("deducted_net_profit_growth", "ratio", _parameter("current", "deducted_net_profit"), _parameter("comparable", "deducted_net_profit", "comparable"), zero_rule="comparable_zero"),
    "gross_margin": _spec("gross_margin", "ratio", _parameter("revenue", "revenue"), _parameter("cogs", "cost_of_sales"), zero_rule="revenue_zero", na_sectors=_FINANCIAL_NA),
    "operating_margin": _spec("operating_margin", "ratio", _parameter("operating_profit", "operating_profit"), _parameter("revenue", "revenue"), zero_rule="revenue_zero", na_sectors=_FINANCIAL_NA),
    "net_margin": _spec("net_margin", "ratio", _parameter("attributable_net_profit", "net_profit_attr"), _parameter("revenue", "revenue"), zero_rule="revenue_zero"),
    "roe": _spec("roe", "ratio", _parameter("net_profit_attr", "net_profit_attr"), _parameter("equity_start", "equity_attr", "start"), _parameter("equity_end", "equity_attr", "end"), zero_rule="average_equity_zero"),
    "roa": _spec("roa", "ratio", _parameter("net_profit", "net_profit"), _parameter("assets_start", "total_assets", "start"), _parameter("assets_end", "total_assets", "end"), zero_rule="average_assets_zero"),
    "roic": _spec("roic", "ratio", _parameter("ebit", "ebit"), _parameter("tax", "income_tax_rate"), _parameter("interest_debt", "interest_bearing_debt"), _parameter("equity", "equity_attr"), _parameter("eligible_cash", "cash_and_equivalents"), zero_rule="invested_capital_zero", na_sectors=_FINANCIAL_NA),
    "debt_to_assets": _spec("debt_to_assets", "ratio", _parameter("total_liabilities", "total_liabilities"), _parameter("total_assets", "total_assets"), zero_rule="assets_zero"),
    "net_debt": _spec("net_debt", "yuan", _parameter("interest_debt", "interest_bearing_debt"), _parameter("eligible_cash", "cash_and_equivalents"), zero_rule="not_applicable"),
    "current_ratio": _spec("current_ratio", "ratio", _parameter("current_assets", "current_assets"), _parameter("current_liabilities", "current_liabilities"), zero_rule="current_liabilities_zero", na_sectors=_FINANCIAL_NA),
    "quick_ratio": _spec("quick_ratio", "ratio", _parameter("current_assets", "current_assets"), _parameter("inventory", "inventory", required=False), _parameter("other_illiquid", "other_illiquid_assets", required=False), _parameter("current_liabilities", "current_liabilities"), zero_rule="current_liabilities_zero", na_sectors=_FINANCIAL_NA),
    "receivable_turnover": _spec("receivable_turnover", "times", _parameter("revenue", "revenue"), _parameter("receivables_start", "accounts_receivable", "start"), _parameter("receivables_end", "accounts_receivable", "end"), zero_rule="average_receivables_zero", na_sectors=_FINANCIAL_NA),
    "inventory_turnover": _spec("inventory_turnover", "times", _parameter("cogs", "cost_of_sales"), _parameter("inventory_start", "inventory", "start"), _parameter("inventory_end", "inventory", "end"), zero_rule="average_inventory_zero", na_sectors=_FINANCIAL_NA),
    "cfo_to_net_profit": _spec("cfo_to_net_profit", "ratio", _parameter("cfo", "operating_cash_flow"), _parameter("net_profit", "net_profit_attr"), zero_rule="net_profit_zero"),
    "free_cash_flow": _spec("free_cash_flow", "yuan", _parameter("cfo", "operating_cash_flow"), _parameter("capex", "capex_paid"), zero_rule="not_applicable"),
    "rd_expense_ratio": _spec("rd_expense_ratio", "ratio", _parameter("rd", "rd_expense"), _parameter("revenue", "revenue"), zero_rule="revenue_zero", na_sectors=_FINANCIAL_NA),
    "selling_expense_ratio": _spec("selling_expense_ratio", "ratio", _parameter("expense", "selling_expense"), _parameter("revenue", "revenue"), zero_rule="revenue_zero", na_sectors=_FINANCIAL_NA),
    "admin_expense_ratio": _spec("admin_expense_ratio", "ratio", _parameter("expense", "admin_expense"), _parameter("revenue", "revenue"), zero_rule="revenue_zero", na_sectors=_FINANCIAL_NA),
    "eps": _spec("eps", "yuan", _parameter("net_profit_attr", "net_profit_attr"), _parameter("weighted_shares", "weighted_avg_shares"), zero_rule="shares_zero"),
    "bvps": _spec("bvps", "yuan", _parameter("equity_attr", "equity_attr"), _parameter("period_end_shares", "period_end_shares"), zero_rule="shares_zero"),
    "cfo_per_share": _spec("cfo_per_share", "yuan", _parameter("cfo", "operating_cash_flow"), _parameter("weighted_shares", "weighted_avg_shares"), zero_rule="shares_zero"),
    "share_change": _spec("share_change", "ratio", _parameter("end_shares", "period_end_shares", "end"), _parameter("start_shares", "period_end_shares", "start"), zero_rule="start_shares_zero"),
}
# Backwards-compatible public name; both generation and validation use the rich registry above.
METRIC_RECOMPUTE_REGISTRY = METRIC_FORMULA_REGISTRY


def _fact_value(fact: dict) -> Optional[str]:
    value = fact.get("normalized_value")
    return value if value is not None else fact.get("raw_value")


def _select_fact(facts: List[dict], parameter: MetricParameterSpec, period_end: str) -> Optional[dict]:
    candidates = [f for f in facts if f.get("taxonomy_code") == parameter.taxonomy_code and _fact_value(f) is not None]
    if parameter.period_role in ("current", "end"):
        exact = [f for f in candidates if f.get("period_end") == period_end]
        undated = [f for f in candidates if not f.get("period_end")]
        candidates = exact or undated
    else:
        candidates = [f for f in candidates if f.get("period_end") and f.get("period_end") < period_end]
        if candidates:
            latest = max(f.get("period_end") for f in candidates)
            candidates = [f for f in candidates if f.get("period_end") == latest]
    return sorted(candidates, key=lambda f: str(f.get("fact_id") or ""))[0] if candidates else None


def resolve_metric_inputs(metric_code: str, facts: List[dict], period_end: str) -> tuple[Dict[str, Optional[str]], List[FinancialMetricInputBinding]]:
    spec = METRIC_FORMULA_REGISTRY[metric_code]
    values: Dict[str, Optional[str]] = {}
    bindings: List[FinancialMetricInputBinding] = []
    for parameter in spec.parameters:
        fact = _select_fact(facts, parameter, period_end)
        values[parameter.name] = _fact_value(fact) if fact else None
        if fact:
            bindings.append(FinancialMetricInputBinding(
                parameter=parameter.name, fact_id=str(fact.get("fact_id")),
                taxonomy_code=parameter.taxonomy_code,
                period_end=fact.get("period_end") or period_end,
                period_role=parameter.period_role,
            ))
    return values, bindings


def recompute_from_lineage(metric: dict, facts: List[dict]) -> tuple[Optional[MetricResult], List[str]]:
    """严格验证参数级绑定并复算；任何歧义都返回错误，绝不猜测。"""
    spec = METRIC_FORMULA_REGISTRY.get(metric.get("metric_code"))
    if spec is None:
        return None, [f"未登记的指标公式: {metric.get('metric_code')}"]
    errors: List[str] = []
    facts_by_id = {f.get("fact_id"): f for f in facts if f.get("fact_id")}
    raw_bindings = metric.get("input_bindings") or []
    by_parameter: Dict[str, dict] = {}
    for binding in raw_bindings:
        parameter = binding.get("parameter")
        if parameter in by_parameter:
            errors.append(f"参数绑定重复: {parameter}")
        else:
            by_parameter[parameter] = binding
    expected_names = {p.name for p in spec.parameters}
    if set(by_parameter) - expected_names:
        errors.append("存在公式未定义的参数绑定")
    values: Dict[str, Optional[str]] = {}
    for parameter in spec.parameters:
        binding = by_parameter.get(parameter.name)
        if not binding:
            values[parameter.name] = None
            if parameter.required:
                errors.append(f"缺少参数绑定: {parameter.name}")
            continue
        fact = facts_by_id.get(binding.get("fact_id"))
        if not fact:
            errors.append(f"参数 {parameter.name} 引用不存在事实")
            values[parameter.name] = None
            continue
        if binding.get("taxonomy_code") != parameter.taxonomy_code or fact.get("taxonomy_code") != parameter.taxonomy_code:
            errors.append(f"参数 {parameter.name} taxonomy 错配")
        if binding.get("period_role") != parameter.period_role:
            errors.append(f"参数 {parameter.name} 期间角色错配")
        if binding.get("period_end") != fact.get("period_end"):
            errors.append(f"参数 {parameter.name} 绑定期间与事实不一致")
        fact_period = fact.get("period_end")
        if parameter.period_role in ("current", "end") and fact_period != metric.get("period_end"):
            errors.append(f"参数 {parameter.name} 应绑定当前/期末期间")
        if parameter.period_role in ("start", "comparable") and (not fact_period or fact_period >= metric.get("period_end", "")):
            errors.append(f"参数 {parameter.name} 应绑定更早期间")
        if parameter.period_role in ("start", "comparable") and fact_period:
            prior_periods = [f.get("period_end") for f in facts
                             if f.get("taxonomy_code") == parameter.taxonomy_code
                             and f.get("period_end") and f.get("period_end") < metric.get("period_end", "")]
            if prior_periods and fact_period != max(prior_periods):
                errors.append(f"参数 {parameter.name} 未绑定最近可比期间")
        values[parameter.name] = _fact_value(fact)
    binding_ids = {b.get("fact_id") for b in raw_bindings}
    if binding_ids != set(metric.get("input_fact_ids") or []):
        errors.append("input_fact_ids 与参数绑定不一致")
    if errors:
        return None, errors
    return spec.formula(**values), []


def compute_metric(
    company_entity_id: str,
    metric_code: str,
    inputs: Dict[str, Optional[str]],
    facts: List[dict],
    period_end: str,
    sector: str = "general",
) -> FinancialMetric:
    """计算单个指标并构造 FinancialMetric 对象。

    inputs: 兼容旧调用签名；正式数值不信任该 dict，而从 facts 的参数级绑定读取。
    facts: 当前及可比期间 FinancialFact dict（用于数值和输入血缘）。
    sector: general / non_financial / financial / cyclical。
    """
    spec = METRIC_FORMULA_REGISTRY.get(metric_code)
    if spec is None:
        raise ValueError(f"未知指标: {metric_code}")

    applicable = sector not in spec.not_applicable_sectors
    if not applicable:
        return FinancialMetric(
            metric_id=str(uuid.uuid4()),
            company_entity_id=company_entity_id,
            metric_code=metric_code,
            period_end=period_end,
            period_basis="annual" if period_end.endswith("12-31") else "interim",
            value=None,
            unit=spec.unit,
            status="not_applicable",
            formula_id=spec.formula_id,
            formula_version=spec.formula_version,
            input_fact_ids=[],
            input_bindings=[],
            input_metric_ids=[],
            precision=spec.precision,
            sector_applicability="financial",
            quality_warnings=["金融企业不适用"],
            evidence_ids=[],
            calculated_at=now_iso(),
            version=1,
        )

    resolved_inputs, bindings = resolve_metric_inputs(metric_code, facts, period_end)
    result: MetricResult = spec.formula(**resolved_inputs)
    input_fact_ids = sorted({binding.fact_id for binding in bindings})
    return FinancialMetric(
        metric_id=str(uuid.uuid4()),
        company_entity_id=company_entity_id,
        metric_code=metric_code,
        period_end=period_end,
        period_basis="annual" if period_end.endswith("12-31") else "interim",
        value=result.value,
        unit=spec.unit,
        status=result.status,
        formula_id=spec.formula_id,
        formula_version=spec.formula_version,
        input_fact_ids=input_fact_ids,
        input_bindings=bindings,
        input_metric_ids=[],
        precision=spec.precision,
        sector_applicability=sector,
        quality_warnings=result.warnings,
        evidence_ids=[],
        calculated_at=now_iso(),
        version=1,
    )


def compute_period_metrics(
    company_entity_id: str,
    facts: List[dict],
    period_end: str,
    sector: str = "general",
) -> List[FinancialMetric]:
    """计算一个期间的全部核心指标（输入不足的指标返回 missing 状态而非跳过）。"""
    metrics: List[FinancialMetric] = []
    for code in METRIC_FORMULA_REGISTRY:
        metrics.append(compute_metric(company_entity_id, code, {}, facts, period_end, sector))
    return metrics
