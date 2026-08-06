"""Phase 4 财务/估值指标的单一 Markdown 展示契约。"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re
from typing import Any, Dict, Iterable, List, Tuple


@dataclass(frozen=True)
class MetricDisplaySpec:
    metric_code: str
    label: str
    section_id: int
    format_kind: str
    aliases: Tuple[str, ...] = ()


def _display(code: str, label: str, section: int, kind: str,
             aliases: Tuple[str, ...] = ()) -> MetricDisplaySpec:
    return MetricDisplaySpec(code, label, section, kind, aliases)


FINANCIAL_METRIC_DISPLAY: Dict[str, MetricDisplaySpec] = {
    "revenue_growth": _display("revenue_growth", "收入增长", 10, "percent"),
    "net_profit_growth": _display("net_profit_growth", "归母净利润增长", 11, "percent"),
    "deducted_net_profit_growth": _display("deducted_net_profit_growth", "扣非净利润增长", 11, "percent"),
    "gross_margin": _display("gross_margin", "毛利率", 11, "percent", ("综合毛利率",)),
    "operating_margin": _display("operating_margin", "营业利润率", 11, "percent"),
    "net_margin": _display("net_margin", "净利率", 11, "percent"),
    "roe": _display("roe", "ROE", 11, "percent"),
    "roa": _display("roa", "ROA", 11, "percent"),
    "roic": _display("roic", "ROIC", 11, "percent"),
    "cfo_to_net_profit": _display("cfo_to_net_profit", "CFO/净利润", 12, "times"),
    "debt_to_assets": _display("debt_to_assets", "资产负债率", 13, "percent"),
    "net_debt": _display("net_debt", "净负债", 13, "amount"),
    "current_ratio": _display("current_ratio", "流动比率", 13, "times"),
    "quick_ratio": _display("quick_ratio", "速动比率", 13, "times"),
    "receivable_turnover": _display("receivable_turnover", "应收周转", 14, "times"),
    "inventory_turnover": _display("inventory_turnover", "存货周转", 14, "times"),
    "free_cash_flow": _display("free_cash_flow", "自由现金流", 15, "amount"),
    "rd_expense_ratio": _display("rd_expense_ratio", "研发费用率", 16, "percent"),
    "selling_expense_ratio": _display("selling_expense_ratio", "销售费用率", 16, "percent"),
    "admin_expense_ratio": _display("admin_expense_ratio", "管理费用率", 16, "percent"),
    "eps": _display("eps", "每股收益", 7, "per_share"),
    "bvps": _display("bvps", "每股净资产", 7, "per_share"),
    "cfo_per_share": _display("cfo_per_share", "每股经营现金流", 7, "per_share"),
    "share_change": _display("share_change", "股本变化", 7, "percent"),
}

VALUATION_METRIC_DISPLAY: Dict[str, MetricDisplaySpec] = {
    "PE_TTM": _display("PE_TTM", "PE（TTM）", 24, "times"),
    "PB": _display("PB", "PB", 24, "times"),
    "PS_TTM": _display("PS_TTM", "PS（TTM）", 24, "times"),
    "EV_EBITDA": _display("EV_EBITDA", "EV/EBITDA", 24, "times"),
    "FCF_YIELD": _display("FCF_YIELD", "自由现金流收益率", 24, "percent"),
    "DIVIDEND_YIELD": _display("DIVIDEND_YIELD", "股息率", 24, "percent"),
}


def format_metric_value(value: Any, format_kind: str) -> str:
    if value is None:
        return "N/A"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    quantum = Decimal("0.01")
    if format_kind == "percent":
        return f"{(number * 100).quantize(quantum, rounding=ROUND_HALF_UP)}%"
    if format_kind == "times":
        return f"{number.quantize(quantum, rounding=ROUND_HALF_UP)} 倍"
    if format_kind == "amount":
        return f"{number.quantize(quantum, rounding=ROUND_HALF_UP)} 元"
    if format_kind == "per_share":
        return f"{number.quantize(quantum, rounding=ROUND_HALF_UP)} 元/股"
    return str(number)


def render_metric_line(metric: Dict[str, Any], spec: MetricDisplaySpec, metric_id: str) -> str:
    token = format_metric_value(metric.get("value"), spec.format_kind)
    return f"- {spec.label}：{token} <!-- metric-id:{metric_id} metric-code:{spec.metric_code} -->"


def display_terms(spec: MetricDisplaySpec) -> Tuple[str, ...]:
    """Labels that make a list item a formal metric assertion."""
    return (spec.label,) + spec.aliases


def controlled_metric_sections() -> set[int]:
    return {spec.section_id for spec in (*FINANCIAL_METRIC_DISPLAY.values(), *VALUATION_METRIC_DISPLAY.values())}


def unmarked_metric_assertion(line: str) -> bool:
    """Detect a visible formal metric assertion that must carry the stable marker."""
    if not re.match(r"^\s*-\s+", line):
        return False
    specs = (*FINANCIAL_METRIC_DISPLAY.values(), *VALUATION_METRIC_DISPLAY.values())
    if any(term in line for spec in specs for term in display_terms(spec)):
        return True
    return bool(re.search(r"\d(?:[\d,.]*)(?:%|\s*(?:倍|元(?:/股)?|万元|亿元))", line))


def latest_financial_metrics(metrics: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """每个 code 只正式展示最新期间对象；选择规则供 Renderer/Validator 共用。"""
    latest: Dict[str, Dict[str, Any]] = {}
    for metric in metrics:
        code = metric.get("metric_code")
        if code not in FINANCIAL_METRIC_DISPLAY:
            continue
        previous = latest.get(code)
        if previous is None or (metric.get("period_end") or "") > (previous.get("period_end") or ""):
            latest[code] = metric
    return [latest[code] for code in FINANCIAL_METRIC_DISPLAY if code in latest]


def valuation_metric_id(snapshot_id: str, metric_code: str) -> str:
    return f"valuation:{snapshot_id}:{metric_code}"
