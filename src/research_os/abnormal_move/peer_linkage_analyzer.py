"""板块联动与个股特异性（Phase 3 任务书 7.9-7.10 节）。

- 有效同行集合：advancing_ratio / declining_ratio / peer_median_return /
  peer_return_dispersion / subject_cross_sectional_percentile /
  same_direction_abnormal_count
- 最低同行数：行业 10、概念 8；不足时写明样本不足，不得用两三只股票宣称板块共振
- 个股特异性：abs(industry_excess) severity>=4 或 横截面分位>=97.5% 且板块
  中位收益 severity<=1 或 beta_adjusted_residual severity>=4
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from research_os.abnormal_move.anomaly_detector import (
    historical_percentile,
    pct_change,
    robust_stats,
    robust_z_score,
    severity_from_percentile,
)
from research_os.abnormal_move.config import (
    IDIOSYNCRATIC_CROSS_SECTIONAL_PCT,
    IDIOSYNCRATIC_EXCESS_SEVERITY,
    IDIOSYNCRATIC_PEER_MEDIAN_SEVERITY,
    MIN_PEERS_CONCEPT,
    MIN_PEERS_INDUSTRY,
)
from research_os.models import (
    AbnormalMoveObservation,
    AnomalyMetric,
    MarketDailyOhlcv,
    PeerMove,
)
from research_os.utils.id import new_uuid


@dataclass
class LinkageResult:
    peer_moves: List[PeerMove]
    metrics: List[AnomalyMetric]
    sample_ok: bool
    effective_peers: int
    advancing_ratio: Optional[float]
    declining_ratio: Optional[float]
    peer_median_return: Optional[float]
    subject_cross_sectional_percentile: Optional[float]
    same_direction_abnormal_count: int
    idiosyncratic: bool
    reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class PeerLinkageAnalyzer:
    """板块联动分析。"""

    def min_peers_for(self, entity_type: str) -> int:
        return MIN_PEERS_INDUSTRY if entity_type == "company" else MIN_PEERS_CONCEPT

    def analyze(
        self,
        observation: AbnormalMoveObservation,
        peer_bars: Dict[str, List[MarketDailyOhlcv]],
        metric_by_type: Optional[Dict[str, AnomalyMetric]] = None,
    ) -> LinkageResult:
        """分析板块联动。

        peer_bars: {peer_entity_id: bars}（每个 peer 的完整历史，最后一天为异动日）
        metric_by_type: detector 输出的指标（用于特异性判定）
        """
        metric_by_type = metric_by_type or {}
        min_peers = self.min_peers_for(observation.entity_type)
        effective = {k: v for k, v in peer_bars.items() if v}
        n = len(effective)
        sample_ok = n >= min_peers
        warnings: List[str] = []
        reasons: List[str] = []
        if not sample_ok:
            warnings.append(
                f"有效同行数 {n} < 最低要求 {min_peers}"
                f"（{'行业' if observation.entity_type == 'company' else '概念'}），"
                "不得宣称板块共振"
            )

        peer_moves: List[PeerMove] = []
        returns: List[float] = []
        for pid, bars in effective.items():
            bars = sorted(bars, key=lambda b: b.trade_date)
            if len(bars) < 2:
                continue
            ret = bars[-1].close / bars[-2].close - 1.0
            returns.append(ret)
            # peer 自身 severity：用其历史 robust 统计
            hist = [bars[i].close / bars[i - 1].close - 1.0
                    for i in range(1, len(bars) - 1)]
            sev = 0
            z = None
            if len(hist) >= 20 and hist:
                med, mad = robust_stats(hist)
                if mad == 0:
                    pct = historical_percentile(ret, hist)
                    sev = 0 if ret == med else severity_from_percentile(max(pct, 100.0 - pct))
                else:
                    z = robust_z_score(ret, med, mad)
                    pct = historical_percentile(ret, hist)
                    sev = max(severity_from_percentile(max(pct, 100.0 - pct)),
                              _sev_z(z) if z is not None else 0)
            peer_moves.append(PeerMove(
                peer_entity_id=pid,
                peer_name="",
                return_value=round(ret, 6),
                robust_z=round(z, 4) if z is not None else None,
                severity=sev,
                same_direction=(ret > 0) == (observation.raw_return or 0) > 0,
                abnormal=sev >= 3,
                note="",
            ))

        if not returns:
            return LinkageResult(
                peer_moves=[], metrics=[], sample_ok=False, effective_peers=0,
                advancing_ratio=None, declining_ratio=None,
                peer_median_return=None, subject_cross_sectional_percentile=None,
                same_direction_abnormal_count=0, idiosyncratic=False,
                reasons=reasons, warnings=warnings,
            )

        advancing = sum(1 for r in returns if r > 0) / len(returns)
        declining = sum(1 for r in returns if r < 0) / len(returns)
        median_ret = statistics.median(returns)
        dispersion = statistics.median([abs(r - median_ret) for r in returns])
        subject_ret = observation.raw_return
        cross_pct = historical_percentile(subject_ret, returns) if subject_ret is not None else None
        subject_dir = (subject_ret or 0) > 0
        same_abnormal = sum(1 for pm in peer_moves
                            if pm.abnormal and pm.same_direction == subject_dir)

        metrics: List[AnomalyMetric] = []
        obs_id = observation.observation_id
        metrics.append(AnomalyMetric(
            metric_id=new_uuid(), observation_id=obs_id,
            metric_type="peer_breadth",  # type: ignore[arg-type]
            value=round(advancing, 4), unit="ratio",
            direction="positive" if advancing >= 0.5 else "negative",
            benchmark_entity_id=None, baseline_window=0,
            baseline_method="cross_section", baseline_median=None,
            baseline_mad=None, robust_z=None,
            historical_percentile=None,
            cross_sectional_percentile=round(cross_pct, 2) if cross_pct is not None else None,
            severity=_breadth_severity(advancing), sample_size=n,
            minimum_sample_size=min_peers,
            status="valid" if sample_ok else "insufficient_sample",
            calculation_version="peer.v1",
            evidence_ids=[], warnings=warnings[:1] if not sample_ok else [],
            missing_data=[],
        ))
        metrics.append(AnomalyMetric(
            metric_id=new_uuid(), observation_id=obs_id,
            metric_type="peer_median_return",  # type: ignore[arg-type]
            value=round(median_ret, 6), unit="pct",
            direction="positive" if median_ret > 0 else ("negative" if median_ret < 0 else "neutral"),
            benchmark_entity_id=None, baseline_window=0,
            baseline_method="cross_section", baseline_median=None,
            baseline_mad=round(dispersion, 6), robust_z=None,
            historical_percentile=None, cross_sectional_percentile=None,
            severity=_median_severity(median_ret), sample_size=n,
            minimum_sample_size=min_peers,
            status="valid" if sample_ok else "insufficient_sample",
            calculation_version="peer.v1",
            evidence_ids=[], warnings=[], missing_data=[],
        ))

        # 个股特异性（任务书 7.10）
        idiosyncratic, idio_reasons = self._idiosyncratic(
            metric_by_type, cross_pct, median_ret, sample_ok)
        reasons.extend(idio_reasons)
        if idiosyncratic:
            metrics.append(AnomalyMetric(
                metric_id=new_uuid(), observation_id=obs_id,
                metric_type="idiosyncratic_move",  # type: ignore[arg-type]
                value=1.0, unit="flag",
                direction="positive" if subject_dir else "negative",
                benchmark_entity_id=None, baseline_window=0,
                baseline_method="rule_7_10", baseline_median=None,
                baseline_mad=None, robust_z=None,
                historical_percentile=None,
                cross_sectional_percentile=round(cross_pct, 2) if cross_pct is not None else None,
                severity=4, sample_size=n,
                minimum_sample_size=min_peers,
                status="valid", calculation_version="peer.v1",
                evidence_ids=[], warnings=[], missing_data=[],
            ))

        return LinkageResult(
            peer_moves=peer_moves, metrics=metrics, sample_ok=sample_ok,
            effective_peers=n, advancing_ratio=round(advancing, 4),
            declining_ratio=round(declining, 4),
            peer_median_return=round(median_ret, 6),
            subject_cross_sectional_percentile=round(cross_pct, 2) if cross_pct is not None else None,
            same_direction_abnormal_count=same_abnormal,
            idiosyncratic=idiosyncratic, reasons=reasons, warnings=warnings,
        )

    def _idiosyncratic(self, metric_by_type: Dict[str, AnomalyMetric],
                       cross_pct: Optional[float],
                       median_ret: Optional[float],
                       sample_ok: bool) -> tuple:
        reasons: List[str] = []
        ind_excess = metric_by_type.get("industry_excess_return")
        beta_resid = metric_by_type.get("beta_adjusted_residual")
        if ind_excess and ind_excess.severity >= IDIOSYNCRATIC_EXCESS_SEVERITY:
            reasons.append("行业相对收益 severity>=4")
        if cross_pct is not None and cross_pct >= IDIOSYNCRATIC_CROSS_SECTIONAL_PCT:
            if median_ret is not None:
                med_sev = _median_severity(median_ret)
                if med_sev <= IDIOSYNCRATIC_PEER_MEDIAN_SEVERITY:
                    reasons.append(
                        f"横截面分位 {cross_pct:.1f}% >= 97.5% 且板块中位收益 severity<=1")
        if beta_resid and beta_resid.severity >= IDIOSYNCRATIC_EXCESS_SEVERITY:
            reasons.append("beta 调整残差 severity>=4")
        return bool(reasons), reasons


def _sev_z(abs_z: float) -> int:
    if abs_z >= 2.58:
        return 5
    if abs_z >= 2.24:
        return 4
    if abs_z >= 1.96:
        return 3
    if abs_z >= 1.65:
        return 2
    if abs_z >= 1.28:
        return 1
    return 0


def _breadth_severity(advancing: float) -> int:
    """广度 severity：>0.8 极强、>0.7 强、>0.6 中、>0.5 弱。"""
    if advancing >= 0.9:
        return 5
    if advancing >= 0.8:
        return 4
    if advancing >= 0.7:
        return 3
    if advancing >= 0.6:
        return 2
    if advancing >= 0.5:
        return 1
    return 0


def _median_severity(median_ret: Optional[float]) -> int:
    if median_ret is None:
        return 0
    abs_m = abs(median_ret)
    if abs_m >= 0.05:
        return 4
    if abs_m >= 0.03:
        return 3
    if abs_m >= 0.015:
        return 2
    if abs_m >= 0.005:
        return 1
    return 0
