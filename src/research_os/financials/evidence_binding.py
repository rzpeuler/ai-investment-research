"""核心财务事实与官方披露原件的确定性 Evidence 绑定。"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from research_os.documents.disclosure_import import _official_source
from research_os.models import DocumentBlock, Evidence, FinancialDataManifest, FinancialFact, FinancialReport
from research_os.models.financials import FinancialEvidenceBindingManifest
from research_os.utils.decimal import normalize_decimal_string
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_model

CORE_FINANCIAL_CODES = frozenset({
    "revenue", "cost_of_sales", "operating_profit", "net_profit",
    "net_profit_attr", "total_assets", "total_liabilities", "equity_attr",
    "operating_cash_flow",
})


@dataclass
class FinancialBindingResult:
    bound_fact_ids: List[str] = field(default_factory=list)
    block_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)


def load_binding_manifest(path: Path) -> FinancialEvidenceBindingManifest:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    model = FinancialEvidenceBindingManifest(**payload)
    errors = validate_model(model)
    if errors:
        raise ValueError(f"官方财务定位清单未通过 Schema: {errors[:5]}")
    return model


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "research-os:" + kind + ":" + ":".join(parts)))


def _locator_payload(locator: Any, fact: Dict[str, Any], document: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "locator_kind": locator.locator_kind,
        "cell_reference": locator.cell_reference,
        "text_start": locator.text_start,
        "text_end": locator.text_end,
        "structured_field": locator.structured_field,
        "taxonomy_code": locator.taxonomy_code,
        "period_end": locator.period_end,
        "company_entity_id": fact["company_entity_id"],
        "reported_raw_value": locator.reported_raw_value,
        "currency": locator.currency,
        "unit_scale": locator.unit_scale,
        "document_checksum": document["sha256"],
        "source_url": document["source_url"],
        "confirmation_status": locator.confirmation_status,
        "confirmed_by": locator.confirmed_by,
        "confirmed_at": locator.confirmed_at,
        "correction_reason": locator.correction_reason,
    }


def bind_official_financial_evidence(
    project_root: Path,
    db: Any,
    *,
    manifest: FinancialDataManifest,
    reports: List[FinancialReport],
    facts: List[FinancialFact],
    binding: FinancialEvidenceBindingManifest,
    as_of: str,
    requested_at: str,
) -> FinancialBindingResult:
    """核验 locator 和原件后，写入 block/Evidence 并回填事实血缘。"""
    if binding.company_entity_id not in manifest.company_entity_ids:
        raise ValueError("定位清单公司实体与财务 manifest 不一致")
    if binding.as_of != as_of:
        raise ValueError("定位清单 as_of 与研究截止时间不一致")

    result = FinancialBindingResult()
    seen_fact_ids: set[str] = set()
    report_by_id = {report.financial_report_id: report for report in reports}
    for locator in binding.locators:
        matches = [
            fact for fact in facts
            if fact.taxonomy_code == locator.taxonomy_code
            and fact.period_end == locator.period_end
            and fact.statement_scope == locator.statement_scope
        ]
        if len(matches) != 1:
            raise ValueError(
                f"locator 必须唯一匹配一个 FinancialFact: "
                f"{locator.taxonomy_code}/{locator.period_end}/{locator.statement_scope}"
            )
        fact = matches[0]
        if fact.fact_id in seen_fact_ids:
            raise ValueError(f"同一 FinancialFact 重复绑定: {fact.fact_id}")
        seen_fact_ids.add(fact.fact_id)
        if fact.company_entity_id != binding.company_entity_id:
            raise ValueError("FinancialFact 公司实体与定位清单不一致")
        if normalize_decimal_string(fact.raw_value or fact.normalized_value or "") != locator.reported_raw_value:
            raise ValueError(f"官方定位值与 FinancialFact 数值不一致: {fact.fact_id}")
        if fact.currency != locator.currency or fact.unit_scale != locator.unit_scale:
            raise ValueError(f"官方定位币种或单位与 FinancialFact 不一致: {fact.fact_id}")
        if locator.page_end < locator.page_start:
            raise ValueError("locator.page_end 不得早于 page_start")
        if parse_iso(locator.confirmed_at) > parse_iso(requested_at):
            raise ValueError("人工确认时间不得晚于 requested_at")
        if locator.confirmation_status == "corrected" and not (locator.correction_reason or "").strip():
            raise ValueError("人工校正必须记录 correction_reason")

        document = db.get("document_records", locator.document_id)
        if document is None:
            raise ValueError(f"官方文档不存在: {locator.document_id}")
        if document.get("company_entity_id") != binding.company_entity_id:
            raise ValueError("官方文档公司实体与财务事实不一致")
        if document.get("report_period_end") and document["report_period_end"] != fact.period_end:
            raise ValueError("官方文档报告期与财务事实不一致")
        if (
            not document.get("source_url")
            or parse_iso(document.get("published_at", "")) > parse_iso(as_of)
        ):
            raise ValueError("官方文档 URL 缺失或披露时间晚于 as_of")
        source = _official_source(
            Path(project_root), document["source_id"], document["source_url"])
        local_path = Path(document.get("local_path") or "")
        if not local_path.is_file() or _sha256(local_path) != document.get("sha256"):
            raise ValueError("官方文档文件缺失或 checksum 不一致")

        document_evidence = db.get("evidence", locator.document_evidence_id)
        if document_evidence is None:
            raise ValueError(f"官方文档 Evidence 不存在: {locator.document_evidence_id}")
        if (
            document_evidence.get("source_id") != document["source_id"]
            or document_evidence.get("source_tier") not in {"S", "A"}
            or document_evidence.get("evidence_type") != "official_disclosure"
            or document_evidence.get("url") != document["source_url"]
        ):
            raise ValueError("官方文档 Evidence 资格或 URL 不一致")
        raw_item = db.get("raw_items", document_evidence["raw_item_id"])
        if raw_item is None or raw_item.get("content_hash") != document["sha256"]:
            raise ValueError("官方文档 RawItem 缺失或 checksum 血缘不一致")

        block_id = _stable_id("financial-block", document["sha256"], fact.fact_id)
        evidence_id = _stable_id("financial-evidence", document["sha256"], fact.fact_id)
        payload = _locator_payload(locator, fact.model_dump(), document)
        block = DocumentBlock(
            block_id=block_id, document_id=document["document_id"],
            block_type="table_cell" if locator.locator_kind in {"table", "row", "column", "cell"} else "text",
            page_start=locator.page_start, page_end=locator.page_end,
            bbox=None, sequence_no=0, section_path=locator.section_path,
            content_excerpt=locator.source_excerpt,
            content_hash=hashlib.sha256(locator.source_excerpt.encode("utf-8")).hexdigest(),
            table_id=locator.table_id, row_index=locator.row_index,
            column_index=locator.column_index, normalized_payload=payload,
            extraction_method="manual", confidence=1.0,
            correction_status="corrected" if locator.confirmation_status == "corrected" else "accepted",
            correction_of_block_id=None, source_id=document["source_id"],
            evidence_ids=[evidence_id], version=1, created_at=now_iso(),
        )
        evidence = Evidence(
            evidence_id=evidence_id, source_id=document["source_id"],
            raw_item_id=document_evidence["raw_item_id"],
            title=f"{fact.label_raw}（{fact.period_end}）",
            publisher=document_evidence["publisher"],
            published_at=document["published_at"], retrieved_at=document["retrieved_at"],
            url=document["source_url"], excerpt=locator.source_excerpt,
            evidence_type="official_disclosure",
            independence_group=f"official-document:{document['sha256']}",
            source_tier=source.source_tier, access_status="ok",
        )
        for obj in (block, evidence):
            errors = validate_model(obj)
            if errors:
                raise ValueError(f"{type(obj).__name__} 未通过 Schema: {errors[:5]}")
            db.upsert(obj)

        fact.source_document_id = document["document_id"]
        fact.source_block_ids = list(dict.fromkeys([*fact.source_block_ids, block_id]))
        fact.evidence_ids = list(dict.fromkeys([*fact.evidence_ids, evidence_id]))
        fact.source_priority = 1 if source.source_tier == "S" else 2
        db.upsert(fact)

        report = report_by_id.get(fact.financial_report_id)
        if report is not None:
            report.document_id = document["document_id"]
            report.source_ids = list(dict.fromkeys([*report.source_ids, document["source_id"]]))
            report.evidence_ids = list(dict.fromkeys([*report.evidence_ids, evidence_id]))
            if document.get("audit_status") == "audited":
                report.audit_status = "audited"
            db.upsert(report)

        result.bound_fact_ids.append(fact.fact_id)
        result.block_ids.append(block_id)
        result.evidence_ids.append(evidence_id)
        result.document_ids.append(document["document_id"])

    manifest.document_ids = list(dict.fromkeys([*manifest.document_ids, *result.document_ids]))
    manifest.source_ids = list(dict.fromkeys([
        *manifest.source_ids,
        *[db.get("document_records", doc_id)["source_id"] for doc_id in result.document_ids],
    ]))
    manifest.warnings = list(dict.fromkeys([
        *manifest.warnings,
        "人工财务导入已逐项绑定并复核官方披露原件；原始导入来源等级保持不变",
    ]))
    db.upsert(manifest)
    return result
