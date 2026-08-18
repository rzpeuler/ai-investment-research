"""P7-D4 M2：derive_existing 执行链离线测试。

覆盖：FinancialDerivationExecutor 正常 derive（produced refs）、无 subject fail closed、
prerequisite 不满足 not_executable、execution dependencies 强制（前置未 completed →
derive 不执行）、幂等（FinancialReport 已存在 → inserted=False）、未来披露 PIT。
全部离线（FakeDB + synthetic blocks）。
"""
from __future__ import annotations

import pytest

from research_os.data_layer.derivation import (
    DerivationPrerequisiteResolver,
    FinancialDerivationExecutor,
    FinancialDerivationService,
)
from research_os.data_layer.execution import AcquisitionExecutionService
from research_os.models import (
    AcquisitionPlan,
    AcquisitionStep,
    DocumentBlock,
    DocumentRecord,
)

TS = "2026-04-30T10:00:00+08:00"
AS_OF = "2026-05-01T00:00:00+08:00"


class _FakeDB:
    def __init__(self, records=None, blocks=None):
        self._records = records or []
        self._blocks = blocks or []
        self._tables = {
            "financial_data_manifests": {}, "financial_reports": {},
            "financial_facts": {}, "evidence": {},
        }
        self.upserted = []

    def upsert(self, obj):
        name = type(obj).__name__
        if name == "FinancialDataManifest":
            key = obj.manifest_id
            table = "financial_data_manifests"
        elif name == "FinancialReport":
            key = obj.financial_report_id
            table = "financial_reports"
        elif name == "FinancialFact":
            key = obj.fact_id
            table = "financial_facts"
        elif name == "Evidence":
            key = obj.evidence_id
            table = "evidence"
        else:
            return
        self._tables[table][key] = obj.model_dump()
        self.upserted.append(obj)

    def query(self, sql, params=()):
        if "financial_reports" in sql and "financial_report_id = ?" in sql:
            return [{"payload": p} for p in self._tables["financial_reports"].values()
                    if p.get("financial_report_id") == (params[0] if params else None)]
        if "document_records" in sql:
            return [{"payload": r.model_dump()} for r in self._records]
        if "document_blocks" in sql and "document_id = ?" in sql:
            return [{"payload": b.model_dump()} for b in self._blocks
                    if getattr(b, "document_id", None) == (params[0] if params else None)]
        if "evidence" in sql:
            return [{"payload": p} for p in self._tables["evidence"].values()]
        return []


def _record(**overrides) -> DocumentRecord:
    base = dict(
        document_id="doc-1", company_entity_id="company:maotai",
        security_entity_id="security:600519.SH", document_type="annual_report",
        title="贵州茅台：2025年年度报告", source_id="cninfo",
        source_url="https://static.cninfo.com.cn/x.PDF", local_path=None,
        external_id="ann-1", published_at="2026-04-30T10:00:00+08:00",
        retrieved_at=TS, report_period_end="2025-12-31", fiscal_year=2025,
        mime_type="application/pdf", file_size_bytes=100, sha256="b" * 64,
        storage_policy="metadata_and_excerpt", copyright_status="statutory_filing",
        text_layer_status="present", table_parse_status="not_started",
        ocr_status="not_started", parser_name="pypdf", parser_version="6.0",
        page_count=10, audit_status="unknown", parse_status="parsed",
        warnings=[], version=1, created_at=TS, updated_at=TS,
    )
    base.update(overrides)
    return DocumentRecord(**base)


def _block(text: str, block_id: str, document_id: str = "doc-1") -> DocumentBlock:
    return DocumentBlock(
        block_id=block_id, document_id=document_id, block_type="text",
        page_start=1, page_end=1, bbox=None, sequence_no=0, section_path=[],
        content_excerpt=text, content_hash="c" * 64, table_id=None,
        row_index=None, column_index=None, normalized_payload=None,
        extraction_method="native_text", confidence=None,
        correction_status="unreviewed", correction_of_block_id=None,
        source_id="cninfo", evidence_ids=[], version=1, created_at=TS,
    )


def _financial_blocks() -> list:
    return [
        _block("单位：元", "b-unit"),
        _block("合并利润表", "b-isl"),
        _block("项目 本期金额 上期金额", "b-ishead"),
        _block("营业收入 10,000,000.00 9,000,000.00", "b-rev"),
        _block("归属于母公司所有者的净利润 1,800,000.00 1,400,000.00", "b-np"),
        _block("合并资产负债表", "b-bs"),
        _block("项目 期末余额 期初余额", "b-bshead"),
        _block("资产总计 25,000,000.00 20,000,000.00", "b-assets"),
        _block("负债合计 10,000,000.00 9,000,000.00", "b-liab"),
        _block("归属于母公司所有者权益合计 15,000,000.00 11,000,000.00", "b-equity"),
    ]


def _executor(db):
    return FinancialDerivationExecutor(
        db, resolver=DerivationPrerequisiteResolver(db),
        service=FinancialDerivationService(db),
    )


def _route_input(subjects=("company:maotai",)):
    from research_os.data_layer.execution import RouteExecutionInput
    return RouteExecutionInput(
        query={"entity_ids": list(subjects)},
        time_window={"start": None, "end": AS_OF},
    )


