"""P7-D4 M1：TransientDisclosureMaterializer（方案 B，taskbook §8）。

CNINFO 官方年报 → transient PDF 下载 → 严格校验 → 原生文本解析 →
DocumentRecord / DocumentBlock / Evidence 幂等持久化 → temp PDF 删除。

约束（taskbook P7-D4 §7/§9/§10/§41/§42）：
- storage_policy = metadata_and_excerpt；local_path = null；不永久保存完整 PDF。
- 复用 download_official_document() 的全部安全校验（source_id 登记/host/redirect/
  timeout/max_bytes/empty），并额外：PDF magic header、Content-Type 合理性、
  HTML error page 拒绝、zero-byte 拒绝、checksum before parsing。
- pypdf 缺失 → CONTROL_PLANE_CONFIGURATION_ERROR；解析失败 → DOCUMENT_PARSE_FAILED。
- 稳定 UUID5 幂等：同一官方文档重复运行 inserted→reused。
"""
from __future__ import annotations

import hashlib
import tempfile
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Optional

from research_os.documents.disclosure_import import download_official_document
from research_os.documents.registry import parse_pdf_text
from research_os.models import (
    DocumentBlock,
    DocumentRecord,
    Evidence,
    RawItem,
)
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_model

_UUID5_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

# 文档级 Evidence 的 excerpt 长度上限（metadata_and_excerpt 边界）
_EXCERPT_LIMIT = 600


@dataclass
class DocumentMaterializationResult:
    document_id: str
    block_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    inserted: bool = True  # False = 幂等复用
    page_count: Optional[int] = None
    warnings: List[str] = field(default_factory=list)


def _stable_id(kind: str, *parts: str) -> str:
    return str(uuid.uuid5(_UUID5_NS, "research-os:" + kind + ":" + ":".join(parts)))


def _validate_pdf_bytes(data: bytes, content_type: str = "") -> None:
    """PDF 下载内容校验（taskbook §9）；任何失败 → raise ValueError（fail closed）。"""
    if not data:
        raise ValueError("PDF 内容为空（zero-byte）")
    if len(data) < 5 or data[:4] != b"%PDF":
        raise ValueError("下载内容不是 PDF（缺 PDF magic header；可能为 HTML/错误页）")
    low = data[:1024].lower()
    for marker in (b"<html", b"<!doctype", b"<head"):
        if marker in low:
            raise ValueError("下载内容为 HTML 错误页/登录页，拒绝当作 PDF")
    if content_type:
        ct = content_type.lower()
        if "html" in ct or "text/plain" in ct:
            raise ValueError(f"Content-Type 不合理（{content_type!r}），拒绝当作 PDF")


class _ContentTypeCapture:
    """包装 urlopen 记录响应 Content-Type，供 PDF 合理性检查。"""

    def __init__(self, opener: Callable):
        self._opener = opener
        self.content_type = ""

    def __call__(self, request: Any, timeout: Optional[float] = None) -> Any:
        response = self._opener(request, timeout=timeout)
        try:
            headers = getattr(response, "headers", None)
            if headers is not None:
                self.content_type = headers.get("Content-Type", "")
        except Exception:  # noqa: BLE001 -- Content-Type 缺失不阻断 magic header 校验
            pass
        return response


