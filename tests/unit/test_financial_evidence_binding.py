"""核心财务事实到官方原件的定位、数值和审计绑定测试。"""
from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

import pytest

from research_os.documents import import_disclosure
from research_os.equity_research.validator import validate_equity_research
from research_os.financials.evidence_binding import CORE_FINANCIAL_CODES, bind_official_financial_evidence
from research_os.financials.import_service import import_financial_file, persist_import
from research_os.models.financials import FinancialEvidenceBindingManifest
from research_os.storage import Database
from research_os.validators.schema_validator import validate_model

ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-04-01T23:59:59+08:00"
REQUESTED_AT = "2026-04-02T10:00:00+08:00"


@pytest.fixture()
def binding_context(tmp_path, monkeypatch):
    (tmp_path / "registry").mkdir()
    shutil.copy2(ROOT / "registry" / "sources.yaml", tmp_path / "registry" / "sources.yaml")
    shutil.copytree(ROOT / "schemas", tmp_path / "schemas")
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(tmp_path))
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()
    pdf = tmp_path / "annual.pdf"
    pdf.write_bytes(b"%PDF-1.4 official financial statements %%EOF")
    disclosure = import_disclosure(
        tmp_path, db, entity_code="company:600519.SH", file_path=pdf,
        source_id="cninfo",
        source_url="http://static.cninfo.com.cn/finalpage/2026-04-01/report.pdf",
        publisher="贵州茅台股份有限公司", published_at="2026-04-01T18:00:00+08:00",
        document_type="annual_report", title="2025年年度报告",
        report_period_end="2025-12-31", fiscal_year=2025,
    )
    csv_path = tmp_path / "facts.csv"
    csv_path.write_text(
        "company_entity_id,period_start,period_end,fiscal_year,report_type,statement_scope,statement_type,taxonomy_code,label_raw,value,unit_scale,currency,published_at\n"
        "company:600519.SH,2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,1000000,1,CNY,2026-04-01T18:00:00+08:00\n",
        encoding="utf-8",
    )
    imported = import_financial_file(csv_path, company_entity_id="company:600519.SH")
    persist_import(db, imported)
    yield tmp_path, db, disclosure, imported, pdf
    db.close()


def _binding(disclosure, **changes):
    locator = {
        "taxonomy_code": "revenue", "period_end": "2025-12-31",
        "statement_scope": "consolidated", "document_id": disclosure.document_id,
        "document_evidence_id": disclosure.evidence_id, "locator_kind": "cell",
        "page_start": 88, "page_end": 88, "section_path": ["合并利润表"],
        "table_id": "income_statement", "row_index": 3, "column_index": 1,
        "cell_reference": "营业收入/本期", "text_start": None, "text_end": None,
        "structured_field": "revenue.current", "source_excerpt": "营业收入 1,000,000 元",
        "reported_raw_value": "1000000", "currency": "CNY", "unit_scale": 1,
        "confirmation_status": "confirmed", "confirmed_by": "acceptance-reviewer",
        "confirmed_at": "2026-04-02T09:00:00+08:00", "correction_reason": None,
    }
    locator.update(changes)
    return FinancialEvidenceBindingManifest(
        binding_version="1.0.0", company_entity_id="company:600519.SH",
        as_of=AS_OF, locators=[locator],
    )


def test_bind_official_financial_evidence_creates_full_lineage(binding_context):
    root, db, disclosure, imported, _ = binding_context
    binding = _binding(disclosure)
    assert validate_model(binding) == []
    result = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact], binding=binding,
        as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    assert len(result.bound_fact_ids) == 1
    fact = db.get("financial_facts", result.bound_fact_ids[0])
    block = db.get("document_blocks", result.block_ids[0])
    evidence = db.get("evidence", result.evidence_ids[0])
    document = db.get("document_records", disclosure.document_id)
    assert fact["source_document_id"] == disclosure.document_id
    assert fact["source_block_ids"] == result.block_ids
    assert fact["evidence_ids"] == result.evidence_ids
    assert fact["source_priority"] == 1
    assert block["page_start"] == 88
    assert block["normalized_payload"]["reported_raw_value"] == "1000000"
    assert block["normalized_payload"]["document_checksum"] == document["sha256"]
    assert evidence["evidence_type"] == "official_disclosure"
    assert evidence["source_tier"] == "S"
    assert evidence["url"] == document["source_url"]
    assert disclosure.document_id in imported.manifest.document_ids
    assert imported.reports[0].document_id == disclosure.document_id


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"reported_raw_value": "999999"}, "数值不一致"),
        ({"currency": "USD"}, "币种或单位"),
        ({"document_id": "missing"}, "官方文档不存在"),
        ({"confirmed_at": "2026-04-02T10:00:01+08:00"}, "晚于 requested_at"),
        ({"confirmation_status": "corrected", "correction_reason": None}, "correction_reason"),
    ],
)
def test_binding_rejects_invalid_or_unverified_input(binding_context, changes, message):
    root, db, disclosure, imported, _ = binding_context
    with pytest.raises(ValueError, match=message):
        bind_official_financial_evidence(
            root, db, manifest=imported.manifest, reports=imported.reports,
            facts=[row.fact for row in imported.rows if row.fact],
            binding=_binding(disclosure, **changes), as_of=AS_OF,
            requested_at=REQUESTED_AT,
        )


def test_binding_rejects_tampered_official_file(binding_context):
    root, db, disclosure, imported, pdf = binding_context
    Path(disclosure.storage_path).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="checksum"):
        bind_official_financial_evidence(
            root, db, manifest=imported.manifest, reports=imported.reports,
            facts=[row.fact for row in imported.rows if row.fact],
            binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
        )


