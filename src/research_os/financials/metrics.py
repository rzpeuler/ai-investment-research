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
from research_os.utils.decimal import normalize_decimal_string
from research_os.utils.time import now_iso


@dataclass(frozen=True)
class MetricParameterSpec:
    name: str
    taxonomy_code: str
    period_role: str
    required: bool = True
    allowed_statement_types: Tuple[str, ...] = ()


@dataclass(frozen=True)
class MetricFormulaSpec:
    """生成器和 Validator 共用的唯一公式契约。"""
    metric_code: str
    formula: Callable[..., MetricResult]
    parameters: Tuple[MetricParameterSpec, ...]
    unit: str
    precision: int
    rounding_mode: Optional[str]
    formula_id: str
    formula_version: str
    zero_denominator_rule: str
    not_applicable_sectors: Tuple[str, ...] = ()


_TAXONOMY_STATEMENT_TYPES: Dict[str, Tuple[str, ...]] = {
    "revenue": ("income_statement",),
    "net_profit_attr": ("income_statement",),
    "deducted_net_profit": ("income_statement",),
    "cost_of_sales": ("income_statement",),
    "operating_profit": ("income_statement",),
    "net_profit": ("income_statement",),
    "ebit": ("income_statement",),
    "income_tax_rate": ("income_statement", "note", "operating_data"),
    "rd_expense": ("income_statement",),
    "selling_expense": ("income_statement",),
    "admin_expense": ("income_statement",),
    "equity_attr": ("balance_sheet",),
    "total_assets": ("balance_sheet",),
    "total_liabilities": ("balance_sheet",),
    "current_assets": ("balance_sheet",),
    "current_liabilities": ("balance_sheet",),
    "inventory": ("balance_sheet",),
    "accounts_receivable": ("balance_sheet",),
    "interest_bearing_debt": ("balance_sheet", "note"),
    "cash_and_equivalents": ("balance_sheet", "note"),
    "other_illiquid_assets": ("balance_sheet", "note"),
    "operating_cash_flow": ("cash_flow",),
    "capex_paid": ("cash_flow",),
    "weighted_avg_shares": ("income_statement", "equity_statement", "note", "operating_data"),
    "period_end_shares": ("balance_sheet", "equity_statement", "note", "operating_data"),
}


def _parameter(name: str, taxonomy: str, role: str = "current", required: bool = True) -> MetricParameterSpec:
    allowed = _TAXONOMY_STATEMENT_TYPES.get(taxonomy)
    if not allowed:
        raise ValueError(f"指标参数缺 statement_type 契约: {taxonomy}")
    return MetricParameterSpec(name, taxonomy, role, required, allowed)