class TestDeriveExecutor:
    def test_normal_derive_completed(self):
        db = _FakeDB(records=[_record()], blocks=_financial_blocks())
        step = AcquisitionStep(
            step_id="s1", requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=["s0"], status="pending", warnings=[])
        outcome = _executor(db).execute(step=step, route_input=_route_input(),
                                        task_id="t1", as_of=AS_OF)
        assert outcome.status == "completed"
        assert outcome.reason_codes == []
        assert any(r.startswith("financial_report:") for r in outcome.produced_record_refs)
        assert any(r.startswith("financial_fact:") for r in outcome.produced_record_refs)
        # 持久化写入
        assert db._tables["financial_reports"]
        assert db._tables["financial_facts"]

    def test_idempotent_second_run(self):
        db = _FakeDB(records=[_record()], blocks=_financial_blocks())
        step = AcquisitionStep(
            step_id="s1", requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=[], status="pending", warnings=[])
        first = _executor(db).execute(step=step, route_input=_route_input(),
                                      task_id="t1", as_of=AS_OF)
        second = _executor(db).execute(step=step, route_input=_route_input(),
                                       task_id="t1", as_of=AS_OF)
        assert first.status == "completed"
        assert second.status == "completed"
        assert second.reused_record_refs
        assert len(db._tables["financial_facts"]) == len(first.produced_record_refs) - 2

    def test_no_subject_fails_closed(self):
        db = _FakeDB(records=[_record()], blocks=_financial_blocks())
        step = AcquisitionStep(
            step_id="s1", requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=[], status="pending", warnings=[])
        outcome = _executor(db).execute(step=step, route_input=_route_input([]),
                                        task_id="t1", as_of=AS_OF)
        assert outcome.status == "not_executable"
        assert "DERIVATION_PREREQUISITE_MISSING" in outcome.reason_codes

    def test_future_published_not_eligible(self):
        db = _FakeDB(
            records=[_record(published_at="2026-06-01T00:00:00+08:00")],
            blocks=_financial_blocks())
        step = AcquisitionStep(
            step_id="s1", requirement_id="financial_statement_data",
            data_type="financial_statement_data", action="derive_existing",
            dependencies=[], status="pending", warnings=[])
        outcome = _executor(db).execute(step=step, route_input=_route_input(),
                                        task_id="t1", as_of="2026-05-01T00:00:00+08:00")
        assert outcome.status == "not_executable"
        assert "DERIVATION_PREREQUISITE_MISSING" in outcome.reason_codes


class _FakeRouter:
    def resolve_with_items(self, *a, **k):
        raise AssertionError("derive-only execution must not touch router")


class _FakeRepository:
    def persist_batch(self, **k):
        raise AssertionError("derive-only execution must not persist raw items")


class _MinimalExecution(AcquisitionExecutionService):
    pass


def _execution_service(derivation):
    from pathlib import Path

    from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
    from research_os.data_layer.execution_policy import ExecutionPolicy
    from research_os.routing.scenario_requirements import (
        ScenarioDataRequirementRegistry,
    )

    root = Path(__file__).resolve().parents[2]
    req = ScenarioDataRequirementRegistry(
        root / "registry" / "scenario_data_requirements.yaml")
    cap = AcquisitionCapabilityRegistry(
        root / "registry" / "data_acquisition_capabilities.yaml",
        scenario_requirements=req, repo_root=root,
    )
    policy = ExecutionPolicy(
        enabled=True, allowed_actions=("route_existing_sources",),
        production_collector_ids=("nbs", "cninfo"))
    return AcquisitionExecutionService(
        policy=policy, requirement_registry=req, capability_registry=cap,
        router=_FakeRouter(), repository=_FakeRepository(), derivation=derivation,
    )


class TestExecutionDependencies:
    def test_dependency_not_completed_blocks_derive(self):
        service = _execution_service(_executor(_FakeDB()))
        plan = AcquisitionPlan(
            task_id="t1", scenario="stock_research_report", as_of=AS_OF,
            steps=[
                AcquisitionStep(
                    step_id="sA", requirement_id="company_document",
                    data_type="company_document", action="route_existing_sources",
                    dependencies=[], status="pending", warnings=[]),
                AcquisitionStep(
                    step_id="sB", requirement_id="financial_statement_data",
                    data_type="financial_statement_data", action="derive_existing",
                    dependencies=["sA"], status="pending", warnings=[]),
            ],
            warnings=[],
        )
        # 无 route_inputs → route 步骤失败 → derive 依赖未满足 → blocked
        result = service.execute(
            plan=plan, task_id="t1", scenario="stock_research_report",
            as_of=AS_OF, dry_run=False, live_authorized=True,
        )
        derive_step = result.steps[1]
        assert derive_step.status == "not_executable"
        assert "DERIVATION_PREREQUISITE_MISSING" in derive_step.reason_codes

    def test_derive_without_executor_fails_closed(self):
        service = _execution_service(None)
        plan = AcquisitionPlan(
            task_id="t1", scenario="stock_research_report", as_of=AS_OF,
            steps=[AcquisitionStep(
                step_id="sB", requirement_id="financial_statement_data",
                data_type="financial_statement_data", action="derive_existing",
                dependencies=[], status="pending", warnings=[])],
            warnings=[],
        )
        result = service.execute(
            plan=plan, task_id="t1", scenario="stock_research_report",
            as_of=AS_OF, dry_run=False, live_authorized=True,
        )
        assert result.steps[0].status == "not_executable"
        assert result.steps[0].reason_codes == ["DERIVATION_FAILED"]
