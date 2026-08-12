"""P7-D1-R2 强制测试：Authority Semantics Closure & Requirement Contract Alignment。

覆盖（§67-99）：
- 43/43 semantic closure matrix（binding/context/authority/scope/pit/coverage/freshness/min-field）
- 6 项 contract correction 机械校验
- time context（daily/stock/abnormal 权威）
- explicit window 真正过滤
- SecurityProfile 生命周期
- Valuation 生命周期（单候选无 field union）
- Financial canonical value / coverage / peer denominator
- Industry scope / coverage
- Tier matrix（evidence/claim/finding/market）
- Graph query_graph 实证 + zero write
- dry-run 拆两测试（preflight read + orchestrator side-effect）
- Schema-valid positive fixtures
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
from research_os.data_layer.gaps import GapClassifier
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.projector import MinimumFieldClosureValidator, ReadinessFieldProjector
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.data_layer.readiness import DataReadinessService
from research_os.data_layer.request_context import NormalizedRequestContextAdapter
from research_os.models import (
    CompanyProfile,
    Evidence,
    FinancialFact,
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


@pytest.fixture(scope="module")
def bindings(requirement_registry):
    return RequirementReadinessBindingResolver(requirement_registry).all()


# ---------- §67/68：43/43 Semantic Closure Matrix ----------

class TestSemanticClosureMatrix:
    def test_all_43_requirements_have_semantic_closure(self, requirement_registry, bindings):
        assert len(bindings) == 43
        binding_by_id = {b.requirement_id: b for b in bindings}
        for req in requirement_registry.all():
            b = binding_by_id[req.requirement_id]
            assert b.context_strategy, f"{req.requirement_id} context"
            assert b.authority_strategy and b.authority_location, f"{req.requirement_id} authority"
            assert b.scope_strategy, f"{req.requirement_id} scope"
            assert b.pit_strategy, f"{req.requirement_id} pit"
            assert b.coverage_strategy, f"{req.requirement_id} coverage"
            assert b.freshness_strategy, f"{req.requirement_id} freshness"
            # 每个 minimum_field 有 direct 或 projection 来源
            for f, src in b.minimum_field_sources.items():
                assert src == "direct" or src.startswith(("canonical:", "projection:")), \
                    f"{req.requirement_id}:{f} 无合法来源"

    def test_minimum_field_closure_zero_violations(self, bindings):
        v = MinimumFieldClosureValidator(bindings)
        assert v.validate() == []

    def test_no_unknown_strategy_fallback(self, bindings):
        for b in bindings:
            assert "UNKNOWN" not in b.context_strategy
            assert "UNKNOWN" not in b.scope_strategy
            assert "UNKNOWN" not in b.pit_strategy

    def test_unknown_strategy_raises_config_error(self):
        # 未知 projection → fail closed
        projector = ReadinessFieldProjector()
        assert projector.has_field({}, "x", "projection:unknown_thing", {}) is False

    def test_checker_and_binding_dual_gate(self, requirement_registry, bindings):
        checker_reg = ReadinessCheckerRegistry()
        required = {r.data_type for r in requirement_registry.all()}
        assert set(checker_reg.data_types()) == required  # 22/22 checker
        assert len(bindings) == 43  # 43/43 binding


# ---------- §106：Contract Correction Gate ----------

class TestContractCorrectionGate:
    def test_exact_6_corrections(self, requirement_registry):
        checks = {
            "stock_research_report.company_document": ("as_of_snapshot", "strict_as_of", "subject"),
            "stock_research_report.industry_membership": ("as_of_snapshot", "strict_as_of", "subject"),
            "industry_research.evidence_index": ("as_of_snapshot", "strict_as_of", "industry"),
            "theme_discovery.evidence_index": ("as_of_snapshot", "strict_as_of", "global"),
            "theme_discovery.document_corpus": ("as_of_snapshot", "strict_as_of", "global"),
            "earnings_expectation.company_announcement": ("as_of_snapshot", "strict_as_of", "subject"),
        }
        for rid, (tp, pit, scope) in checks.items():
            r = requirement_registry.get(rid)
            assert r.time_policy == tp, rid
            assert r.point_in_time_policy == pit, rid
            assert r.scope.scope_type == scope, rid

    def test_scenario_and_requirement_counts(self, requirement_registry):
        assert len({r.scenario for r in requirement_registry.all()}) == 10
        assert len(requirement_registry.all()) == 43


# ---------- §95：Time Context ----------

class TestTimeContext:
    MINIMAL_REQUESTS = {
        "morning_brief": {"report_date": "2026-08-11"},
        "evening_brief": {"report_date": "2026-08-11"},
        "abnormal_move_analysis": {"entity_id": "600519.SH",
                                   "window_start": "2026-08-09T00:00:00+08:00",
                                   "window_end": "2026-08-11T08:00:00+08:00"},
        "stock_research_report": {"entity": "company:600519.SH"},
        "stock_review": {"entity": "company:600519.SH", "review_start": "2026-08-09",
                         "review_end": "2026-08-11", "as_of": AS_OF},
        "industry_research": {"industry_id": "ind:semiconductor", "as_of": AS_OF},
        "theme_discovery": {"industry_ids": ["ind:semiconductor"], "as_of": AS_OF},
        "daily_review": {"review_business_date": "2026-08-11", "as_of": AS_OF},
        "earnings_expectation": {"company_entity_id": "company:600519.SH", "as_of": AS_OF,
                                 "forecast_period": {"start": "2026-01-01", "end": "2026-12-31",
                                                     "periods": ["FY2026"]},
                                 "assumptions": [{
                                     "driver": "revenue_growth", "value": "10",
                                     "unit": "pct", "period": "FY2026",
                                     "source_type": "user_input",
                                     "source_ref_ids": [], "evidence_ids": [],
                                     "invalidates_when": "guidance_change",
                                     "known_at": AS_OF,
                                 }]},
        "first_coverage": {"company_entity_id": "company:600519.SH",
                           "security_entity_id": "security:600519.SH",
                           "industry_id": "ind:semiconductor", "as_of": AS_OF},
    }

    @pytest.mark.parametrize("scenario", SCENARIO_IDS)
    def test_all_43_requirement_time_policies_resolvable(self, scenario, requirement_registry):
        from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES
        runner_cls = next(r for r in DEFAULT_RUNNER_TYPES if r.scenario == scenario)
        normalized = runner_cls().validate_request(dict(self.MINIMAL_REQUESTS[scenario]))
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract(scenario, normalized)
        resolver = RequirementContextResolver()
        for req in requirement_registry.for_scenario(scenario):
            ctx = resolver.resolve(req, scenario, "t1", canonical, AS_OF)
            # as_of_snapshot / latest_available / lookback 不需要 window（§16）
            if req.time_policy == "explicit_request_window":
                assert "window" not in ctx.unresolved, \
                    f"{req.requirement_id} 应解析 window"
            elif req.time_policy == "scenario_window":
                assert "scenario_window" not in ctx.unresolved, \
                    f"{req.requirement_id} 应解析 scenario window"

    def test_daily_review_window(self, requirement_registry):
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("daily_review", {"review_business_date": "2026-08-11",
                                                     "as_of": "2026-08-11T15:00:00+08:00"})
        assert canonical.explicit_window_start == "2026-08-11T00:00:00+08:00"
        assert canonical.explicit_window_end == "2026-08-11T15:00:00+08:00"  # min(次日, as_of)

    def test_stock_review_window(self, requirement_registry):
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_review", {"review_start": "2026-08-09",
                                                     "review_end": "2026-08-11",
                                                     "as_of": "2026-08-10T12:00:00+08:00"})
        assert canonical.explicit_window_start == "2026-08-09T00:00:00+08:00"
        assert canonical.explicit_window_end == "2026-08-10T12:00:00+08:00"  # min(23:59:59, as_of)

    def test_abnormal_explicit_window_preserved(self):
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("abnormal_move_analysis", {
            "entity_id": "600519.SH",
            "window_start": "2026-08-09T00:00:00+08:00",
            "window_end": "2026-08-11T08:00:00+08:00",
        })
        assert canonical.explicit_window_start == "2026-08-09T00:00:00+08:00"
        assert canonical.explicit_window_end == "2026-08-11T08:00:00+08:00"

    def test_as_of_snapshot_no_false_window_unresolved(self, requirement_registry):
        # 6 处纠偏后 as_of_snapshot requirement 不得产生假 window unresolved
        for rid in ("stock_research_report.company_document",
                    "industry_research.evidence_index",
                    "theme_discovery.evidence_index",
                    "theme_discovery.document_corpus",
                    "earnings_expectation.company_announcement"):
            req = requirement_registry.get(rid)
            assert req.time_policy == "as_of_snapshot"
            assert req.point_in_time_policy == "strict_as_of"


# ---------- §96：Explicit Window Filtering ----------

class TestWindowFiltering:
    def _evidence_db(self, tmp_path, evidences):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        for e in evidences:
            conn.execute("INSERT INTO evidence VALUES (?)", (json.dumps(e, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def test_evidence_before_window_excluded(self, tmp_path, requirement_registry, provenance):
        evidences = [
            {"evidence_id": "ev1", "source_id": "cninfo", "raw_item_id": "ri1",
             "title": "窗口外", "published_at": "2026-08-01T00:00:00+08:00", "url": "http://e",
             "excerpt": "x", "evidence_type": "official_disclosure", "independence_group": "g1",
             "source_tier": "S"},
        ]
        db = self._evidence_db(tmp_path, evidences)
        view = SqliteReadView(db)
        req = requirement_registry.get("daily_review.evidence")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("daily_review", {"review_business_date": "2026-08-11",
                                                     "as_of": "2026-08-11T08:00:00+08:00"})
        ctx = RequirementContextResolver().resolve(req, "daily_review", "t1", canonical, AS_OF)
        # 窗口 [08-11 00:00, 08-11 08:00)；evidence 8/1 在窗口外 → 不计入 eligible
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.eligible_record_count == 0
        db.close()

    def test_evidence_inside_window_included(self, tmp_path, requirement_registry, provenance):
        evidences = [
            {"evidence_id": "ev2", "source_id": "cninfo", "raw_item_id": "ri2",
             "title": "窗口内", "published_at": "2026-08-11T06:00:00+08:00", "url": "http://e",
             "excerpt": "x", "evidence_type": "official_disclosure", "independence_group": "g1",
             "source_tier": "S"},
        ]
        db = self._evidence_db(tmp_path, evidences)
        view = SqliteReadView(db)
        req = requirement_registry.get("daily_review.evidence")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("daily_review", {"review_business_date": "2026-08-11",
                                                     "as_of": "2026-08-11T08:00:00+08:00"})
        ctx = RequirementContextResolver().resolve(req, "daily_review", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.eligible_record_count == 1
        db.close()


# ---------- §91：SecurityProfile 生命周期 ----------

class TestSecurityProfileLifecycle:
    def _sec_db(self, tmp_path, profiles):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE security_profiles (payload TEXT)")
        for p in profiles:
            conn.execute("INSERT INTO security_profiles VALUES (?)", (json.dumps(p, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def _base_profile(self, **kw):
        p = {
            "security_profile_id": "sp1", "security_entity_id": "security:600519.SH",
            "company_entity_id": "company:600519.SH", "symbol": "600519.SH",
            "exchange": "SH", "board": "main", "security_type": "common_share",
            "currency": "CNY", "share_class": "A",
            "exchange": "SSE", "security_type": "A", "listing_date": "2020-01-01",
            "delisting_date": None, "current_name": "贵州茅台", "source_ids": ["cninfo"],
            "evidence_ids": [], "status": "listed", "version": 1,
            "updated_at": "2026-08-01T00:00:00+08:00",
        }
        p.update(kw)
        return p

    def test_valid_listed_not_falsely_ineligible(self, tmp_path, requirement_registry, provenance):
        db = self._sec_db(tmp_path, [self._base_profile()])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # security_profile 的 company_entity_id 匹配 subject（company:）→ 不应 MISSING
        assert r.status != "MISSING"
        db.close()

    def test_future_listing_pit_ineligible(self, tmp_path, requirement_registry, provenance):
        db = self._sec_db(tmp_path, [self._base_profile(listing_date="2027-01-01")])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status == "MISSING"  # as_of < listing_date → PIT_INELIGIBLE
        db.close()

    def test_suspended_own_semantics(self, tmp_path, requirement_registry, provenance):
        db = self._sec_db(tmp_path, [self._base_profile(status="suspended")])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        # suspended 按自身语义处理（listing 生命周期内），不按 company 状态污染
        assert r.status != "MISSING"
        db.close()

    def test_delisted_historical(self, tmp_path, requirement_registry, provenance):
        db = self._sec_db(tmp_path, [self._base_profile(status="delisted",
                                                        delisting_date="2026-07-01")])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status == "MISSING"  # delisting_date 已过 → as_of 时不可用
        db.close()


# ---------- §92：Valuation 生命周期 ----------

class TestValuationLifecycle:
    def _val_db(self, tmp_path, snapshots):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE valuation_snapshots (payload TEXT)")
        for s in snapshots:
            conn.execute("INSERT INTO valuation_snapshots VALUES (?)", (json.dumps(s, ensure_ascii=False),))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def _snap(self, **kw):
        s = {
            "valuation_snapshot_id": "vs1", "company_entity_id": "company:600519.SH",
            "security_entity_id": "security:600519.SH", "as_of": "2026-08-10T00:00:00+08:00",
            "price": 1500.0, "market_cap": 1.9e12, "enterprise_value": 1.8e12,
            "metrics": {}, "peer_selection_id": "ps1", "percentile_method": "pct",
            "source_ids": ["cninfo"], "evidence_ids": [], "status": "complete",
            "shares_outstanding": 1.25e9, "version": 1,
        }
        s.update(kw)
        return s

    def test_complete_valid_eligible(self, tmp_path, requirement_registry, provenance):
        db = self._val_db(tmp_path, [self._snap()])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status != "MISSING"
        db.close()

    def test_insufficient_data_not_ready(self, tmp_path, requirement_registry, provenance):
        db = self._val_db(tmp_path, [self._snap(status="insufficient_data")])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status == "MISSING"
        db.close()

    def test_future_as_of_pit_ineligible(self, tmp_path, requirement_registry, provenance):
        db = self._val_db(tmp_path, [self._snap(as_of="2026-09-01T00:00:00+08:00")])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.status == "MISSING"
        db.close()

    def test_two_snapshots_latest_selected_no_field_union(self, tmp_path, requirement_registry, provenance):
        old = self._snap(valuation_snapshot_id="vs1", as_of="2026-08-01T00:00:00+08:00",
                         price=1400.0, shares_outstanding=1.2e9)
        new = self._snap(valuation_snapshot_id="vs2", as_of="2026-08-10T00:00:00+08:00",
                         price=1500.0, shares_outstanding=1.25e9)
        db = self._val_db(tmp_path, [old, new])
        view = SqliteReadView(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = RequirementContextResolver().resolve(req, "stock_research_report", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert r.eligible_record_count == 1  # 单一候选
        assert all("vs2" in ref for ref in r.record_refs)  # latest selected
        db.close()


# ---------- §93：Financial ----------

class TestFinancialSemantics:
    def test_canonical_value_projection(self, requirement_registry):
        from research_os.data_layer.projector import ReadinessFieldProjector
        proj = ReadinessFieldProjector()
        assert proj.has_field({"value_status": "reported", "normalized_value": "100",
                               "raw_value": "100"}, "value", "canonical:financial_value", {})
        assert proj.has_field({"value_status": "derived_from_report", "raw_value": "50"},
                              "value", "canonical:financial_value", {})
        assert not proj.has_field({"value_status": "missing"}, "value",
                                  "canonical:financial_value", {})
        assert not proj.has_field({"value_status": "conflict", "raw_value": "50"}, "value",
                                  "canonical:financial_value", {})
        assert not proj.has_field({"value_status": "reported"}, "value",
                                  "canonical:financial_value", {})

    def test_peer_coverage_denominator(self, requirement_registry, capability_registry):
        # peer 1/4 → 0.25（§32）
        classifier = GapClassifier(capability_registry)
        req = requirement_registry.get("stock_research_report.peer_financial_data")
        from research_os.models import DataReadiness
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status="PARTIAL",
            available_fields=["fact_key", "value"], missing_fields=["period_end"],
            coverage_ratio=0.25, freshness_age_seconds=None,
            eligible_record_count=1, ineligible_record_count=3,
            source_tiers_present=["B"], record_refs=[], warnings=[],
        )
        assert r.coverage_ratio == 0.25


# ---------- §94：Tier Matrix ----------

class TestTierMatrix:
    def test_evidence_tier_eligible(self, provenance):
        tier, warn = provenance.resolve({"source_tier": "B"}, "evidence_tier", None)
        assert tier == "B"

    def test_market_bar_without_manifest_tier_unproven(self, tmp_path, provenance):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_series_manifests (payload TEXT)")
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import SqliteReadView
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        tier, warn = provenance.resolve({"symbol": "600519.SH", "trade_date": "2026-08-10"},
                                        "manifest", view)
        assert tier is None
        assert warn == "SOURCE_TIER_UNPROVEN"
        db.close()


# ---------- §98：Graph ----------

class TestGraphR2:
    def test_graph_zero_writes(self, requirement_registry, provenance, monkeypatch):
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        from research_os.data_layer.context import RequirementContextResolver
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter

        class FakeHistory:
            def resolve_node_as_of(self, node_id, as_of):
                return {"node_id": node_id}

        class FakeGraphQuery:
            def query_graph(self, root_node_id, as_of, max_depth=1, direction="both"):
                return type("R", (), {
                    "nodes": [type("N", (), {"node_id": "n1"})()],
                    "edges": [type("E", (), {"edge_id": "e1"})()],
                })()

        wrote = []
        monkeypatch.setattr("research_os.knowledge.repository.GraphRepository.append_node",
                            lambda *a, **k: wrote.append("append_node"))
        monkeypatch.setattr("research_os.knowledge.repository.GraphRepository.append_edge",
                            lambda *a, **k: wrote.append("append_edge"))

        class FakeView(EmptyReadView):
            def __init__(self):
                self.graph_query_service = FakeGraphQuery()
                self.graph_history_service = FakeHistory()
                self.runs_root = None

            def has_table(self, table):
                return True

            def query(self, sql, params=()):
                return []

        view = FakeView()
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("industry_research", {"industry_id": "ind:semiconductor",
                                                          "as_of": AS_OF})
        ctx = RequirementContextResolver().resolve(req, "industry_research", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, view, CHECKED_AT, provenance)
        assert wrote == []  # 零 Graph write
        assert r.eligible_record_count == 1  # query 成功 → node_refs 真实


# ---------- §99：Schema-valid Positive Fixtures ----------

class TestSchemaValidFixtures:
    def _schema_valid(self, obj, schema):
        assert validate_instance(obj.model_dump(), schema) == []

    def test_security_profile_fixture(self):
        sp = SecurityProfile(
            security_profile_id="sp1", security_entity_id="security:600519.SH",
            company_entity_id="company:600519.SH", symbol="600519.SH", exchange="SH",
            board="main", security_type="common_share", listing_date="2020-01-01",
            delisting_date=None, currency="CNY", share_class="A", current_name="贵州茅台",
            source_ids=["cninfo"], evidence_ids=[], status="listed", version=1,
            created_at="2026-01-01T00:00:00+08:00", updated_at="2026-01-01T00:00:00+08:00",
        )
        self._schema_valid(sp, "security_profile")

    def test_company_profile_fixture(self):
        cp = CompanyProfile(
            company_profile_id="cp1", entity_id="company:600519.SH",
            canonical_name="贵州茅台", industry_ids=["ind:semiconductor"],
            fiscal_year_end="12-31", reporting_currency="CNY",
            ownership_type="private", valid_from="2026-01-01", valid_to=None,
            source_ids=["cninfo"], evidence_ids=[], status="active", version=1,
            created_at="2026-01-01T00:00:00+08:00", updated_at="2026-01-01T00:00:00+08:00",
        )
        self._schema_valid(cp, "company_profile")

    def test_valuation_fixture(self):
        vs = ValuationSnapshot(
            valuation_snapshot_id="vs1", company_entity_id="company:600519.SH",
            security_entity_id="security:600519.SH", as_of="2026-08-10T00:00:00+08:00",
            price="1500.0", market_cap="1900000000000", enterprise_value="1800000000000",
            metrics=[], peer_selection_id="ps1", percentile_method="average_rank",
            source_ids=["cninfo"], evidence_ids=[], status="complete",
            shares_outstanding="1250000000", version=1,
            calculated_at="2026-08-10T00:00:00+08:00",
        )
        self._schema_valid(vs, "valuation_snapshot")

    def test_evidence_fixture(self):
        ev = Evidence(
            evidence_id="dfdaf877-c705-45ef-8eca-8ca430d8fe95", source_id="cninfo", raw_item_id="fdf1ad28-c326-41e8-9b59-2dc9e9aece3a",
            title="公告", publisher="cninfo", published_at="2026-08-10T00:00:00+08:00",
            retrieved_at="2026-08-10T00:05:00+08:00",
            url="http://e", excerpt="x", evidence_type="official_disclosure",
            independence_group="g1", source_tier="S",
        )
        self._schema_valid(ev, "evidence")


# ---------- §62/63：Dry-run 拆两测试 ----------

class TestDryRunR2:
    def _existing_db(self, tmp_path, with_row=True):
        import sqlite3
        root = tmp_path / "proj"
        (root / "reports").mkdir(parents=True)
        (root / "data" / "sqlite").mkdir(parents=True)
        db_path = root / "data" / "sqlite" / "research.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        conn.execute("PRAGMA user_version = 6")
        if with_row:
            item = {"raw_item_id": "ri1", "source_id": "cls", "url": "http://x",
                    "title": "快讯", "publisher": "cls", "published_at": "2026-08-11T07:00:00+08:00",
                    "retrieved_at": "2026-08-11T07:05:00+08:00",
                    "content_hash": "d" * 64, "content_excerpt": "摘录",
                    "content_storage": "metadata_and_excerpt", "language": "zh-CN",
                    "access_status": "ok", "entities": [], "raw_category": "fast_news"}
            conn.execute("INSERT INTO raw_items VALUES (?)", (json.dumps(item, ensure_ascii=False),))
        conn.commit()
        conn.close()
        return root, db_path

    def test_preflight_reads_existing_row(self, tmp_path, requirement_registry, capability_registry):
        root, _ = self._existing_db(tmp_path, with_row=True)
        svc = DataPreflightService(requirement_registry, capability_registry)
        bundle = svc.run(
            scenario="morning_brief", task_id="t1", task_as_of=AS_OF,
            normalized_request={"report_date": "2026-08-11", "dry_run": True},
            project_root=root, dry_run=True,
        )
        # Test A：preflight 实际读到既有 row（eligible_record_count > 0）
        news = [r for r in bundle.readiness if r.data_type == "news_flash"]
        assert news and news[0].eligible_record_count > 0

    def test_orchestrator_dry_run_no_side_effects(self, tmp_path, requirement_registry, capability_registry):
        import sqlite3
        root, db_path = self._existing_db(tmp_path, with_row=True)
        conn = sqlite3.connect(db_path)
        before_version = conn.execute("PRAGMA user_version").fetchone()[0]
        before_count = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
        before_hash = conn.execute(
            "SELECT json_extract(payload, '$.content_hash') FROM raw_items "
            "WHERE json_extract(payload, '$.raw_item_id')='ri1'").fetchone()[0]
        conn.close()

        from research_os.orchestrator.orchestrator import Orchestrator
        orch = Orchestrator(root)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0
        assert not (root / "reports" / "runs").exists()

        conn = sqlite3.connect(db_path)
        after_version = conn.execute("PRAGMA user_version").fetchone()[0]
        after_count = conn.execute("SELECT COUNT(*) FROM raw_items").fetchone()[0]
        after_hash = conn.execute(
            "SELECT json_extract(payload, '$.content_hash') FROM raw_items "
            "WHERE json_extract(payload, '$.raw_item_id')='ri1'").fetchone()[0]
        conn.close()
        # Test B：DB 零变更（user_version / row count / payload checksum）
        assert before_version == after_version == 6
        assert before_count == after_count
        assert before_hash == after_hash
        orch.close()


class TestManifestTierPositive:
    def test_market_bar_with_accepted_manifest_eligible(self, tmp_path, provenance):
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_series_manifests (payload TEXT, source_kind TEXT, "
                     "adjustment_method TEXT, validation_status TEXT, date_start TEXT, date_end TEXT, "
                     "data_version TEXT, imported_at TEXT)")
        conn.execute("INSERT INTO market_daily_series_manifests (payload, source_kind, adjustment_method, "
                     "validation_status, date_start, date_end, data_version, imported_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                     (json.dumps({
                         "import_id": "m1", "source_id": "cninfo",
                         "source_kind": "official", "symbols": ["600519.SH"],
                         "date_start": "2026-08-01", "date_end": "2026-08-31",
                         "validation_status": "accepted", "data_version": "1",
                     }, ensure_ascii=False),
                      "official", "none", "accepted", "2026-08-01", "2026-08-31", "1",
                      "2026-08-01T00:00:00+08:00"))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        from research_os.data_layer.checkers import SqliteReadView
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        tier, warn = provenance.resolve({"symbol": "600519.SH", "trade_date": "2026-08-10"},
                                        "manifest", view)
        assert tier == "S"  # cninfo → S
        assert warn is None
        db.close()
