"""异动分析黄金测试 fixture（Phase 3 任务书 20 节）。

构造确定性行情序列与事件池；离线、可复算。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.event_window_retriever import RetrievedItem
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    MarketDailyOhlcv,
)
from research_os.utils.id import new_uuid

UUID = "12345678-1234-1234-1234-123456789abc"


def bar(d: date, close: float, volume: float = 1000.0,
        open_: Optional[float] = None, high: Optional[float] = None,
        low: Optional[float] = None) -> MarketDailyOhlcv:
    o = open_ if open_ is not None else close
    h = high if high is not None else max(o, close) * 1.01
    l = low if low is not None else min(o, close) * 0.99
    return MarketDailyOhlcv(
        bar_id=new_uuid(), symbol="600519.SH", trade_date=d.isoformat(),
        open=o, high=h, low=l, close=close, volume=volume,
    )


def series_to(start: date, end: date, base: float = 10.0, drift: float = 0.001,
              noise: float = 0.0005, move: float = 0.0,
              vol_mult: float = 1.0) -> List[MarketDailyOhlcv]:
    """从 start 生成工作日序列直到 end（含）。最后一天可施加 move 与放量。"""
    bars = []
    d = start
    price = base
    i = 0
    while d <= end:
        while d.weekday() >= 5:
            d += timedelta(days=1)
        is_last = d == end
        jump = price * move if is_last else 0.0
        pattern = (i % 3) - 1
        bars.append(bar(d, price + jump,
                        volume=1000 * vol_mult if is_last else 1000))
        price *= (1 + drift + pattern * noise)
        d += timedelta(days=1)
        i += 1
    return bars


def series(start: date, n: int, base: float = 10.0, drift: float = 0.001,
           vol: float = 0.0, noise: float = 0.0005) -> List[MarketDailyOhlcv]:
    """n 个连续工作日序列；最后一天可用 vol 施加跳变。"""
    bars = []
    d = start
    price = base
    for i in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        jump = price * vol if i == n - 1 else 0.0
        pattern = (i % 3) - 1
        bars.append(bar(d, price + jump, volume=3000 if i == n - 1 and vol else 1000))
        price *= (1 + drift + pattern * noise)
        d += timedelta(days=1)
    return bars


END = date(2026, 8, 5)


def big_move_series(start: date, n: int = 70, move: float = 0.095,
                    vol_mult: float = 3.0) -> List[MarketDailyOhlcv]:
    """最后一天大涨/大跌 + 放量（异动成立场景），最后一天固定为 2026-08-05。"""
    return series_to(start, END, move=move, vol_mult=vol_mult)


def flat_series(start: date, n: int = 70) -> List[MarketDailyOhlcv]:
    """平稳序列（无异动），最后一天 2026-08-05。"""
    return series_to(start, END, move=0.0)


def short_series(start: date, n: int = 10) -> List[MarketDailyOhlcv]:
    """样本不足序列（新股，<20 交易日）。"""
    return series_to(start, date(2026, 5, 15))


def request(analysis_date: str = "2026-08-05") -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID, task_id=UUID, entity_id="600519.SH",
        entity_type="company", analysis_date=analysis_date,
        window_start="2026-08-01", window_end=analysis_date,
        as_of=f"{analysis_date}T20:00:00",
    )


def observation(**kw) -> AbnormalMoveObservation:
    base = dict(
        observation_id="22222222-2222-2222-2222-222222222222",
        request_id=UUID, entity_id="600519.SH", entity_type="company",
        window_start="2026-08-01", window_end="2026-08-05",
        trade_date="2026-08-05", raw_return=0.095,
        move_start_at="2026-08-05T09:30:00", move_end_at="2026-08-05T15:00:00",
        primary_anomaly_types=["absolute_return"],
    )
    base.update(kw)
    return AbnormalMoveObservation(**base)


def event(title: str, source_id: str = "cninfo",
          published_at: str = "2026-08-04T09:00:00",
          entities: Optional[List[str]] = None,
          layer: int = 1, url: str = "https://example.com/x") -> RetrievedItem:
    return RetrievedItem(
        item_id=new_uuid(), layer=layer, kind="raw_item", source_id=source_id,
        title=title, published_at=published_at, retrieved_at=published_at,
        url=url, excerpt=f"{title}（摘录）",
        entities=entities or ["company:600519.SH"],
    )


# ---------- 黄金案例定义 ----------

CASES: Dict[str, Dict[str, Any]] = {
    # === 20.1 可明确归因 ===
    "announcement_direct_trigger": {
        "category": "attributable",
        "bars": "big_move",
        "events": [event("贵州茅台发布业绩预增公告", published_at="2026-08-04T09:00:00")],
        "expected_status": "EXPLAINED",
        "allowed_categories": ["direct_trigger"],
        "forbidden_categories": ["after_the_fact_explanation"],
        "min_independent_evidence": 1,
        "confidence_range": (0.5, 1.0),
    },
    "industry_policy_resonance": {
        "category": "attributable",
        "bars": "big_move",
        "events": [event("白酒行业税收政策调整落地", published_at="2026-08-04T09:00:00"),
                   event("白酒板块集体上涨", source_id="cls", published_at="2026-08-04T10:00:00")],
        # 政策 + 板块共振双候选均高分且分差<8 -> 多原因共同作用
        "expected_status": "MULTI_CAUSE",
        "allowed_categories": ["direct_trigger", "industry_or_theme_resonance"],
        "forbidden_categories": [],
        "min_independent_evidence": 1,
        "confidence_range": (0.4, 1.0),
    },
    "earnings_forecast": {
        "category": "attributable",
        "bars": "big_move",
        "events": [event("600519 发布半年度业绩预告，净利润增长 20%",
                        published_at="2026-08-04T08:30:00")],
        "expected_status": "EXPLAINED",
        "allowed_categories": ["direct_trigger"],
        "forbidden_categories": ["after_the_fact_explanation"],
        "min_independent_evidence": 1,
        "confidence_range": (0.5, 1.0),
    },
    # === 20.2 容易错误归因 ===
    "after_fact_media_report": {
        "category": "misattribution",
        "bars": "big_move",
        "events": [event("收盘后机构解读今日大涨原因", published_at="2026-08-05T20:00:00")],
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": ["after_the_fact_explanation"],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "old_news_recirculation": {
        "category": "misattribution",
        "bars": "big_move",
        "events": [event("三个月前的旧利好被重新转发", published_at="2026-05-01T09:00:00",
                        entities=["company:600519.SH"])],
        # 原始披露远早于窗口（novelty=1 旧闻）且无新增变量 -> 不得标为直接触发
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": ["old_news_recirc", "after_the_fact_explanation"],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "title_match_wrong_entity": {
        "category": "misattribution",
        "bars": "big_move",
        "events": [event("另一家同名公司的公告", published_at="2026-08-04T09:00:00",
                        entities=["company:000001.SZ"])],
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": [],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "reposts_counted_once": {
        "category": "misattribution",
        "bars": "big_move",
        "events": [event("快讯：公司签订大单", source_id="cls",
                         published_at="2026-08-04T09:00:00"),
                   event("快讯：公司签订大单", source_id="cls",
                         published_at="2026-08-04T09:05:00"),
                   event("快讯：公司签订大单", source_id="cls",
                         published_at="2026-08-04T09:10:00")],
        # 转载按 independence_group 计 1 组；单组 B 级快讯达不到直接证据门槛
        # （任务书 11.5：需 S/A 原始组或双独立 A/B 组）-> 无法归因
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": [],
        "forbidden_categories": [],
        "assert_independence_groups": 1,
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "community_first_official_later": {
        "category": "misattribution",
        "bars": "big_move",
        "events": [event("社区传闻公司重组", source_id="xueqiu", layer=3,
                         published_at="2026-08-04T10:00:00"),
                   event("公司公告确认重组事项落地", published_at="2026-08-05T08:00:00")],
        # 官方确认（异动前披露）构成主原因；社区传闻不得单独成为主原因
        "expected_status": "EXPLAINED",
        "allowed_categories": ["direct_trigger", "secondary_catalyst"],
        "forbidden_primary_categories": ["unverified_rumor"],
        "min_independent_evidence": 1,
        "confidence_range": (0.4, 1.0),
    },
    "positive_news_stock_down": {
        "category": "misattribution",
        "bars": "big_move_negative",
        "events": [event("公司发布盈利增长公告", published_at="2026-08-04T09:00:00")],
        # 确定性评分不得按方向自动加减分（任务书 11.3）；方向语义验证留 LLM 层，
        # 本案例断言：候选不被方向匹配加分、也不因方向相反被惩罚
        "expected_status": "EXPLAINED",
        "allowed_categories": ["direct_trigger"],
        "forbidden_categories": [],
        "assert_no_direction_bonus": True,
        "min_independent_evidence": 1,
        "confidence_range": (0.4, 1.0),
    },
    # === 20.3 无法归因 ===
    "no_credible_event": {
        "category": "unattributable",
        "bars": "big_move",
        "events": [],
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": [],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "only_anonymous_rumor": {
        "category": "unattributable",
        "bars": "big_move",
        "events": [event("某散户爆料重大利好", source_id="xueqiu", layer=3,
                         published_at="2026-08-04T10:00:00")],
        "expected_status": "UNEXPLAINED_MOVE",
        "allowed_categories": ["unverified_rumor"],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.6),
    },
    "high_authority_conflict": {
        "category": "unattributable",
        "bars": "big_move",
        "events": [event("公司公告业绩增长", published_at="2026-08-04T09:00:00"),
                   event("交易所警示函：业绩数据存在重大差错", published_at="2026-08-04T09:30:00")],
        "contradicting_index": 0,   # 注入反证：公告候选同时有 supports 与 contradicts
        "expected_status": "SOURCE_CONFLICT",
        "allowed_categories": [],
        "forbidden_categories": [],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.5),
    },
    # === 20.4 数据不足 ===
    "insufficient_quotes": {
        "category": "data_insufficient",
        "bars": "short_series",   # 10 天（新股/样本不足）
        "events": [event("公司公告", published_at="2026-08-04T09:00:00")],
        "expected_status": "INSUFFICIENT_EVIDENCE",
        "allowed_categories": [],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.5),
    },
    # === 20.5 数据边界 ===
    "mad_zero": {
        "category": "boundary",
        "bars": "flat_series",    # 收益率全同 -> MAD=0，无异动事实
        "events": [event("公司公告", published_at="2026-08-04T09:00:00")],
        # 行情事实本身不成立 -> INSUFFICIENT_EVIDENCE（任务书 11.6），不是 UNEXPLAINED_MOVE
        "expected_status": "INSUFFICIENT_EVIDENCE",
        "allowed_categories": [],
        "forbidden_categories": ["direct_trigger"],
        "min_independent_evidence": 0,
        "confidence_range": (0.0, 0.5),
    },
}
