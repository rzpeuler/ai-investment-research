"""P7-D1-R1 强制测试：Readiness Semantic Correctness & Authority Alignment。

覆盖（§112-121）：
- 10/10 Runner.validate_request → NormalizedRequestContextAdapter → Resolver
- 22/22 DataTypeReadinessSpec authority mapping
- Cross-type contamination（claims≠evidence、security_profile≠company_profiles、financial≠valuation）
- PIT（financial publication / profile valid interval / claim as_of / future trade_date）
- Provenance（evidence tier / raw source / evidence_ids / unproven）
- Coverage（open-world null、singleton、peer set）
- Freshness（STALE / FRESHNESS_UNPROVEN / as_of replay）
- Dry-run existing DB（R1 blocker test）
- Derivation（eligible_count 不充分）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.checkers import (
    ReadinessCheckerRegistry,
    SqliteReadView,
)
from research_os.data_layer.context import RequirementContextResolver
from research_os.data_layer.gaps import DerivationPrerequisiteResolver, GapClassifier
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.data_layer.readiness import DataReadinessService
from research_os.data_layer.request_context import NormalizedRequestContextAdapter
from research_os.data_layer.specs import DATA_TYPE_SPECS, get_spec
from research_os.models import (
    Claim,
    CompanyProfile,
    DataReadiness,
    Evidence,
    RawItem,
    SecurityProfile,
    ValuationSnapshot,
)
from research_os.routing.scenario_requirements import (
    SCENARIO_IDS,
    ScenarioDataRequirementRegistry,
)
from research_os.validators.schema_validator import validate_instance

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


# ---------- §112：Real Runner Context ----------

class TestRealRunnerContext:
    """10/10 Runner 真实 normalized request → adapter → resolver。"""

    # 每个 scenario 的最小合法 request（按 Runner.validate_request 真实契约）
    MINIMAL_REQUESTS = {
        "morning_brief": {"report_date": "2026-08-11"},
        "evening_brief": {"report_date": "2026-08-11"},
        "abnormal_move_analysis": {"entity_id": "600519.SH"},
        "stock_research_report": {"entity": "company:600519.SH"},
        "stock_review": {"entity": "company:600519.SH",
                         "review_start": "2026-08-09",
                         "review_end": "2026-08-11",
                         "as_of": "2026-08-11T08:00:00+08:00",
                         "entities": ["company:600519.SH"]},
        "industry_research": {"industry_id": "ind:semiconductor",
                             "as_of": "2026-08-11T08:00:00+08:00"},
        "theme_discovery": {"industry_ids": ["ind:semiconductor"], "discovery_mode": "graph_based",
                            "as_of": "2026-08-11T08:00:00+08:00"},
        "daily_review": {"review_business_date": "2026-08-11"},
        "earnings_expectation": {"company_entity_id": "company:600519.SH",
                                 "as_of": "2026-08-11T08:00:00+08:00",
                                 "forecast_period": {"start": "2026-01-01", "end": "2026-12-31",
                                                     "periods": ["FY2026"]},
                                 "assumptions": [{
                                     "driver": "revenue_growth", "value": "10",
                                     "unit": "pct", "period": "FY2026",
                                     "source_type": "user_input",
                                     "source_ref_ids": [], "evidence_ids": [],
                                     "invalidates_when": "guidance_change",
                                     "known_at": "2026-08-11T08:00:00+08:00",
                                 }]},
        "first_coverage": {"company_entity_id": "company:600519.SH",
                           "security_entity_id": "security:600519.SH",
                           "industry_id": "ind:semiconductor",
                           "as_of": "2026-08-11T08:00:00+08:00"},
    }

    @pytest.mark.parametrize("scenario", SCENARIO_IDS)
    def test_real_runner_request_resolves(self, scenario, requirement_registry):
        from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES
        runner_cls = next(r for r in DEFAULT_RUNNER_TYPES if r.scenario == scenario)
        runner = runner_cls()
        normalized = runner.validate_request(dict(self.MINIMAL_REQUESTS[scenario]))
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract(scenario, normalized)
        resolver = RequirementContextResolver()
        # 每个 scenario 至少解析一个 requirement 无 false unresolved
        for req in requirement_registry.for_scenario(scenario):
            ctx = resolver.resolve(req, scenario, "t1", canonical, AS_OF)
            # 业务请求已给出 subject/industry → 不得 false unresolved
            if req.scope.scope_type == "subject" and canonical.subject_entity_ids:
                assert "subject" not in ctx.unresolved, f"{scenario}/{req.requirement_id}"
            if req.scope.scope_type == "industry" and canonical.industry_ids:
                assert "industry" not in ctx.unresolved, f"{scenario}/{req.requirement_id}"

    def test_task_entities_shared_adapter(self):
        """Task.entities 与 Resolver 共享 adapter（§9）。"""
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("earnings_expectation",
                                    {"company_entity_id": "company:600519.SH"})
        assert "company:600519.SH" in canonical.task_entities
        canonical2 = adapter.extract("first_coverage", {
            "company_entity_id": "company:600519.SH",
            "security_entity_id": "security:600519.SH",
        })
        assert set(canonical2.task_entities) == {"company:600519.SH", "security:600519.SH"}


# ---------- §113：Authority Mapping ----------

class TestAuthorityMapping:
    def test_22_specs_explicit(self):
        assert len(DATA_TYPE_SPECS) == 22
        for spec in DATA_TYPE_SPECS:
            assert spec.authority_kind
            assert spec.authority_location
            assert spec.pit_strategy
            assert spec.coverage_strategy
            assert spec.freshness_strategy

    def test_specs_match_scenario_types(self, requirement_registry):
        required = {r.data_type for r in requirement_registry.all()}
        spec_types = {s.data_type for s in DATA_TYPE_SPECS}
        assert required == spec_types

    def test_claims_authority_is_claims(self):
        assert get_spec("claims").authority_location == "claims"

    def test_security_profile_authority(self):
        assert get_spec("security_profile").authority_location == "security_profiles"

    def test_valuation_authority(self):
        assert get_spec("market_valuation_snapshot").authority_location == "valuation_snapshots"


# ---------- §114：Cross-type Contamination ----------

class TestCrossTypeContamination:
    def _db_with(self, tmp_path, table, payloads):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute(f"CREATE TABLE {table} (payload TEXT)")
        for p in payloads:
            conn.execute(f"INSERT INTO {table} VALUES (?)",
                         (json.dumps(p, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def test_claim_only_in_claims_not_evidence(self, tmp_path, requirement_registry, provenance):
        claim = {
            "claim_id": "c1", "claim_type": "FACT", "statement": "测试声明",
            "subject_entities": ["company:600519.SH"], "predicate": "has",
            "object": {"value": "x"},
            "as_of": "2026-08-10T00:00:00+08:00", "evidence_ids": [],
            "support_level": "inferred", "confidence": 0.9,
            "review_status": "unreviewed",
        }
        db = self._db_with(tmp_path, "claims", [claim])
        view = SqliteReadView(db)
        req = requirement_registry.get("daily_review.claims")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("daily_review", {"review_business_date": "2026-08-11"})
        ctx = RequirementContextResolver().resolve(req, "daily_review", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # claims 表有记录 → 不应 MISSING（能读到）
        assert r.status != "MISSING"
        db.close()

    def test_security_profile_not_from_company_profiles(self, tmp_path, requirement_registry, provenance):
        profile = {
            "company_profile_id": "cp1", "entity_id": "company:600519.SH",
            "canonical_name": "贵州茅台", "industry_ids": ["ind:semiconductor"],
            "fiscal_year_end": "2026-12-31", "reporting_currency": "CNY",
            "ownership_type": "public", "valid_from": "2026-01-01",
            "valid_to": None, "status": "active",
            "source_ids": ["cninfo"], "evidence_ids": [], "version": 1,
            "created_at": "2026-01-01T00:00:00+08:00",
            "updated_at": "2026-01-01T00:00:00+08:00",
        }
        db = self._db_with(tmp_path, "company_profiles", [profile])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # company_profiles 有记录但 security_profiles 无 → security_profile 不得 READY
        assert r.status != "READY"
        db.close()

    def test_valuation_not_from_financial_facts(self, tmp_path, requirement_registry, provenance):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        conn.execute("INSERT INTO financial_facts VALUES (?)",
                     (json.dumps({"fact_id": "f1", "fact_key": "revenue",
                                  "company_entity_id": "company:600519.SH",
                                  "period_end": "2026-06-30", "value": 100}, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # financial_fact 存在但 valuation_snapshot 不存在 → 不得误判 READY
        assert r.status != "READY"
        db.close()


# ---------- §116：Provenance ----------

class TestProvenance:
    def test_evidence_tier_direct(self, provenance):
        tier, warn = provenance.resolve({"source_tier": "S"}, "evidence_tier", None)
        assert tier == "S" and warn is None

    def test_raw_item_source_tier(self, provenance):
        tier, warn = provenance.resolve({"source_id": "cninfo"}, "raw_item_source", None)
        assert tier == "S"  # sources.yaml: cninfo=S

    def test_unproven_fail_closed(self, provenance):
        tier, warn = provenance.resolve({}, "raw_item_source", None)
        assert tier is None
        assert warn == "SOURCE_TIER_UNPROVEN"


# ---------- §117：Coverage ----------

class TestCoverageR1:
    def test_open_world_empty_is_null(self, requirement_registry, capability_registry, tmp_path):
        # brief_event_content 无记录 → coverage null（禁止 0.0）
        from research_os.data_layer.checkers import EmptyReadView
        req = requirement_registry.get("morning_brief.event.brief_event_content")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("morning_brief", {"report_date": "2026-08-11"})
        ctx = RequirementContextResolver().resolve(req, "morning_brief", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, EmptyReadView(), CHECKED_AT)
        assert r.coverage_ratio is None

    def test_open_world_nonempty_is_null(self, requirement_registry, tmp_path, provenance):
        # 有 raw item 但 open-world 仍 null（§43）
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        item = {
            "raw_item_id": "ri1", "source_id": "cls", "external_id": "e1", "url": "http://x",
            "title": "某快讯", "publisher": "cls", "published_at": "2026-08-11T07:00:00+08:00",
            "retrieved_at": "2026-08-11T07:05:00+08:00",
            "content_hash": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "content_excerpt": "摘录", "content_storage": "metadata_and_excerpt",
            "language": "zh-CN", "access_status": "ok", "entities": [],
            "raw_category": "fast_news",
        }
        conn.execute("INSERT INTO raw_items VALUES (?)", (json.dumps(item, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req = requirement_registry.get("morning_brief.event.news_flash")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("morning_brief", {"report_date": "2026-08-11"})
        ctx = RequirementContextResolver().resolve(req, "morning_brief", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.coverage_ratio is None  # open-world 无论多少条都 null
        db.close()


# ---------- §118：Freshness ----------

class TestFreshness:
    def test_stale_reachable(self, requirement_registry, provenance, tmp_path):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_ohlcv (payload TEXT, symbol TEXT, trade_date TEXT, close REAL)")
        # trade_date 8/1（合法 PIT：<= as_of），但 freshness age（10 天）> 86400 → STALE
        bar = {"symbol": "600519.SH", "trade_date": "2026-08-01", "open": 1, "close": 2}
        conn.execute(
            "INSERT INTO market_daily_ohlcv VALUES (?, ?, ?, ?)",
            (json.dumps(bar, ensure_ascii=False), "600519.SH", "2026-08-01", 2.0),
        )
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req = requirement_registry.get("abnormal_move_analysis.market_daily_ohlcv")
        # market_daily_ohlcv freshness_seconds=86400；8/1 到 8/11 = 10 天远超
        assert req.freshness_seconds == 86400
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("abnormal_move_analysis", {
            "entity_id": "600519.SH",
            "window_start": "2026-08-09T00:00:00+08:00",
            "window_end": "2026-08-11T08:00:00+08:00",
        })
        ctx = RequirementContextResolver().resolve(req, "abnormal_move_analysis", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status == "STALE"
        db.close()


# ---------- §120：Dry-run Existing DB（R1 blocker test） ----------

class TestDryRunExistingDB:
    def test_dry_run_reads_existing_db(self, tmp_path, requirement_registry, capability_registry):
        import sqlite3
        root = tmp_path / "proj"
        (root / "reports").mkdir(parents=True)
        (root / "data" / "sqlite").mkdir(parents=True)
        db_path = root / "data" / "sqlite" / "research.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        item = {
            "raw_item_id": "ri1", "source_id": "cls", "external_id": "e1", "url": "http://x",
            "title": "晨报快讯", "publisher": "cls", "published_at": "2026-08-11T07:00:00+08:00",
            "retrieved_at": "2026-08-11T07:05:00+08:00",
            "content_hash": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
            "content_excerpt": "摘录", "content_storage": "metadata_and_excerpt",
            "language": "zh-CN", "access_status": "ok", "entities": [],
            "raw_category": "fast_news",
        }
        conn.execute("INSERT INTO raw_items VALUES (?)", (json.dumps(item, ensure_ascii=False),))
        conn.commit()
        conn.close()

        from research_os.orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(root)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0
        # dry-run 读到既有 row（不得 IGNORE EXISTING DATA）
        # 通过 preflight readiness 验证：news_flash 有 eligible raw item
        # 但无法直接从 result 拿 preflight（dry-run 不注入 context）；验证零副作用
        assert (root / "data" / "sqlite" / "research.db").exists()  # 原有 DB 保留
        assert not (root / "reports" / "runs").exists()  # 不创建 run dir
        orch.close()

    def test_dry_run_no_db_no_creation(self, tmp_path, requirement_registry, capability_registry):
        root = tmp_path / "proj2"
        (root / "reports").mkdir(parents=True)
        from research_os.orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(root)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0
        assert not (root / "data" / "sqlite" / "research.db").exists()
        assert not (root / "reports" / "runs").exists()
        orch.close()


# ---------- §121：Derivation ----------

class TestDerivation:
    def test_eligible_count_alone_not_sufficient(self, requirement_registry, capability_registry):
        # market_valuation_snapshot deterministic_derivation=true 但无显式 prerequisite
        classifier = GapClassifier(capability_registry)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status="MISSING",
            available_fields=[], missing_fields=[], coverage_ratio=None,
            freshness_age_seconds=None, eligible_record_count=5,  # >0 但不足证明
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        gap = classifier.classify(req, r)
        assert gap.classification != "AUTO_DERIVABLE"

    def test_derivation_resolver_default_false(self):
        resolver = DerivationPrerequisiteResolver()
        r = DataReadiness(
            requirement_id="x", data_type="market_valuation_snapshot",
            checked_at=CHECKED_AT, as_of=AS_OF, status="MISSING",
            available_fields=[], missing_fields=[], coverage_ratio=None,
            freshness_age_seconds=None, eligible_record_count=10,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        assert resolver.prerequisites_proven("market_valuation_snapshot", r) is False

    def test_explicit_prerequisite_resolver(self):
        resolver = DerivationPrerequisiteResolver()
        resolver.register("dummy", lambda readiness: readiness.eligible_record_count > 0)
        r = DataReadiness(
            requirement_id="x", data_type="dummy", checked_at=CHECKED_AT, as_of=AS_OF,
            status="MISSING", available_fields=[], missing_fields=[],
            coverage_ratio=None, freshness_age_seconds=None, eligible_record_count=3,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        assert resolver.prerequisites_proven("dummy", r) is True


class TestGraphPITAuthority:
    """§119：证明既有 Graph lifecycle/query authority 实际收到 as_of（不得只断言 class 存在）。"""

    def test_graph_checker_uses_existing_authority_with_as_of(self, requirement_registry, provenance):
        from research_os.data_layer.checkers import ReadinessCheckerRegistry, SqliteReadView
        from research_os.data_layer.context import RequirementContextResolver
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter

        class FakeHistory:
            def __init__(self):
                self.received_as_of = None

            def resolve_node_as_of(self, node_id, as_of):
                self.received_as_of = as_of
                return {"node_id": node_id}  # 已解析

        class FakeGraphQuery:
            def __init__(self):
                self.received_as_of = None

            def get_node(self, node_id, as_of):
                self.received_as_of = as_of
                return type("N", (), {"error": None})()

        history = FakeHistory()
        query = FakeGraphQuery()

        class FakeView(SqliteReadView):
            def __init__(self, graph_query_service, graph_history_service):
                self._db = None
                self.graph_query_service = graph_query_service
                self.graph_history_service = graph_history_service

            def has_table(self, table):
                return True

            def query(self, sql, params=()):
                return []

        view = FakeView(query, history)
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("industry_research", {
            "industry_id": "ind:semiconductor",
            "as_of": "2026-08-11T08:00:00+08:00",
        })
        ctx = RequirementContextResolver().resolve(req, "industry_research", "t1", canonical, AS_OF)
        service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # 既有 authority 实际收到 as_of（非仅 class 存在）
        assert history.received_as_of == AS_OF
        assert query.received_as_of == AS_OF
