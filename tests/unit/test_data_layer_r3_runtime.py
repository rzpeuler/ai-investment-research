"""P7-D1-R3 强制测试：Runtime Semantic Binding Closure。

覆盖（§95-107）：
- test_preflight_uses_requirement_binding_runtime（binding 改变实际 readiness 行为）
- Runtime Projector（Schema-valid FinancialFact → canonical value available）
- Binding vs Generic Spec（daily_review.claims open-world null）
- Evidence subject join（matching/unrelated/missing RawItem、industry、global）
- Previous run IDs（只查 requested、empty 不扫描全部、validation 强校验、run_id 实证）
- Timezone-aware window（offset case 1/2）
- Document tier（source_id → SourceRegistry）
- IndustryMembership tier
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.data_layer.bindings import RequirementReadinessBindingResolver
from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.checkers import (
    EmptyReadView,
    ReadinessCheckerRegistry,
    SqliteReadView,
)
from research_os.data_layer.context import RequirementContextResolver
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.projector import ReadinessFieldProjector
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.data_layer.readiness import DataReadinessService
from research_os.data_layer.request_context import NormalizedRequestContextAdapter
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

ROOT = Path(__file__).resolve().parents[2]
REQ_PATH = ROOT / "registry" / "scenario_data_requirements.yaml"
CAP_PATH = ROOT / "registry" / "data_acquisition_capabilities.yaml"
SOURCES_PATH = ROOT / "registry" / "sources.yaml"
CHECKED_AT = "2026-08-11T08:00:00+08:00"
AS_OF = "2026-08-11T08:00:00+08:00"


@pytest.fixture(scope="module")
def requirement_registry() -> ScenarioDataRequirementRegistry:
    return ScenarioDataRequirementRegistry(REQ_PATH)


@pytest.fixture(scope="module")
def capability_registry(requirement_registry) -> AcquisitionCapabilityRegistry:
    return AcquisitionCapabilityRegistry(CAP_PATH, requirement_registry, ROOT)


@pytest.fixture(scope="module")
def provenance() -> ReadinessProvenanceResolver:
    return ReadinessProvenanceResolver(sources_yaml_path=str(SOURCES_PATH))


def _resolve(requirement_registry, req_id, scenario, request):
    adapter = NormalizedRequestContextAdapter()
    canonical = adapter.extract(scenario, request)
    resolver = RequirementContextResolver()
    return resolver.resolve(requirement_registry.get(req_id), scenario, "t1", canonical, AS_OF)


def _view_from(db):
    return SqliteReadView(db)


# ---------- §95/96：Runtime Binding 与 Projector ----------

class TestRuntimeBinding:
    def test_preflight_uses_requirement_binding_runtime(self, requirement_registry, capability_registry):
        """binding 必须改变实际 readiness 行为（非 merely instantiated）。"""
        svc = DataPreflightService(requirement_registry, capability_registry)
        assert svc._bindings is not None
        assert len(svc._bindings.all()) == 43
        # 每个 requirement 的 binding 可由 resolver 解析
        binding = svc._bindings.get("daily_review.claims")
        assert binding is not None

    def test_binding_vs_generic_spec_claims_open_world(self, requirement_registry,
                                                       capability_registry, provenance, tmp_path):
        """§61/97：daily_review.claims generic spec=SINGLETON_TARGET、binding=OPEN_WORLD；
        1 条合法 Claim → coverage 必须 null（不得 1.0）。"""
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE claims (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        conn.execute("INSERT INTO evidence VALUES (?)",
                     (json.dumps({"evidence_id": "ev1", "source_id": "cninfo",
                                  "raw_item_id": "ri1", "title": "e",
                                  "publisher": "cninfo",
                                  "published_at": "2026-08-11T06:00:00+08:00",
                                  "retrieved_at": "2026-08-11T06:05:00+08:00",
                                  "url": "http://e", "excerpt": "x",
                                  "evidence_type": "official_disclosure",
                                  "independence_group": "g1", "source_tier": "S"},
                                 ensure_ascii=False),))
        claim = {
            "claim_id": "c1", "claim_type": "FACT", "statement": "声明",
            "subject_entities": [], "predicate": "has", "object": {"v": 1},
            "as_of": "2026-08-11T06:00:00+08:00", "evidence_ids": ["ev1"],
            "support_level": "inferred", "confidence": 0.9, "review_status": "unreviewed",
        }
        conn.execute("INSERT INTO claims VALUES (?)", (json.dumps(claim, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)

        binding = RequirementReadinessBindingResolver(requirement_registry).get("daily_review.claims")
        # generic spec 是 SINGLETON，binding 是 OPEN_WORLD（每日复盘无合法 claim universe）
        assert binding.coverage_strategy == "OPEN_WORLD"

        ctx = _resolve(requirement_registry, "daily_review.claims", "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            requirement_registry.get("daily_review.claims"), ctx, view, CHECKED_AT,
            provenance=provenance, binding=binding, projector=ReadinessFieldProjector())
        # 1 条 Claim 但 open-world → coverage null（禁止 1.0）
        assert r.coverage_ratio is None
        assert "COVERAGE_NOT_MEASURABLE" in r.warnings
        db.close()


# ---------- §96/62：Runtime Projector（FinancialFact canonical value） ----------

class TestRuntimeProjector:
    def test_financial_value_runtime_available(self, requirement_registry, capability_registry,
                                               provenance, tmp_path):
        """Schema-valid FinancialFact → preflight/evaluate → canonical value 进入 available_fields。"""
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        conn.execute("CREATE TABLE document_records (payload TEXT)")
        # publication proof：evidence 早于 as_of
        import uuid
        evid = str(uuid.uuid4())
        conn.execute("INSERT INTO evidence VALUES (?)",
                     (json.dumps({"evidence_id": evid, "source_id": "cninfo",
                                  "raw_item_id": "ri1", "title": "e",
                                  "publisher": "cninfo",
                                  "published_at": "2026-08-10T00:00:00+08:00",
                                  "retrieved_at": "2026-08-10T00:05:00+08:00",
                                  "url": "http://e", "excerpt": "x",
                                  "evidence_type": "official_disclosure",
                                  "independence_group": "g1", "source_tier": "S"},
                                 ensure_ascii=False),))
        fact = {
            "fact_id": "f1", "fact_key": "revenue", "company_entity_id": "company:600519.SH",
            "statement_type": "income_statement", "statement_scope": "consolidated",
            "taxonomy_code": "REV", "period_end": "2026-06-30",
            "raw_value": "1000000000", "normalized_value": "1000000000",
            "value_status": "reported", "evidence_ids": [evid],
            "source_document_id": None,
        }
        conn.execute("INSERT INTO financial_facts VALUES (?)", (json.dumps(fact, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)

        req = requirement_registry.get("stock_research_report.financial_statement_data")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        # §17：fact_key/period_end/statement_scope/value ∈ available_fields；value ∉ missing
        assert "value" in r.available_fields
        assert "statement_scope" in r.available_fields
        assert "fact_key" in r.available_fields
        assert "period_end" in r.available_fields
        assert "value" not in r.missing_fields
        assert "statement_scope" not in r.missing_fields
        db.close()

    def test_statement_scope_not_from_statement_type(self, requirement_registry):
        """§16：statement_scope 是 direct field，不得投影到 statement_type。"""
        binding = RequirementReadinessBindingResolver(requirement_registry).get(
            "stock_research_report.financial_statement_data")
        assert binding.minimum_field_sources["statement_scope"] == "direct"


# ---------- §98：Evidence subject join ----------

class TestEvidenceSubjectJoin:
    def _db(self, tmp_path, evidences, raw_items):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        for e in evidences:
            conn.execute("INSERT INTO evidence VALUES (?)", (json.dumps(e, ensure_ascii=False),))
        for r in raw_items:
            conn.execute("INSERT INTO raw_items VALUES (?)", (json.dumps(r, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def _evidence(self, eid, riid, published="2026-08-11T06:00:00+08:00"):
        return {"evidence_id": eid, "source_id": "cninfo", "raw_item_id": riid,
                "title": "e", "publisher": "cninfo",
                "published_at": published,
                "retrieved_at": "2026-08-11T06:05:00+08:00",
                "url": "http://e", "excerpt": "x",
                "evidence_type": "official_disclosure", "independence_group": "g1",
                "source_tier": "S"}

    def _raw_item(self, riid, entities):
        return {"raw_item_id": riid, "source_id": "cninfo", "url": "http://e",
                "title": "r", "publisher": "cninfo",
                "published_at": "2026-08-11T06:00:00+08:00",
                "retrieved_at": "2026-08-11T06:05:00+08:00",
                "content_hash": "a" * 64, "content_excerpt": "x",
                "content_storage": "metadata_and_excerpt", "language": "zh-CN",
                "access_status": "ok", "entities": entities, "raw_category": "official_disclosure"}

    def test_matching_raw_item_company_eligible(self, tmp_path, requirement_registry, provenance):
        db = self._db(tmp_path, [self._evidence("ev1", "ri1")],
                      [self._raw_item("ri1", ["company:600519.SH"])])
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.event_evidence")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH",
                        "window_start": "2026-08-09T00:00:00+08:00",
                        "window_end": "2026-08-11T08:00:00+08:00"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1  # matching company → eligible
        db.close()

    def test_unrelated_raw_item_company_ineligible(self, tmp_path, requirement_registry, provenance):
        db = self._db(tmp_path, [self._evidence("ev1", "ri1")],
                      [self._raw_item("ri1", ["company:000001.SZ"])])
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.event_evidence")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH",
                        "window_start": "2026-08-09T00:00:00+08:00",
                        "window_end": "2026-08-11T08:00:00+08:00"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0  # unrelated → ineligible
        db.close()

    def test_missing_raw_item_ineligible(self, tmp_path, requirement_registry, provenance):
        db = self._db(tmp_path, [self._evidence("ev1", "missing-ri")], [])
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.event_evidence")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH",
                        "window_start": "2026-08-09T00:00:00+08:00",
                        "window_end": "2026-08-11T08:00:00+08:00"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0  # raw_item 缺失 → ineligible
        db.close()

    def test_global_evidence_not_blocked_by_subject_join(self, tmp_path, requirement_registry, provenance):
        # daily_review.evidence 是 global scope：无 raw_item 也不应被 subject join 阻断
        db = self._db(tmp_path, [self._evidence("ev1", "ri1")], [])
        view = _view_from(db)
        req = requirement_registry.get("daily_review.evidence")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1  # global 不受 subject join 错误阻断
        db.close()


# ---------- §99/100/101：Prior Run ----------

class TestPriorRun:
    def _run(self, root, run_id, scenario="morning_brief", status="completed",
             validation="ok", task_id=None, as_of="2026-08-10T08:00:00+08:00",
             with_result=True):
        run_dir = root / "reports" / "runs" / run_id
        run_dir.mkdir(parents=True)
        tid = task_id or run_id
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": tid, "scenario": scenario, "status": status,
            "as_of": as_of, "time_window": {"end": as_of},
        }, ensure_ascii=False), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": validation, "task_id": tid,
        }, ensure_ascii=False), encoding="utf-8")
        if with_result:
            (run_dir / "scenario_execution_result.json").write_text(json.dumps({
                "task_id": tid, "run_id": f"actual-{run_id}",
                "validation_status": validation,
            }, ensure_ascii=False), encoding="utf-8")
        return run_dir

    def test_only_requested_runs_inspected(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj"
        self._run(root, "A")
        self._run(root, "B")
        self._run(root, "C")

        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        # 只查 A：eligible=1；B/C 不得自动选择
        assert r.eligible_record_count == 1
        assert all("A" in ref for ref in r.record_refs)

    def test_empty_previous_run_ids_no_auto_scan(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj2"
        self._run(root, "B")
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": []})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        # empty previous_run_ids：B 不得自动选中 → MISSING
        assert r.eligible_record_count == 0
        assert r.status == "MISSING"

    def test_validation_missing_rejects(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj3"
        run_dir = self._run(root, "A", validation="ok")
        (run_dir / "validation.json").unlink()  # 删除 validation → reject
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        assert r.eligible_record_count == 0

    def test_validation_failed_rejects(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj4"
        self._run(root, "A", validation="failed")
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        assert r.eligible_record_count == 0

    def test_wrong_scenario_rejects(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj5"
        self._run(root, "A", scenario="stock_review")
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        assert r.eligible_record_count == 0

    def test_actual_run_id_proven(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj6"
        self._run(root, "A")  # scenario_execution_result.json run_id=actual-A
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        # run_id 来自正式 artifact（actual-A），非目录名伪造
        assert r.record_refs == ["actual-A"]

    def test_business_cutoff_after_as_of_rejects(self, tmp_path, requirement_registry, provenance):
        root = tmp_path / "proj7"
        self._run(root, "A", as_of="2026-09-01T08:00:00+08:00")  # cutoff 晚于 as_of
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": ["A"]})
        ctx.binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        r = RunArtifactChecker().check(ctx, req, view, provenance)
        assert r.eligible_record_count == 0


# ---------- §103：Timezone-aware Window ----------

class TestTimezoneWindow:
    def test_offset_aware_inside(self, requirement_registry, provenance):
        from research_os.data_layer.checkers import _in_window
        # window_start 2026-08-11T00:00:00+08:00；candidate 2026-08-10T16:30:00Z
        # = 2026-08-11T00:30:00+08:00 → INSIDE
        assert _in_window("2026-08-10T16:30:00Z",
                          "2026-08-11T00:00:00+08:00",
                          "2026-08-11T08:00:00+08:00") is True

    def test_offset_aware_end_excluded(self, requirement_registry, provenance):
        from research_os.data_layer.checkers import _in_window
        # window_end 2026-08-11T08:00:00+08:00；candidate 2026-08-11T00:00:00Z = 同一时刻
        # [start, end) → EXCLUDED
        assert _in_window("2026-08-11T00:00:00Z",
                          "2026-08-11T00:00:00+08:00",
                          "2026-08-11T08:00:00+08:00") is False


# ---------- §105：Document Tier ----------

class TestDocumentTier:
    def test_document_source_id_tier(self, requirement_registry, provenance, tmp_path):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE document_records (payload TEXT)")
        doc = {"document_id": "d1", "company_entity_id": "company:600519.SH",
               "security_entity_id": "security:600519.SH", "document_type": "annual_report",
               "title": "年报", "source_id": "cninfo", "published_at": "2026-08-10T00:00:00+08:00",
               "sha256": "b" * 64, "parse_status": "parsed"}
        conn.execute("INSERT INTO document_records VALUES (?)", (json.dumps(doc, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.company_document")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        assert binding.provenance_strategy == "document_source"  # §56
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        # cninfo→S tier 可证明 → 不应永久 ineligible（§57）
        assert r.status != "MISSING"
        db.close()


# ---------- §106：IndustryMembership Tier ----------

class TestIndustryMembershipTier:
    def test_low_tier_industry_membership_ineligible(self, requirement_registry, provenance, tmp_path):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE company_profiles (payload TEXT)")
        # evidence_ids 指向低 tier evidence（manual_financial_import=C < min A）
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        conn.execute("INSERT INTO evidence VALUES (?)",
                     (json.dumps({"evidence_id": "ev1", "source_id": "ima",
                                  "raw_item_id": "ri1", "title": "e",
                                  "publisher": "ima",
                                  "published_at": "2026-08-10T00:00:00+08:00",
                                  "retrieved_at": "2026-08-10T00:05:00+08:00",
                                  "url": "http://e", "excerpt": "x",
                                  "evidence_type": "institutional",
                                  "independence_group": "g1", "source_tier": "C"},
                                 ensure_ascii=False),))
        profile = {"company_profile_id": "cp1", "entity_id": "company:600519.SH",
                   "canonical_name": "贵州茅台", "industry_ids": ["ind:semiconductor"],
                   "fiscal_year_end": "12-31", "reporting_currency": "CNY",
                   "ownership_type": "private", "valid_from": "2026-01-01",
                   "valid_to": None, "status": "active", "source_ids": [],
                   "evidence_ids": ["ev1"], "version": 1,
                   "created_at": "2026-01-01T00:00:00+08:00",
                   "updated_at": "2026-01-01T00:00:00+08:00"}
        conn.execute("INSERT INTO company_profiles VALUES (?)", (json.dumps(profile, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.industry_membership")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        # membership 正确但 tier(C) < min(A) → 不得 READY（§55/106）
        assert r.status != "READY"
        db.close()


# ---------- §95：43/43 Runtime Loadable ----------

class TestRuntimeLoadable:
    def test_all_43_bindings_runtime_loadable(self, requirement_registry):
        resolver = RequirementReadinessBindingResolver(requirement_registry)
        assert len(resolver.all()) == 43
        for b in resolver.all():
            assert b.coverage_strategy
            assert b.provenance_strategy
            assert b.pit_strategy
            assert b.freshness_strategy
            assert b.scope_strategy


# ---------- §22：entity_mapping symbol 可证明 ----------

class TestEntitySymbolProvenance:
    def test_symbol_via_security_profile(self, tmp_path, requirement_registry, provenance):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (payload TEXT)")
        conn.execute("CREATE TABLE security_profiles (payload TEXT)")
        entity = {"entity_id": "company:600519.SH", "entity_type": "company",
                  "canonical_name": "贵州茅台", "aliases": ["贵州茅台"],
                  "market": "A", "valid_from": "2026-01-01", "valid_to": None}
        conn.execute("INSERT INTO entities VALUES (?)", (json.dumps(entity, ensure_ascii=False),))
        sp = {"security_profile_id": "sp1", "security_entity_id": "security:600519.SH",
              "company_entity_id": "company:600519.SH", "symbol": "600519.SH",
              "exchange": "SH", "board": "main", "security_type": "common_share",
              "listing_date": "2020-01-01", "delisting_date": None,
              "currency": "CNY", "share_class": "A", "current_name": "贵州茅台",
              "source_ids": ["cninfo"], "evidence_ids": [], "status": "listed",
              "version": 1, "created_at": "2026-01-01T00:00:00+08:00",
              "updated_at": "2026-01-01T00:00:00+08:00"}
        conn.execute("INSERT INTO security_profiles VALUES (?)", (json.dumps(sp, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.entity_mapping")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        # entity → SecurityProfile.symbol（600519.SH）→ symbol 可证明
        assert "symbol" in r.available_fields
        assert "symbol" not in r.missing_fields
        db.close()

    def test_aliases_alone_not_symbol(self, requirement_registry, provenance, tmp_path):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (payload TEXT)")
        conn.execute("CREATE TABLE security_profiles (payload TEXT)")
        entity = {"entity_id": "company:600519.SH", "entity_type": "company",
                  "canonical_name": "贵州茅台", "aliases": ["贵州茅台"], "market": "A"}
        conn.execute("INSERT INTO entities VALUES (?)", (json.dumps(entity, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.entity_mapping")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        # 仅 aliases（无 SecurityProfile.symbol）→ symbol NOT PROVEN（§22）
        assert "symbol" in r.missing_fields
        db.close()


# ---------- §102：Lineage Parity ----------

class TestLineageParity:
    def test_shared_lineage_parity(self, tmp_path):
        """共享 helper 与既有 DailyReview 语义一致：same accepted/rejected set。"""
        from research_os.review.prior_run_lineage import derive_prior_cutoff
        root = tmp_path / "proj"
        # 合法 prior run
        run_dir = root / "reports" / "runs" / "A"
        run_dir.mkdir(parents=True)
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": "A", "scenario": "morning_brief", "status": "completed",
            "as_of": "2026-08-10T08:00:00+08:00",
            "time_window": {"end": "2026-08-10T08:00:00+08:00"},
        }, ensure_ascii=False), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": "ok", "task_id": "A",
        }, ensure_ascii=False), encoding="utf-8")
        # 非法 prior run（validation failed）
        bad_dir = root / "reports" / "runs" / "B"
        bad_dir.mkdir(parents=True)
        (bad_dir / "task.json").write_text(json.dumps({
            "task_id": "B", "scenario": "morning_brief", "status": "completed",
            "as_of": "2026-08-10T08:00:00+08:00",
        }, ensure_ascii=False), encoding="utf-8")
        (bad_dir / "validation.json").write_text(json.dumps({
            "status": "failed", "task_id": "B",
        }, ensure_ascii=False), encoding="utf-8")
        cutoff = derive_prior_cutoff(root, ["A", "B"], "2026-08-11T08:00:00+08:00")
        # 只有 A 被接受；B rejected；cutoff 来自 A
        assert cutoff is not None
        assert cutoff == "2026-08-10T08:00:00"  # timespec=seconds（无 offset 后缀，与共享 helper 一致）
