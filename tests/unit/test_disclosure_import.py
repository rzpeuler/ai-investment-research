"""官方披露原件导入、去重、来源资格、下载和 CLI 测试。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.documents.disclosure_import import (
    download_official_document,
    import_disclosure,
)
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance

ROOT = Path(__file__).resolve().parents[2]
PUBLISHED = "2026-04-01T18:00:00+08:00"
URL = "http://static.cninfo.com.cn/finalpage/2026-04-01/annual-report.pdf"


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    (tmp_path / "registry").mkdir()
    shutil.copy2(ROOT / "registry" / "sources.yaml", tmp_path / "registry" / "sources.yaml")
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(tmp_path))
    return tmp_path


@pytest.fixture()
def db(project_root):
    database = Database(project_root / "data" / "sqlite" / "research.db")
    database.initialize()
    yield database
    database.close()


def _pdf(root: Path, name="annual-report.pdf", content=b"%PDF-1.4\n/Font /Contents\n%%EOF"):
    path = root / name
    path.write_bytes(content)
    return path


def _import(project_root, db, file_path, **changes):
    payload = {
        "entity_code": "company:600519.SH", "file_path": file_path,
        "source_id": "cninfo", "source_url": URL,
        "publisher": "贵州茅台股份有限公司", "published_at": PUBLISHED,
        "document_type": "annual_report", "title": "2025年年度报告",
        "report_period_end": "2025-12-31", "fiscal_year": 2025,
    }
    payload.update(changes)
    return import_disclosure(project_root, db, **payload)


def test_official_file_import_builds_traceable_objects(project_root, db):
    result = _import(project_root, db, _pdf(project_root))
    assert result.validation_status == "qualified"
    assert result.source_tier == "S"
    assert result.duplicate is False
    assert result.parsed_blocks == 1
    stored = Path(result.storage_path)
    assert stored.is_file()
    assert stored.parent == project_root / "data" / "disclosures" / "company_600519.SH"
    assert stored.stem == result.checksum

    document = db.get("document_records", result.document_id)
    raw = db.get("raw_items", result.raw_item_id)
    evidence = db.get("evidence", result.evidence_id)
    block = db.get("document_blocks", result.metadata_block_id)
    assert document["source_url"] == URL
    assert document["copyright_status"] == "statutory_filing"
    assert document["sha256"] == result.checksum
    assert raw["content_hash"] == result.checksum
    assert raw["url"] == URL
    assert evidence["raw_item_id"] == result.raw_item_id
    assert evidence["evidence_type"] == "official_disclosure"
    assert evidence["source_tier"] == "S"
    assert block["document_id"] == result.document_id
    assert block["normalized_payload"]["locator_kind"] == "document_metadata"
    for name, payload in [
        ("document_record", document), ("raw_item", raw),
        ("evidence", evidence), ("document_block", block),
    ]:
        assert validate_instance(payload, name) == []


def test_checksum_deduplicates_same_content(project_root, db):
    first = _import(project_root, db, _pdf(project_root, "first.pdf"))
    second = _import(project_root, db, _pdf(project_root, "renamed.pdf"))
    assert second.duplicate is True
    assert second.document_id == first.document_id
    assert second.storage_path == first.storage_path
    assert db.count("document_records") == 1
    assert db.count("raw_items") == 1
    assert db.count("evidence") == 1


def test_same_name_different_content_is_not_overwritten(project_root, db):
    path = _pdf(project_root, "report.pdf", b"%PDF first")
    first = _import(project_root, db, path)
    path.write_bytes(b"%PDF second")
    second = _import(project_root, db, path)
    assert second.duplicate is False
    assert first.checksum != second.checksum
    assert Path(first.storage_path).read_bytes() == b"%PDF first"
    assert Path(second.storage_path).read_bytes() == b"%PDF second"
    assert db.count("document_records") == 2


@pytest.mark.parametrize(
    ("changes", "message"),
    [({"source_url": ""}, "source_url"),
     ({"published_at": ""}, "published_at"),
     ({"publisher": ""}, "publisher"),
     ({"source_id": "user_document"}, "官方披露资格"),
     ({"source_url": "https://example.com/report.pdf"}, "域名")],
)
def test_invalid_metadata_or_source_is_rejected(project_root, db, changes, message):
    with pytest.raises(ValueError, match=message):
        _import(project_root, db, _pdf(project_root), **changes)
    assert db.count("document_records") == 0


def test_missing_file_is_rejected(project_root, db):
    with pytest.raises(FileNotFoundError):
        _import(project_root, db, project_root / "missing.pdf")


class FakeDownloadResponse:
    def __init__(self, data=b"%PDF official", url=URL, content_length=None):
        self.data = data
        self.url = url
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.data[:limit]


def test_official_download_validates_final_domain_and_size(project_root):
    data = download_official_document(
        project_root, source_id="cninfo", source_url=URL,
        urlopen=lambda request, timeout: FakeDownloadResponse(),
    )
    assert data == b"%PDF official"
    with pytest.raises(ValueError, match="域名"):
        download_official_document(
            project_root, source_id="cninfo", source_url=URL,
            urlopen=lambda request, timeout: FakeDownloadResponse(
                url="https://example.com/redirect.pdf"),
        )
    with pytest.raises(ValueError, match="大小上限"):
        download_official_document(
            project_root, source_id="cninfo", source_url=URL, max_bytes=5,
            urlopen=lambda request, timeout: FakeDownloadResponse(content_length=100),
        )


def test_cli_import_disclosure(project_root):
    file_path = _pdf(project_root)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "documents", "import-disclosure", "--entity", "600519.SH",
        "--file", str(file_path), "--source-id", "cninfo", "--source-url", URL,
        "--publisher", "贵州茅台股份有限公司", "--published-at", PUBLISHED,
        "--document-type", "annual_report", "--report-period-end", "2025-12-31",
        "--fiscal-year", "2025",
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["validation_status"] == "qualified"
    assert payload["source_tier"] == "S"
    assert payload["document_id"]
    assert payload["raw_item_id"]
    assert payload["evidence_id"]
