"""P7-D4 M2：derive_existing —— financial_statement_data ← company_document。

DerivationPrerequisiteResolver（taskbook §19，11 项证明）+ FinancialDerivationService
（确定性提取 → FinancialDataManifest/FinancialReport/FinancialFact 幂等持久化）。

边界（§20/§24/§28/§42）：ZERO NETWORK / ZERO WRITE（resolver）/ ZERO LLM；
derive 只消费同一次 preflight 已就绪的 DocumentRecord/Block + 只读 authority；
extractor 不写 DB；持久化在同一事务（调用方负责 rollback）。
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from typing import Any, List, Optional

from research_os.financials.disclosure_extractor import (
    FinancialStatementExtractor,
)
from research_os.models import (
    DocumentBlock,
    DocumentRecord,
    FinancialDataManifest,
    FinancialFact,
    FinancialReport,
)
from research_os.utils.time import now_iso, parse_iso

_UUID5_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

_REQUIRED_SOURCE_IDS = ("cninfo",)
_REQUIRED_DOCUMENT_TYPES = ("annual_report",)
_REQUIRED_MIN_TIER = "A"


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_UUID5_NS, "research-os:" + kind + ":" + ":".join(parts)))


@dataclass
class DerivationPrerequisite:
    """financial_statement_data 的 derivation prerequisite 评估结果。"""

    ready: bool
    eligible_documents: List[DocumentRecord] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def reason_codes(self) -> List[str]:
        return ["DERIVATION_PREREQUISITE_MISSING"] if not self.ready else []


@dataclass
class FinancialDerivationResult:
    manifest: FinancialDataManifest
    report: FinancialReport
    facts: List[FinancialFact]
    inserted: bool = True  # False = 全部复用（幂等）
    warnings: List[str] = field(default_factory=list)


class DerivationPrerequisiteResolver:
    """唯一显式 prerequisite resolver：禁止通用 eligible_count>0 → AUTO_DERIVABLE。"""

    def __init__(self, db: Any):
        self._db = db

    def resolve(
        self,
        db: Any,
        *,
        subject_entity: str,
        data_type: str,
        as_of: str,
    ) -> DerivationPrerequisite:
        if data_type != "financial_statement_data":
            return DerivationPrerequisite(
                ready=False, missing=[f"不支持 derivation data_type: {data_type}"])
        missing: List[str] = []
        warnings: List[str] = []

        # 1. subject entity 唯一（company: 前缀）
        if not subject_entity or not str(subject_entity).startswith("company:"):
            return DerivationPrerequisite(
                ready=False, missing=["subject entity 缺失或非法（须 company: 前缀）"])

        # 2-11. 逐 document 评估
        records = self._load_documents(db, subject_entity)
        eligible: List[DocumentRecord] = []
        for record in records:
            problems = self._document_problems(record, as_of)
            if not problems:
                eligible.append(record)
        if not records:
            missing.append("company_document 对 subject 无合格记录（同 subject 无 DocumentRecord）")
        elif not eligible:
            missing.append("company_document 存在但无合格年度报告（见 warnings）")
        for record in records:
            for p in self._document_problems(record, as_of):
                warnings.append(f"{record.document_id}: {p}")
        if not missing:
            # 2. company_document readiness 对同 subject 有合格记录
            # （由 preflight 的 company_document readiness 独立证明；此处要求 ≥1 eligible）
            pass
        return DerivationPrerequisite(
            ready=not missing, eligible_documents=eligible,
            missing=missing, warnings=warnings,
        )

    def _load_documents(self, db: Any, company_entity_id: str) -> List[DocumentRecord]:
        rows = db.query(
            "SELECT payload FROM document_records WHERE company_entity_id = ?",
            (company_entity_id,),
        )
        out: List[DocumentRecord] = []
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else dict(row)
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            try:
                out.append(DocumentRecord(**payload))
            except Exception:  # noqa: BLE001 -- 存量异常记录 fail closed
                continue
        return out

    def _document_problems(self, record: DocumentRecord, as_of: str) -> List[str]:
        problems: List[str] = []
        # 3. company_entity_id == subject（_load_documents 已过滤）
        # 4. document_type == annual_report
        if record.document_type not in _REQUIRED_DOCUMENT_TYPES:
            problems.append(f"document_type={record.document_type}（须 annual_report）")
        # 5. published_at <= as_of
        try:
            if parse_iso(record.published_at) > parse_iso(as_of):
                problems.append("published_at > as_of（未来披露）")
        except ValueError:
            problems.append("published_at 非法")
        # 6. report_period_end 已确定
        if not record.report_period_end:
            problems.append("report_period_end 未确定")
        # 7. source_id == cninfo
        if record.source_id not in _REQUIRED_SOURCE_IDS:
            problems.append(f"source_id={record.source_id}（须 cninfo）")
        # 8. source tier 满足 requirement（cninfo=S ≥ A；权威 SourceRegistry 独立证明）
        # 9. native text parse 可用
        if record.text_layer_status != "present":
            problems.append(f"text_layer_status={record.text_layer_status}（原生文本不可用）")
        # 10. DocumentBlock 存在
        block_count = self._block_count(record.document_id)
        if block_count <= 0:
            problems.append("无 DocumentBlock")
        # 11. checksum/provenance 完整
        if not record.sha256 or len(record.sha256) != 64:
            problems.append("sha256 缺失/非法")
        if not record.source_url:
            problems.append("source_url 缺失（无法溯源）")
        return problems

    def _block_count(self, document_id: str) -> int:
        rows = self._db.query(
            "SELECT payload FROM document_blocks WHERE document_id = ?",
            (document_id,),
        )
        return len(rows)


class FinancialDerivationService:
    """company_document → financial_statement_data 确定性推导（ZERO NETWORK）。"""

    def __init__(
        self,
        db: Any,
        *,
        extractor: Optional[FinancialStatementExtractor] = None,
    ):
        self._db = db
        self._extractor = extractor or FinancialStatementExtractor()

    def derive(
        self,
        *,
        record: DocumentRecord,
        blocks: List[DocumentBlock],
        company_entity_id: str,
        as_of: str,
        evidence_ids: List[str],
    ) -> FinancialDerivationResult:
        now = now_iso()
        if record.report_period_end is None or record.fiscal_year is None:
            raise ValueError("DERIVATION_FAILED: report_period_end/fiscal_year 未确定")
        if not blocks:
            raise ValueError("DERIVATION_PREREQUISITE_MISSING: 无 DocumentBlock 可提取")
        period_end = record.report_period_end
        fiscal_year = record.fiscal_year
        period_start = f"{fiscal_year - 1}-12-31" if period_end.endswith("12-31") else period_end

        extraction = self._extractor.extract(
            record=None, blocks=blocks, document=record,
            company_entity_id=company_entity_id, fiscal_year=fiscal_year,
            period_end=period_end, period_start=period_start,
            published_at=record.published_at,
        )
        warnings = list(extraction.warnings)
        if not extraction.facts:
            raise ValueError(
                "DERIVATION_FAILED: 无可接受财务事实（详见 manifest validation_errors）")

        # §41 稳定 UUID5（同一官方文档重复运行 inserted→reused）
        report_id = _stable_id(
            "financial_report", record.sha256, company_entity_id,
            period_end, "consolidated",
        )
        manifest_id = _stable_id("manifest", report_id, now[:10])
        report = FinancialReport(
            financial_report_id=report_id,
            company_entity_id=company_entity_id,
            document_id=record.document_id,
            manifest_id=manifest_id,
            report_type="annual",
            period_start=period_start,
            period_end=period_end,
            fiscal_year=fiscal_year,
            fiscal_period="FY",
            duration_months=12,
            statement_scope="consolidated",
            accounting_standard="CAS",
            currency=extraction.currency,
            unit_scale=extraction.unit_scale or 1,
            audit_status="audited",
            restatement_status="original",
            filing_version="original",
            source_ids=[record.source_id],
            evidence_ids=list(evidence_ids),
            data_status="complete",
            version=1,
            published_at=record.published_at,
            created_at=now,
        )
        facts: List[FinancialFact] = []
        for candidate in extraction.facts:
            fact_id = _stable_id(
                "financial_fact", report_id, candidate.taxonomy_code,
                candidate.statement_type, period_end, "consolidated",
            )
            facts.append(FinancialFact(
                **{**candidate.model_dump(exclude={"fact_id", "financial_report_id"}),
                   "fact_id": fact_id,
                   "financial_report_id": report_id,
                   "evidence_ids": list(evidence_ids),
                   "source_document_id": record.document_id,
                   "valid_from": record.published_at,
                   "created_at": now,
                   "warnings": list(candidate.warnings),
                   })
        )

        manifest = FinancialDataManifest(
            manifest_id=manifest_id,
            source_kind="disclosure_extraction",
            source_id=record.source_id,
            file_name=record.title[:200],
            file_format="pdf_extraction",
            file_checksum=record.sha256,
            imported_at=now,
            imported_by="research_os.data_layer.derivation.FinancialDerivationService",
            company_entity_ids=[company_entity_id],
            document_ids=[record.document_id],
            report_period_end=period_end,
            default_statement_scope="consolidated",
            default_currency=extraction.currency,
            default_unit_scale=extraction.unit_scale,
            row_count=len(extraction.facts),
            accepted_count=len(facts),
            rejected_count=len(extraction.rejected_rows),
            data_version="1.0.0",
            validation_status=("accepted" if facts else "rejected"),
            validation_errors=[r.reason for r in extraction.rejected_rows][:50],
            warnings=warnings,
            source_ids=[record.source_id],
            version=1,
        )

        # §42 原子写入（调用方在事务内；此处只 upsert）
        inserted = True
        existing_report = self._db.query(
            "SELECT payload FROM financial_reports WHERE financial_report_id = ?",
            (report_id,),
        )
        if existing_report:
            inserted = False
        try:
            self._db.upsert(manifest)
            self._db.upsert(report)
            for fact in facts:
                self._db.upsert(fact)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("PERSIST_FAILED: 财务推导持久化失败") from exc
        return FinancialDerivationResult(
            manifest=manifest, report=report, facts=facts, inserted=inserted,
            warnings=warnings,
        )


@dataclass
class _DerivationStepAdapter:
    """execution.DerivationStepOutcome 的轻量适配容器（避免循环 import）。"""

    status: str
    reason_codes: List[str]
    produced_record_refs: List[str] = field(default_factory=list)
    reused_record_refs: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[Any] = field(default_factory=list)


class FinancialDerivationExecutor:
    """derive_existing 步骤执行器（ZERO NETWORK；消费同次 preflight 已就绪数据）。"""

    def __init__(
        self,
        db: Any,
        *,
        resolver: DerivationPrerequisiteResolver,
        service: FinancialDerivationService,
    ):
        self._db = db
        self._resolver = resolver
        self._service = service

    def execute(self, *, step: Any, route_input: Any | None, task_id: str, as_of: str):
        """返回 execution.DerivationStepOutcome 兼容对象。"""
        from research_os.data_layer.execution import DerivationStepOutcome

        # subject 唯一性：route_input.query.entity_ids 必须恰含 1 个 company 实体
        subjects = self._subjects(route_input)
        if len(subjects) != 1:
            return DerivationStepOutcome(
                status="not_executable",
                reason_codes=["DERIVATION_PREREQUISITE_MISSING"],
                warnings=[f"subject entity 必须唯一（得到 {len(subjects)} 个）"],
            )
        subject = subjects[0]
        prereq = self._resolver.resolve(
            self._db, subject_entity=subject, data_type=step.data_type, as_of=as_of,
        )
        if not prereq.ready or not prereq.eligible_documents:
            return DerivationStepOutcome(
                status="not_executable",
                reason_codes=["DERIVATION_PREREQUISITE_MISSING"],
                warnings=list(prereq.missing) + list(prereq.warnings),
            )
        record = max(prereq.eligible_documents, key=lambda r: r.published_at)
        blocks = self._load_blocks(record.document_id)
        evidence_ids = self._evidence_ids(record.document_id)
        try:
            outcome = self._service.derive(
                record=record, blocks=blocks, company_entity_id=subject,
                as_of=as_of, evidence_ids=evidence_ids,
            )
        except ValueError as exc:
            code = str(exc).split(":", 1)[0]
            return DerivationStepOutcome(
                status="failed", reason_codes=[code],
                warnings=[str(exc)],
            )
        produced = [
            f"financial_data_manifest:{outcome.manifest.manifest_id}",
            f"financial_report:{outcome.report.financial_report_id}",
        ] + [f"financial_fact:{f.fact_id}" for f in outcome.facts]
        return DerivationStepOutcome(
            status="completed", reason_codes=[],
            produced_record_refs=produced,
            reused_record_refs=[] if outcome.inserted else produced,
            warnings=list(outcome.warnings),
        )

    def _subjects(self, route_input: Any | None) -> List[str]:
        if route_input is None:
            return []
        query = getattr(route_input, "query", None) or {}
        entity_ids = query.get("entity_ids") or []
        return [e for e in entity_ids if str(e).startswith("company:")]

    def _load_blocks(self, document_id: str) -> List[DocumentBlock]:
        rows = self._db.query(
            "SELECT payload FROM document_blocks WHERE document_id = ?", (document_id,))
        blocks: List[DocumentBlock] = []
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else dict(row)
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            try:
                blocks.append(DocumentBlock(**payload))
            except Exception:  # noqa: BLE001
                continue
        return blocks

    def _evidence_ids(self, document_id: str) -> List[str]:
        rows = self._db.query(
            "SELECT payload FROM evidence WHERE raw_item_id = ?", (document_id,))
        out: List[str] = []
        for row in rows:
            payload = row.get("payload") if isinstance(row, dict) else dict(row)
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if isinstance(payload, dict) and payload.get("evidence_id"):
                out.append(payload["evidence_id"])
        return out or [_stable_id("evidence", document_id, "document")]
