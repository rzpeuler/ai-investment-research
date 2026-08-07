"""Claim / Evidence 构建器（Phase 4 二次验收修复 BLOCKER 1）。

真实对象，非 ID 别名：
- Evidence：来源/原始条目/标题/发布者/披露时间/URL/摘录/来源等级/独立证据组，
  通过 evidence.schema.json 校验；
- Claim：主体/谓词/宾语/证据/支持级别/置信度/审核状态，通过 claim.schema.json 校验；
- ResearchFinding.evidence_ids 指向真实 Evidence ID（不再用 metric_id 冒充）。

Evidence 来源类型：manual_input；Phase 2 事件必须复用其原始 Evidence，不在此重造。
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional

from research_os.models.core import Claim, Evidence, RawItem
from research_os.utils.time import now_iso


def build_evidence_from_fact(
    fact: Dict[str, Any],
    *,
    published_at: str,
    retrieved_at: str,
    file_name: str = "用户财务导入",
    raw_item_id: Optional[str] = None,
    provenance: Optional[Dict[str, Any]] = None,
) -> Evidence:
    """从财务事实构造真实 Evidence。

    published_at 必须是报告真实披露时间（不得用导入时刻/报告期末冒充）。
    """
    label = fact.get("label_raw") or fact.get("taxonomy_code") or "财务科目"
    period_end = fact.get("period_end") or ""
    value = fact.get("raw_value") or fact.get("normalized_value") or ""
    unit = fact.get("normalized_unit") or fact.get("currency") or ""
    fact_id = fact.get("fact_id") or str(uuid.uuid4())
    provenance = provenance or {}
    locator = provenance.get("locator") or f"field:{fact.get('taxonomy_code', 'unknown')}"
    return Evidence(
        evidence_id=str(uuid.uuid4()),
        source_id="manual_financial_import",
        raw_item_id=raw_item_id or fact_id,
        title=f"{label}（{period_end}）",
        publisher=file_name,
        published_at=published_at,
        retrieved_at=retrieved_at,
        url=provenance.get("url") or f"manual://financial_import/{fact_id}",
        excerpt=(f"{label}={value}（单位:{unit}，报告期 {period_end}；定位:{locator}；"
                 f"checksum:{provenance.get('checksum', 'unknown')}）"),
        evidence_type="manual_input",
        independence_group=f"fact:{fact_id}",
        source_tier="C",
        access_status="ok",
    )


def build_raw_item_from_fact(
    fact: Dict[str, Any], *, published_at: str, retrieved_at: str,
    file_name: str, manifest_id: str, checksum: str, locator: str,
    source_kind: str = "manual_import", parser_version: str = "unknown",
    imported_at: str = "", is_statutory_original: bool = False,
) -> RawItem:
    """为人工财务行建立可持久化 RawItem，Evidence 不再直接指向 FinancialFact。"""
    fact_id = fact.get("fact_id") or str(uuid.uuid4())
    label = fact.get("label_raw") or fact.get("taxonomy_code") or "财务科目"
    excerpt = (f"{label}={fact.get('raw_value') or fact.get('normalized_value')}；"
               f"manifest={manifest_id}；checksum={checksum}；locator={locator}；"
               f"source_kind={source_kind}；parser_version={parser_version}；"
               f"imported_at={imported_at or retrieved_at}；"
               f"is_statutory_original={str(is_statutory_original).lower()}")
    content_hash = hashlib.sha256(
        json.dumps(fact, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return RawItem(
        raw_item_id=str(uuid.uuid4()), source_id="manual_financial_import",
        external_id=fact_id,
        url=f"manual://financial_import/{manifest_id}/{fact_id}",
        title=f"{file_name}：{label}", publisher=file_name, author=None,
        published_at=published_at, retrieved_at=retrieved_at,
        content_hash=content_hash, content_excerpt=excerpt[:500],
        content_storage="metadata_and_excerpt", language="zh-CN",
        access_status="ok", entities=[fact.get("company_entity_id", "")],
        raw_category="financial_fact_import",
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
        object={
            **(finding.get("object") or {}),
            "finding_id": finding.get("finding_id"),
            "section_id": finding.get("section_id", ""),
        },
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
        e.evidence_id: e.model_dump()
        for e in evidences
    }