def test_validator_accepts_a_valid_official_core_fact_lineage(binding_context):
    root, db, disclosure, imported, _ = binding_context
    bound = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact],
        binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    outcome = validate_equity_research(
        result={"research_status": "partial_success"},
        facts=[db.get("financial_facts", bound.bound_fact_ids[0])],
        documents=[db.get("document_records", disclosure.document_id)],
        blocks=[db.get("document_blocks", bound.block_ids[0])],
        evidences=[db.get("evidence", bound.evidence_ids[0])],
        as_of=AS_OF, request={"requested_at": REQUESTED_AT},
    )
    assert not [issue for issue in outcome.issues if issue.rule_id.startswith("ERV-08")]


def test_validator_rejects_confirmation_after_requested_at(binding_context):
    root, db, disclosure, imported, _ = binding_context
    bound = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact],
        binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    block = db.get("document_blocks", bound.block_ids[0])
    block["normalized_payload"]["confirmed_at"] = "2026-04-02T10:00:01+08:00"
    outcome = validate_equity_research(
        facts=[db.get("financial_facts", bound.bound_fact_ids[0])],
        documents=[db.get("document_records", disclosure.document_id)],
        blocks=[block], evidences=[db.get("evidence", bound.evidence_ids[0])],
        as_of=AS_OF, request={"requested_at": REQUESTED_AT},
    )
    assert any(issue.rule_id == "ERV-086" and "requested_at" in issue.message
               for issue in outcome.errors)


@pytest.mark.parametrize("future_object", ["document", "evidence"])
def test_validator_still_rejects_official_source_published_after_as_of(
    binding_context, future_object,
):
    root, db, disclosure, imported, _ = binding_context
    bound = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact],
        binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    document = db.get("document_records", disclosure.document_id)
    evidence = db.get("evidence", bound.evidence_ids[0])
    if future_object == "document":
        document["published_at"] = "2026-04-02T00:00:00+08:00"
    else:
        evidence["published_at"] = "2026-04-02T00:00:00+08:00"
    outcome = validate_equity_research(
        facts=[db.get("financial_facts", bound.bound_fact_ids[0])],
        documents=[document], blocks=[db.get("document_blocks", bound.block_ids[0])],
        evidences=[evidence], as_of=AS_OF,
        request={"requested_at": REQUESTED_AT},
    )
    assert any(issue.rule_id == "ERV-085" and "晚于 as_of" in issue.message
               for issue in outcome.errors)


def test_validator_rejects_tier_c_core_fact_even_with_unrelated_official_evidence(binding_context):
    _, db, disclosure, imported, _ = binding_context
    fact = next(row.fact.model_dump() for row in imported.rows if row.fact)
    unrelated = db.get("evidence", disclosure.evidence_id)
    fact["evidence_ids"] = [disclosure.evidence_id]
    outcome = validate_equity_research(
        result={"research_status": "success"}, facts=[fact],
        evidences=[unrelated], as_of=AS_OF,
    )
    assert any(issue.rule_id == "ERV-080" for issue in outcome.errors)
    assert any(issue.rule_id == "ERV-087" for issue in outcome.errors)


def test_validator_allows_success_when_all_nine_core_codes_have_official_lineage(binding_context):
    root, db, disclosure, imported, _ = binding_context
    bound = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact],
        binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    base_fact = db.get("financial_facts", bound.bound_fact_ids[0])
    base_block = db.get("document_blocks", bound.block_ids[0])
    base_evidence = db.get("evidence", bound.evidence_ids[0])
    facts, blocks, evidences = [], [], []
    for index, code in enumerate(sorted(CORE_FINANCIAL_CODES)):
        fact, block, evidence = deepcopy(base_fact), deepcopy(base_block), deepcopy(base_evidence)
        fact["fact_id"] = f"fact-{index}"
        fact["taxonomy_code"] = code
        fact["statement_type"] = (
            "balance_sheet" if code in {"total_assets", "total_liabilities", "equity_attr"}
            else "cash_flow" if code == "operating_cash_flow" else "income_statement"
        )
        fact["instant_or_duration"] = "instant" if fact["statement_type"] == "balance_sheet" else "duration"
        block["block_id"] = f"block-{index}"
        block["normalized_payload"]["taxonomy_code"] = code
        evidence["evidence_id"] = f"evidence-{index}"
        block["evidence_ids"] = [evidence["evidence_id"]]
        fact["source_block_ids"] = [block["block_id"]]
        fact["evidence_ids"] = [evidence["evidence_id"]]
        facts.append(fact)
        blocks.append(block)
        evidences.append(evidence)
    outcome = validate_equity_research(
        result={"research_status": "success"}, facts=facts,
        documents=[db.get("document_records", disclosure.document_id)],
        blocks=blocks, evidences=evidences, as_of=AS_OF,
    )
    assert not [issue for issue in outcome.issues if issue.rule_id.startswith("ERV-08")]


def test_validator_rejects_locator_value_tampering(binding_context):
    root, db, disclosure, imported, _ = binding_context
    bound = bind_official_financial_evidence(
        root, db, manifest=imported.manifest, reports=imported.reports,
        facts=[row.fact for row in imported.rows if row.fact],
        binding=_binding(disclosure), as_of=AS_OF, requested_at=REQUESTED_AT,
    )
    block = db.get("document_blocks", bound.block_ids[0])
    block["normalized_payload"]["reported_raw_value"] = "1"
    outcome = validate_equity_research(
        facts=[db.get("financial_facts", bound.bound_fact_ids[0])],
        documents=[db.get("document_records", disclosure.document_id)],
        blocks=[block], evidences=[db.get("evidence", bound.evidence_ids[0])],
        as_of=AS_OF,
    )
    assert any(issue.rule_id == "ERV-084" for issue in outcome.errors)
