"""晨报 RawItem -> Evidence 确定性构建。"""
from __future__ import annotations

import hashlib
import re
from typing import Dict

from research_os.models import Evidence, RawItem
from research_os.utils.id import new_uuid
from research_os.validators.schema_validator import validate_instance


def _independence_group(item: RawItem) -> str:
    """同标题转载归入同一独立证据组，不把转载数量当独立来源数量。"""
    normalized = re.sub(r"\s+", "", item.title).lower()
    return "story:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]


def build_evidence(item: RawItem, source_tiers: Dict[str, str], channel: str) -> Evidence:
    evidence_type = {
        "official_disclosure": "official_disclosure",
        "government_and_regulator": "official_statistics",
        "company_official": "company_official",
        "fast_news": "news_report",
        "deep_financial_media": "media_report",
        "community_sentiment": "social_opinion",
        "institutional_activity": "institution_material",
        "market_data": "market_data",
    }.get(channel, "unknown")
    evidence = Evidence(
        evidence_id=new_uuid(), source_id=item.source_id, raw_item_id=item.raw_item_id,
        title=item.title, publisher=item.publisher, published_at=item.published_at,
        retrieved_at=item.retrieved_at, url=item.url, excerpt=item.content_excerpt[:500],
        evidence_type=evidence_type, independence_group=_independence_group(item),
        source_tier=source_tiers.get(item.source_id, "C"),  # type: ignore[arg-type]
        access_status=item.access_status,
    )
    errors = validate_instance(evidence.model_dump(), "evidence")
    if errors:
        raise ValueError(f"Evidence 未通过 Schema 校验: {errors}")
    return evidence


def evidence_index(evidences: list[Evidence]) -> Dict[str, dict]:
    return {e.evidence_id: e.model_dump() for e in evidences}
