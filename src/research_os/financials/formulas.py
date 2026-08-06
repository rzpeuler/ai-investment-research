"""财务指标公式（Phase 4 任务书 3.12/Commit 6）。

所有指标为确定性公式，使用 Decimal，不得调用 LLM；分母为零/缺失/不适用显式标记。
比率内部至少 8 位小数；渲染四舍五入不得回写结构化对象。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional

from research_os.financials.periods import yoy

FORMULA_VERSION = "1.0.0"


def _dec(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(value)
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
class MetricResult:
    metric_code: str
    value: Optional[str]
    status: str  # valid / missing / not_applicable / zero_denominator / conflict / insufficient_sample
    formula_id: str
    warnings: List[str] = field(default_factory=list)


def _ratio(numerator: Optional[str], denominator: Optional[str], code: str) -> MetricResult:
    dn, dd = _dec(numerator), _dec(denominator)
    if dn is None or dd is None:
        return MetricResult(code, None, "missing", f"{code}_v1", ["输入缺失"])
    if dd == 0:
        return MetricResult(code, None, "zero_denominator", f"{code}_v1", ["分母为零"])
    return MetricResult(code, _fmt(dn / dd), "valid", f"{code}_v1")


def _growth(current: Optional[str], comparable: Optional[str], code: str) -> MetricResult:
    r = yoy(current, comparable)
    return MetricResult(code, r.value, r.status, f"{code}_v1", r.warnings)


# ---------- 增长类 ----------

def revenue_growth(current: Optional[str], comparable: Optional[str]) -> MetricResult:
    return _growth(current, comparable, "revenue_growth")


def net_profit_growth(current: Optional[str], comparable: Optional[str]) -> MetricResult:
    return _growth(current, comparable, "net_profit_growth")


def deducted_net_profit_growth(current: Optional[str], comparable: Optional[str]) -> MetricResult:
    return _growth(current, comparable, "deducted_net_profit_growth")


# ---------- 利润率类 ----------

def gross_margin(revenue: Optional[str], cogs: Optional[str]) -> MetricResult:
    """(Revenue−COGS)/Revenue；金融企业通常 N/A（由适用性层处理）。"""
    dr, dc = _dec(revenue), _dec(cogs)
    if dr is None or dc is None:
        return MetricResult("gross_margin", None, "missing", "gross_margin_v1", ["输入缺失"])
    if dr == 0:
        return MetricResult("gross_margin", None, "zero_denominator", "gross_margin_v1", ["收入为零"])
    return MetricResult("gross_margin", _fmt((dr - dc) / dr), "valid", "gross_margin_v1")


def operating_margin(operating_profit: Optional[str], revenue: Optional[str]) -> MetricResult:
    return _ratio(operating_profit, revenue, "operating_margin")


def net_margin(attributable_net_profit: Optional[str], revenue: Optional[str]) -> MetricResult:
    return _ratio(attributable_net_profit, revenue, "net_margin")


# ---------- 回报类 ----------

def _average(a: Optional[str], b: Optional[str]) -> Optional[Decimal]:
    da, db = _dec(a), _dec(b)
    if da is None or db is None:
        return None
    return (da + db) / 2


def roe(net_profit_attr: Optional[str], equity_start: Optional[str], equity_end: Optional[str]) -> MetricResult:
    avg = _average(equity_start, equity_end)
    if avg is None:
        return MetricResult("roe", None, "missing", "roe_v1", ["净资产期初期末缺失"])
    if avg == 0:
        return MetricResult("roe", None, "zero_denominator", "roe_v1", ["平均净资产为零"])
    dn = _dec(net_profit_attr)
    if dn is None:
        return MetricResult("roe", None, "missing", "roe_v1", ["归母净利润缺失"])
    return MetricResult("roe", _fmt(dn / avg), "valid", "roe_v1")


def roa(net_profit: Optional[str], assets_start: Optional[str], assets_end: Optional[str]) -> MetricResult:
    avg = _average(assets_start, assets_end)
    if avg is None or _dec(net_profit) is None:
        return MetricResult("roa", None, "missing", "roa_v1", ["输入缺失"])
    if avg == 0:
        return MetricResult("roa", None, "zero_denominator", "roa_v1", ["平均资产为零"])
    return MetricResult("roa", _fmt(_dec(net_profit) / avg), "valid", "roa_v1")


def roic(ebit: Optional[str], tax: Optional[str], interest_debt: Optional[str],
         equity: Optional[str], eligible_cash: Optional[str]) -> MetricResult:
    """NOPAT / AverageInvestedCapital；缺任一核心输入 → missing；银行/证券/保险 N/A（适用性层）。"""
    d_ebit, d_tax, d_debt, d_equity, d_cash = map(_dec, (ebit, tax, interest_debt, equity, eligible_cash))
    if any(d is None for d in (d_ebit, d_tax, d_debt, d_equity, d_cash)):
        return MetricResult("roic", None, "missing", "roic_v1", ["缺核心输入，不得伪造"])
    nopat = d_ebit * (1 - d_tax)
    invested = d_debt + d_equity - d_cash
    if invested == 0:
        return MetricResult("roic", None, "zero_denominator", "roic_v1", ["投入资本为零"])
    return MetricResult("roic", _fmt(nopat / invested), "valid", "roic_v1")


# ---------- 资产负债类 ----------

def debt_to_assets(total_liabilities: Optional[str], total_assets: Optional[str]) -> MetricResult:
    return _ratio(total_liabilities, total_assets, "debt_to_assets")


def net_debt(interest_debt: Optional[str], eligible_cash: Optional[str]) -> MetricResult:
    """净负债 = 有息负债 − 可扣除现金（受限资金排除，由调用方传入 eligible_cash）。"""
    d_debt, d_cash = _dec(interest_debt), _dec(eligible_cash)
    if d_debt is None or d_cash is None:
        return MetricResult("net_debt", None, "missing", "net_debt_v1", ["输入缺失"])
    return MetricResult("net_debt", _fmt(d_debt - d_cash), "valid", "net_debt_v1")


def current_ratio(current_assets: Optional[str], current_liabilities: Optional[str]) -> MetricResult:
    return _ratio(current_assets, current_liabilities, "current_ratio")


def quick_ratio(current_assets: Optional[str], inventory: Optional[str],
                other_illiquid: Optional[str], current_liabilities: Optional[str]) -> MetricResult:
    """(CA − Inventory − OtherIlliquid)/CL；银行等 N/A（适用性层）。"""
    d_ca, d_inv, d_other, d_cl = map(_dec, (current_assets, inventory, other_illiquid, current_liabilities))
    if any(d is None for d in (d_ca, d_cl)):
        return MetricResult("quick_ratio", None, "missing", "quick_ratio_v1", ["输入缺失"])
    if d_cl == 0:
        return MetricResult("quick_ratio", None, "zero_denominator", "quick_ratio_v1", ["流动负债为零"])
    numerator = d_ca - (d_inv or 0) - (d_other or 0)
    return MetricResult("quick_ratio", _fmt(numerator / d_cl), "valid", "quick_ratio_v1")


# ---------- 周转类 ----------

def receivable_turnover(revenue: Optional[str], receivables_start: Optional[str], receivables_end: Optional[str]) -> MetricResult:
    avg = _average(receivables_start, receivables_end)
    if avg is None or _dec(revenue) is None:
        return MetricResult("receivable_turnover", None, "missing", "receivable_turnover_v1", ["输入缺失"])
    if avg == 0:
        return MetricResult("receivable_turnover", None, "zero_denominator", "receivable_turnover_v1", ["平均应收为零"])
    return MetricResult("receivable_turnover", _fmt(_dec(revenue) / avg), "valid", "receivable_turnover_v1")


def inventory_turnover(cogs: Optional[str], inventory_start: Optional[str], inventory_end: Optional[str]) -> MetricResult:
    avg = _average(inventory_start, inventory_end)
    if avg is None or _dec(cogs) is None:
        return MetricResult("inventory_turnover", None, "missing", "inventory_turnover_v1", ["输入缺失（无 COGS 则 N/A）"])
    if avg == 0:
        return MetricResult("inventory_turnover", None, "zero_denominator", "inventory_turnover_v1", ["平均存货为零"])
    return MetricResult("inventory_turnover", _fmt(_dec(cogs) / avg), "valid", "inventory_turnover_v1")


# ---------- 现金流类 ----------

def cfo_to_net_profit(cfo: Optional[str], net_profit: Optional[str]) -> MetricResult:
    dn = _dec(net_profit)
    if dn is None or _dec(cfo) is None:
        return MetricResult("cfo_to_net_profit", None, "missing", "cfo_to_net_profit_v1", ["输入缺失"])
    if dn == 0:
        return MetricResult("cfo_to_net_profit", None, "zero_denominator", "cfo_to_net_profit_v1", ["净利润为零"])
    return MetricResult("cfo_to_net_profit", _fmt(_dec(cfo) / dn), "valid", "cfo_to_net_profit_v1",
                        ["negative_profit"] if dn < 0 else [])


def free_cash_flow(cfo: Optional[str], capex: Optional[str]) -> MetricResult:
    d_cfo, d_capex = _dec(cfo), _dec(capex)
    if d_cfo is None or d_capex is None:
        return MetricResult("free_cash_flow", None, "missing", "free_cash_flow_v1", ["输入缺失"])
    return MetricResult("free_cash_flow", _fmt(d_cfo - d_capex), "valid", "free_cash_flow_v1")


# ---------- 费用率类 ----------

def expense_ratio(expense: Optional[str], revenue: Optional[str], code: str) -> MetricResult:
    return _ratio(expense, revenue, code)


def rd_expense_ratio(rd: Optional[str], revenue: Optional[str]) -> MetricResult:
    return expense_ratio(rd, revenue, "rd_expense_ratio")


def selling_expense_ratio(expense: Optional[str], revenue: Optional[str]) -> MetricResult:
    return expense_ratio(expense, revenue, "selling_expense_ratio")


def admin_expense_ratio(expense: Optional[str], revenue: Optional[str]) -> MetricResult:
    return expense_ratio(expense, revenue, "admin_expense_ratio")


# ---------- 每股类 ----------

def eps(net_profit_attr: Optional[str], weighted_shares: Optional[str]) -> MetricResult:
    return _ratio(net_profit_attr, weighted_shares, "eps")


def bvps(equity_attr: Optional[str], period_end_shares: Optional[str]) -> MetricResult:
    return _ratio(equity_attr, period_end_shares, "bvps")


def cfo_per_share(cfo: Optional[str], weighted_shares: Optional[str]) -> MetricResult:
    return _ratio(cfo, weighted_shares, "cfo_per_share")


def share_change(end_shares: Optional[str], start_shares: Optional[str]) -> MetricResult:
    return _growth(end_shares, start_shares, "share_change")


# ---------- 注册表 ----------

METRIC_FUNCTIONS: Dict[str, object] = {
    "revenue_growth": revenue_growth,
    "net_profit_growth": net_profit_growth,
    "deducted_net_profit_growth": deducted_net_profit_growth,
    "gross_margin": gross_margin,
    "operating_margin": operating_margin,
    "net_margin": net_margin,
    "roe": roe,
    "roa": roa,
    "roic": roic,
    "debt_to_assets": debt_to_assets,
    "net_debt": net_debt,
    "current_ratio": current_ratio,
    "quick_ratio": quick_ratio,
    "receivable_turnover": receivable_turnover,
    "inventory_turnover": inventory_turnover,
    "cfo_to_net_profit": cfo_to_net_profit,
    "free_cash_flow": free_cash_flow,
    "rd_expense_ratio": rd_expense_ratio,
    "selling_expense_ratio": selling_expense_ratio,
    "admin_expense_ratio": admin_expense_ratio,
    "eps": eps,
    "bvps": bvps,
    "cfo_per_share": cfo_per_share,
    "share_change": share_change,
}

# 金融企业（银行/证券/保险）不适用的指标
FINANCIAL_NA = {
    "gross_margin", "operating_margin", "current_ratio", "quick_ratio",
    "receivable_turnover", "inventory_turnover", "rd_expense_ratio",
    "selling_expense_ratio", "admin_expense_ratio", "roic",
}
