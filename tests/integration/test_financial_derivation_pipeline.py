"""P7-D4 M5：company_document → derive_existing → readiness recheck 集成测试（离线）。

用真实 SQLite（tmp_path）+ synthetic PDF + mock 下载，验证完整链：
materialize（DocumentRecord/Block/Evidence 幂等持久化）
→ DerivationPrerequisiteResolver（合格）
→ FinancialDerivationService（FinancialReport/Manifest/Facts 幂等）
→ DataPreflightService recheck（financial_statement_data readiness 变化）。
零网络。
"""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.derivation import (
    DerivationPrerequisiteResolver,
    FinancialDerivationExecutor,
)
from research_os.data_layer.preflight import DataPreflightService
from research_os.documents.disclosure_materializer import TransientDisclosureMaterializer
from research_os.models import DocumentBlock
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry
from research_os.storage.db import Database

TS = "2026-04-30T10:00:00+08:00"
AS_OF = "2026-05-01T00:00:00+08:00"
ROOT = Path(__file__).resolve().parents[2]


def _make_pdf_bytes() -> bytes:
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _real_parser(path, document_id, source_id):
    text = (
        "贵州茅台2025年年度报告 单位：元\n"
        "合并利润表\n项目 本期金额 上期金额\n"
        "营业收入 10,000,000.00 9,000,000.00\n"
        "归属于母公司所有者的净利润 1,800,000.00 1,400,000.00\n"
        "合并资产负债表\n项目 期末余额 期初余额\n"
        "资产总计 25,000,000.00 20,000,000.00\n"
        "负债合计 10,000,000.00 9,000,000.00\n"
        "归属于母公司所有者权益合计 15,000,000.00 11,000,000.00\n"
    )
    blocks = []
    for i, line in enumerate(text.splitlines()):
        blocks.append(DocumentBlock(
            block_id=f"blk-{i}", document_id=document_id, block_type="text",
            page_start=1, page_end=1, bbox=None, sequence_no=i, section_path=[],
            content_excerpt=line, content_hash=f"{i:064x}", table_id=None,
            row_index=None, column_index=None, normalized_payload=None,
            extraction_method="native_text", confidence=None,
            correction_status="unreviewed", correction_of_block_id=None,
            source_id=source_id, evidence_ids=[], version=1, created_at=TS,
        ))
    return blocks


@pytest.fixture
def project_db(tmp_path) -> Database:
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()  # 应用迁移（建 document_records/document_blocks/evidence/financial_*）
    return db


@pytest.fixture
def materializer(project_db):
    return TransientDisclosureMaterializer(project_db, parser=_real_parser)


def _urlopen(data: bytes):
    response = MagicMock()
    response.geturl.return_value = "https://static.cninfo.com.cn/finalpage/2026/x.PDF"
    response.headers = {"Content-Type": "application/pdf"}
    response.read.return_value = data
    response.__enter__.return_value = response
    return lambda request, timeout=None: response


