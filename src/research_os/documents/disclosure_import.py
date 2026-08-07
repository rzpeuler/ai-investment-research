"""官方披露原件的辅助导入、内容寻址存储和 Evidence 构建。"""
from __future__ import annotations

import hashlib
import shutil
import urllib.error
import urllib.request
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from research_os.documents.registry import (
    parse_native_text,
    parse_pdf_text,
    parse_table_blocks,
    register_document,
    sha256_file,
)
from research_os.models import DocumentBlock, DocumentRecord, Evidence, RawItem
from research_os.source_registry import SourceRegistry
from research_os.storage import Database
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_model

IMPORTER_NAME = "official_disclosure_import"
IMPORTER_VERSION = "1.0.0"
OFFICIAL_SOURCE_TYPES = {
    "official_disclosure", "exchange_disclosure", "regulatory_disclosure",
    "government_statistics", "company_official",
}


@dataclass(frozen=True)
class DisclosureImportResult:
    document_id: str
    raw_item_id: str
    evidence_id: str
    metadata_block_id: str
    checksum: str
    published_at: str
    source_id: str
    source_tier: str
    validation_status: str
    storage_path: str
    original_filename: str
    duplicate: bool
    parsed_blocks: int

    def model_dump(self) -> Dict[str, Any]:
        return asdict(self)


def _registry(project_root: Path) -> SourceRegistry:
    return SourceRegistry(Path(project_root) / "registry" / "sources.yaml")


def _official_source(project_root: Path, source_id: str, source_url: str):
    source = _registry(project_root).get(source_id)
    if source is None:
        raise ValueError(f"未登记来源: {source_id}")
    if source.source_type not in OFFICIAL_SOURCE_TYPES or source.source_tier not in {"S", "A"}:
        raise ValueError(f"来源 {source_id} 不具备官方披露资格")
    if source.paid or source.login_required or source.access_level not in {
        "public", "public_but_unstable"
    }:
        raise ValueError(f"来源 {source_id} 不允许公开辅助导入")
    if not source.last_verified_at or not source.verification_evidence:
        raise ValueError(f"来源 {source_id} 缺少真实验证证据")
    url = urlsplit(source_url)
    base = urlsplit(source.base_domain or "")
    if url.scheme not in {"http", "https"} or not url.hostname or not base.hostname:
        raise ValueError("source_url 必须是已登记官方来源的 http/https URL")
    official_host = base.hostname.lower().removeprefix("www.")
    actual_host = url.hostname.lower().removeprefix("www.")
    if actual_host != official_host and not actual_host.endswith(f".{official_host}"):
        raise ValueError(
            f"source_url 域名 {actual_host} 与来源 {source_id} 的 {official_host} 不匹配")
    return source


def _stable_id(kind: str, checksum: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"research-os:{kind}:{checksum}"))


def _content_path(project_root: Path, entity_code: str, checksum: str, suffix: str) -> Path:
    safe_entity = entity_code.replace(":", "_").replace("/", "_").replace("\\", "_")
    safe_suffix = suffix.lower() if suffix and len(suffix) <= 10 else ".bin"
    return Path(project_root) / "data" / "disclosures" / safe_entity / f"{checksum}{safe_suffix}"


def _metadata_block(
    *, document_id: str, block_id: str, source_id: str, title: str,
    publisher: str, source_url: str, published_at: str,
) -> DocumentBlock:
    excerpt = f"{title}；发布者:{publisher}；披露时间:{published_at}；官方位置:{source_url}"
    return DocumentBlock(
        block_id=block_id, document_id=document_id, block_type="header",
        page_start=1, page_end=1, bbox=None, sequence_no=0,
        section_path=["document_metadata"], content_excerpt=excerpt[:2000],
        content_hash=hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
        table_id=None, row_index=None, column_index=None,
        normalized_payload={
            "locator_kind": "document_metadata", "publisher": publisher,
            "source_url": source_url, "published_at": published_at,
        },
        extraction_method="manual", confidence=1.0,
        correction_status="accepted", correction_of_block_id=None,
        source_id=source_id, evidence_ids=[], version=1, created_at=now_iso(),
    )


