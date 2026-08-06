"""财务质量与异常检测（Phase 4 任务书 3.13/Commit 7）。

四层阈值：A 会计硬规则 > B 公司历史 robust 统计 > C 同行分位 > D 版本化固定后备阈值。
规则只产生事实/告警/研究问题/风险候选；不得自动认定造假、质量差、必然减值、必然违约。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Dict, List, Optional

QUALITY_RULES_VERSION = "1.0.0"

# 固定后备阈值（config/financial_quality.yaml 同步）
FALLBACK = {
    "cfo_np_floor": Decimal("0.8"),
    "receivable_excess_pp": Decimal("20"),        # 应收增长−收入增长 20pp
    "receivable_ratio_rise_pp": Decimal("5"),     # 应收/收入上升 5pp
    "gross_margin_change_pp": Decimal("5"),       # 毛利率变化 5pp
    "robust_z_threshold": Decimal("3"),
    "non_recurring_ratio": Decimal("0.30"),       # 非经常性损益/归母净利润 30%
    "non_recurring_high": Decimal("0.50"),        # 50% 标高
    "goodwill_ratio": Decimal("0.20"),            # 商誉/资产 20%
    "rd_capitalization_ratio": Decimal("0.50"),   # 研发资本化 50%
    "related_party_ratio": Decimal("0.05"),       # 关联交易/收入 5%
    "dividend_cfo_ratio": Decimal("1.00"),        # 分红/CFO 100%
}


@dataclass
class QualityWarning:
    rule_code: str
    severity: str  # info / warning
    message: str
    evidence: List[str] = field(default_factory=list)
    rule_version: str = QUALITY_RULES_VERSION


def _dec(value: Optional[str]) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _pct(a: Optional[str], b: Optional[str]) -> Optional[Decimal]:
    """返回百分点差（a−b，输入为比率时 ×100）。"""
    da, db = _dec(a), _dec(b)
    if da is None or db is None:
        return None
    return (da - db) * 100


# ---------- A. 会计硬规则 ----------

def audit_opinion_change(previous: str, current: str) -> List[QualityWarning]:
    """无保留 → 保留/否定/无法表示意见。"""
    downgrade = {
        "unmodified": {"qualified", "adverse", "disclaimer"},
        "qualified": {"adverse", "disclaimer"},
    }
    if current in downgrade.get(previous, set()):
        return [QualityWarning(
            rule_code="audit_opinion_change", severity="warning",
            message=f"审计意见变化：{previous} → {current}",
        )]
    return []


def restatement_present(restatement_statuses: List[str]) -> List[QualityWarning]:
    if any(s in ("restated", "superseded") for s in restatement_statuses):
        return [QualityWarning(
            rule_code="restatement", severity="warning",
            message="存在报表重述（restated/superseded），须保留历史版本并核对当前版本",
        )]
    return []


# ---------- B/C/D. 动态与后备规则 ----------

def profit_growth_cashflow_deterioration(
    net_profit_growth: Optional[str],
    cfo_growth: Optional[str],
    cfo: Optional[str],
    net_profit: Optional[str],
) -> List[QualityWarning]:
    """利润增长但现金流恶化：净利润增长为正且 CFO 同比为负；或 CFO/NP<0.8 且历史显著下降。"""
    warnings: List[QualityWarning] = []
    d_npg, d_cfog = _dec(net_profit_growth), _dec(cfo_growth)
    if d_npg is not None and d_npg > 0 and d_cfog is not None and d_cfog < 0:
        warnings.append(QualityWarning(
            rule_code="profit_growth_cashflow_deterioration", severity="warning",
            message=f"净利润增长 {d_npg} 但 CFO 同比 {d_cfog}（恶化）",
        ))
    d_cfo, d_np = _dec(cfo), _dec(net_profit)
    if d_cfo is not None and d_np is not None and d_np != 0:
        ratio = d_cfo / d_np
        if ratio < FALLBACK["cfo_np_floor"]:
            warnings.append(QualityWarning(
                rule_code="profit_growth_cashflow_deterioration", severity="warning",
                message=f"CFO/净利润 = {ratio} 低于后备阈值 {FALLBACK['cfo_np_floor']}",
            ))
    return warnings


def receivable_growth_exceeds_revenue(
    receivable_growth: Optional[str],
    revenue_growth: Optional[str],
    receivable_ratio_current: Optional[str],
    receivable_ratio_previous: Optional[str],
    peer_p90_diff: Optional[str] = None,
) -> List[QualityWarning]:
    """应收快于收入：应收增长−收入增长 > max(20pp, 同行P90差值)，且应收/收入上升≥5pp。"""
    gap = _pct(receivable_growth, revenue_growth)
    if gap is None:
        return []
    threshold = peer_p90_diff if _dec(peer_p90_diff) is not None else FALLBACK["receivable_excess_pp"]
    rise = _pct(receivable_ratio_current, receivable_ratio_previous)
    if gap > threshold and (rise is not None and rise >= FALLBACK["receivable_ratio_rise_pp"]):
        return [QualityWarning(
            rule_code="receivable_growth_exceeds_revenue", severity="warning",
            message=f"应收增长−收入增长 = {gap}pp（阈值 {threshold}pp），应收/收入上升 {rise}pp",
        )]
    return []


def gross_margin_abnormal(
    current: Optional[str],
    previous: Optional[str],
    robust_z: Optional[str] = None,
    peer_p5: Optional[str] = None,
    peer_p95: Optional[str] = None,
) -> List[QualityWarning]:
    """毛利率异常：变化超 5pp 且 |robust Z|>3，或处于同行 P5/P95 之外。"""
    change = _pct(current, previous)
    if change is None:
        return []
    warnings: List[QualityWarning] = []
    d_z = _dec(robust_z)
    if abs(change) > FALLBACK["gross_margin_change_pp"] and (d_z is not None and abs(d_z) > FALLBACK["robust_z_threshold"]):
        warnings.append(QualityWarning(
            rule_code="gross_margin_abnormal", severity="warning",
            message=f"毛利率变化 {change}pp，robust Z = {d_z}",
        ))
    d_cur, d_p5, d_p95 = _dec(current), _dec(peer_p5), _dec(peer_p95)
    if d_cur is not None and d_p5 is not None and d_p95 is not None and (d_cur < d_p5 or d_cur > d_p95):
        warnings.append(QualityWarning(
            rule_code="gross_margin_abnormal", severity="warning",
            message=f"毛利率 {d_cur} 处于同行 P5/P95 之外（[{d_p5}, {d_p95}]）",
        ))
    return warnings


def high_non_recurring(non_recurring: Optional[str], net_profit: Optional[str]) -> List[QualityWarning]:
    """|非经常性损益|/|归母净利润| > 30%（>50% 标高严重度）。"""
    d_nr, d_np = _dec(non_recurring), _dec(net_profit)
    if d_nr is None or d_np is None or d_np == 0:
        return []
    ratio = abs(d_nr) / abs(d_np)
    if ratio > FALLBACK["non_recurring_high"]:
        return [QualityWarning(
            rule_code="high_non_recurring", severity="warning",
            message=f"非经常性损益/归母净利润 = {ratio}（>50% 高严重度）",
        )]
    if ratio > FALLBACK["non_recurring_ratio"]:
        return [QualityWarning(
            rule_code="high_non_recurring", severity="warning",
            message=f"非经常性损益/归母净利润 = {ratio}（>30%）",
        )]
    return []


def goodwill_concentration(goodwill: Optional[str], total_assets: Optional[str]) -> List[QualityWarning]:
    d_g, d_a = _dec(goodwill), _dec(total_assets)
    if d_g is None or d_a is None or d_a == 0:
        return []
    ratio = d_g / d_a
    if ratio > FALLBACK["goodwill_ratio"]:
        return [QualityWarning(
            rule_code="goodwill_concentration", severity="warning",
            message=f"商誉/资产 = {ratio}（>20%）",
        )]
    return []


def rd_capitalization_abnormal(capitalized: Optional[str], rd_total: Optional[str], peer_p90: Optional[str] = None) -> List[QualityWarning]:
    d_c, d_t = _dec(capitalized), _dec(rd_total)
    if d_c is None or d_t is None or d_t == 0:
        return []
    ratio = d_c / d_t
    threshold = _dec(peer_p90) if _dec(peer_p90) is not None else FALLBACK["rd_capitalization_ratio"]
    if ratio > threshold:
        return [QualityWarning(
            rule_code="rd_capitalization_abnormal", severity="warning",
            message=f"研发资本化比例 = {ratio}（阈值 {threshold}）",
        )]
    return []


def related_party_transactions(amount: Optional[str], revenue: Optional[str]) -> List[QualityWarning]:
    d_a, d_r = _dec(amount), _dec(revenue)
    if d_a is None or d_r is None or d_r == 0:
        return []
    ratio = d_a / d_r
    if ratio > FALLBACK["related_party_ratio"]:
        return [QualityWarning(
            rule_code="related_party_transactions", severity="warning",
            message=f"关联交易/收入 = {ratio}（>5%）",
        )]
    return []


def high_dividend_high_debt(dividend: Optional[str], cfo: Optional[str], net_debt_rising: bool) -> List[QualityWarning]:
    d_d, d_c = _dec(dividend), _dec(cfo)
    if d_d is None or d_c is None or d_c == 0:
        return []
    ratio = d_d / d_c
    if ratio > FALLBACK["dividend_cfo_ratio"] and net_debt_rising:
        return [QualityWarning(
            rule_code="high_dividend_high_debt", severity="warning",
            message=f"分红/CFO = {ratio}（>100%）且净负债上升",
        )]
    return []


def restricted_cash(cash: Optional[str], restricted: Optional[str]) -> List[QualityWarning]:
    d_c, d_r = _dec(cash), _dec(restricted)
    if d_c is None or d_r is None or d_c == 0:
        return []
    ratio = d_r / d_c
    if ratio > Decimal("0.3"):
        return [QualityWarning(
            rule_code="restricted_cash", severity="warning",
            message=f"受限资金占货币资金 {ratio}（>30%），不得把全部货币资金当作可用现金",
        )]
    return []


# ---------- robust 统计（B 层） ----------

def robust_z_series(values: List[Optional[str]]) -> Optional[Decimal]:
    """历史序列 robust Z：|x − median| / (1.4826 × MAD)。样本不足返回 None。"""
    nums = [v for v in values if v is not None]
    if len(nums) < 5:
        return None
    decs = [Decimal(v) for v in nums]
    med = median(decs)
    deviations = [abs(x - med) for x in decs]
    mad = median(deviations)
    if mad == 0:
        return None  # MAD=0 时无统计意义
    scale = Decimal("1.4826") * mad
    return (decs[-1] - med) / scale


def run_quality_checks(
    *,
    net_profit_growth: Optional[str] = None,
    cfo_growth: Optional[str] = None,
    cfo: Optional[str] = None,
    net_profit: Optional[str] = None,
    receivable_growth: Optional[str] = None,
    revenue_growth: Optional[str] = None,
    receivable_ratio_current: Optional[str] = None,
    receivable_ratio_previous: Optional[str] = None,
    gross_margin_current: Optional[str] = None,
    gross_margin_previous: Optional[str] = None,
    non_recurring: Optional[str] = None,
    goodwill: Optional[str] = None,
    total_assets: Optional[str] = None,
    rd_capitalized: Optional[str] = None,
    rd_total: Optional[str] = None,
    related_party_amount: Optional[str] = None,
    revenue: Optional[str] = None,
    dividend: Optional[str] = None,
    cash: Optional[str] = None,
    restricted: Optional[str] = None,
    net_debt_rising: bool = False,
    previous_audit_opinion: Optional[str] = None,
    current_audit_opinion: Optional[str] = None,
    restatement_statuses: Optional[List[str]] = None,
    gross_margin_history: Optional[List[Optional[str]]] = None,
) -> List[QualityWarning]:
    """汇总运行财务质量规则。只产生告警，不认定造假/必然风险。"""
    warnings: List[QualityWarning] = []
    warnings.extend(profit_growth_cashflow_deterioration(
        net_profit_growth, cfo_growth, cfo, net_profit))
    warnings.extend(receivable_growth_exceeds_revenue(
        receivable_growth, revenue_growth, receivable_ratio_current, receivable_ratio_previous))
    robust_z = None
    if gross_margin_history:
        robust_z = robust_z_series(gross_margin_history)
    warnings.extend(gross_margin_abnormal(
        gross_margin_current, gross_margin_previous,
        robust_z=str(robust_z) if robust_z is not None else None))
    warnings.extend(high_non_recurring(non_recurring, net_profit))
    warnings.extend(goodwill_concentration(goodwill, total_assets))
    warnings.extend(rd_capitalization_abnormal(rd_capitalized, rd_total))
    warnings.extend(related_party_transactions(related_party_amount, revenue))
    warnings.extend(high_dividend_high_debt(dividend, cfo, net_debt_rising))
    warnings.extend(restricted_cash(cash, restricted))
    if previous_audit_opinion and current_audit_opinion:
        warnings.extend(audit_opinion_change(previous_audit_opinion, current_audit_opinion))
    if restatement_statuses:
        warnings.extend(restatement_present(restatement_statuses))
    return warnings