class TestCompanyDocumentPipeline:
    def test_materialize_then_derive_then_recheck(
        self, project_db, materializer, monkeypatch
    ):
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen(_make_pdf_bytes()))
        # 1) materialize company_document
        doc = materializer.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id="security:600519.SH", source_id="cninfo",
            source_url="https://static.cninfo.com.cn/finalpage/2026/x.PDF",
            title="贵州茅台：2025年年度报告", published_at=TS,
            document_type="annual_report", external_id="ann-1",
            report_period_end="2025-12-31", fiscal_year=2025,
        )
        assert doc.inserted is True
        assert project_db.query(
            "SELECT payload FROM document_records WHERE document_id = ?",
            (doc.document_id,))
        assert project_db.query(
            "SELECT payload FROM document_blocks WHERE document_id = ?",
            (doc.document_id,))

        # 2) derive financial facts（ZERO NETWORK）
        executor = FinancialDerivationExecutor(
            project_db, resolver=DerivationPrerequisiteResolver(project_db),
            service=__import__(
                "research_os.data_layer.derivation", fromlist=["FinancialDerivationService"]
            ).FinancialDerivationService(project_db),
        )
        from research_os.data_layer.execution import RouteExecutionInput
        from research_os.models import AcquisitionStep

        step = AcquisitionStep(
            step_id="sB", requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=["sA"], status="pending", warnings=[])
        outcome = executor.execute(
            step=step, task_id="t1", as_of=AS_OF,
            route_input=RouteExecutionInput(
                query={"entity_ids": ["company:maotai"]},
                time_window={"start": None, "end": AS_OF}),
        )
        assert outcome.status == "completed", outcome.warnings
        assert len(outcome.produced_record_refs) >= 5  # manifest + report + ≥3 facts

        reports = project_db.query(
            "SELECT payload FROM financial_reports WHERE company_entity_id = ?",
            ("company:maotai",))
        assert reports
        report = json.loads(reports[0]["payload"]) if isinstance(
            reports[0]["payload"], str) else reports[0]["payload"]
        assert report["report_type"] == "annual"
        assert report["statement_scope"] == "consolidated"
        assert report["period_end"] == "2025-12-31"
        assert report["published_at"] == TS  # valid_from = official published_at

        facts = project_db.query(
            "SELECT payload FROM financial_facts WHERE company_entity_id = ?",
            ("company:maotai",))
        assert len(facts) >= 3
        codes = set()
        for row in facts:
            payload = json.loads(row["payload"]) if isinstance(
                row["payload"], str) else row["payload"]
            codes.add(payload["taxonomy_code"])
            assert payload["evidence_ids"]  # 每个 fact 必须有 evidence lineage（§39）
            assert payload["valid_from"] == TS  # §37
        assert {"revenue", "total_assets", "equity_attr"} <= codes

        # 3) 幂等 rerun
        second = executor.execute(
            step=step, task_id="t1", as_of=AS_OF,
            route_input=RouteExecutionInput(
                query={"entity_ids": ["company:maotai"]},
                time_window={"start": None, "end": AS_OF}),
        )
        assert second.status == "completed"
        assert second.reused_record_refs
        assert len(project_db.query(
            "SELECT payload FROM financial_facts WHERE company_entity_id = ?",
            ("company:maotai",))) == len(facts)

        # 4) DataPreflight recheck（权威 readiness-after）
        req = ScenarioDataRequirementRegistry(
            ROOT / "registry" / "scenario_data_requirements.yaml")
        cap = AcquisitionCapabilityRegistry(
            ROOT / "registry" / "data_acquisition_capabilities.yaml",
            scenario_requirements=req, repo_root=ROOT,
        )
        preflight = DataPreflightService(
            req, cap, derivation_prerequisites={
                "financial_statement_data": "company_document"})
        bundle = preflight.run(
            scenario="stock_research_report",
            task_id="11111111-1111-4111-8111-111111111111",
            task_as_of=AS_OF,
            normalized_request={
                "entity": "company:maotai",  # stock_research_report 的 subject 字段
                "as_of": AS_OF,
            },
            project_root=ROOT, db=project_db, runs_root=ROOT / "reports" / "runs",
            graph_repo=None, dry_run=False,
        )
        fin = next(
            (r for r in bundle.readiness
             if r.requirement_id == "stock_research_report.financial_statement_data"), None)
        assert fin is not None
        # 有真实 financial_facts 后不再 MISSING（PIT：published_at=TS ≤ as_of）
        assert fin.eligible_record_count >= 3

    def test_pit_future_document_not_eligible(self, project_db, materializer, monkeypatch):
        # as_of < published_at → derive prerequisite 不满足（§50 A）
        monkeypatch.setattr(
            "research_os.documents.disclosure_materializer.urllib.request.urlopen",
            _urlopen(_make_pdf_bytes()))
        doc = materializer.materialize(
            ROOT, company_entity_id="company:maotai",
            security_entity_id=None, source_id="cninfo",
            source_url="https://static.cninfo.com.cn/x.PDF",
            title="贵州茅台：2025年年度报告", published_at="2026-06-01T00:00:00+08:00",
            document_type="annual_report", external_id="ann-2",
            report_period_end="2025-12-31", fiscal_year=2025,
        )
        assert doc.inserted is True
        resolver = DerivationPrerequisiteResolver(project_db)
        result = resolver.resolve(
            project_db, subject_entity="company:maotai",
            data_type="financial_statement_data", as_of="2026-05-01T00:00:00+08:00")
        assert result.ready is False
        assert any("未来披露" in w for w in result.warnings)
