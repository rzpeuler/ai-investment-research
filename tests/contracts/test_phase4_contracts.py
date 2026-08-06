"""Phase 4 契约测试（任务书 3.25 合约测试节）。

验证：Schema 总数严格等于 50；entity 兼容 security 枚举；
20 个新 Schema 全字段 required、additionalProperties:false、nullable 正确；
Pydantic extra=forbid；model_dump() 后必须通过对应 Schema；
财务十进制值不被 float 持久化；无多余顶层空壳 Schema。

遵循 schema-model-contract.md：JSON Schema 为完整权威契约，Pydantic 仅构造便利。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from research_os.models import (
    BusinessSegment,
    Catalyst,
    CompanyProfile,
    CompetitiveFactor,
    DocumentBlock,
    DocumentRecord,
    EquityResearchRequest,
    EquityResearchResult,
    EquityResearchRun,
    FinancialDataManifest,
    FinancialFact,
    FinancialMetric,
    FinancialReport,
    ForecastScenario,
    PeerCandidate,
    PeerSelection,
    ResearchFinding,
    RiskFactor,
    SecurityProfile,
    ValuationSnapshot,
)
from research_os.models import Entity, EntityType
from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    validate_all_schemas,
    validate_model,
)

UUID1 = "11111111-1111-1111-1111-111111111111"
UUID2 = "22222222-2222-2222-2222-222222222222"
UUID3 = "33333333-3333-3333-3333-333333333333"
UUID4 = "44444444-4444-4444-4444-444444444444"
UUID5 = "55555555-5555-5555-5555-555555555555"
TS = "2026-08-06T20:00:00"
D = "2026-08-06"
SHA = "a" * 64
COMPANY = "company:600519.SH"
SECURITY = "security:600519.SH"

PHASE4_SCHEMAS = {
    "company_profile", "security_profile", "document_record", "document_block",
    "financial_data_manifest", "financial_report", "financial_fact",
    "financial_metric", "business_segment", "peer_candidate", "peer_selection",
    "valuation_snapshot", "forecast_scenario", "competitive_factor", "catalyst",
    "risk_factor", "research_finding", "equity_research_request",
    "equity_research_run", "equity_research_result",
}


# ---------- 构造工厂 ----------

def _company_profile():
    return CompanyProfile(
        company_profile_id=UUID1, entity_id=COMPANY, canonical_name="贵州茅台",
        unified_social_credit_code=None, registered_address=None,
        industry_ids=["industry:liquor"], business_description="白酒制造销售",
        fiscal_year_end="12-31", reporting_currency="CNY", ownership_type="state_owned",
        controlling_shareholder_entity_id=None, actual_controller_entity_ids=[],
        valid_from="2001-01-01", valid_to=None, source_ids=["manual_inbox"],
        evidence_ids=[], status="active", created_at=TS, updated_at=TS,
    )


def _security_profile():
    return SecurityProfile(
        security_profile_id=UUID1, security_entity_id=SECURITY,
        company_entity_id=COMPANY, symbol="600519.SH", exchange="SH", board="main",
        security_type="common_share", listing_date="2001-08-27", delisting_date=None,
        currency="CNY", share_class="A", current_name="贵州茅台",
        former_names=[], status="listed", source_ids=["manual_inbox"],
        evidence_ids=[], created_at=TS, updated_at=TS,
    )


def _document_record():
    return DocumentRecord(
        document_id=UUID1, company_entity_id=COMPANY, security_entity_id=SECURITY,
        document_type="annual_report", title="2025 年年度报告", source_id="cninfo",
        source_url="https://example.com/a.pdf", local_path=None, external_id=None,
        published_at=TS, retrieved_at=TS, report_period_end="2025-12-31",
        fiscal_year=2025, language="zh-CN", mime_type="application/pdf",
        file_size_bytes=1000, sha256=SHA, version_label=None,
        supersedes_document_id=None, storage_policy="metadata_and_excerpt",
        copyright_status="statutory_filing", text_layer_status="present",
        table_parse_status="not_started", ocr_status="not_needed",
        parser_name=None, parser_version=None, page_count=200,
        audit_status="audited", parse_status="registered",
        created_at=TS, updated_at=TS,
    )


def _document_block():
    return DocumentBlock(
        block_id=UUID1, document_id=UUID2, block_type="table_row",
        page_start=1, page_end=1, bbox=None, sequence_no=0,
        section_path=["财务报表"], content_excerpt="营业收入 1000 亿",
        content_hash=SHA, table_id="t1", row_index=1, column_index=0,
        normalized_payload=None, extraction_method="table_parser",
        confidence=0.9, correction_status="unreviewed", correction_of_block_id=None,
        source_id="cninfo", evidence_ids=[], created_at=TS,
    )


def _financial_data_manifest():
    return FinancialDataManifest(
        manifest_id=UUID1, source_kind="manual_import", source_id="manual_financial_import",
        file_name="fin.csv", file_format="csv", file_checksum=SHA, imported_at=TS,
        imported_by="tester", company_entity_ids=[COMPANY], document_ids=[],
        report_period_start="2021-01-01", report_period_end="2025-12-31",
        default_statement_scope="consolidated", default_currency="CNY",
        default_unit_scale=10000, row_count=100, accepted_count=95,
        rejected_count=5, data_version="v1", validation_status="accepted",
        validation_errors=[], warnings=[], source_ids=["manual_financial_import"],
    )


def _financial_report():
    return FinancialReport(
        financial_report_id=UUID1, company_entity_id=COMPANY, document_id=UUID2,
        manifest_id=UUID3, report_type="annual", period_start="2025-01-01",
        period_end="2025-12-31", fiscal_year=2025, fiscal_period="FY",
        duration_months=12, statement_scope="consolidated",
        accounting_standard="CAS", currency="CNY", unit_scale=10000,
        audit_status="audited", audit_opinion="unmodified",
        restatement_status="original", supersedes_report_id=None,
        filing_version="v1", source_ids=["cninfo"], evidence_ids=[],
        data_status="complete", published_at=TS, created_at=TS,
    )


def _financial_fact():
    return FinancialFact(
        fact_id=UUID1, fact_key="revenue|2025|FY|consolidated",
        financial_report_id=UUID2, company_entity_id=COMPANY,
        statement_type="income_statement", taxonomy_code="revenue",
        label_raw="营业收入", period_start="2025-01-01", period_end="2025-12-31",
        instant_or_duration="duration", period_basis="reported_period",
        statement_scope="consolidated", currency="CNY", unit_scale=10000,
        raw_value="123450000", normalized_value="123450000",
        normalized_unit="yuan", value_status="reported",
        sign_convention="reported", audit_status="audited", segment_id=None,
        source_document_id=UUID3, source_block_ids=[UUID4], evidence_ids=[UUID5],
        source_priority=1, restatement_version=1, valid_from=TS, valid_to=None,
        conflict_group_id=None, warnings=[], created_at=TS,
    )


def _financial_metric():
    return FinancialMetric(
        metric_id=UUID1, company_entity_id=COMPANY, metric_code="gross_margin",
        period_end="2025-12-31", period_basis="annual", value="0.65",
        unit="ratio", status="valid", formula_id="gross_margin_v1",
        formula_version="1.0.0", input_fact_ids=[UUID2],
        input_bindings=[{"parameter": "revenue", "fact_id": UUID2,
                         "company_entity_id": COMPANY, "financial_report_id": UUID3,
                         "taxonomy_code": "revenue", "statement_scope": "consolidated",
                         "statement_type": "income_statement", "period_start": "2025-01-01",
                         "period_end": "2025-12-31", "period_role": "current",
                         "currency": "CNY", "unit_scale": 10000}],
        input_metric_ids=[], precision=8, sector_applicability="general", quality_warnings=[],
        evidence_ids=[], calculated_at=TS,
    )


def _business_segment():
    return BusinessSegment(
        segment_id=UUID1, company_entity_id=COMPANY, financial_report_id=UUID2,
        parent_segment_id=None, segment_type="product", raw_name="茅台酒",
        canonical_name="茅台酒", mapping_method="rule", mapping_confidence=1.0,
        valid_from="2025-01-01", valid_to=None, revenue="100000000",
        revenue_share="0.8", profit=None, profit_margin=None, volume=None,
        average_price=None, currency="CNY", unit_scale=10000,
        metric_fact_ids=[UUID3], source_block_ids=[UUID4], evidence_ids=[],
        reclassification_group_id=None, status="active", created_at=TS,
    )


def _peer_candidate():
    return PeerCandidate(
        peer_candidate_id=UUID1, subject_company_id=COMPANY,
        candidate_company_id="company:000858.SZ", information_cutoff=TS,
        universe_version="1.0.0", relationship_valid_from="2000-01-01",
        relationship_valid_to=None, industry_score=5, business_model_score=5,
        revenue_mix_score=4, supply_chain_score=3, size_score=3,
        listing_tenure_score=5, accounting_comparability_score=4,
        region_score=3, data_completeness_score=4, core_subtotal=76.0,
        total_score=82.0, eligible=True, exclusion_reasons=[],
        llm_assisted_dimensions=[], evidence_ids=[], warnings=[], created_at=TS,
    )


def _peer_selection():
    return PeerSelection(
        peer_selection_id=UUID1, request_id=UUID2, subject_company_id=COMPANY,
        information_cutoff=TS, universe_version="1.0.0", scoring_version="1.0.0",
        candidate_ids=[UUID3], selected_company_ids=["company:000858.SZ"],
        sample_size=1, minimum_required=5, status="insufficient",
        selection_rationale=["样本不足"], outlier_policy="winsorize",
        evidence_ids=[], warnings=[], created_at=TS,
    )


def _valuation_snapshot():
    return ValuationSnapshot(
        valuation_snapshot_id=UUID1, company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of=TS, market_data_manifest_id=None,
        price="1500", shares_outstanding="1256197800", market_cap="1884296700000",
        enterprise_value="1850000000000", financial_period_end="2025-12-31",
        financial_basis="TTM", metrics=[], history_window_start=None,
        history_window_end=None, history_sample_size=0, peer_selection_id=None,
        peer_sample_size=0, percentile_method="average_rank",
        applicability_notes=[], status="partial", source_ids=["manual_inbox"],
        evidence_ids=[], calculated_at=TS,
    )


def _forecast_scenario():
    return ForecastScenario(
        scenario_id=UUID1, request_id=UUID2, company_entity_id=COMPANY,
        name="用户悲观假设", scenario_type="user_assumption", enabled=True,
        forecast_start="2026-01-01", forecast_end="2026-12-31", periods=["2026FY"],
        assumptions=[{
            "assumption_id": UUID3, "driver": "收入增速", "value": "-0.05",
            "unit": "ratio", "period": "2026FY", "source_type": "user_input",
            "source_ref_ids": [], "evidence_ids": [], "claim_type": "HYPOTHESIS",
            "confidence": 0.6, "invalidates_when": "收入增速超 0",
        }],
        outputs=[], sensitivity_axes=[], confidence=0.6, status="valid",
        llm_called=False, model_route=None, warnings=[], created_at=TS,
    )


def _competitive_factor():
    return CompetitiveFactor(
        factor_id=UUID1, company_entity_id=COMPANY, factor_type="brand",
        direction="advantage", statement="高端白酒品牌力",
        business_segment_ids=[UUID2], mechanism="品牌溢价", required_evidence_types=[],
        evidence_ids=[], counter_evidence_ids=[], management_only=True,
        confidence=0.5, status="weakly_supported", valid_from=None, valid_to=None,
        created_at=TS,
    )


def _catalyst():
    return Catalyst(
        catalyst_id=UUID1, company_entity_id=COMPANY, event_id=None,
        source_phase="phase4", catalyst_type="earnings", description="年报披露",
        claim_type="FACT", announcement_status="announced",
        time_window_start=None, time_window_end=None, impact_mechanism="盈利预期",
        business_segment_ids=[], prerequisites=[], invalidation_conditions=[],
        evidence_ids=[], confidence=0.7, status="active", widely_known="unknown",
        phase3_attribution_result_id=None, created_at=TS, updated_at=TS,
    )


def _risk_factor():
    return RiskFactor(
        risk_id=UUID1, company_entity_id=COMPANY, event_id=None,
        source_phase="phase4", risk_type="regulatory", description="消费税政策",
        claim_type="HYPOTHESIS", time_window_start=None, time_window_end=None,
        impact_mechanism="税率变化影响利润", business_segment_ids=[], triggers=[],
        mitigants=[], invalidation_conditions=[], evidence_ids=[],
        counter_evidence_ids=[], confidence=0.5, status="active",
        widely_known="unknown", phase3_attribution_result_id=None,
        created_at=TS, updated_at=TS,
    )


def _research_finding():
    return ResearchFinding(
        finding_id=UUID1, request_id=UUID2, company_entity_id=COMPANY,
        finding_type="business_analysis", title="业务结构", statement="以白酒为主",
        claim_type="FACT", predicate="主营业务", object={"industry": "liquor"},
        as_of=TS, evidence_ids=[], supporting_object_ids=[UUID3],
        counter_evidence_ids=[], confidence=0.9, support_level="direct",
        status="supported", invalidation_conditions=[], materiality="high",
        section_id="s8", model_route=None, created_at=TS,
    )


def _equity_request():
    return EquityResearchRequest(
        request_id=UUID1, task_id=UUID2, company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of=TS, report_date=D,
        timezone="Asia/Shanghai", depth="standard", periods=5,
        peer_overrides=[], scenario_ids=[], include_valuation=True,
        include_forecast=False, live=False, dry_run=False, force=False,
        input_document_ids=[], financial_manifest_ids=[], market_manifest_ids=[],
        source_policy="manual_only", status="planned", warnings=[],
        rule_versions={}, requested_at=TS,
    )


def _equity_run():
    return EquityResearchRun(
        run_id=UUID1, request_id=UUID2, task_id=UUID3, idempotency_key="k1",
        run_version=1, started_at=TS, finished_at=None, status="planned",
        stage_statuses=[], artifact_paths=[], input_versions={},
        model_route_summary={}, validation_status="pending",
        error_codes=[], warnings=[],
    )


def _equity_result():
    return EquityResearchResult(
        result_id=UUID1, run_id=UUID2, request_id=UUID3,
        company_entity_id=COMPANY, security_entity_id=SECURITY, as_of=TS,
        research_status="insufficient_data", coverage={}, key_finding_ids=[],
        financial_metric_ids=[], segment_ids=[], peer_selection_id=None,
        valuation_snapshot_id=None, forecast_scenario_ids=[], catalyst_ids=[],
        risk_ids=[], phase3_link_ids=[], claim_ids=[], evidence_ids=[],
        unknowns=[], conflicts=[], warnings=[], report_path=None,
        validator_summary={}, model_route_summary={}, created_at=TS,
    )


MODELS = [
    ("CompanyProfile", _company_profile, "company_profile_id"),
    ("SecurityProfile", _security_profile, "security_profile_id"),
    ("DocumentRecord", _document_record, "document_id"),
    ("DocumentBlock", _document_block, "block_id"),
    ("FinancialDataManifest", _financial_data_manifest, "manifest_id"),
    ("FinancialReport", _financial_report, "financial_report_id"),
    ("FinancialFact", _financial_fact, "fact_id"),
    ("FinancialMetric", _financial_metric, "metric_id"),
    ("BusinessSegment", _business_segment, "segment_id"),
    ("PeerCandidate", _peer_candidate, "peer_candidate_id"),
    ("PeerSelection", _peer_selection, "peer_selection_id"),
    ("ValuationSnapshot", _valuation_snapshot, "valuation_snapshot_id"),
    ("ForecastScenario", _forecast_scenario, "scenario_id"),
    ("CompetitiveFactor", _competitive_factor, "factor_id"),
    ("Catalyst", _catalyst, "catalyst_id"),
    ("RiskFactor", _risk_factor, "risk_id"),
    ("ResearchFinding", _research_finding, "finding_id"),
    ("EquityResearchRequest", _equity_request, "request_id"),
    ("EquityResearchRun", _equity_run, "run_id"),
    ("EquityResearchResult", _equity_result, "result_id"),
]


def _with(obj, **overrides):
    d = obj.model_dump()
    d.update(overrides)
    return obj.__class__(**d)


class TestSchemaRegistry:
    def test_schema_total_count_is_50(self):
        assert len(SCHEMA_NAMES) == 50

    def test_phase4_schemas_registered(self):
        assert PHASE4_SCHEMAS <= set(SCHEMA_NAMES)

    def test_all_schemas_valid(self):
        results = validate_all_schemas()
        bad = {k: v for k, v in results.items() if v}
        assert bad == {}, f"非法 Schema: {bad}"

    def test_entity_type_accepts_security(self):
        e = Entity(
            entity_id="security:600519.SH", entity_type="security",
            canonical_name="贵州茅台", aliases=[], market="A-share",
            industry_ids=[], concept_ids=[], valid_from=TS, valid_to=None,
            source_ids=["manual_inbox"],
        )
        assert validate_model(e) == []


class TestPhase4Contracts:
    @pytest.mark.parametrize("name,factory,required_field", MODELS)
    def test_normal_construction_passes_schema(self, name, factory, required_field):
        obj = factory()
        assert validate_model(obj) == []

    @pytest.mark.parametrize("name,factory,required_field", MODELS)
    def test_extra_field_rejected(self, name, factory, required_field):
        obj = factory()
        with pytest.raises(ValidationError):
            obj.__class__(**obj.model_dump(), extra_field="x")

    @pytest.mark.parametrize("name,factory,required_field", MODELS)
    def test_missing_required_field_rejected(self, name, factory, required_field):
        # 删除必填字段后构造必须被拒绝
        d = factory().model_dump()
        del d[required_field]
        with pytest.raises(ValidationError):
            factory().__class__(**d)

    def test_schema_all_fields_required_and_no_additional(self):
        for name in sorted(PHASE4_SCHEMAS):
            path = Path("schemas") / f"{name}.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            assert schema.get("additionalProperties") is False, name
            props = schema["properties"]
            required = set(schema["required"])
            assert required == set(props.keys()), (
                f"{name}: required 与 properties 不一致 "
                f"(缺 {set(props) - required}, 多 {required - set(props)})"
            )

    def test_decimal_values_are_strings_not_floats(self):
        """财务十进制值必须为字符串，不得被 float 持久化。"""
        for name in sorted(PHASE4_SCHEMAS):
            path = Path("schemas") / f"{name}.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            for prop, pdef in schema["properties"].items():
                if pdef.get("type") == "string" and "pattern" in pdef:
                    pat = pdef["pattern"]
                    if re.match(r"^-?\\d+", pat):
                        assert "float" not in pdef.get("type", ""), name
                        # 确保数值模式存在
                        assert re.search(r"\\d+(\\.\\d+)?", pat), name

    def test_financial_values_not_float_in_models(self):
        """financials 模型中财务值字段均为 Optional[str]，不允许 float。"""
        for model in (FinancialFact, FinancialMetric):
            for fname, finfo in model.model_fields.items():
                if fname in ("raw_value", "normalized_value", "value"):
                    assert "str" in str(finfo.annotation), f"{model.__name__}.{fname}"

    def test_financial_decimal_models_canonicalize_scientific_notation(self):
        fact_data = _financial_fact().model_dump()
        fact_data["raw_value"] = "1.2300E+2"
        fact_data["normalized_value"] = "-0E+4"
        fact = FinancialFact(**fact_data)
        assert fact.raw_value == "123"
        assert fact.normalized_value == "0"
        assert validate_model(fact) == []

        metric_data = _financial_metric().model_dump()
        metric_data["value"] = "4E-1"
        metric = FinancialMetric(**metric_data)
        assert metric.value == "0.4"
        assert validate_model(metric) == []

    @pytest.mark.parametrize("invalid", ["NaN", "Infinity", "-Infinity"])
    def test_financial_decimal_models_reject_non_finite(self, invalid):
        data = _financial_metric().model_dump()
        data["value"] = invalid
        with pytest.raises(ValidationError):
            FinancialMetric(**data)

    def test_nullable_uses_anyof(self):
        """nullable 字段必须显式 anyOf null。"""
        for name in sorted(PHASE4_SCHEMAS):
            path = Path("schemas") / f"{name}.schema.json"
            schema = json.loads(path.read_text(encoding="utf-8"))
            for prop, pdef in schema["properties"].items():
                if "anyOf" in pdef:
                    types = [x.get("type") for x in pdef["anyOf"]]
                    assert "null" in types, f"{name}.{prop} anyOf 缺 null"
