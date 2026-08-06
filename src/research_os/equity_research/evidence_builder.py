"""Claim / Evidence 构建器（Phase 4 二次验收修复 BLOCKER 1）。

真实对象，非 ID 别名：
- Evidence：来源/原始条目/标题/发布者/披露时间/URL/摘录/来源等级/独立证据组，
  通过 evidence.schema.json 校验；
- Claim：主体/谓词/宾语/证据/支持级别/置信度/审核状态，通过 claim.schema.json 校验；
- ResearchFinding.evidence_ids 指向真实 Evidence ID（不再用 metric_id 冒充）。

Evidence 来源类型（evidence_type）：
- manual_input：用户财务导入（fact 行）；published_at=报告真实披露时间
- official_disclosure：Phase 3 归因/晨报事件（已披露公告）
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from research_os.models.core import Claim, Evidence, ReviewStatus, SupportLevel
from research_os.utils.time import now_iso


def build_evidence_from_fact(
    fact: Dict[str, Any],
    *,
    published_at: str,
    retrieved_at: str,
    file_name: str = "用户财务导入",
) -> Evidence:
    """从财务事实构造真实 Evidence。

    published_at 必须是报告真实披露时间（不得用导入时刻/报告期末冒充）。
    """
    label = fact.get("label_raw") or fact.get("taxonomy_code") or "财务科目"
    period_end = fact.get("period_end") or ""
    value = fact.get("raw_value") or fact.get("normalized_value") or ""
    unit = fact.get("normalized_unit") or fact.get("currency") or ""
    fact_id = fact.get("fact_id") or str(uuid.uuid4())
    return Evidence(
        evidence_id=str(uuid.uuid4()),
        source_id="manual_financial_import",
        raw_item_id=fact_id,
        title=f"{label}（{period_end}）",
        publisher=file_name,
        published_at=published_at,
        retrieved_at=retrieved_at,
        url=f"manual://financial_import/{fact_id}",
        excerpt=f"{label}={value}（单位:{unit}，报告期 {period_end}）",
        evidence_type="manual_input",
        independence_group=f"fact:{fact_id}",
        source_tier="C",
        access_status="ok",
    )


def build_evidence_from_event(
    event: Dict[str, Any],
    *,
    retrieved_at: str,
) -> Optional[Evidence]:
    """从晨报事件构造 Evidence（official_disclosure）。"""
    event_id = event.get("event_id")
    title = event.get("title") or "事件"
    published_at = event.get("published_at") or event.get("event_time") or event.get("created_at")
    if not published_at or not event_id:
        return None
    return Evidence(
        evidence_id=str(uuid.uuid4()),
        source_id="morning_brief_events",
        raw_item_id=event_id,
        title=title,
        publisher=event.get("source_name") or "晨报事件",
        published_at=published_at,
        retrieved_at=retrieved_at,
        url=event.get("url") or f"manual://morning_events/{event_id}",
        excerpt=title[:200],
        evidence_type="official_disclosure",
        independence_group=f"event:{event_id}",
        source_tier="B",
        access_status="ok",
    )


def build_claim_from_finding(
    finding: Dict[str, Any],
    *,
    company_entity_id: str,
    evidence_ids: List[str],
) -> Claim:
    """从 ResearchFinding 构造真实 Claim（claim_id 独立 UUID，不替代 finding_id）。"""
    return Claim(
        claim_id=str(uuid.uuid4()),
        claim_type=finding.get("claim_type", "UNKNOWN"),  # type: ignore[arg-type]
        statement=finding.get("statement", ""),
        subject_entities=[company_entity_id],
        predicate=finding.get("title") or finding.get("finding_type", ""),
        object={"finding_id": finding.get("finding_id"), "section_id": finding.get("section_id", "")},
        as_of=finding.get("as_of") or now_iso(),
        evidence_ids=evidence_ids,
        support_level=finding.get("support_level", "indirect"),  # type: ignore[arg-type]
        confidence=float(finding.get("confidence", 0.5)),
        valid_until=finding.get("valid_until"),
        review_status=finding.get("review_status", "unreviewed"),  # type: ignore[arg-type]
    )


def build_evidence_index(evidences: List[Evidence]) -> Dict[str, Any]:
    """evidence_index：ID → 来源摘要（供引用完整性快速核验）。"""
    return {
        e.evidence_id: {
            "source_id": e.source_id,
            "raw_item_id": e.raw_item_id,
            "title": e.title,
            "published_at": e.published_at,
            "evidence_type": e.evidence_type,
            "independence_group": e.independence_group,
            "source_tier": e.source_tier,
        }
        for e in evidences
    }
