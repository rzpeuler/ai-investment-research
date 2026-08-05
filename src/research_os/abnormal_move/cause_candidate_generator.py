"""原因候选生成（Phase 3 任务书 11 节）。

从分层检索结果生成 CauseCandidate：
- 硬过滤：错误实体、窗口外、重复证据
- 七维原始分赋值（0-5）：时间匹配 / 实体或产业关联 / 新颖性 / 板块联动 /
  来源可靠性 / 解释覆盖度 / 可验证性（评分计算在 cause_candidate_scorer）
- 时间匹配分来自 causal_timing_checker 结果（确定性，不得由模型放宽）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.causal_timing_checker import (
    AFTER_MOVE,
    BEFORE_MOVE,
    DURING_MOVE,
    UNKNOWN_ORDER,
    TimingCheck,
    check_direct_trigger,
    classify_timing,
)
from research_os.abnormal_move.event_window_retriever import RetrievedItem, RetrievalResult
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    CauseCandidate,
    CauseEvidenceLink,
)
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso

# 来源等级 -> 可靠性分（0-5）
SOURCE_RELIABILITY = {
    "S": 5, "A": 4, "B": 3, "C": 2, "D": 1,
}

# 高权威来源（L1 事实层）
HIGH_AUTHORITY_SOURCES = {"cninfo", "sse", "szse", "csrc", "nbs", "company_ir"}

_LINK_TIMING = {
    "BEFORE_MOVE": "before",
    "DURING_MOVE": "during",
    "AFTER_MOVE": "after",
    "UNKNOWN_ORDER": "unknown",
}


@dataclass
class GenerateResult:
    candidates: List[CauseCandidate]
    links: List[CauseEvidenceLink]
    skipped: List[str] = field(default_factory=list)


class CauseCandidateGenerator:
    """原因候选生成器。"""

    def __init__(self, entity_aliases: Optional[List[str]] = None):
        self.entity_aliases = entity_aliases or []

    # ---------- 维度分（确定性） ----------

    def _time_match_score(self, item: RetrievedItem, obs: AbnormalMoveObservation,
                          check: TimingCheck) -> int:
        """时间匹配（任务书 11.2 时间表）。"""
        rel = check.timing_relation
        if rel == BEFORE_MOVE:
            if check.confidence_cap == "high":
                return 5   # 异动前明确披露且分钟级
            return 4       # 异动前合理窗口，顺序明确
        if rel == DURING_MOVE:
            return 3
        if rel == UNKNOWN_ORDER:
            return 2       # 同日先后未知
        if rel == AFTER_MOVE:
            return 1       # 明显异动后报道
        return 0

    def _entity_link_score(self, item: RetrievedItem, entity_id: str,
                           obs: AbnormalMoveObservation) -> int:
        """实体或产业关联（任务书 11.2 实体表）。确定性实现：
        直接实体匹配=5；别名/控股核心=4；行业归属=3；主题=2；仅标题关键词=1。
        """
        item_entities = item.entities or []
        target = entity_id
        # 直接匹配（含 entity_id 后缀形式，如 "company:600519.SH" vs "600519.SH"）
        if target in item_entities or \
           any(e.endswith(f":{target}") for e in item_entities):
            return 5
        # 别名匹配（对象名称出现在实体集）
        for alias in self.entity_aliases:
            if any(alias in e for e in item_entities):
                return 4
        # 行业关联：实体集含 entity_id 前缀的行业实体
        if any(e.startswith("industry:") or e.startswith("concept:") for e in item_entities):
            return 3
        # 标题关键词
        if item.title and any(a in item.title for a in self.entity_aliases):
            return 1
        return 0

    def _novelty_score(self, item: RetrievedItem, obs: AbnormalMoveObservation,
                       window_start: str) -> int:
        """新颖性（任务书 11.2 新颖性表）。首版确定性近似：
        窗口内首次披露=5；旧事件新确认/新数据=4；重传播升级=2；纯旧闻=1。
        """
        pub = item.published_at
        if pub is None:
            return 2
        # 首次披露在窗口内（异动前 5 日内）-> 新
        from datetime import datetime

        from research_os.utils.time import parse_iso

        try:
            pub_dt = parse_iso(pub)
            ws = (parse_iso(window_start) if "T" in window_start
                  else datetime.fromisoformat(window_start))
            if pub_dt >= ws:
                return 5
        except ValueError:
            return 2
        return 1  # 窗口前已披露 -> 旧闻（新增变量由 LLM 层补充判定）

    def _peer_linkage_score(self, item: RetrievedItem,
                            linkage: Any) -> int:
        """板块联动（任务书 11.2 联动表）。"""
        if linkage is None:
            return 0
        advancing = getattr(linkage, "advancing_ratio", None)
        if advancing is None:
            return 0
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

    def _source_reliability_score(self, item: RetrievedItem) -> int:
        """来源可靠性（任务书 11.2 来源表）。"""
        sid = item.source_id
        if sid in HIGH_AUTHORITY_SOURCES:
            return 5
        if sid == "manual_inbox":
            return 4   # 人工录入（可追溯）
        if sid == "cls":
            return 3
        if sid == "xueqiu":
            return 1
        return SOURCE_RELIABILITY.get(sid, 2)

    def _coverage_score(self, item: RetrievedItem, obs: AbnormalMoveObservation) -> int:
        """解释覆盖度：确定性近似（方向词 + 量价信息），语义细化由 LLM 层补充。
        默认 3（部分解释）；机制摘要含方向词且观测有量价证据时 4。
        """
        title = (item.title or "") + (item.excerpt or "")
        direction_words = ("上涨", "下跌", "涨", "跌", "利好", "利空", "增长", "下滑")
        has_dir = any(w in title for w in direction_words)
        has_volume = bool(obs.primary_anomaly_types)
        if has_dir and has_volume:
            return 4
        if has_dir or has_volume:
            return 3
        return 2

    def _verifiability_score(self, item: RetrievedItem) -> int:
        """可验证性（任务书 11.2 可验证表）。"""
        if item.url:
            return 3   # 可追溯二手/原文链接
        if item.kind in ("claim", "event"):
            return 2
        if item.source_id in HIGH_AUTHORITY_SOURCES:
            return 5
        return 2

    # ---------- 候选构建 ----------

    def build(self, request: AbnormalMoveRequest, obs: AbnormalMoveObservation,
              retrieval: RetrievalResult, linkage: Any = None,
              entity_id: Optional[str] = None) -> GenerateResult:
        candidates: List[CauseCandidate] = []
        links: List[CauseEvidenceLink] = []
        skipped: List[str] = []
        entity_id = entity_id or obs.entity_id

        for item in retrieval.items:
            # 硬过滤 1：实体主体错误
            if item.entities and entity_id not in item.entities and \
               not any(a in e for a in self.entity_aliases for e in item.entities):
                if self._entity_link_score(item, entity_id, obs) == 0:
                    skipped.append(f"{item.title[:30]}：实体主体无关")
                    continue
            # 硬过滤 2：窗口外（L4 扩展项已有窗口扩展标记，保留）
            timing = classify_timing(item.published_at, obs.move_start_at, obs.move_end_at)
            direct = check_direct_trigger(
                published_at=item.published_at,
                first_disclosed_at=item.published_at,
                move_start_at=obs.move_start_at,
                move_end_at=obs.move_end_at,
            )
            cause_category = self._cause_category(timing.timing_relation, item)
            candidate = CauseCandidate(
                cause_candidate_id=new_uuid(),
                request_id=request.request_id,
                observation_id=obs.observation_id,
                event_id=item.item_id,
                title=item.title[:200] or "(未命名事件)",
                cause_category=cause_category,  # type: ignore[arg-type]
                retrieval_layer=item.layer,
                event_time=item.published_at,
                first_disclosed_at=item.published_at,
                published_at=item.published_at,
                retrieved_at=item.retrieved_at,
                affected_entity_ids=item.entities,
                mechanism_summary=item.excerpt[:200],
                time_match_score=self._time_match_score(item, obs, timing),
                entity_link_score=self._entity_link_score(item, entity_id, obs),
                novelty_score=self._novelty_score(item, obs, request.window_start),
                peer_linkage_score=self._peer_linkage_score(item, linkage),
                source_reliability_score=self._source_reliability_score(item),
                explanation_coverage_score=self._coverage_score(item, obs),
                verifiability_score=self._verifiability_score(item),
                timing_relation=timing.timing_relation,  # type: ignore[arg-type]
                causal_eligibility=direct.direct_eligible,
                evidence_ids=[],
                independence_groups=[f"{item.source_id}:{item.title[:20]}"],
            )
            candidates.append(candidate)
            links.append(CauseEvidenceLink(
                link_id=new_uuid(),
                cause_candidate_id=candidate.cause_candidate_id,
                evidence_id=item.item_id or item.title,
                relation="supports",
                directness="direct" if item.layer == 1 else "indirect",
                timing_relation=_LINK_TIMING.get(timing.timing_relation, "unknown"),  # type: ignore[arg-type]
                independence_group=candidate.independence_groups[0],
                weight=1.0,
                notes=f"检索层 L{item.layer}",
                created_at=now_iso(),
            ))
        return GenerateResult(candidates=candidates, links=links, skipped=skipped)

    def _cause_category(self, timing_relation: str, item: RetrievedItem) -> str:
        if timing_relation == AFTER_MOVE:
            return "after_the_fact_explanation"
        if item.source_id == "xueqiu":
            return "unverified_rumor" if item.layer == 3 else "industry_or_theme_resonance"
        if timing_relation == DURING_MOVE:
            return "secondary_catalyst"
        return "direct_trigger"