def _validate_and_upsert(db: Database, obj: Any) -> None:
    errors = validate_model(obj)
    if errors:
        raise ValueError(f"{type(obj).__name__} 未通过 Schema: {errors[:5]}")
    db.upsert(obj)


def import_disclosure(
    project_root: Path,
    db: Database,
    *,
    entity_code: str,
    file_path: Path,
    source_id: str,
    source_url: str,
    publisher: str,
    published_at: str,
    document_type: str,
    title: Optional[str] = None,
    report_period_end: Optional[str] = None,
    fiscal_year: Optional[int] = None,
) -> DisclosureImportResult:
    """导入已下载的官方原件；元数据和来源资格缺一即拒绝。"""
    project_root = Path(project_root)
    file_path = Path(file_path)
    if not file_path.is_file():
        raise FileNotFoundError(file_path)
    if not entity_code or not entity_code.startswith("company:"):
        raise ValueError("entity_code 必须是 company:<股票代码>")
    if not source_url:
        raise ValueError("缺少 source_url")
    if not publisher.strip():
        raise ValueError("缺少 publisher")
    if not published_at:
        raise ValueError("缺少 published_at")
    source = _official_source(project_root, source_id, source_url)

    checksum = sha256_file(file_path)
    document_id = _stable_id("document", checksum)
    raw_item_id = _stable_id("raw-item", checksum)
    evidence_id = _stable_id("evidence", checksum)
    metadata_block_id = _stable_id("metadata-block", checksum)
    existing = db.get("document_records", document_id)
    if existing is not None:
        return DisclosureImportResult(
            document_id=document_id, raw_item_id=raw_item_id, evidence_id=evidence_id,
            metadata_block_id=metadata_block_id, checksum=checksum,
            published_at=existing["published_at"], source_id=existing["source_id"],
            source_tier=source.source_tier, validation_status="qualified",
            storage_path=existing["local_path"], original_filename=file_path.name,
            duplicate=True,
            parsed_blocks=len(db.query(
                "SELECT block_id FROM document_blocks WHERE document_id = ?", (document_id,))),
        )

    destination = _content_path(project_root, entity_code, checksum, file_path.suffix)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.copy2(file_path, destination)
    retrieved_at = now_iso()
    doc = register_document(
        destination, document_type=document_type, source_id=source_id,
        title=title or file_path.name, published_at=published_at,
        company_entity_id=entity_code, report_period_end=report_period_end,
        fiscal_year=fiscal_year, storage_policy="local_file_reference",
        copyright_status="statutory_filing", parser_name=IMPORTER_NAME,
        parser_version=IMPORTER_VERSION,
        audit_status="audited" if document_type in {"annual_report", "audit_report"} else "unknown",
    )
    doc.document_id = document_id
    doc.source_url = source_url
    doc.external_id = None
    doc.retrieved_at = retrieved_at
    doc.created_at = retrieved_at
    doc.updated_at = retrieved_at
    _validate_and_upsert(db, doc)

    metadata = _metadata_block(
        document_id=document_id, block_id=metadata_block_id, source_id=source_id,
        title=doc.title, publisher=publisher, source_url=source_url,
        published_at=published_at,
    )
    metadata.evidence_ids = [evidence_id]
    _validate_and_upsert(db, metadata)
    parsed_blocks = 1
    suffix = destination.suffix.lower()
    blocks = []
    if suffix in {".html", ".htm", ".txt"}:
        blocks = parse_native_text(destination, document_id, source_id)
    elif suffix == ".csv":
        blocks = parse_table_blocks(destination, document_id, source_id)
    elif suffix == ".pdf":
        blocks = parse_pdf_text(destination, document_id, source_id)
    for index, block in enumerate(blocks, start=1):
        block.block_id = _stable_id(f"block:{index}", checksum)
        block.sequence_no = index
        _validate_and_upsert(db, block)
        parsed_blocks += 1

    raw = RawItem(
        raw_item_id=raw_item_id, source_id=source_id, external_id=document_id,
        url=source_url, title=doc.title, publisher=publisher, author=None,
        published_at=published_at, retrieved_at=retrieved_at,
        content_hash=checksum, content_excerpt=metadata.content_excerpt or doc.title,
        content_storage="metadata_and_excerpt", language="zh-CN", access_status="ok",
        entities=[entity_code], raw_category="official_disclosure",
    )
    evidence = Evidence(
        evidence_id=evidence_id, source_id=source_id, raw_item_id=raw_item_id,
        title=doc.title, publisher=publisher, published_at=published_at,
        retrieved_at=retrieved_at, url=source_url,
        excerpt=(metadata.content_excerpt or doc.title)[:2000],
        evidence_type="official_disclosure",
        independence_group=f"official-document:{checksum}",
        source_tier=source.source_tier, access_status="ok",
    )
    _validate_and_upsert(db, raw)
    _validate_and_upsert(db, evidence)
    for block in blocks:
        block_evidence_id = _stable_id(f"block-evidence:{block.block_id}", checksum)
        block_evidence = Evidence(
            evidence_id=block_evidence_id, source_id=source_id,
            raw_item_id=raw_item_id, title=f"{doc.title}（第 {block.page_start} 页）",
            publisher=publisher, published_at=published_at, retrieved_at=retrieved_at,
            url=source_url, excerpt=(block.content_excerpt or doc.title)[:2000],
            evidence_type="official_disclosure",
            independence_group=f"official-document:{checksum}",
            source_tier=source.source_tier, access_status="ok",
        )
        block.evidence_ids = [block_evidence_id]
        _validate_and_upsert(db, block)
        _validate_and_upsert(db, block_evidence)
    if blocks:
        doc.parse_status = "parsed"
        doc.page_count = max(block.page_end for block in blocks)
        doc.updated_at = now_iso()
        _validate_and_upsert(db, doc)
    return DisclosureImportResult(
        document_id=document_id, raw_item_id=raw_item_id, evidence_id=evidence_id,
        metadata_block_id=metadata_block_id, checksum=checksum,
        published_at=published_at, source_id=source_id, source_tier=source.source_tier,
        validation_status="qualified", storage_path=str(destination),
        original_filename=file_path.name, duplicate=False, parsed_blocks=parsed_blocks,
    )


def download_official_document(
    project_root: Path,
    *,
    source_id: str,
    source_url: str,
    max_bytes: int = 100 * 1024 * 1024,
    timeout_seconds: int = 60,
    urlopen=None,
) -> bytes:
    """受控下载官方原件；调用方负责随后导入。"""
    _official_source(Path(project_root), source_id, source_url)
    opener = urlopen or urllib.request.urlopen
    request = urllib.request.Request(
        source_url, method="GET",
        headers={"Accept": "application/pdf,application/octet-stream,*/*", "User-Agent": "research-os/0.1"},
    )
    try:
        with opener(request, timeout=timeout_seconds) as response:
            final_url = response.geturl() if hasattr(response, "geturl") else source_url
            _official_source(Path(project_root), source_id, final_url)
            length = response.headers.get("Content-Length") if hasattr(response, "headers") else None
            if length and int(length) > max_bytes:
                raise ValueError("官方文件超过下载大小上限")
            data = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"官方文件下载失败 (HTTP {exc.code})") from None
    except urllib.error.URLError as exc:
        raise RuntimeError("官方文件下载网络不可达") from exc
    if not data:
        raise ValueError("官方文件为空")
    if len(data) > max_bytes:
        raise ValueError("官方文件超过下载大小上限")
    return data
