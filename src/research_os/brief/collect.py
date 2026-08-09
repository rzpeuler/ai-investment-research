"""Brief（晨报/晚报）共享采集辅助（Phase 6B 同构复用，DECISIONS #43）。

morning_brief 与 evening_brief 共用同一采集逻辑、来源体系与标准化；
本模块集中管理 ManualInbox -> RawItem 转换、来源通道映射与来源等级。
"""
from __future__ import annotations

from typing import Any, Dict, List

# 来源 -> 监测方向（morning/evening 共用）
BRIEF_CHANNEL_MAP: Dict[str, str] = {
    "cninfo": "official_disclosure", "sse": "official_disclosure",
    "szse": "official_disclosure", "nbs": "government_and_regulator",
    "csrc": "government_and_regulator", "cls": "fast_news",
    "sina_quote": "market_data", "ima": "manual_submission",
    "manual_inbox": "manual_submission",
}

# 来源等级（morning/evening 共用）
BRIEF_SOURCE_TIERS: Dict[str, str] = {
    "cninfo": "S", "sse": "S", "szse": "S", "csrc": "S", "nbs": "S",
    "cls": "B", "sina_quote": "S", "ima": "C", "manual_inbox": "C",
}


def inbox_to_raw_items(entries: List[dict]) -> List[Any]:
    """ManualInbox 条目 -> RawItem（标准化；metadata_and_excerpt 默认存储）。"""
    from research_os.models import RawItem
    from research_os.utils.id import content_sha256, new_uuid

    return [RawItem(
        raw_item_id=new_uuid(), source_id="manual_inbox", external_id=e["inbox_id"],
        url=e["source_url"], title=e["title"], publisher=e["source_name"],
        author=e.get("submitted_by"), published_at=e.get("published_at") or e["submitted_at"],
        retrieved_at=e["submitted_at"],
        content_hash=content_sha256(f"{e['source_url']}|{e['title']}"),
        content_excerpt=e.get("content_excerpt", "")[:300],
        content_storage="metadata_and_excerpt", language="zh-CN", access_status="ok",
        entities=e.get("intended_entities", []), raw_category="manual_submission",
    ) for e in entries]


def append_live_items(raw_items: List[Any]) -> None:
    """追加真实网络采集（可选；失败由覆盖/缺失状态表达，不伪造新闻）。"""
    from research_os.collectors.news import ClsMetadataCollector
    from research_os.collectors.official import CninfoCollector

    for adapter in (CninfoCollector(), ClsMetadataCollector()):
        try:
            for ref in adapter.discover({}, {"start": None, "end": None})[:10]:
                raw_items.extend(adapter.normalize(adapter.fetch(ref)))
        except Exception:
            # 失败由覆盖/缺失状态表达；不得伪造一条"采集失败新闻"。
            continue
