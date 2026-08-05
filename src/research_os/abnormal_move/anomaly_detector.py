"""异动事实检测（Phase 3 任务书 7 节）。

纯确定性计算，不使用模型。输入为一致复权口径的标准化日线（MarketDailyOhlcv）
与可选基准序列；输出 AbnormalMoveObservation + AnomalyMetric 列表。

关键规则：
- 收益率 r_t = close_t / close_(t-1) - 1（一致复权口径）
- robust_z = (x - median) / (1.4826 * MAD + epsilon)；MAD=0 时回退历史经验分位
- severity 按双侧分位或绝对 Z 取更严重者（0-5）
- 样本不足合法降级：<20 只输出有限指标（NEW_LISTING/INSUFFICIENT_EVIDENCE）
- 停牌日不生成价格异动；复牌与上一个实际交易日比较；快照不得进入日级计算
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.config import (
    ANOMALY_RULES_VERSION,
    BASELINE_WINDOW,
    BETA_MIN_SAMPLES,
    BETA_REGRESSION_WINDOW,
    IDIOSYNCRATIC_CROSS_SECTIONAL_PCT,
    IDIOSYNCRATIC_EXCESS_SEVERITY,
    IDIOSYNCRATIC_PEER_MEDIAN_SEVERITY,
    MAD_ZERO_FALLBACK_PERCENTILE,
    MIN_PEERS_CONCEPT,
    MIN_PEERS_INDUSTRY,
    MIN_ROBUST_BASELINE,
    MIN_SAMPLE_FULL,
    MIN_SAMPLE_LIMITED,
    MIN_SAMPLE_NEW_LISTING,
    MIN_SAMPLE_ROBUST,
    MOVE_ABSOLUTE_SEVERITY,
    MOVE_RETURN_SEVERITY,
    MOVE_STATE_SEVERITY,
    MOVE_VOLUME_SEVERITY,
    SEVERITY_TABLE,
    SHORT_WINDOW,
    VOLATILITY_BASELINE,
    VOLATILITY_SHORT,
    WINSORIZE_HIGH,
    WINSORIZE_LOW,
)
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AnomalyMetric,
    MarketDailyOhlcv,
    PeerMove,
)
from research_os.utils.id import new_uuid

EPS = 1e-12


# ---------- 纯函数：统计 ----------


def pct_change(prices: List[float]) -> List[Optional[float]]:
    """r_t = close_t / close_(t-1) - 1；首日 None。"""
    out: List[Optional[float]] = [None]
    for i in range(1, len(prices)):
        prev = prices[i - 1]
        out.append((prices[i] / prev - 1.0) if prev not in (0.0, None) else None)
    return out


def robust_stats(history: List[float]) -> tuple:
    """(median, mad)。历史为空时返回 (None, None)。"""
    if not history:
        return None, None
    median = statistics.median(history)
    mad = statistics.median([abs(x - median) for x in history])
    return median, mad


def robust_z_score(x: float, median: float, mad: float) -> Optional[float]:
    """(x - median) / (1.4826 * MAD + eps)。MAD=0 时返回 None（调用方回退分位）。"""
    if mad == 0:
        return None
    return (x - median) / (1.4826 * mad + EPS)


def historical_percentile(x: float, history: List[float]) -> float:
    """历史经验分位（0-100，双侧）：<= x 的比例。"""
    if not history:
        return 50.0
    return (sum(1.0 for h in history if h <= x) / len(history)) * 100.0


def severity_from_percentile(pct: float) -> int:
    """双侧分位 -> severity（任务书 7.4 表）。"""
    p = pct / 100.0
    for pct_thr, _z, sev in reversed(SEVERITY_TABLE):
        if p >= pct_thr:
            return sev
    return 0


def severity_from_z(abs_z: float) -> int:
    """绝对 robust Z -> severity。"""
    for _pct, z_thr, sev in reversed(SEVERITY_TABLE):
        if abs_z >= z_thr:
            return sev
    return 0


def severity_combined(x: float, history: List[float], median: float, mad: float) -> int:
    """分位与 Z 双口径，取更严重者。MAD=0 时仅用分位。"""
    z = robust_z_score(x, median, mad)
    pct = historical_percentile(x, history)
    sev_pct = severity_from_percentile(max(pct, 100.0 - pct) if history else 0)
    sev_z = severity_from_z(abs(z)) if z is not None else 0
    return max(sev_pct, sev_z)


def winsorize(values: List[float], low: float = WINSORIZE_LOW,
              high: float = WINSORIZE_HIGH) -> List[float]:
    """Winsorize：截断到 [low, high] 分位。"""
    if not values:
        return values
    s = sorted(values)
    lo = s[max(0, int(len(s) * low) - 1)]
    hi = s[min(len(s) - 1, int(len(s) * high))]
    return [min(max(v, lo), hi) for v in values]


def rolling_returns(returns: List[Optional[float]]) -> List[Optional[float]]:
    """RV5 波动率：sqrt(sum(r_i^2, i=t-4..t))。"""
    out: List[Optional[float]] = []
    for i in range(len(returns)):
        window = [r for r in returns[max(0, i - VOLATILITY_SHORT + 1):i + 1] if r is not None]
        if len(window) < 2:
            out.append(None)
            continue
        out.append(math.sqrt(sum(r * r for r in window)))
    return out


def streak_info(returns: List[Optional[float]], idx: int) -> Dict[str, Any]:
    """连续涨跌：从 idx 往前数连续同号。"""
    if idx < 0 or idx >= len(returns) or returns[idx] is None:
        return {"streak_direction": "unknown", "streak_length": 0, "cumulative_return": 0.0}
    direction = "up" if returns[idx] > 0 else ("down" if returns[idx] < 0 else "flat")
    length = 0
    cum = 1.0
    for i in range(idx, -1, -1):
        r = returns[i]
        if r is None:
            break
        if direction == "up" and r <= 0:
            break
        if direction == "down" and r >= 0:
            break
        if direction == "flat" and r != 0:
            break
        length += 1
        cum *= (1.0 + r)
    return {"streak_direction": direction, "streak_length": length,
            "cumulative_return": cum - 1.0}


def beta_adjusted_residual(entity_ret: List[float], market_ret: List[float],
                           industry_ret: Optional[List[float]],
                           target_idx: int) -> Optional[float]:
    """r_entity = alpha + beta_m*r_market + beta_i*r_industry + residual。

    回归窗口默认 60 日、最低 40 个共同有效样本；输入收益率 Winsorize(1%,99%)；
    样本不足返回 None（不输出 beta-adjusted residual）。同时保留 simple excess。
    """
    start = max(0, target_idx - BETA_REGRESSION_WINDOW + 1)
    mr = market_ret[start:target_idx + 1]
    er = entity_ret[start:target_idx + 1]
    ir = industry_ret[start:target_idx + 1] if industry_ret is not None else None

    pairs = [(e, m, i) for e, m, i in zip(er, mr, ir if ir is not None else [None] * len(mr))
             if e is not None and m is not None and (i is not None if ir is not None else True)]
    if len(pairs) < BETA_MIN_SAMPLES:
        return None
    es = winsorize([p[0] for p in pairs])
    ms = winsorize([p[1] for p in pairs])
    if ir is not None:
        ins = winsorize([p[2] for p in pairs])
    else:
        ins = None

    n = len(es)
    mean_e = sum(es) / n
    mean_m = sum(ms) / n
    var_m = sum((m - mean_m) ** 2 for m in ms) / n
    if var_m == 0:
        return None
    beta_m = sum((e - mean_e) * (m - mean_m) for e, m in zip(es, ms)) / (n * var_m)
    residual_target = None
    if ir is not None:
        mean_i = sum(ins) / n
        var_i = sum((i - mean_i) ** 2 for i in ins) / n
        # 简化两因子 OLS（正规方程）
        x1 = [(m - mean_m) for m in ms]
        x2 = [(i - mean_i) for i in ins]
        y = [(e - mean_e) for e in es]
        s11 = sum(a * a for a in x1)
        s12 = sum(a * b for a, b in zip(x1, x2))
        s22 = sum(b * b for b in x2)
        y1 = sum(a * b for a, b in zip(x1, y))
        y2 = sum(a * b for a, b in zip(x2, y))
        det = s11 * s22 - s12 * s12
        if abs(det) < EPS:
            return None
        b_m = (y1 * s22 - y2 * s12) / det
        b_i = (y2 * s11 - y1 * s12) / det
        a = mean_e - b_m * mean_m - b_i * mean_i
        e_t, m_t, i_t = es[-1], ms[-1], ins[-1]
        residual_target = e_t - (a + b_m * m_t + b_i * i_t)
    else:
        a = mean_e - beta_m * mean_m
        e_t, m_t = es[-1], ms[-1]
        residual_target = e_t - (a + beta_m * m_t)
    return residual_target


# ---------- 检测编排 ----------


@dataclass
class DetectResult:
    observation: AbnormalMoveObservation
    metrics: List[AnomalyMetric]
    abnormal: bool
    reasons: List[str]
    sample_size: int


class AnomalyDetector:
    """确定性异动检测器。"""

    def __init__(self, request: AbnormalMoveRequest,
                 calendar_id: str = "cn-exchange"):
        self.request = request
        self.calendar_id = calendar_id

    # ---------- 检测入口 ----------

    def detect(
        self,
        bars: List[MarketDailyOhlcv],
        benchmarks: Optional[Dict[str, List[MarketDailyOhlcv]]] = None,
        flags: Optional[Dict[str, Any]] = None,
    ) -> DetectResult:
        """检测异动事实。

        bars: entity 的历史日线（升序，含 analysis_date 前后足够样本）
        benchmarks: {"market": [...], "industry": [...], "concept": [...]} 对齐序列
        flags: {"ST": bool, "suspended": bool, "resumption": bool,
                "ex_rights": bool, "ex_dividend": bool, "price_limit": str|None}
        """
        flags = flags or {}
        if not bars:
            raise ValueError("无日线数据，无法检测异动事实")
        bars = sorted(bars, key=lambda b: b.trade_date)
        target = bars[-1]
        trade_date = target.trade_date
        n = len(bars)

        prices = [b.close for b in bars]
        returns = pct_change(prices)
        target_idx = n - 1
        target_ret = returns[target_idx]

        # 样本分级
        sample_status = self._sample_status(n)
        observation = AbnormalMoveObservation(
            observation_id=new_uuid(),
            request_id=self.request.request_id,
            entity_id=self.request.entity_id,
            entity_type=self.request.entity_type,
            window_start=self.request.window_start,
            window_end=self.request.window_end,
            trade_date=trade_date,
            granularity=self.request.granularity,
            provisional=bool(flags.get("provisional", False)),
            market_data_ids=[b.bar_id for b in bars[-1:]],
            data_manifest_ids=[],
            adjustment_method=self._adjustment_method(bars),
            raw_return=target_ret,
            status="ok",
            market_state_flags=[],
        )
        metrics: List[AnomalyMetric] = []
        warnings: List[str] = []
        missing: List[str] = []

        # 特殊状态
        state_flags = self._state_flags(flags, n)
        observation.market_state_flags = state_flags
        if "SUSPENDED" in state_flags:
            observation.status = "suspended_no_move"
            return DetectResult(observation, metrics, abnormal=False,
                                reasons=["停牌日不生成价格异动"], sample_size=n)

        # 历史基线（target 之前，不含 target）
        hist_ret = [r for r in returns[:target_idx] if r is not None]
        hist_prices = prices[:target_idx]

        # --- 绝对收益 ---
        if sample_status in ("full", "robust", "limited"):
            abs_metric = self._metric(
                "absolute_return", target_ret, "pct",
                hist_ret, sample_status, n,
                observation_id=observation.observation_id,
                direction=_direction(target_ret),
            )
            metrics.append(abs_metric)
        else:
            warnings.append("有效样本 < 20：不输出正式历史分位，仅输出原始涨跌")
            observation.missing_data.append("historical_percentile")
            missing.append("historical_percentile")

        # --- 相对收益（benchmarks） ---
        benchmark_ret = self._benchmark_returns(benchmarks, bars)
        rel_metrics = self._relative_metrics(hist_ret, sample_status, n,
                                             benchmark_ret, target_idx, returns,
                                             observation.observation_id)
        metrics.extend(rel_metrics)

        # --- Beta 调整残差 ---
        beta_metric = self._beta_metric(benchmark_ret, returns, target_idx,
                                        sample_status, n,
                                        observation.observation_id)
        if beta_metric is not None:
            metrics.append(beta_metric)
        else:
            missing.append("beta_adjusted_residual")

        # --- 量价指标 ---
        volume_metrics = self._volume_amount_metrics(bars, target_idx, sample_status, n,
                                                     observation.observation_id)
        metrics.extend(volume_metrics)
        amplitude_metrics = self._amplitude_gap_vol_metrics(bars, returns, target_idx,
                                                            sample_status, n,
                                                            observation.observation_id)
        metrics.extend(amplitude_metrics)

        # --- 连续涨跌（事实，不自动成为原因） ---
        streak = streak_info(returns, target_idx)
        if sample_status in ("full", "robust", "limited") and target_ret is not None:
            streak_pct = historical_percentile(
                target_ret, hist_ret) if hist_ret else None
            metrics.append(self._metric(
                "return_streak", target_ret, "pct", hist_ret, sample_status, n,
                observation_id=observation.observation_id,
                direction=_direction(target_ret),
                extra={"streak_direction": streak["streak_direction"],
                       "streak_length": streak["streak_length"],
                       "cumulative_return": round(streak["cumulative_return"], 6),
                       "historical_percentile": round(streak_pct, 2)
                       if streak_pct is not None else None},
            ))

        # --- 换手率（仅来源提供） ---
        turnover = self._turnover_metric(bars, target_idx, sample_status, n,
                                         observation.observation_id)
        if turnover is not None:
            metrics.append(turnover)

        # --- 特异性与成立判定 ---
        metric_by_type = {m.metric_type: m for m in metrics}
        abnormal, reasons = self._decide_abnormal(metric_by_type, state_flags,
                                                  sample_status, flags)
        for m in metrics:  # 回填 observation_id（Schema 必填）
            m.observation_id = observation.observation_id
        observation.metric_ids = [m.metric_id for m in metrics]
        observation.primary_anomaly_types = self._primary_types(metric_by_type, reasons)
        observation.confidence = self._confidence(sample_status, state_flags)
        observation.warnings = warnings
        observation.missing_data = list(dict.fromkeys(missing))
        if not abnormal:
            observation.status = "no_abnormal_move"
        return DetectResult(observation, metrics, abnormal=abnormal,
                            reasons=reasons, sample_size=n)

    # ---------- 辅助 ----------

    def _sample_status(self, n: int) -> str:
        if n < MIN_SAMPLE_LIMITED:
            return "insufficient"
        if n < MIN_SAMPLE_ROBUST:
            return "limited"
        if n < MIN_SAMPLE_FULL:
            return "robust"
        return "full"

    def _adjustment_method(self, bars: List[MarketDailyOhlcv]) -> str:
        """检测复权口径一致性：manifest 由调用方提供；此处按 bars 检查价格单调性提示。"""
        # 简化：从 data_manifest_ids 无法推断，调用方保证一致；不一致由 validator 拦截
        return "none"

    def _state_flags(self, flags: Dict[str, Any], n: int) -> List[str]:
        out: List[str] = []
        if flags.get("suspended"):
            out.append("SUSPENDED")
        if flags.get("resumption"):
            out.append("RESUMPTION")
        if n < MIN_SAMPLE_NEW_LISTING:
            out.append("NEW_LISTING")
        if flags.get("st"):
            out.append("ST")
        if flags.get("price_limit") == "up":
            out.append("PRICE_LIMIT_UP")
        if flags.get("price_limit") == "down":
            out.append("PRICE_LIMIT_DOWN")
        if flags.get("ex_rights"):
            out.append("EX_RIGHTS")
        if flags.get("ex_dividend"):
            out.append("EX_DIVIDEND")
        if flags.get("provisional"):
            out.append("CURRENT_SESSION_NOT_CLOSED")
        if flags.get("mixed_adjustment"):
            out.append("MIXED_ADJUSTMENT")
        return out

    def _metric(self, metric_type: str, value: Optional[float], unit: str,
                history: List[float], sample_status: str, n: int,
                observation_id: str,
                direction: str = "unknown",
                baseline_window: Optional[int] = None,
                benchmark_entity_id: Optional[str] = None,
                cross_pct: Optional[float] = None,
                extra: Optional[Dict[str, Any]] = None) -> AnomalyMetric:
        """构造指标：robust Z / 分位 / severity。"""
        median, mad = robust_stats(history)
        z = robust_z_score(value, median, mad) if (value is not None and median is not None) else None
        pct = historical_percentile(value, history) if value is not None and history else None
        sev = 0
        if value is not None and history:
            if mad == 0:
                # MAD=0：若 x 与中位数一致则无异常；否则按经验分位（0 或 100）判严重度
                if value == median:
                    sev = 0
                else:
                    sev = severity_from_percentile(max(pct, 100.0 - pct))
            else:
                sev = severity_combined(value, history, median, mad)
        warnings = [MAD_ZERO_FALLBACK_PERCENTILE] if (mad == 0 and history) else []
        status = "valid" if sample_status in ("full", "robust", "limited") else "insufficient_sample"
        if value is None:
            status = "missing_input"
        metric = AnomalyMetric(
            metric_id=new_uuid(),
            observation_id=observation_id,
            metric_type=metric_type,  # type: ignore[arg-type]
            value=round(value, 6) if value is not None else None,
            unit=unit,
            direction=direction,  # type: ignore[arg-type]
            benchmark_entity_id=benchmark_entity_id,
            baseline_window=baseline_window or (len(history) if history else 0),
            baseline_method="median_mad",
            baseline_median=round(median, 6) if median is not None else None,
            baseline_mad=round(mad, 6) if mad is not None else None,
            robust_z=round(z, 4) if z is not None else None,
            historical_percentile=round(pct, 2) if pct is not None else None,
            cross_sectional_percentile=cross_pct,
            severity=sev,
            sample_size=n if history else 0,
            minimum_sample_size=MIN_SAMPLE_LIMITED,
            status=status,  # type: ignore[arg-type]
            calculation_version=ANOMALY_RULES_VERSION,
            warnings=warnings,
        )
        if extra:
            for k, v in extra.items():
                if hasattr(metric, k):
                    setattr(metric, k, v)
        return metric

    def _benchmark_returns(self, benchmarks: Optional[Dict[str, List[MarketDailyOhlcv]]],
                           bars: List[MarketDailyOhlcv]) -> Dict[str, List[Optional[float]]]:
        """按 trade_date 对齐基准收益率到 entity 交易日序列（基准自身逐日收益率）。"""
        out: Dict[str, List[Optional[float]]] = {}
        entity_dates = [b.trade_date for b in bars]
        for name, bm_bars in (benchmarks or {}).items():
            bm = sorted(bm_bars, key=lambda b: b.trade_date)
            bm_by_date = {b.trade_date: b.close for b in bm}
            rets: List[Optional[float]] = []
            prev: Optional[float] = None
            for d in entity_dates:
                if d not in bm_by_date:
                    rets.append(None)
                    continue
                cur = bm_by_date[d]
                rets.append((cur / prev - 1.0) if prev else None)
                prev = cur
            out[name] = rets
        return out

    def _relative_metrics(self, hist_ret: List[float], sample_status: str, n: int,
                          benchmark_ret: Dict[str, List[Optional[float]]],
                          target_idx: int, returns: List[Optional[float]],
                          observation_id: str) -> List[AnomalyMetric]:
        metrics = []
        target_ret = returns[target_idx] if target_idx < len(returns) else None
        # 相对收益 = r_entity - r_benchmark（同日）
        for name in ("market", "industry", "concept"):
            bret = benchmark_ret.get(name)
            if bret is None:
                continue
            b_t = bret[target_idx] if target_idx < len(bret) else None
            if b_t is None:
                continue
            excess = (target_ret - b_t) if target_ret is not None else None
            # 相对收益的历史序列：需要历史相对序列——用逐日差重建
            hist_excess = []
            for i in range(target_idx):
                e = returns[i]
                b = bret[i]
                if e is not None and b is not None:
                    hist_excess.append(e - b)
            metric_type = f"{name}_excess_return"
            metrics.append(self._metric(
                metric_type, excess, "pct", hist_excess, sample_status, n,
                observation_id=observation_id,
                direction=_direction(excess),
                baseline_window=BASELINE_WINDOW,
                benchmark_entity_id=f"benchmark:{name}",
            ))
        return metrics

    def _beta_metric(self, benchmark_ret: Dict[str, List[Optional[float]]],
                     returns: List[Optional[float]], target_idx: int,
                     sample_status: str, n: int,
                     observation_id: str) -> Optional[AnomalyMetric]:
        if sample_status != "full":
            return None
        mret = benchmark_ret.get("market")
        if not mret or target_idx >= len(mret):
            return None
        irets = benchmark_ret.get("industry")
        e_ret = [r for r in returns if r is not None]
        m_ret = [r for r in mret if r is not None]
        if len(e_ret) < BETA_MIN_SAMPLES or len(m_ret) < BETA_MIN_SAMPLES:
            return None
        # 用共同有效索引
        aligned_e = []
        aligned_m = []
        aligned_i = []
        for i in range(target_idx + 1):
            e = returns[i]
            m = mret[i]
            if e is None or m is None:
                continue
            aligned_e.append(e)
            aligned_m.append(m)
            aligned_i.append(irets[i] if irets and i < len(irets) else None)
        if len(aligned_e) < BETA_MIN_SAMPLES:
            return None
        has_i = aligned_i and all(x is not None for x in aligned_i)
        residual = beta_adjusted_residual(
            aligned_e, aligned_m, aligned_i if has_i else None, len(aligned_e) - 1)
        if residual is None:
            return None
        hist_res = []
        for k in range(20, len(aligned_e)):
            r = beta_adjusted_residual(aligned_e[:k + 1], aligned_m[:k + 1],
                                       aligned_i[:k + 1] if has_i else None, k)
            if r is not None:
                hist_res.append(r)
        return self._metric(
            "beta_adjusted_residual", residual, "pct", hist_res, sample_status, n,
            observation_id=observation_id,
            direction=_direction(residual),
            baseline_window=BETA_REGRESSION_WINDOW,
            benchmark_entity_id="benchmark:market",
        )

    def _volume_amount_metrics(self, bars: List[MarketDailyOhlcv], target_idx: int,
                               sample_status: str, n: int,
                               observation_id: str) -> List[AnomalyMetric]:
        """量/额异常（任务书 7.5）。

        volume_ratio = volume_t / median(volume_20)。value 与历史序列同口径
        （滚动 20 日 median 的 ratio 序列），robust Z / 分位 / severity 可复算。
        成交额缺失 -> amount_anomaly.status=missing_input，不从价格/量估算。
        """
        metrics = []
        volumes = [b.volume for b in bars]
        target_v = volumes[target_idx]
        hist_v = volumes[:target_idx]
        if len(hist_v) >= SHORT_WINDOW:
            ratios = []
            for i in range(SHORT_WINDOW, target_idx):
                med = statistics.median(volumes[i - SHORT_WINDOW:i])
                ratios.append(volumes[i] / med if med else 1.0)
            med20 = statistics.median(hist_v[-SHORT_WINDOW:])
            value = (target_v / med20) if med20 else 1.0
            metrics.append(self._metric(
                "volume_anomaly", value, "ratio", ratios, sample_status, n,
                observation_id=observation_id,
                direction=_direction(value - 1.0),
                baseline_window=SHORT_WINDOW,
            ))
        amounts = [b.amount for b in bars if b.amount is not None]
        if amounts and bars[target_idx].amount is not None:
            target_a = bars[target_idx].amount
            hist_a = [b.amount for b in bars[:target_idx] if b.amount is not None]
            if len(hist_a) >= SHORT_WINDOW:
                ratios_a = []
                for i in range(SHORT_WINDOW, len(hist_a)):
                    med = statistics.median(hist_a[i - SHORT_WINDOW:i])
                    ratios_a.append(hist_a[i] / med if med else 1.0)
                med20_a = statistics.median(hist_a[-SHORT_WINDOW:])
                value_a = (target_a / med20_a) if med20_a else 1.0
                metrics.append(self._metric(
                    "amount_anomaly", value_a, "ratio", ratios_a, sample_status, n,
                    observation_id=observation_id,
                    direction=_direction(value_a - 1.0),
                    baseline_window=SHORT_WINDOW,
                ))
        elif bars[target_idx].amount is None:
            metrics.append(self._metric(
                "amount_anomaly", None, "ratio", [], sample_status, n,
                observation_id=observation_id,
                direction="unknown"))
        return metrics

    def _amplitude_gap_vol_metrics(self, bars: List[MarketDailyOhlcv],
                                   returns: List[Optional[float]], target_idx: int,
                                   sample_status: str, n: int,
                                   observation_id: str) -> List[AnomalyMetric]:
        metrics = []
        prev_close = bars[target_idx - 1].close if target_idx > 0 else None
        b = bars[target_idx]
        if prev_close and prev_close > 0:
            amplitude = (b.high - b.low) / prev_close
            hist_amp = []
            for i in range(1, target_idx):
                pc = bars[i - 1].close
                if pc and pc > 0:
                    hist_amp.append((bars[i].high - bars[i].low) / pc)
            metrics.append(self._metric(
                "amplitude_anomaly", amplitude, "pct", hist_amp, sample_status, n,
                observation_id=observation_id,
                direction="positive" if amplitude > 0 else "neutral",
                baseline_window=min(VOLATILITY_BASELINE, len(hist_amp)),
            ))
            gap = (b.open / prev_close - 1.0)
            hist_gap = []
            for i in range(1, target_idx):
                pc = bars[i - 1].close
                if pc and pc > 0:
                    hist_gap.append(bars[i].open / pc - 1.0)
            metrics.append(self._metric(
                "gap", gap, "pct", hist_gap, sample_status, n,
                observation_id=observation_id,
                direction=_direction(gap),
                baseline_window=min(VOLATILITY_BASELINE, len(hist_gap)),
            ))
        rv = rolling_returns(returns)
        rv_t = rv[target_idx]
        hist_rv = [r for r in rv[:target_idx] if r is not None]
        if rv_t is not None:
            metrics.append(self._metric(
                "volatility_anomaly", rv_t, "pct", hist_rv, sample_status, n,
                observation_id=observation_id,
                direction="positive",
                baseline_window=VOLATILITY_BASELINE,
            ))
        return metrics

    def _turnover_metric(self, bars: List[MarketDailyOhlcv], target_idx: int,
                         sample_status: str, n: int,
                         observation_id: str) -> Optional[AnomalyMetric]:
        """换手率：仅来源提供并验证后计算；缺失时输出 UNKNOWN（missing_input）。"""
        b = bars[target_idx]
        if not hasattr(b, "turnover_rate") or getattr(b, "turnover_rate", None) is None:
            return self._metric("turnover_anomaly", None, "pct", [], sample_status, n,
                                observation_id=observation_id,
                                direction="unknown")
        return None

    def _decide_abnormal(self, metric_by_type: Dict[str, AnomalyMetric],
                         state_flags: List[str], sample_status: str,
                         flags: Dict[str, Any]) -> tuple:
        """综合异动成立规则（任务书 7.11）。"""
        reasons: List[str] = []
        if sample_status == "insufficient":
            return False, ["有效样本不足，不判定异动成立"]
        ret_metrics = [m for k, m in metric_by_type.items()
                       if k in ("absolute_return", "market_excess_return",
                                "industry_excess_return", "concept_excess_return")]
        vol_metrics = [m for k, m in metric_by_type.items()
                       if k in ("volume_anomaly", "amount_anomaly",
                                "amplitude_anomaly", "volatility_anomaly")]
        # A: 收益/相对收益 severity>=3 且量/额/振幅/波动至少一个 severity>=2
        if any(m.severity >= MOVE_RETURN_SEVERITY for m in ret_metrics) and \
           any(m.severity >= MOVE_VOLUME_SEVERITY for m in vol_metrics):
            reasons.append("A：收益/相对收益 severity>=3 且量价指标 severity>=2")
        # B: 任一主指标 severity=5
        if any(m.severity >= MOVE_ABSOLUTE_SEVERITY for m in ret_metrics + vol_metrics):
            reasons.append("B：主指标 severity=5")
        # C: 特殊状态（复牌/涨跌停/跳空）且相对市场或行业 severity>=3
        state_special = any(f in state_flags for f in
                            ("RESUMPTION", "PRICE_LIMIT_UP", "PRICE_LIMIT_DOWN"))
        rel_metrics = [m for k, m in metric_by_type.items()
                       if k in ("market_excess_return", "industry_excess_return")]
        if state_special and any(m.severity >= MOVE_STATE_SEVERITY for m in rel_metrics):
            reasons.append("C：特殊状态（复牌/涨跌停）且相对基准 severity>=3")
        return bool(reasons), reasons

    def _primary_types(self, metric_by_type: Dict[str, AnomalyMetric],
                       reasons: List[str]) -> List[str]:
        if not reasons:
            return []
        out = []
        for m in metric_by_type.values():
            if m.severity >= 3:
                out.append(m.metric_type)
        return out[:6]

    def _confidence(self, sample_status: str, state_flags: List[str]) -> Optional[float]:
        base = {"full": 0.9, "robust": 0.8, "limited": 0.6, "insufficient": 0.3}[sample_status]
        if "NEW_LISTING" in state_flags:
            base = min(base, 0.4)
        if "MIXED_ADJUSTMENT" in state_flags:
            base = min(base, 0.4)
        return round(base, 2)


def _direction(value: Optional[float]) -> str:
    if value is None:
        return "unknown"
    if value > 0:
        return "positive"
    if value < 0:
        return "negative"
    return "neutral"
