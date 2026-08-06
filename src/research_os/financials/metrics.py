"""财务指标计算服务（Phase 4 任务书 3.12/Commit 6）。

从 FinancialFact 输入构建 FinancialMetric；所有指标确定性计算，输入血缘完整
（input_fact_ids），公式版本进 formula_version；不输出研究结论。
"""
from __future__ import annotations

import uuid
from typing import Dict, List, Optional

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
    for code in inputs:
        input_fact_ids.extend(_fact_ids_by_key(facts, code))
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