class TransientDisclosureMaterializer:
    """受控 materialize 单一文档：下载 → 校验 → 解析 → 幂等持久化 → 删除 temp。"""

    def __init__(self, db: Any, *, parser: Callable = parse_pdf_text):
        self._db = db
        self._parser = parser

    def materialize(
        self,
        project_root: Path,
        *,
        company_entity_id: str,
        security_entity_id: Optional[str],
        source_id: str,
        source_url: str,
        title: str,
        published_at: str,
        document_type: str,
        external_id: str,
        report_period_end: str,
        fiscal_year: int,
        raw_item: Optional[RawItem] = None,
        max_bytes: int = 100 * 1024 * 1024,
        timeout_seconds: int = 60,
    ) -> DocumentMaterializationResult:
        """materialize 一份官方年报。重复调用对同一文档幂等（UUID5 + upsert）。"""
        now = now_iso()
        # 1) checksum before parsing：下载后立即哈希
        capture = _ContentTypeCapture(urllib.request.urlopen)
        try:
            data = download_official_document(
                project_root, source_id=source_id, source_url=source_url,
                max_bytes=max_bytes, timeout_seconds=timeout_seconds,
                urlopen=capture,
            )
        except Exception as exc:  # noqa: BLE001 -- 结构化失败（不泄露原始内容）
            raise ValueError(f"DOCUMENT_DOWNLOAD_FAILED: {type(exc).__name__}") from None
        _validate_pdf_bytes(data, content_type=capture.content_type)
        sha256 = hashlib.sha256(data).hexdigest()

        document_id = _stable_id(
            "document", sha256, company_entity_id, report_period_end, document_type,
        )
        # 2) 幂等：同 checksum/company/period/type 已存在 → reuse
        existing = self._load_document(document_id)
        if existing is not None:
            return DocumentMaterializationResult(
                document_id=document_id,
                block_ids=self._block_ids_for(document_id),
                evidence_ids=self._evidence_ids_for(document_id),
                inserted=False,
                page_count=existing.page_count,
                warnings=["复用既有 DocumentRecord（幂等）"],
            )

        # 3) transient 落盘解析（temp 文件，解析后删除）
        blocks: List[DocumentBlock] = []
        page_count: Optional[int] = None
        tmp_path: Optional[Path] = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
                handle.write(data)
                tmp_path = Path(handle.name)
            try:
                blocks = self._parser(tmp_path, document_id, source_id)
            except Exception:  # noqa: BLE001 -- parser failure is a document error
                raise ValueError("DOCUMENT_PARSE_FAILED: 原生文本解析失败") from None
            try:
                from pypdf import PdfReader  # noqa: F401
            except Exception:  # noqa: BLE001
                raise ValueError(
                    "CONTROL_PLANE_CONFIGURATION_ERROR: pypdf 缺失（生产解析能力未配置）"
                ) from None
            page_count = self._count_pages(tmp_path)
        finally:
            if tmp_path is not None and tmp_path.exists():
                tmp_path.unlink(missing_ok=True)

        record = DocumentRecord(
            document_id=document_id,
            company_entity_id=company_entity_id,
            security_entity_id=security_entity_id,
            document_type=document_type,
            title=title,
            source_id=source_id,
            source_url=source_url,
            local_path=None,  # 不保存完整 PDF
            external_id=external_id,
            published_at=published_at,
            retrieved_at=now,
            report_period_end=report_period_end,
            fiscal_year=fiscal_year,
            mime_type="application/pdf",
            file_size_bytes=len(data),
            sha256=sha256,
            storage_policy="metadata_and_excerpt",
            copyright_status="statutory_filing",
            text_layer_status=("present" if blocks else "absent"),
            table_parse_status="not_started",
            ocr_status="not_started",
            parser_name="pypdf",
            parser_version=self._parser_version(),
            page_count=page_count,
            audit_status="unknown",
            parse_status=("parsed" if blocks else "registered"),
            warnings=[] if blocks else ["DOCUMENT_NATIVE_TEXT_UNAVAILABLE"],
            version=1,
            created_at=now,
            updated_at=now,
        )

        # 4) 文档级 Evidence（raw_item 关联公告；excerpt 用文档标题/首个 block）
        evidence = self._build_evidence(
            company_entity_id=company_entity_id,
            source_id=source_id,
            source_url=source_url,
            title=title,
            published_at=published_at,
            now=now,
            document_id=document_id,
            raw_item=raw_item,
            blocks=blocks,
        )

        # 5) 原子写入（同一事务）：record → blocks → evidence
        try:
            self._db.upsert(record)
            for block in blocks:
                self._db.upsert(block)
            if evidence is not None:
                self._db.upsert(evidence)
        except Exception:  # noqa: BLE001 -- 任一失败整体失败（调用方 rollback 语义）
            raise ValueError("PERSIST_FAILED: DocumentRecord/Block/Evidence 持久化失败") from None

        result = DocumentMaterializationResult(
            document_id=document_id,
            block_ids=[b.block_id for b in blocks],
            evidence_ids=[evidence.evidence_id] if evidence is not None else [],
            inserted=True,
            page_count=page_count,
        )
        if not blocks:
            result.warnings.append("DOCUMENT_NATIVE_TEXT_UNAVAILABLE: 无原生文本层（不调用 OCR）")
        return result

    # ---------- helpers ----------

    def _build_evidence(
        self, *, company_entity_id: str, source_id: str, source_url: str, title: str,
        published_at: str, now: str, document_id: str, raw_item: Optional[RawItem],
        blocks: List[DocumentBlock],
    ) -> Optional[Evidence]:
        excerpt = title[: _EXCERPT_LIMIT]
        if blocks:
            excerpt = (blocks[0].content_excerpt or title)[: _EXCERPT_LIMIT]
        evidence_id = _stable_id("evidence", document_id, "document")
        return Evidence(
            evidence_id=evidence_id,
            source_id=source_id,
            raw_item_id=(raw_item.raw_item_id if raw_item is not None else document_id),
            title=title[:200],
            publisher=company_entity_id,
            published_at=published_at,
            retrieved_at=now,
            url=source_url,
            excerpt=excerpt,
            evidence_type="official_document",
            independence_group=_stable_id("independence", document_id),
            source_tier="A",
            access_status="ok",
        )

    def _load_document(self, document_id: str) -> Optional[DocumentRecord]:
        rows = self._db.query(
            "SELECT payload FROM document_records WHERE document_id = ?", (document_id,))
        if not rows:
            return None
        payload = rows[0].get("payload")
        if isinstance(payload, str):
            import json

            try:
                payload = json.loads(payload)
            except (TypeError, ValueError):
                return None
        if not isinstance(payload, dict):
            return None
        try:
            return DocumentRecord(**payload)
        except Exception:  # noqa: BLE001 -- 存量 payload 结构异常 → 视为不存在（fail closed）
            return None

    def _block_ids_for(self, document_id: str) -> List[str]:
        rows = self._db.query(
            "SELECT payload FROM document_blocks WHERE document_id = ?", (document_id,))
        out = []
        for row in rows:
            payload = row["payload"] if isinstance(row, dict) else dict(row)
            if isinstance(payload, str):
                import json
                payload = json.loads(payload)
            bid = payload.get("block_id") if isinstance(payload, dict) else None
            if bid:
                out.append(bid)
        return out

    def _evidence_ids_for(self, document_id: str) -> List[str]:
        return [_stable_id("evidence", document_id, "document")]

    def _count_pages(self, path: Path) -> Optional[int]:
        try:
            from pypdf import PdfReader

            return len(PdfReader(str(path)).pages)
        except Exception:  # noqa: BLE001
            return None

    def _parser_version(self) -> Optional[str]:
        try:
            import pypdf

            return getattr(pypdf, "__version__", None)
        except Exception:  # noqa: BLE001
            return None
