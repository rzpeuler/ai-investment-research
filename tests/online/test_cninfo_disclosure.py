"""巨潮公告检索和原件下载的最小在线验收。"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from research_os.collectors.official import CninfoCollector
from research_os.documents import download_official_document

pytestmark = pytest.mark.online


def test_cninfo_annual_report_metadata_and_download_live() -> None:
    if os.environ.get("RESEARCH_SOURCE_ONLINE") != "1":
        pytest.skip("需要 RESEARCH_SOURCE_ONLINE=1")

    root = Path(__file__).resolve().parents[2]
    refs = CninfoCollector().discover(
        {"searchkey": "贵州茅台"},
        {"start": "2025-04-01T00:00:00", "end": "2025-04-10T23:59:59"},
    )
    annual_reports = [
        ref for ref in refs
        if ref.extra.get("secCode") == "600519"
        and ref.title == "贵州茅台2024年年度报告"
    ]
    assert annual_reports, "未定位到贵州茅台 2024 年年度报告"
    report = annual_reports[0]
    assert report.external_id
    assert report.published_at
    assert report.url.lower().endswith(".pdf")

    content = download_official_document(
        root, source_id="cninfo", source_url=report.url,
        max_bytes=80 * 1024 * 1024, timeout_seconds=60,
    )
    assert content.startswith(b"%PDF-")
    assert len(content) > 100_000
    assert len(hashlib.sha256(content).hexdigest()) == 64
