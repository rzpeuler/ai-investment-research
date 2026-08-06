"""估值模块（Phase 4 任务书 3.16/Commit 11）。

- 市值优先 direct_market_cap，否则 price × shares_outstanding（时点一致）；
- EV = 市值 + 有息负债 + 优先股 + 少数股东权益 − 可扣除现金 − 非经营性投资；
  受限现金不得扣除；少数股东权益缺失时 EV/EBITDA 降级；
- PE/PB/PS/EV_EBITDA/FCF_Yield/股息率；净利润<=0 等 → not_applicable；
- 历史分位 >=36 样本、>=60 完整；同行分位 >=5 完整、3-4 有限、<3 不计算；
- 禁止目标价/合理价值/上涨空间/买卖区间（Validator 兜底）。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from statistics import median
from typing import Dict, List, Optional

from research_os.models.valuation import ValuationMetric, ValuationSnapshot
from research_os.utils.time import now_iso

VALUATION_RULES_VERSION = "1.0.0"

HISTORY_MIN_SAMPLES = 36
HISTORY_FULL_SAMPLES = 60
PEER_FULL = 5
PEER_LIMITED_MIN = 3

FINANCIAL_ENTERPRISE = {"bank", "securities", "insurance"}


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
class ValuationInputs:
    """估值输入（市值/股本/价格须时点一致）。"""
    company_entity_id: str
    security_entity_id: str
    as_of: str
    price: Optional[str] = None
    shares_outstanding: Optional[str] = None
    direct_market_cap: Optional[str] = None
    interest_debt: Optional[str] = None
    preferred_equity: Optional[str] = None
    minority_interest: Optional[str] = None
    eligible_cash: Optional[str] = None
    non_operating_investments: Optional[str] = None
    financial_period_end: Optional[str] = None
    financial_basis: str = "TTM"
    # TTM 财务输入
    net_profit_ttm: Optional[str] = None
    revenue_ttm: Optional[str] = None
    ebitda_ttm: Optional[str] = None
    fcf_ttm: Optional[str] = None
    equity_attr: Optional[str] = None
    trailing_dividend: Optional[str] = None
    sector: str = "general"  # general / financial / cyclical / non_financial


@dataclass
class MarketCapResult:
    market_cap: Optional[str]
    method: str  # direct / price_times_shares / missing
    warnings: List[str] = field(default_factory=list)


def compute_market_cap(inp: ValuationInputs) -> MarketCapResult:
    """市值：优先 direct_market_cap，否则 price × shares_outstanding。"""
    if _dec(inp.direct_market_cap) is not None:
        return MarketCapResult(inp.direct_market_cap, "direct", [])
    d_price, d_shares = _dec(inp.price), _dec(inp.shares_outstanding)
    if d_price is None or d_shares is None:
        return MarketCapResult(None, "missing", ["市值/股本/价格缺失，时点无法对齐"])
    if d_price < 0 or d_shares <= 0:
        return MarketCapResult(None, "missing", ["价格或股本非法（价格>=0、股本>0）"])
    return MarketCapResult(_fmt(d_price * d_shares), "price_times_shares", [])


def compute_ev(inp: ValuationInputs, market_cap: Optional[str]) -> tuple[Optional[str], List[str]]:
    """EV = 市值 + 有息负债 + 优先股 + 少数股东权益 − 可扣除现金 − 非经营性投资。"""
    d_mc = _dec(market_cap)
    if d_mc is None:
        return None, ["市值缺失，无法计算 EV"]
    warnings: List[str] = []
    d_debt = _dec(inp.interest_debt) or Decimal(0)
    d_pref = _dec(inp.preferred_equity) or Decimal(0)
    d_minority = _dec(inp.minority_interest)
    if d_minority is None:
        warnings.append("少数股东权益缺失，EV/EBITDA 降级")
        d_minority = Decimal(0)
    d_cash = _dec(inp.eligible_cash) or Decimal(0)
    d_nonop = _dec(inp.non_operating_investments) or Decimal(0)
    ev = d_mc + d_debt + d_pref + d_minority - d_cash - d_nonop
    if ev < 0:
        warnings.append("EV 为负（净现金公司），须复核 EligibleCash 构成")
    return _fmt(ev), warnings


def _ratio_metric(code: str, numerator: Optional[str], denominator: Optional[str],
                  not_applicable_when_negative: bool = True) -> ValuationMetric:
    dn, dd = _dec(numerator), _dec(denominator)
    warnings: List[str] = []
    if dn is None or dd is None:
        return ValuationMetric(metric_code=code, numerator=numerator, denominator=denominator,
                               value=None, unit="ratio", status="missing", formula_version=VALUATION_RULES_VERSION, warnings=["输入缺失"])
    if dd <= 0:
        return ValuationMetric(metric_code=code, numerator=numerator, denominator=denominator,
                               value=None, unit="ratio", status="not_applicable", formula_version=VALUATION_RULES_VERSION,
                               warnings=["分母 <= 0，指标不适用"])
    if not_applicable_when_negative and dn < 0:
        return ValuationMetric(metric_code=code, numerator=numerator, denominator=denominator,
                               value=None, unit="ratio", status="not_applicable", formula_version=VALUATION_RULES_VERSION,
                               warnings=["分子 < 0，指标不适用"])
    value = _fmt(dn / dd)
    if dn < 0 and not not_applicable_when_negative:
        warnings.append("负值指标不得解释为便宜")
    return ValuationMetric(metric_code=code, numerator=numerator, denominator=denominator,
                           value=value, unit="ratio", status="valid", formula_version=VALUATION_RULES_VERSION, warnings=warnings)


def compute_valuation_metrics(inp: ValuationInputs, market_cap: Optional[str], ev: Optional[str]) -> List[ValuationMetric]:
    """计算 PE/PB/PS/EV_EBITDA/FCF_Yield/股息率（含不适用判定）。"""
    metrics: List[ValuationMetric] = []
    d_mc = _dec(market_cap)
    d_ev = _dec(ev)

    # PE_TTM：净利润<=0 → N/A
    metrics.append(_ratio_metric("PE_TTM", market_cap, inp.net_profit_ttm))
    # PB：净资产<=0 → N/A
    metrics.append(_ratio_metric("PB", market_cap, inp.equity_attr))
    # PS_TTM
    metrics.append(_ratio_metric("PS_TTM", market_cap, inp.revenue_ttm))
    # EV/EBITDA：银行/证券/保险 N/A；EBITDA<=0 → N/A
    if inp.sector in FINANCIAL_ENTERPRISE:
        metrics.append(ValuationMetric(metric_code="EV_EBITDA", numerator=None, denominator=None, value=None,
                                       unit="ratio", status="not_applicable", formula_version=VALUATION_RULES_VERSION,
                                       warnings=["金融企业 EV/EBITDA 不适用"]))
    else:
        m = _ratio_metric("EV_EBITDA", ev, inp.ebitda_ttm)
        if d_ev is None:
            m.warnings.append("EV 缺失")
        metrics.append(m)
    # FCF_Yield：FCF<0 允许负值但不得解释为便宜
    d_fcf = _dec(inp.fcf_ttm)
    if d_mc is None or d_fcf is None:
        metrics.append(ValuationMetric(metric_code="FCF_YIELD", numerator=inp.fcf_ttm, denominator=market_cap,
                                       value=None, unit="ratio", status="missing", formula_version=VALUATION_RULES_VERSION, warnings=["输入缺失"]))
    elif d_mc == 0:
        metrics.append(ValuationMetric(metric_code="FCF_YIELD", numerator=inp.fcf_ttm, denominator=market_cap,
                                       value=None, unit="ratio", status="not_applicable", formula_version=VALUATION_RULES_VERSION, warnings=["市值为零"]))
    else:
        val = _fmt(d_fcf / d_mc)
        warnings = ["FCF 为负，负收益率不得解释为便宜"] if d_fcf < 0 else []
        metrics.append(ValuationMetric(metric_code="FCF_YIELD", numerator=inp.fcf_ttm, denominator=market_cap,
                                       value=val, unit="ratio", status="valid", formula_version=VALUATION_RULES_VERSION, warnings=warnings))
    # 股息率
    d_div = _dec(inp.trailing_dividend)
    if d_mc is None or d_div is None:
        metrics.append(ValuationMetric(metric_code="DIVIDEND_YIELD", numerator=inp.trailing_dividend, denominator=market_cap,
                                       value=None, unit="ratio", status="missing", formula_version=VALUATION_RULES_VERSION, warnings=["输入缺失"]))
    elif d_mc == 0:
        metrics.append(ValuationMetric(metric_code="DIVIDEND_YIELD", numerator=inp.trailing_dividend, denominator=market_cap,
                                       value=None, unit="ratio", status="not_applicable", formula_version=VALUATION_RULES_VERSION, warnings=["市值为零"]))
    else:
        metrics.append(ValuationMetric(metric_code="DIVIDEND_YIELD", numerator=inp.trailing_dividend, denominator=market_cap,
                                       value=_fmt(d_div / d_mc), unit="ratio", status="valid", formula_version=VALUATION_RULES_VERSION, warnings=[]))
    return metrics


def percentile_rank(value: Optional[str], history: List[Optional[str]]) -> Optional[Decimal]:
    """平均秩分位（与 Phase 3 分位法一致）：value 在 history 中的分位（0-1）。"""
    d = _dec(value)
    if d is None:
        return None
    valid: List[Decimal] = []
    for v in history:
        dv = _dec(v)
        if dv is not None:
            valid.append(dv)
    if len(valid) < HISTORY_MIN_SAMPLES:
        return None
    valid = sorted(valid)
    rank = sum(1 for x in valid if x <= d)
    return Decimal(rank) / Decimal(len(valid))


def percentile_status(sample_size: int) -> str:
    """历史分位样本状态：>=60 完整 / 36-59 有限 / <36 不足。"""
    if sample_size >= HISTORY_FULL_SAMPLES:
        return "full"
    if sample_size >= HISTORY_MIN_SAMPLES:
        return "limited"
    return "insufficient"


def peer_percentile_status(sample_size: int) -> str:
    """同行分位样本状态：>=5 完整 / 3-4 有限 / <3 不计算。"""
    if sample_size >= PEER_FULL:
        return "full"
    if sample_size >= PEER_LIMITED_MIN:
        return "limited"
    return "insufficient"


def build_valuation_snapshot(
    inp: ValuationInputs,
    history_values: Optional[List[Optional[str]]] = None,
    peer_values: Optional[List[Optional[str]]] = None,
    peer_selection_id: Optional[str] = None,
) -> ValuationSnapshot:
    """构造估值快照（市值 → EV → 指标 → 分位状态）。"""
    mc = compute_market_cap(inp)
    ev, ev_warnings = compute_ev(inp, mc.market_cap)
    metrics = compute_valuation_metrics(inp, mc.market_cap, ev)

    applicability_notes: List[str] = []
    if inp.sector in FINANCIAL_ENTERPRISE:
        applicability_notes.append("金融企业：EV/EBITDA 等通用指标不适用")
    if inp.sector == "cyclical":
        applicability_notes.append("周期企业：PE 仅作观察，须提示周期位置和利润基数")
    if _dec(inp.net_profit_ttm) is not None and _dec(inp.net_profit_ttm) < 0:
        applicability_notes.append("净利润为负：PE 不适用，PS/PB 有条件使用")
    if mc.method == "price_times_shares":
        applicability_notes.append("市值由 price × shares 计算（时点一致）")

    history_size = len([v for v in (history_values or []) if v is not None])
    peer_size = len([v for v in (peer_values or []) if v is not None])
    h_status = percentile_status(history_size)
    p_status = peer_percentile_status(peer_size)
    if h_status == "insufficient":
        applicability_notes.append(f"历史样本 {history_size} < 36，不输出正式历史分位")
    if p_status == "insufficient":
        applicability_notes.append(f"同行样本 {peer_size} < 3，不输出正式同行分位")
    elif p_status == "limited":
        applicability_notes.append(f"同行样本 {peer_size}（3-4），只展示样本值和中位数，不称正式分位")

    status = "complete"
    if any(m.status == "missing" for m in metrics) or mc.market_cap is None:
        status = "partial"
    if all(m.status == "not_applicable" for m in metrics) and mc.market_cap is None:
        status = "insufficient_data"
    if inp.sector in FINANCIAL_ENTERPRISE:
        status = "partial"  # 金融企业合法降级

    return ValuationSnapshot(
        valuation_snapshot_id=str(uuid.uuid4()),
        company_entity_id=inp.company_entity_id,
        security_entity_id=inp.security_entity_id,
        as_of=inp.as_of,
        market_data_manifest_id=None,
        price=inp.price,
        shares_outstanding=inp.shares_outstanding,
        market_cap=mc.market_cap,
        enterprise_value=ev,
        financial_period_end=inp.financial_period_end,
        financial_basis=inp.financial_basis,  # type: ignore[arg-type]
        metrics=metrics,
        history_window_start=None,
        history_window_end=None,
        history_sample_size=history_size,
        peer_selection_id=peer_selection_id,
        peer_sample_size=peer_size,
        percentile_method="average_rank",
        applicability_notes=applicability_notes + ev_warnings,
        status=status,  # type: ignore[arg-type]
        source_ids=[],
        evidence_ids=[],
        version=1,
        calculated_at=now_iso(),
    )