def _spec(code: str, unit: str, *parameters: MetricParameterSpec,
          zero_rule: str = "formula_defined", na_sectors: Tuple[str, ...] = ()) -> MetricFormulaSpec:
    return MetricFormulaSpec(code, METRIC_FUNCTIONS[code], parameters, unit, 8, None,
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
METRIC_BINDING_IDENTITY_FIELDS = (
    "company_entity_id", "financial_report_id", "taxonomy_code", "statement_scope",
    "statement_type", "period_start", "period_end", "currency", "unit_scale",
)


def _fact_value(fact: dict) -> Optional[str]:
    value = fact.get("normalized_value")
    return value if value is not None else fact.get("raw_value")


def normalize_metric_decimal(value: object, precision: int, rounding_mode: Optional[str]) -> str:
    """Return the canonical persisted value; precision is never an error tolerance."""
    return normalize_decimal_string(value, precision=precision, rounding_mode=rounding_mode)


def fact_selection_key(fact: dict, reports_by_id: Optional[Dict[str, dict]] = None) -> tuple:
    """Shared current-version priority used by generation and validation."""
    report = (reports_by_id or {}).get(fact.get("financial_report_id"), {})
    restate_rank = {"restated": 0, "superseded": 1, "original": 2}
    return (restate_rank.get(report.get("restatement_status", "original"), 3),
            int(fact.get("source_priority", 6)), -int(fact.get("restatement_version", 1)),
            str(fact.get("fact_id") or ""))


def build_metric_input_binding(parameter: MetricParameterSpec, fact: dict) -> FinancialMetricInputBinding:
    """Single binding constructor paired with the Validator identity contract below."""
    return FinancialMetricInputBinding(
        parameter=parameter.name, fact_id=str(fact.get("fact_id")),
        company_entity_id=fact.get("company_entity_id"),
        financial_report_id=fact.get("financial_report_id"),
        taxonomy_code=parameter.taxonomy_code,
        statement_scope=fact.get("statement_scope"),
        statement_type=fact.get("statement_type"),
        period_start=fact.get("period_start"), period_end=fact.get("period_end"),
        period_role=parameter.period_role,
        currency=fact.get("currency"), unit_scale=fact.get("unit_scale"),
    )


def _select_fact(facts: List[dict], parameter: MetricParameterSpec, period_end: str,
                 company_entity_id: Optional[str] = None,
                 reports: Optional[List[dict]] = None) -> Optional[dict]:
    candidates = [
        f for f in facts
        if f.get("taxonomy_code") == parameter.taxonomy_code
        and f.get("statement_type") in parameter.allowed_statement_types
        and _fact_value(f) is not None
    ]
    if company_entity_id:
        candidates = [f for f in candidates if f.get("company_entity_id") == company_entity_id]
    if parameter.period_role in ("current", "end"):
        exact = [f for f in candidates if f.get("period_end") == period_end]
        undated = [f for f in candidates if not f.get("period_end")]
        candidates = exact or undated
    else:
        candidates = [f for f in candidates if f.get("period_end") and f.get("period_end") < period_end]
        if candidates:
            latest = max(f.get("period_end") for f in candidates)
            candidates = [f for f in candidates if f.get("period_end") == latest]
    reports_by_id = {r.get("financial_report_id"): r for r in (reports or [])}
    return sorted(candidates, key=lambda f: fact_selection_key(f, reports_by_id))[0] if candidates else None


def resolve_metric_inputs(metric_code: str, facts: List[dict], period_end: str,
                          company_entity_id: str,
                          reports: Optional[List[dict]] = None) -> tuple[Dict[str, Optional[str]], List[FinancialMetricInputBinding]]:
    spec = METRIC_FORMULA_REGISTRY[metric_code]
    values: Dict[str, Optional[str]] = {}
    bindings: List[FinancialMetricInputBinding] = []
    for parameter in spec.parameters:
        fact = _select_fact(facts, parameter, period_end, company_entity_id, reports)
        values[parameter.name] = _fact_value(fact) if fact else None
        if fact:
            bindings.append(build_metric_input_binding(parameter, fact))
    return values, bindings


def recompute_from_lineage(metric: dict, facts: List[dict], reports: Optional[List[dict]] = None) -> tuple[Optional[MetricResult], List[str]]:
    """严格验证参数级绑定并复算；任何歧义都返回错误，绝不猜测。"""
    spec = METRIC_FORMULA_REGISTRY.get(metric.get("metric_code"))
    if spec is None:
        return None, [f"未登记的指标公式: {metric.get('metric_code')}"]
    errors: List[str] = []
    facts_by_id = {f.get("fact_id"): f for f in facts if f.get("fact_id")}
    reports_by_id = {r.get("financial_report_id"): r for r in (reports or []) if r.get("financial_report_id")}
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
        for field in METRIC_BINDING_IDENTITY_FIELDS:
            if binding.get(field) != fact.get(field):
                errors.append(f"参数 {parameter.name} 绑定身份字段 {field} 与事实不一致")
        if binding.get("taxonomy_code") != parameter.taxonomy_code or fact.get("taxonomy_code") != parameter.taxonomy_code:
            errors.append(f"参数 {parameter.name} taxonomy 错配")
        if fact.get("statement_type") not in parameter.allowed_statement_types:
            errors.append(
                f"参数 {parameter.name} statement_type 不符合公式契约: "
                f"{fact.get('statement_type')!r} not in {parameter.allowed_statement_types}"
            )
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
        preferred = _select_fact(facts, parameter, metric.get("period_end", ""),
                                 metric.get("company_entity_id"), reports)
        if preferred and preferred.get("fact_id") != fact.get("fact_id"):
            errors.append(f"参数 {parameter.name} 未绑定当前优先事实版本")
        report = reports_by_id.get(fact.get("financial_report_id"))
        if report is None:
            errors.append(f"参数 {parameter.name} 引用的财务报告不存在")
        else:
            for field in ("company_entity_id", "statement_scope", "currency", "unit_scale", "period_end"):
                if report.get(field) != fact.get(field):
                    errors.append(f"参数 {parameter.name} 的事实与报告字段 {field} 不一致")
            if fact.get("period_start") is not None and report.get("period_start") != fact.get("period_start"):
                errors.append(f"参数 {parameter.name} 的事实与报告期间起点不一致")
        values[parameter.name] = _fact_value(fact)
    binding_ids = {b.get("fact_id") for b in raw_bindings}
    if binding_ids != set(metric.get("input_fact_ids") or []):
        errors.append("input_fact_ids 与参数绑定不一致")
    bound_facts = [facts_by_id.get(b.get("fact_id")) for b in raw_bindings]
    bound_facts = [f for f in bound_facts if f]
    for field in ("company_entity_id", "statement_scope", "currency", "unit_scale"):
        values_for_field = {f.get(field) for f in bound_facts}
        if len(values_for_field) > 1:
            errors.append(f"公式输入事实的 {field} 口径混用")
    if any(f.get("company_entity_id") != metric.get("company_entity_id") for f in bound_facts):
        errors.append("指标公司与输入事实公司不一致")
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
    reports: Optional[List[dict]] = None,
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

    resolved_inputs, bindings = resolve_metric_inputs(metric_code, facts, period_end, company_entity_id, reports)
    result: MetricResult = spec.formula(**resolved_inputs)
    value = normalize_metric_decimal(result.value, spec.precision, spec.rounding_mode) if result.value is not None else None
    input_fact_ids = sorted({binding.fact_id for binding in bindings})
    return FinancialMetric(
        metric_id=str(uuid.uuid4()),
        company_entity_id=company_entity_id,
        metric_code=metric_code,
        period_end=period_end,
        period_basis="annual" if period_end.endswith("12-31") else "interim",
        value=value,
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
    reports: Optional[List[dict]] = None,
) -> List[FinancialMetric]:
    """计算一个期间的全部核心指标（输入不足的指标返回 missing 状态而非跳过）。"""
    metrics: List[FinancialMetric] = []
    for code in METRIC_FORMULA_REGISTRY:
        metrics.append(compute_metric(company_entity_id, code, {}, facts, period_end, sector, reports))
    return metrics
