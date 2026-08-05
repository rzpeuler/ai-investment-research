"""基准选择（Phase 3 任务书 8 节）。

- 市场基准：按证券板块和配置表确定（registry/market_benchmarks.yaml），
  不得把当前表现最接近的指数自动选作市场基准
- 行业/概念候选：七维评分（权重固定，总分 100）+ 资格规则 + 防事后选择
  （pre_window_subtotal >= 45；概念关系 valid_from <= window_start；
   异动期联动只用于确认，不得改变概念历史有效期）
- 降级链：市场+行业+概念 -> 市场+行业 -> 仅市场 -> BENCHMARK_INSUFFICIENT，
  每次降级必须进入报告
- information_cutoff 等于异动窗口开始，防止事后选择
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from research_os.abnormal_move.config import BENCHMARK_RULES_VERSION
from research_os.models import (
    BenchmarkCandidate,
    BenchmarkSelection,
    MarketDailyOhlcv,
)
from research_os.utils.id import new_uuid

# ---------- 权重（任务书 8.2 表，总分 100） ----------

BENCHMARK_WEIGHTS: Dict[str, float] = {
    "stable_industry": 25,
    "main_business": 20,
    "supply_chain": 10,
    "preexisting_concept": 10,
    "historical_correlation": 15,
    "event_window_linkage": 10,
    "current_event_relevance": 10,
}

# 防事后选择维度：窗口开始前就存在的信息
PRE_WINDOW_DIMENSIONS = (
    "stable_industry", "main_business", "supply_chain",
    "preexisting_concept", "historical_correlation",
)

MIN_TOTAL_INDUSTRY = 60.0          # 主行业基准总分门槛（8.3）
MIN_STABLE_BUSINESS_INDUSTRY = 25.0  # stable+main 加权分门槛
MIN_TOTAL_CONCEPT = 65.0           # 辅助概念基准总分门槛
MIN_PRE_WINDOW_SUBTOTAL = 45.0     # 防事后选择门槛
MIN_PRE_WINDOW_CONCEPT = 45.0

CORRELATION_WINDOW = 60            # 历史相关性窗口（交易日）
CORRELATION_MIN_SAMPLES = 30       # 相关性最低共同样本

FALLBACK_STATUSES = ["full", "no_concept", "market_only", "insufficient"]


def board_of(entity_id: str) -> str:
    """按证券代码推断板块（main/gem/star）。非公司实体返回 main。"""
    code = entity_id.split(":")[-1].split(".")[0]
    if code.startswith(("300", "301")):
        return "gem"
    if code.startswith(("688", "689")):
        return "star"
    return "main"


def _dimension_score(raw: int, weight: float) -> float:
    return raw / 5.0 * weight


@dataclass
class SelectResult:
    candidates: List[BenchmarkCandidate]
    selection: BenchmarkSelection
    fallback_status: str
    rationale: List[str]
    market_benchmark_id: Optional[str] = None
    industry_benchmark_id: Optional[str] = None
    concept_benchmark_ids: List[str] = field(default_factory=list)


class MarketBenchmarkRegistry:
    """市场基准注册表（任务书 8.1）。"""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else Path("registry") / "market_benchmarks.yaml"

    def load(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(f"市场基准注册表不存在: {self.path}")
        with self.path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return data.get("market_benchmarks", [])

    def select_for_board(self, board: str) -> Optional[str]:
        """按板块选择市场基准。

        优先专用板块基准（创业板指/科创50 等）；无专用时回退全市场默认（沪深300）。
        不得把当前表现最接近的指数自动选作市场基准。
        """
        benchmarks = self.load()
        specialized = [b for b in benchmarks
                       if board in b.get("board_scope", []) and "默认" not in b.get("notes", "")]
        if specialized:
            return specialized[0]["benchmark_entity_id"]
        default = [b for b in benchmarks
                   if board in b.get("board_scope", []) and "默认" in b.get("notes", "")]
        return default[0]["benchmark_entity_id"] if default else None


class BenchmarkSelector:
    """行业/概念基准评分与选择。"""

    def __init__(self, registry: Optional[MarketBenchmarkRegistry] = None):
        self.registry = registry or MarketBenchmarkRegistry()

    # ---------- 相关性评分 ----------

    @staticmethod
    def _pearson(x: List[float], y: List[float]) -> Optional[float]:
        n = len(x)
        if n < CORRELATION_MIN_SAMPLES:
            return None
        mean_x = sum(x) / n
        mean_y = sum(y) / n
        cov = sum((a - mean_x) * (b - mean_y) for a, b in zip(x, y))
        var_x = sum((a - mean_x) ** 2 for a in x)
        var_y = sum((b - mean_y) ** 2 for b in y)
        if var_x == 0 or var_y == 0:
            return None
        return cov / math.sqrt(var_x * var_y)

    def _correlation_score(self, entity_bars: List[MarketDailyOhlcv],
                           bench_bars: List[MarketDailyOhlcv],
                           window_start: str) -> tuple:
        """窗口前 CORRELATION_WINDOW 日收益率相关 -> (score 0-5, sample_size)。"""
        e = sorted(entity_bars, key=lambda b: b.trade_date)
        b = sorted(bench_bars, key=lambda b: b.trade_date)
        b_by_date = {x.trade_date: x.close for x in b}
        # 只取窗口开始前的数据
        pairs = []
        prev_e: Optional[float] = None
        prev_b: Optional[float] = None
        for bar in e:
            if bar.trade_date >= window_start:
                break
            bc = b_by_date.get(bar.trade_date)
            if bc is None:
                prev_b = None
                continue
            if prev_e is not None and prev_b is not None and prev_b > 0:
                r_e = bar.close / prev_e - 1.0
                r_b = bc / prev_b - 1.0
                pairs.append((r_e, r_b))
            prev_e = bar.close
            prev_b = bc
        if len(pairs) < CORRELATION_MIN_SAMPLES:
            return 0, len(pairs)
        corr = self._pearson([p[0] for p in pairs], [p[1] for p in pairs])
        if corr is None:
            return 0, len(pairs)
        abs_c = abs(corr)
        score = 5 if abs_c >= 0.8 else 4 if abs_c >= 0.7 else 3 if abs_c >= 0.6 \
            else 2 if abs_c >= 0.4 else 1 if abs_c >= 0.2 else 0
        return score, len(pairs)

    @staticmethod
    def _event_window_linkage(entity_bars: List[MarketDailyOhlcv],
                              bench_bars: List[MarketDailyOhlcv],
                              window_start: str, window_end: str) -> int:
        """异动期联动（仅确认用，不改变资格）：窗口内方向一致性 -> 0-5。"""
        b_by_date = {x.trade_date: x.close for x in bench_bars}
        e = sorted(entity_bars, key=lambda x: x.trade_date)
        same = 0
        total = 0
        prev_e: Optional[float] = None
        prev_b: Optional[float] = None
        for bar in e:
            if bar.trade_date < window_start or bar.trade_date > window_end:
                prev_e = bar.close
                prev_b = b_by_date.get(bar.trade_date)
                continue
            bc = b_by_date.get(bar.trade_date)
            if bc is None or prev_e is None or prev_b is None or prev_b <= 0:
                prev_e = bar.close
                prev_b = bc
                continue
            r_e = bar.close / prev_e - 1.0
            r_b = bc / prev_b - 1.0
            if r_e != 0 and r_b != 0:
                total += 1
                if (r_e > 0) == (r_b > 0):
                    same += 1
            prev_e = bar.close
            prev_b = bc
        if total == 0:
            return 0
        ratio = same / total
        return 5 if ratio >= 0.9 else 4 if ratio >= 0.8 else 3 if ratio >= 0.7 \
            else 2 if ratio >= 0.5 else 1 if ratio >= 0.3 else 0

    # ---------- 主入口 ----------

    def select(
        self,
        request,
        entity_id: str,
        candidate_inputs: List[Dict[str, Any]],
        entity_bars: List[MarketDailyOhlcv],
        benchmark_bars: Dict[str, List[MarketDailyOhlcv]],
        observation_id: str,
    ) -> SelectResult:
        """选择市场/行业/概念基准。

        candidate_inputs: 行业/概念候选预置关系（维度分 0-5、valid_from/to、
                          benchmark_type、benchmark_entity_id）
        benchmark_bars: {benchmark_entity_id: bars}
        observation_id: 关联的 AbnormalMoveObservation UUID（Schema 必填）
        """
        request_id = request.request_id
        window_start = request.window_start
        window_end = request.window_end
        board = board_of(entity_id)

        market_id = self.registry.select_for_board(board)
        candidates: List[BenchmarkCandidate] = []
        rationale: List[str] = []

        for inp in candidate_inputs:
            btype = inp["benchmark_type"]
            beid = inp["benchmark_entity_id"]
            bbars = benchmark_bars.get(beid, [])
            corr_score, corr_n = self._correlation_score(entity_bars, bbars, window_start)
            linkage = self._event_window_linkage(entity_bars, bbars, window_start, window_end)

            scores = {
                "stable_industry": int(inp.get("stable_industry_score", 0)),
                "main_business": int(inp.get("main_business_score", 0)),
                "supply_chain": int(inp.get("supply_chain_score", 0)),
                "preexisting_concept": int(inp.get("preexisting_concept_score", 0)),
                "historical_correlation": corr_score,
                "event_window_linkage": linkage,
                "current_event_relevance": int(inp.get("current_event_relevance_score", 0)),
            }
            pre_window = sum(
                _dimension_score(scores[d], BENCHMARK_WEIGHTS[d])
                for d in PRE_WINDOW_DIMENSIONS
            )
            total = sum(_dimension_score(scores[d], BENCHMARK_WEIGHTS[d]) for d in BENCHMARK_WEIGHTS)

            exclusion: List[str] = []
            if btype == "concept":
                vf = inp.get("relationship_valid_from")
                if vf and vf > window_start:
                    exclusion.append(f"概念关系 valid_from({vf}) 晚于窗口开始({window_start})，禁止事后选择")
            if pre_window < MIN_PRE_WINDOW_SUBTOTAL:
                exclusion.append(f"窗口前已知关系小计 {pre_window:.1f} < {MIN_PRE_WINDOW_SUBTOTAL}，禁止事后选择")
            if btype == "industry" and total >= MIN_TOTAL_INDUSTRY:
                stable_business = (_dimension_score(scores["stable_industry"], 25)
                                   + _dimension_score(scores["main_business"], 20))
                if stable_business < MIN_STABLE_BUSINESS_INDUSTRY:
                    exclusion.append(f"稳定行业+主营加权 {stable_business:.1f} < {MIN_STABLE_BUSINESS_INDUSTRY}")
            if btype == "concept" and total < MIN_TOTAL_CONCEPT:
                exclusion.append(f"概念基准总分 {total:.1f} < {MIN_TOTAL_CONCEPT}")
            if btype == "industry" and total < MIN_TOTAL_INDUSTRY:
                exclusion.append(f"行业基准总分 {total:.1f} < {MIN_TOTAL_INDUSTRY}")

            candidate = BenchmarkCandidate(
                benchmark_candidate_id=new_uuid(),
                request_id=request_id,
                subject_entity_id=entity_id,
                benchmark_entity_id=beid,
                benchmark_type=btype,  # type: ignore[arg-type]
                relationship_valid_from=inp.get("relationship_valid_from"),
                relationship_valid_to=inp.get("relationship_valid_to"),
                stable_industry_score=scores["stable_industry"],
                main_business_score=scores["main_business"],
                supply_chain_score=scores["supply_chain"],
                preexisting_concept_score=scores["preexisting_concept"],
                historical_correlation_score=corr_score,
                event_window_linkage_score=linkage,
                current_event_relevance_score=scores["current_event_relevance"],
                pre_window_subtotal=round(pre_window, 1),
                total_score=round(total, 1),
                correlation_window=CORRELATION_WINDOW,
                correlation_sample_size=corr_n,
                event_window_breadth=None,
                eligible=not exclusion,
                exclusion_reasons=exclusion,
                confidence=0.9 if not exclusion else 0.3,
            )
            candidates.append(candidate)

        eligible = [c for c in candidates if c.eligible]
        industry_eligible = [c for c in eligible if c.benchmark_type == "industry"]
        concept_eligible = [c for c in eligible if c.benchmark_type == "concept"]
        industry_top = max(industry_eligible, key=lambda c: c.total_score) if industry_eligible else None
        concepts_top = sorted(concept_eligible, key=lambda c: c.total_score, reverse=True)

        industry_id = industry_top.benchmark_entity_id if industry_top else None
        concept_ids = [c.benchmark_entity_id for c in concepts_top[:2]]

        # 降级链（任务书 8.4）
        fallback_status = "full"
        if not concept_ids and industry_id:
            fallback_status = "no_concept"
            rationale.append("无合格概念基准，降级为 市场+行业")
        if not industry_id:
            fallback_status = "market_only"
            rationale.append("无合格行业基准，降级为 仅市场")
        if market_id is None and not industry_id:
            fallback_status = "insufficient"
            rationale.append("市场与行业基准均缺失，BENCHMARK_INSUFFICIENT")

        information_cutoff = f"{window_start}T00:00:00"
        selection = BenchmarkSelection(
            benchmark_selection_id=new_uuid(),
            request_id=request_id,
            observation_id=observation_id,
            market_benchmark_id=market_id,
            primary_industry_benchmark_id=industry_id,
            auxiliary_concept_benchmark_ids=concept_ids,
            peer_basket_id=None,
            selected_at=datetime.now().isoformat(timespec="seconds"),
            information_cutoff=information_cutoff,
            scoring_version=BENCHMARK_RULES_VERSION,
            candidate_ids=[c.benchmark_candidate_id for c in candidates],
            fallback_status=fallback_status,
            selection_rationale=rationale,
            confidence=0.9 if fallback_status == "full" else 0.6,
            missing_data=["industry_benchmark"] if not industry_id else [],
        )
        return SelectResult(
            candidates=candidates, selection=selection,
            fallback_status=fallback_status, rationale=rationale,
            market_benchmark_id=market_id,
            industry_benchmark_id=industry_id,
            concept_benchmark_ids=concept_ids,
        )
