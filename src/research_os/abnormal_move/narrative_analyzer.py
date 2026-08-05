"""叙事分析（Phase 3 任务书 13 节 narrative_analyzer、14.2 节）。

第三层来源 -> Opinion / 叙事摘要。严格区分：
事实线索 / 来源观点 / 传播叙事 / 热度 / 未验证消息。
不得把舆情当事实，不得把社区热度表述为机构买卖行为。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.abnormal_move.event_window_retriever import RetrievedItem

# 监测方向与叙事类型映射
CHANNEL_NARRATIVE = {
    "fast_news": "事实线索",
    "deep_financial_media": "来源观点",
    "community_sentiment": "传播叙事",
    "institutional_activity": "机构叙事",
}


@dataclass
class NarrativeResult:
    facts: List[dict] = field(default_factory=list)         # 事实线索
    opinions: List[dict] = field(default_factory=list)       # 来源观点（含说话者）
    narratives: List[dict] = field(default_factory=list)     # 传播叙事
    unverified: List[dict] = field(default_factory=list)     # 未验证消息
    heat_indicators: Dict[str, int] = field(default_factory=dict)  # 方向热度计数
    warnings: List[str] = field(default_factory=list)


class NarrativeAnalyzer:
    """叙事/舆情分析（确定性归类；语义归纳由 LLM 层补充，不改变归类）。"""

    def analyze(self, items: List[RetrievedItem],
                channel_of: Optional[Dict[str, str]] = None) -> NarrativeResult:
        result = NarrativeResult()
        channel_of = channel_of or {}
        for item in items:
            entry = {
                "item_id": item.item_id,
                "title": item.title,
                "source_id": item.source_id,
                "published_at": item.published_at,
                "url": item.url,
            }
            sid = item.source_id
            if sid in ("cninfo", "sse", "szse", "csrc", "nbs", "company_ir"):
                entry["narrative_type"] = "事实线索"
                result.facts.append(entry)
            elif sid == "xueqiu":
                entry["narrative_type"] = "传播叙事"
                entry["speaker"] = item.raw.get("author") or "匿名用户"
                result.narratives.append(entry)
                if not item.raw.get("author"):
                    result.unverified.append({**entry, "reason": "匿名来源，不能单独支持核心事实"})
            elif sid == "cls":
                entry["narrative_type"] = "来源观点"
                entry["speaker"] = "财联社"
                result.opinions.append(entry)
            else:
                entry["narrative_type"] = "未分类"
                result.narratives.append(entry)
                result.warnings.append(f"来源 {sid} 未映射叙事类型，归入叙事桶待人工复核")
        # 热度指标：仅作为传播度参考，不等于机构买卖
        if result.narratives:
            result.heat_indicators["community_mentions"] = len(result.narratives)
            result.warnings.append("社区提及数仅为传播热度参考，不得解释为机构交易行为")
        return result
