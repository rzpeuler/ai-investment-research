"""财务指标计算服务（Phase 4 任务书 3.12/Commit 6）。

从 FinancialFact 输入构建 FinancialMetric；所有指标确定性计算，输入血缘完整
（input_fact_ids），公式版本进 formula_version；不输出研究结论。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from research_os.financials.formulas import (
    FINANCIAL_NA,
    FORMULA_VERSION,
    METRIC_FUNCTIONS,
    MetricResult,
)
from research_os.models.financials import FinancialMetric
from research_os.utils.time import now_iso


def _value_by_key(facts: List[dict], taxonomy_code: str, period_basis: str = "reported_period") -> Optional[str]:
    """按 taxonomy_code 取事实值（同 code 多版本取第一个非空）。"""
    for f in facts:
        if f.get("taxonomy_code") == taxonomy_code:
            v = f.get("normalized_value") or f.get("raw_value")
            if v is not None:
                return v
    return None


def _fact_ids_by_key(facts: List[dict], taxonomy_code: str) -> List[str]:
    return [f["fact_id"] for f in facts if f.get("taxonomy_code") == taxonomy_code and f.get("fact_id")]


@dataclass(frozen=True)
class MetricRecomputeSpec:
    """指标的可审计复算契约；参数名而非 UUID 顺序定义公式语义。"""
    metric_code: str
    parameter_taxonomy: Tuple[Tuple[str, str], ...]
    unit: str
    precision: int = 8


def _spec(code: str, unit: str, **parameters: str) -> MetricRecomputeSpec:
    return MetricRecomputeSpec(code, tuple(parameters.items()), unit)


# 所有已支持公式都登记；缺失参数、零分母和 N/A 仍由同一公式函数返回确定状态。
METRIC_RECOMPUTE_REGISTRY: Dict[str, MetricRecomputeSpec] = {
    "revenue_growth": _spec("revenue_growth", "ratio", current="revenue", comparable="revenue"),
    "net_profit_growth": _spec("net_profit_growth", "ratio", current="net_profit_attr", comparable="net_profit_attr"),
    "deducted_net_profit_growth": _spec("deducted_net_profit_growth", "ratio", current="deducted_net_profit", comparable="deducted_net_profit"),
    "gross_margin": _spec("gross_margin", "ratio", revenue="revenue", cogs="cost_of_sales"),
    "operating_margin": _spec("operating_margin", "ratio", operating_profit="operating_profit", revenue="revenue"),
    "net_margin": _spec("net_margin", "ratio", attributable_net_profit="net_profit_attr", revenue="revenue"),
    "roe": _spec("roe", "ratio", net_profit_attr="net_profit_attr", equity_start="equity_attr", equity_end="equity_attr"),
    "roa": _spec("roa", "ratio", net_profit="net_profit", assets_start="total_assets", assets_end="total_assets"),
    "roic": _spec("roic", "ratio", ebit="ebit", tax="income_tax_rate", interest_debt="interest_bearing_debt", equity="equity_attr", eligible_cash="cash_and_equivalents"),
    "debt_to_assets": _spec("debt_to_assets", "ratio", total_liabilities="total_liabilities", total_assets="total_assets"),
    "net_debt": _spec("net_debt", "yuan", interest_debt="interest_bearing_debt", eligible_cash="cash_and_equivalents"),
    "current_ratio": _spec("current_ratio", "ratio", current_assets="current_assets", current_liabilities="current_liabilities"),
    "quick_ratio": _spec("quick_ratio", "ratio", current_assets="current_assets", inventory="inventory", other_illiquid="other_illiquid_assets", current_liabilities="current_liabilities"),
    "receivable_turnover": _spec("receivable_turnover", "times", revenue="revenue", receivables_start="accounts_receivable", receivables_end="accounts_receivable"),
    "inventory_turnover": _spec("inventory_turnover", "times", cogs="cost_of_sales", inventory_start="inventory", inventory_end="inventory"),
    "cfo_to_net_profit": _spec("cfo_to_net_profit", "ratio", cfo="operating_cash_flow", net_profit="net_profit_attr"),
    "free_cash_flow": _spec("free_cash_flow", "yuan", cfo="operating_cash_flow", capex="capex_paid"),
    "rd_expense_ratio": _spec("rd_expense_ratio", "ratio", rd="rd_expense", revenue="revenue"),
    "selling_expense_ratio": _spec("selling_expense_ratio", "ratio", expense="selling_expense", revenue="revenue"),
    "admin_expense_ratio": _spec("admin_expense_ratio", "ratio", expense="admin_expense", revenue="revenue"),
    "eps": _spec("eps", "yuan", net_profit_attr="net_profit_attr", weighted_shares="weighted_avg_shares"),
    "bvps": _spec("bvps", "yuan", equity_attr="equity_attr", period_end_shares="period_end_shares"),
    "cfo_per_share": _spec("cfo_per_share", "yuan", cfo="operating_cash_flow", weighted_shares="weighted_avg_shares"),
    "share_change": _spec("share_change", "ratio", end_shares="period_end_shares", start_shares="period_end_shares"),
}


def recompute_from_lineage(metric: dict, facts: List[dict]) -> Optional[MetricResult]:
    """依据 input_fact_ids 和命名 taxonomy 参数复算，不依赖输入 UUID 的排列顺序。"""
    spec = METRIC_RECOMPUTE_REGISTRY.get(metric.get("metric_code"))
    formula = METRIC_FUNCTIONS.get(metric.get("metric_code"))
    if spec is None or formula is None:
        return None
    # 同一 taxonomy 在公式中承担期初/期末或本期/同比期等不同角色时，当前持久化
    # 血缘只保存 ID 列表，尚未保存 parameter→fact 映射，不能靠 UUID 次序猜测。
    # 返回 None 让 Validator 显式警告而非伪造一次“复算”。
    taxonomies = [taxonomy for _, taxonomy in spec.parameter_taxonomy]
    if len(taxonomies) != len(set(taxonomies)):
        return None
    selected = {f.get("fact_id") for f in facts if f.get("fact_id") in set(metric.get("input_fact_ids") or [])}
    values: Dict[str, Optional[str]] = {}
    for parameter, taxonomy in spec.parameter_taxonomy:
        candidates = [f for f in facts if f.get("fact_id") in selected and f.get("taxonomy_code") == taxonomy]
        values[parameter] = _value_by_key(candidates, taxonomy)
    return formula(**values)  # type: ignore[operator]


def compute_metric(
    company_entity_id: str,
    metric_code: str,
    inputs: Dict[str, Optional[str]],
    facts: List[dict],
    period_end: str,
    sector: str = "general",
) -> FinancialMetric:
    """计算单个指标并构造 FinancialMetric 对象。

    inputs: 公式命名参数（revenue/cogs/net_profit_attr/...）。
    facts: 该期间已入库的 FinancialFact dict 列表（用于输入血缘）。
    sector: general / non_financial / financial / cyclical。
    """
    fn = METRIC_FUNCTIONS.get(metric_code)
    if fn is None:
        raise ValueError(f"未知指标: {metric_code}")

    applicable = not (sector == "financial" and metric_code in FINANCIAL_NA)
    if not applicable:
        return FinancialMetric(
            metric_id=str(uuid.uuid4()),
            company_entity_id=company_entity_id,
            metric_code=metric_code,
            period_end=period_end,
            period_basis="annual" if period_end.endswith("12-31") else "interim",
            value=None,
            unit="ratio",
            status="not_applicable",
            formula_id=f"{metric_code}_v1",
            formula_version=FORMULA_VERSION,
            input_fact_ids=[],
            input_metric_ids=[],
            precision=8,
            sector_applicability="financial",
            quality_warnings=["金融企业不适用"],
            evidence_ids=[],
            calculated_at=now_iso(),
            version=1,
        )

    result: MetricResult = fn(**inputs)
    input_fact_ids: List[str] = []
    # 参数名（如 cogs）不等于 taxonomy（cost_of_sales）；血缘必须按注册表恢复。
    spec = METRIC_RECOMPUTE_REGISTRY[metric_code]
    for _, taxonomy_code in spec.parameter_taxonomy:
        input_fact_ids.extend(_fact_ids_by_key(facts, taxonomy_code))
    input_fact_ids = sorted(set(input_fact_ids))
    unit = "ratio" if not metric_code.endswith(("turnover", "eps", "bvps", "cfo_per_share", "net_debt")) else (
        "times" if metric_code.endswith("turnover") else (
            "yuan" if metric_code in ("eps", "bvps", "cfo_per_share", "net_debt") else "ratio"
        )
    )
    return FinancialMetric(
        metric_id=str(uuid.uuid4()),
        company_entity_id=company_entity_id,
        metric_code=metric_code,
        period_end=period_end,
        period_basis="annual" if period_end.endswith("12-31") else "interim",
        value=result.value,
        unit=unit,
        status=result.status,
        formula_id=result.formula_id,
        formula_version=FORMULA_VERSION,
        input_fact_ids=input_fact_ids,
        input_metric_ids=[],
        precision=8,
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
    v = lambda code: _value_by_key(facts, code)  # noqa: E731
    spec: Dict[str, Dict[str, Optional[str]]] = {
        "revenue_growth": {"current": v("revenue"), "comparable": None},  # 由调用方补 comparable
        "net_profit_growth": {"current": v("net_profit_attr"), "comparable": None},
        "gross_margin": {"revenue": v("revenue"), "cogs": v("cost_of_sales")},
        "operating_margin": {"operating_profit": v("operating_profit"), "revenue": v("revenue")},
        "net_margin": {"attributable_net_profit": v("net_profit_attr"), "revenue": v("revenue")},
        "roe": {"net_profit_attr": v("net_profit_attr"), "equity_start": None, "equity_end": v("equity_attr")},
        "roa": {"net_profit": v("net_profit"), "assets_start": None, "assets_end": v("total_assets")},
        "roic": {"ebit": v("ebit"), "tax": None, "interest_debt": None, "equity": v("equity_attr"), "eligible_cash": None},
        "debt_to_assets": {"total_liabilities": v("total_liabilities"), "total_assets": v("total_assets")},
        "net_debt": {"interest_debt": None, "eligible_cash": v("cash_and_equivalents")},
        "current_ratio": {"current_assets": v("current_assets"), "current_liabilities": v("current_liabilities")},
        "quick_ratio": {"current_assets": v("current_assets"), "inventory": v("inventory"),
                        "other_illiquid": None, "current_liabilities": v("current_liabilities")},
        "receivable_turnover": {"revenue": v("revenue"), "receivables_start": None, "receivables_end": v("accounts_receivable")},
        "inventory_turnover": {"cogs": v("cost_of_sales"), "inventory_start": None, "inventory_end": v("inventory")},
        "cfo_to_net_profit": {"cfo": v("operating_cash_flow"), "net_profit": v("net_profit_attr")},
        "free_cash_flow": {"cfo": v("operating_cash_flow"), "capex": v("capex_paid")},
        "rd_expense_ratio": {"rd": v("rd_expense"), "revenue": v("revenue")},
        "selling_expense_ratio": {"expense": v("selling_expense"), "revenue": v("revenue")},
        "admin_expense_ratio": {"expense": v("admin_expense"), "revenue": v("revenue")},
        "eps": {"net_profit_attr": v("net_profit_attr"), "weighted_shares": v("weighted_avg_shares")},
        "bvps": {"equity_attr": v("equity_attr"), "period_end_shares": v("period_end_shares")},
        "cfo_per_share": {"cfo": v("operating_cash_flow"), "weighted_shares": v("weighted_avg_shares")},
        "share_change": {"end_shares": v("period_end_shares"), "start_shares": None},
    }
    metrics: List[FinancialMetric] = []
    for code, inputs in spec.items():
        metrics.append(compute_metric(company_entity_id, code, inputs, facts, period_end, sector))
    return metrics
