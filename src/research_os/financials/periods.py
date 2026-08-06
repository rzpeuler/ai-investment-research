"""期间、单位、币种、口径标准化（Phase 4 任务书 3.11/Commit 5）。

规则：
- 单季拆分：Q2=H1−Q1、Q3=Q3_YTD−H1、Q4=FY−Q3_YTD；仅当公司/口径/币种/单位/科目/
  财年/准则/重述版本全同；拆分值 value_status=derived_from_report，不得写 reported。
- YoY=(Current−Comparable)/abs(Comparable)；Comparable=0 → zero_denominator；负基数加 negative_base 警告。
- QoQ 用单季值，不得用累计值。
- CAGR 仅 Start>0、End>0、Years>0 时计算。
- TTM：LatestFY + CurrentYTD − PriorComparableYTD（方法写入 formula_id）；时点项目不计算。
- 单位标准化到 CNY yuan（仅当原币种为 CNY 直接转换）；外币无汇率证据时保留原币。
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Tuple

# 单位换算：unit_scale（数字倍率）到 yuan（CNY 直接转换）
UNIT_SCALES = {"yuan": 1, "thousand_yuan": 1000, "ten_thousand_yuan": 10000, "hundred_million_yuan": 100000000}


def _scale_factor(unit_scale) -> Decimal:
    """将 unit_scale（数字倍率或注册表名称）转为 Decimal 因子。"""
    if isinstance(unit_scale, int):
        return Decimal(unit_scale) if unit_scale > 0 else Decimal(1)
    factor = UNIT_SCALES.get(str(unit_scale), 1)
    return Decimal(factor) if factor > 0 else Decimal(1)


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
class PeriodKey:
    """期间一致性检查用的口径键。"""
    company: str
    scope: str
    currency: str
    unit_scale: int
    taxonomy_code: str
    fiscal_year: int
    accounting_standard: str
    restatement_version: int


def periods_compatible(a: PeriodKey, b: PeriodKey) -> bool:
    return (
        a.company == b.company and a.scope == b.scope and a.currency == b.currency
        and a.unit_scale == b.unit_scale and a.taxonomy_code == b.taxonomy_code
        and a.fiscal_year == b.fiscal_year and a.accounting_standard == b.accounting_standard
        and a.restatement_version == b.restatement_version
    )


@dataclass
class QuarterSplit:
    quarter: str  # Q2/Q3/Q4
    value: Optional[str]
    status: str  # derived_from_report / missing
    warnings: List[str]


def single_quarter_split(
    key: PeriodKey,
    h1_ytd: Optional[str],
    q1_ytd: Optional[str],
    fy: Optional[str],
    q3_ytd: Optional[str] = None,
) -> List[QuarterSplit]:
    """按任务书公式拆分单季值。所有输入须已按相同口径（periods_compatible）。"""
    results: List[QuarterSplit] = []
    warnings: List[str] = []

    def _sub(a: Optional[str], b: Optional[str], name: str) -> Optional[str]:
        da, db = _dec(a), _dec(b)
        if da is None or db is None:
            return None
        return _fmt(da - db)

    q2 = _sub(h1_ytd, q1_ytd, "Q2")
    results.append(QuarterSplit(
        quarter="Q2", value=q2,
        status="derived_from_report" if q2 is not None else "missing",
        warnings=[],
    ))
    if q3_ytd is not None:
        q3 = _sub(q3_ytd, h1_ytd, "Q3")
        results.append(QuarterSplit(
            quarter="Q3", value=q3,
            status="derived_from_report" if q3 is not None else "missing",
            warnings=[],
        ))
        q4 = _sub(fy, q3_ytd, "Q4")
        results.append(QuarterSplit(
            quarter="Q4", value=q4,
            status="derived_from_report" if q4 is not None else "missing",
            warnings=[],
        ))
    return results


@dataclass
class YoYResult:
    value: Optional[str]
    status: str  # valid / zero_denominator / missing / not_applicable
    warnings: List[str]


def yoy(current: Optional[str], comparable: Optional[str]) -> YoYResult:
    """YoY=(Current−Comparable)/abs(Comparable)。"""
    dc, db = _dec(current), _dec(comparable)
    if dc is None or db is None:
        return YoYResult(None, "missing", ["输入缺失"])
    if db == 0:
        return YoYResult(None, "zero_denominator", ["可比期基数为零"])
    warnings = ["negative_base"] if db < 0 else []
    return YoYResult(_fmt((dc - db) / abs(db)), "valid", warnings)


def qoq(current_single: Optional[str], previous_single: Optional[str]) -> YoYResult:
    """QoQ 用单季值；不得用累计值。"""
    return yoy(current_single, previous_single)


def cagr(start: Optional[str], end: Optional[str], years: Optional[Decimal]) -> YoYResult:
    """CAGR=(End/Start)^(1/Years)−1；仅 Start>0、End>0、Years>0。"""
    ds, de = _dec(start), _dec(end)
    if ds is None or de is None or years is None:
        return YoYResult(None, "missing", ["输入缺失"])
    if ds <= 0 or de <= 0 or years <= 0:
        return YoYResult(None, "not_applicable", ["CAGR 要求 Start>0、End>0、Years>0"])
    ratio = de / ds
    try:
        value = ratio ** (Decimal(1) / years) - Decimal(1)
    except (InvalidOperation, ValueError):
        return YoYResult(None, "not_applicable", ["无法计算"])
    return YoYResult(_fmt(value), "valid", [])


@dataclass
class TTMResult:
    value: Optional[str]
    formula_id: str  # ttm_fy_plus_ytd / ttm_four_quarters
    status: str
    warnings: List[str]


def ttm_fy_plus_ytd(
    latest_fy: Optional[str],
    current_ytd: Optional[str],
    prior_comparable_ytd: Optional[str],
) -> TTMResult:
    """TTM = LatestFY + CurrentYTD − PriorComparableYTD。"""
    d_fy, d_cur, d_prior = _dec(latest_fy), _dec(current_ytd), _dec(prior_comparable_ytd)
    if d_fy is None or d_cur is None or d_prior is None:
        return TTMResult(None, "ttm_fy_plus_ytd", "missing", ["输入缺失"])
    return TTMResult(
        _fmt(d_fy + d_cur - d_prior), "ttm_fy_plus_ytd", "valid", [],
    )


def normalize_to_yuan(
    value: Optional[str],
    unit_scale: int,
    currency: str,
) -> Tuple[Optional[str], str, List[str]]:
    """标准化到 CNY yuan；仅原币种为 CNY 时直接换算；外币无汇率证据保留原币。

    返回 (标准值, 标准单位, 警告)。
    """
    d = _dec(value)
    if d is None:
        return None, "yuan", []
    if currency != "CNY":
        return value, currency, [f"外币 {currency} 无汇率证据，保留原币"]
    factor = _scale_factor(unit_scale)
    return _fmt(d * factor), "yuan", []


def detect_period_basis(period_end: str) -> str:
    """按期末日期推断期间类型：FY/H1/Q1/Q3/OTHER。"""
    if period_end.endswith("12-31") or period_end.endswith("12-30"):
        return "FY"
    if period_end.endswith("06-30"):
        return "H1"
    if period_end.endswith("03-31"):
        return "Q1"
    if period_end.endswith("09-30"):
        return "Q3"
    return "OTHER"


def detect_duration_months(period_end: str) -> int:
    basis = detect_period_basis(period_end)
    return {"FY": 12, "H1": 6, "Q1": 3, "Q3": 9}.get(basis, 12)
