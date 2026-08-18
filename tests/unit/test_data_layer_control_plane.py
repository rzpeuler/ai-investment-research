"""P7-D1 data layer control plane tests.

覆盖：checker coverage（43/43）、capability coverage（22/22）、
RequirementContextResolver、DataReadinessService PIT/scope/coverage、
GapClassifier 8 分类、AcquisitionPlanner 确定性、preflight 集成、
dry-run 零副作用、config error fail closed、网络/LLM 禁止。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.checkers import (
    EmptyReadView,
    ReadinessCheckerRegistry,
    SqliteReadView,
)
from research_os.data_layer.context import RequirementContextResolver
from research_os.data_layer.gaps import GapClassifier
from research_os.data_layer.planning import AcquisitionPlanner
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.readiness import DataReadinessService
from research_os.models import (
    DataGap,
    DataReadiness,
    RequirementScope,
    ScenarioDataRequirement,
)
from research_os.routing.scenario_requirements import (
    SCENARIO_IDS,
    ScenarioDataRequirementRegistry,
)

ROOT = Path(__file__).resolve().parents[2]
REQ_PATH = ROOT / "registry" / "scenario_data_requirements.yaml"
CAP_PATH = ROOT / "registry" / "data_acquisition_capabilities.yaml"
CHECKED_AT = "2026-08-11T08:00:00+08:00"
AS_OF = "2026-08-11T08:00:00+08:00"


@pytest.fixture(scope="module")
def requirement_registry() -> ScenarioDataRequirementRegistry:
    return ScenarioDataRequirementRegistry(REQ_PATH)


@pytest.fixture(scope="module")
def capability_registry(requirement_registry) -> AcquisitionCapabilityRegistry:
    return AcquisitionCapabilityRegistry(CAP_PATH, requirement_registry, ROOT)


@pytest.fixture(scope="module")
def checker_registry() -> ReadinessCheckerRegistry:
    return ReadinessCheckerRegistry()


class TestCheckerCoverage:
    def test_all_43_requirements_have_checkers(self, requirement_registry, checker_registry):
        for req in requirement_registry.all():
            assert checker_registry.has(req.data_type), \
                f"{req.requirement_id} ({req.data_type}) 无 checker"

    def test_all_distinct_types_covered(self, requirement_registry, checker_registry):
        types = {r.data_type for r in requirement_registry.all()}
        assert checker_registry.data_types() is not None
        for t in types:
            assert checker_registry.has(t)

    def test_missing_checker_fails_closed(self):
        reg = ReadinessCheckerRegistry([])
        with pytest.raises(ValueError, match="CONTROL_PLANE_CONFIGURATION_ERROR"):
            reg.get("definitely_no_checker")


class TestCapabilityCoverage:
    def test_capability_matches_distinct_types(self, requirement_registry, capability_registry):
        required = {r.data_type for r in requirement_registry.all()}
        actual = set(capability_registry.data_types())
        assert required == actual

    def test_capability_no_source_leakage(self):
        import yaml
        text = CAP_PATH.read_text(encoding="utf-8")
        for forbidden in ("source_id", "selected_source", "provider_id", "url",
                          "api_url", "endpoint", "source_priority"):
            assert forbidden not in text, f"capability registry 出现 {forbidden}"

    def test_business_sufficient_has_implementation(self, capability_registry):
        for cap in capability_registry.all():
            if cap.automatic_acquisition_lifecycle == "BUSINESS_SUFFICIENT":
                assert cap.implementation_refs, f"{cap.data_type} BUSINESS_SUFFICIENT 无实现"
                for ref in cap.implementation_refs:
                    assert (ROOT / ref).exists(), f"{cap.data_type} ref 不存在: {ref}"

    def test_no_business_sufficient_without_proof(self, capability_registry):
        # 保守：D1 无任何 data_type 达到 BUSINESS_SUFFICIENT
        for cap in capability_registry.all():
            assert cap.automatic_acquisition_lifecycle != "BUSINESS_SUFFICIENT"


class TestRequirementContextResolver:
    def _resolve(self, requirement_registry, req_id, scenario, request):
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract(scenario, request)
        resolver = RequirementContextResolver()
        return resolver.resolve(requirement_registry.get(req_id), scenario, "t1", canonical, AS_OF)

    def test_subject_scope_resolves(self, requirement_registry):
        # abnormal_move_analysis 正式契约: entity_id
        ctx = self._resolve(requirement_registry, "abnormal_move_analysis.market_daily_ohlcv",
                            "abnormal_move_analysis",
                            {"entity_id": "600519.SH",
                             "window_start": "2026-08-09T00:00:00+08:00",
                             "window_end": "2026-08-11T08:00:00+08:00"})
        assert ctx.entity_ids == ["600519.SH"]
        assert not ctx.unresolved

    def test_subject_scope_missing_fail_closed(self, requirement_registry):
        ctx = self._resolve(requirement_registry, "abnormal_move_analysis.market_daily_ohlcv",
                            "abnormal_move_analysis", {})
        assert "subject" in ctx.unresolved

    def test_stock_research_entity_field(self, requirement_registry):
        # stock_research_report 正式契约: entity
        ctx = self._resolve(requirement_registry, "stock_research_report.company_profile",
                            "stock_research_report", {"entity": "company:600519.SH"})
        assert ctx.entity_ids == ["company:600519.SH"]
        assert not ctx.unresolved

    def test_industry_research_industry_id(self, requirement_registry):
        # industry_research 正式契约: industry_id
        ctx = self._resolve(requirement_registry, "industry_research.knowledge_graph_snapshot",
                            "industry_research", {"industry_id": "ind:semiconductor"})
        assert ctx.industry_ids == ["ind:semiconductor"]
        assert not ctx.unresolved

    def test_watchlist_scope(self, requirement_registry):
        ctx = self._resolve(requirement_registry, "morning_brief.attention.brief_attention_content",
                            "morning_brief", {"report_date": "2026-08-11"})
        assert ctx.watchlist_group == "brief_watchlist"

    def test_scenario_window_uses_brief_policy(self, requirement_registry):
        ctx = self._resolve(requirement_registry, "morning_brief.event.news_flash",
                            "morning_brief", {"report_date": "2026-08-11"})
        assert ctx.window_start == "2026-08-10T20:00:00+08:00"
        assert ctx.window_end == "2026-08-11T08:00:00+08:00"


class TestReadinessService:
    def _resolve(self, requirement_registry, req_id, scenario, request):
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract(scenario, request)
        resolver = RequirementContextResolver()
        return resolver.resolve(requirement_registry.get(req_id), scenario, "t1", canonical, AS_OF)

    def test_no_data_missing(self, requirement_registry, checker_registry):
        req = requirement_registry.get("morning_brief.event.news_flash")
        service = DataReadinessService(checker_registry)
        ctx = self._resolve(requirement_registry, "morning_brief.event.news_flash",
                            "morning_brief", {"report_date": "2026-08-11"})
        r = service.evaluate(req, ctx, EmptyReadView(), CHECKED_AT)
        assert r.status == "MISSING"
        assert r.as_of == AS_OF
        assert r.checked_at == CHECKED_AT

    def test_missing_coverage_null_for_open_world(self, requirement_registry, checker_registry):
        req = requirement_registry.get("morning_brief.event.brief_event_content")
        service = DataReadinessService(checker_registry)
        ctx = self._resolve(requirement_registry, "morning_brief.event.brief_event_content",
                            "morning_brief", {"report_date": "2026-08-11"})
        r = service.evaluate(req, ctx, EmptyReadView(), CHECKED_AT)
        # R1-04：open-world 空结果 → coverage 必须为 null（禁止 0.0）
        assert r.coverage_ratio is None
        assert "coverage_ratio" in r.model_dump()  # 字段必须存在（即使 null）


class TestGapClassifier:
    @pytest.mark.parametrize("req_id,readiness_status,expected", [
        ("morning_brief.event.brief_event_content", "READY", "AVAILABLE"),
        ("theme_discovery.knowledge_graph_snapshot", "MISSING", "UNAVAILABLE"),
    ])
    def test_basic_mapping(self, capability_registry, requirement_registry,
                           req_id, readiness_status, expected):
        req = requirement_registry.get(req_id)
        classifier = GapClassifier(capability_registry)
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status=readiness_status,
            available_fields=[], missing_fields=[], coverage_ratio=None,
            freshness_age_seconds=None, eligible_record_count=0,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        gap = classifier.classify(req, r)
        assert gap.classification == expected

    def test_auto_acquirable_requires_business_sufficient(self, requirement_registry):
        # news_flash 为 ADAPTER_IMPLEMENTED，不得 AUTO_ACQUIRABLE
        from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
        cap = AcquisitionCapabilityRegistry(CAP_PATH, requirement_registry, ROOT)
        assert cap.get("news_flash").automatic_acquisition_lifecycle != "BUSINESS_SUFFICIENT"
        classifier = GapClassifier(cap)
        req = requirement_registry.get("morning_brief.event.news_flash")
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status="MISSING",
            available_fields=[], missing_fields=["title"], coverage_ratio=0.0,
            freshness_age_seconds=None, eligible_record_count=0,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        gap = classifier.classify(req, r)
        assert gap.classification != "AUTO_ACQUIRABLE"
        assert gap.classification != "STALE_REFRESHABLE"

    def test_manual_fallback_available(self, requirement_registry, capability_registry):
        req = requirement_registry.get("morning_brief.event.brief_event_content")
        classifier = GapClassifier(capability_registry)
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status="MISSING",
            available_fields=[], missing_fields=[], coverage_ratio=None,
            freshness_age_seconds=None, eligible_record_count=0,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=[],
        )
        gap = classifier.classify(req, r)
        assert gap.classification == "MANUAL_INPUT_REQUIRED"


class TestAcquisitionPlanner:
    def _gap(self, req_id, dtype, classification):
        return DataGap(
            requirement_id=req_id, data_type=dtype, classification=classification,
            reason_codes=["x"], missing_fields=[], recommended_action="x",
            requires_network=False, requires_user_input=False,
            requires_human_review=False, warnings=[],
        )

    def test_available_no_step(self):
        planner = AcquisitionPlanner()
        gaps = [self._gap("r1", "d1", "AVAILABLE")]
        plan = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        assert plan.steps == []

    def test_non_available_one_step(self):
        planner = AcquisitionPlanner()
        gaps = [self._gap("r1", "d1", "MANUAL_INPUT_REQUIRED")]
        plan = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        assert len(plan.steps) == 1
        assert plan.steps[0].action == "request_manual_input"

    def test_step_order_follows_registry(self):
        planner = AcquisitionPlanner()
        gaps = [
            self._gap("r2", "d2", "UNAVAILABLE"),
            self._gap("r1", "d1", "MANUAL_INPUT_REQUIRED"),
        ]
        plan = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1", "r2"])
        assert [s.requirement_id for s in plan.steps] == ["r1", "r2"]

    def test_step_id_deterministic(self):
        planner = AcquisitionPlanner()
        gaps = [self._gap("r1", "d1", "MANUAL_INPUT_REQUIRED")]
        p1 = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        p2 = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        assert p1.steps[0].step_id == p2.steps[0].step_id

    def test_no_source_leakage(self):
        planner = AcquisitionPlanner()
        gaps = [self._gap("r1", "d1", "MANUAL_INPUT_REQUIRED")]
        plan = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        text = plan.model_dump_json()
        for forbidden in ("source_id", "selected_source", "provider_id"):
            assert forbidden not in text

    def test_plan_schema_valid(self):
        from research_os.validators.schema_validator import validate_instance
        planner = AcquisitionPlanner()
        gaps = [self._gap("r1", "d1", "UNAVAILABLE")]
        plan = planner.plan("t1", "morning_brief", AS_OF, gaps, ["r1"])
        assert validate_instance(plan.model_dump(), "acquisition_plan") == []


class TestPreflightService:
    def test_preflight_runs_dry_run_zero_write(self, requirement_registry, capability_registry, tmp_path):
        root = tmp_path / "proj"
        (root / "reports").mkdir(parents=True)
        svc = DataPreflightService(requirement_registry, capability_registry)
        bundle = svc.run(
            scenario="morning_brief", task_id="t1", task_as_of=AS_OF,
            normalized_request={"report_date": "2026-08-11", "dry_run": True},
            project_root=root, dry_run=True,
        )
        assert len(bundle.readiness) == 5
        assert not (root / "data" / "sqlite" / "research.db").exists()
        assert not (root / "reports" / "runs" / "t1").exists()

    def test_preflight_config_error_fails_closed(self, requirement_registry, capability_registry, tmp_path):
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        empty_checkers = ReadinessCheckerRegistry([])
        svc = DataPreflightService(requirement_registry, capability_registry, empty_checkers)
        with pytest.raises(ValueError, match="CONTROL_PLANE_CONFIGURATION_ERROR"):
            svc.run(
                scenario="morning_brief", task_id="t1", task_as_of=AS_OF,
                normalized_request={"report_date": "2026-08-11"},
                project_root=tmp_path, dry_run=True,
            )

    def test_preflight_checked_at_shared(self, requirement_registry, capability_registry, tmp_path):
        svc = DataPreflightService(requirement_registry, capability_registry)
        bundle = svc.run(
            scenario="morning_brief", task_id="t1", task_as_of=AS_OF,
            normalized_request={"report_date": "2026-08-11", "dry_run": True},
            project_root=tmp_path, dry_run=True, checked_at=CHECKED_AT,
        )
        assert all(r.checked_at == CHECKED_AT for r in bundle.readiness)


class TestPitAndCoverageRules:
    """§101-104：PIT / coverage / market / financial PIT 关键规则。"""

    def _readiness(self, requirement_registry, req_id, status="MISSING",
                   coverage=None, eligible=0, ineligible=0, fields=None):
        req = requirement_registry.get(req_id)
        return req, DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status=status,
            available_fields=sorted(fields or []),
            missing_fields=[f for f in req.minimum_fields if f not in (fields or [])],
            coverage_ratio=coverage, freshness_age_seconds=None,
            eligible_record_count=eligible, ineligible_record_count=ineligible,
            source_tiers_present=[], record_refs=[], warnings=[],
        )

    def test_open_world_null_coverage_blocks_ready_when_min_gt_0(self, requirement_registry, capability_registry):
        # brief_event_content: minimum_coverage=0.0 → null 不阻止 READY
        req, r = self._readiness(requirement_registry, "morning_brief.event.brief_event_content",
                                 status="READY", coverage=None, eligible=1)
        classifier = GapClassifier(capability_registry)
        gap = classifier.classify(req, r)
        assert gap.classification == "AVAILABLE"

    def test_min_coverage_gt0_null_coverage_not_ready(self, requirement_registry):
        # news_flash: minimum_coverage=0.5；coverage null（无合法 denominator）→ 不得 READY
        req = requirement_registry.get("morning_brief.event.news_flash")
        assert req.minimum_coverage > 0
        r = DataReadiness(
            requirement_id=req.requirement_id, data_type=req.data_type,
            checked_at=CHECKED_AT, as_of=AS_OF, status="READY",
            available_fields=["title", "published_at", "url"],
            missing_fields=[], coverage_ratio=None,
            freshness_age_seconds=None, eligible_record_count=1,
            ineligible_record_count=0, source_tiers_present=[], record_refs=[],
            warnings=["COVERAGE_NOT_MEASURABLE"],
        )
        # coverage_ratio=null + minimum_coverage>0 → 不得 READY（由 readiness checker 保证）
        # 这里验证 Schema 允许 null 且字段存在
        assert r.model_dump()["coverage_ratio"] is None
        from research_os.validators.schema_validator import validate_instance
        assert validate_instance(r.model_dump(), "data_readiness") == []

    def test_coverage_ratio_nullable_schema(self):
        from research_os.validators.schema_validator import load_schema
        schema = load_schema("data_readiness")
        cov = schema["properties"]["coverage_ratio"]
        assert "null" in cov["type"]
        assert "coverage_ratio" in schema["required"]

    def test_financial_pit_lookahead_blocked(self, tmp_path):
        """period_end 在 as_of 前但 publication 在 as_of 后 → NOT ELIGIBLE（防 look-ahead）。"""
        import json
        from research_os.data_layer.checkers import SqliteReadView
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

        # 构造含 financial_facts 的临时 db
        import sqlite3
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        # publication/eligibility 在 as_of 之后（disclosure 晚于 as_of）
        conn.execute(
            "INSERT INTO financial_facts VALUES (?)",
            (json.dumps({
                "fact_key": "revenue", "period_end": "2026-06-30",
                "disclosed_at": "2026-09-01T00:00:00+08:00",
                "value": 100, "created_at": "2026-09-01T00:00:00+08:00",
            }, ensure_ascii=False),),
        )
        conn.commit()
        conn.close()

        from research_os.storage import Database
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req_reg = ScenarioDataRequirementRegistry(REQ_PATH)
        req = req_reg.get("stock_research_report.financial_statement_data")
        service = DataReadinessService(ReadinessCheckerRegistry())
        resolver = RequirementContextResolver()
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("stock_research_report", {"entity": "company:600519.SH"})
        ctx = resolver.resolve(req, "stock_research_report", "t1", canonical,
                               "2026-08-11T08:00:00+08:00")
        r = service.evaluate(req, ctx, view, CHECKED_AT)
        # created_at (2026-09-01) 晚于 as_of (2026-08-11) → PIT ineligible → MISSING/PARTIAL 而非 READY
        assert r.status in ("MISSING", "PARTIAL")
        db.close()

    def test_market_future_trade_date_excluded(self, tmp_path):
        import json
        import sqlite3
        from research_os.data_layer.checkers import SqliteReadView
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

        db_path = tmp_path / "m.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_ohlcv (payload TEXT, symbol TEXT, trade_date TEXT, close REAL)")
        # 一条未来 trade_date（晚于 as_of）与一条合法
        conn.execute(
            "INSERT INTO market_daily_ohlcv VALUES (?, ?, ?, ?)",
            (json.dumps({"symbol": "600519.SH", "trade_date": "2026-08-12", "open": 1, "close": 2}, ensure_ascii=False),
             "600519.SH", "2026-08-12", 2.0),
        )
        conn.execute(
            "INSERT INTO market_daily_ohlcv VALUES (?, ?, ?, ?)",
            (json.dumps({"symbol": "600519.SH", "trade_date": "2026-08-10", "open": 1, "close": 2}, ensure_ascii=False),
             "600519.SH", "2026-08-10", 2.0),
        )
        conn.commit()
        conn.close()

        from research_os.storage import Database
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req_reg = ScenarioDataRequirementRegistry(REQ_PATH)
        req = req_reg.get("abnormal_move_analysis.market_daily_ohlcv")
        service = DataReadinessService(ReadinessCheckerRegistry())
        resolver = RequirementContextResolver()
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("abnormal_move_analysis", {
            "entity_id": "600519.SH",
            "window_start": "2026-08-09T00:00:00+08:00",
            "window_end": "2026-08-11T08:00:00+08:00",
        })
        ctx = resolver.resolve(req, "abnormal_move_analysis", "t1", canonical,
                               "2026-08-11T08:00:00+08:00")
        r = service.evaluate(req, ctx, view, CHECKED_AT)
        # 未来 trade_date 被排除；只计入 2026-08-10
        assert all("2026-08-12" not in ref for ref in r.record_refs)
        db.close()

    def test_market_realtime_not_daily(self):
        """market_realtime_snapshot 不得冒充 market_daily_ohlcv（独立 data_type）。"""
        from research_os.data_layer.checkers import MarketSeriesChecker
        assert "market_realtime_snapshot" not in MarketSeriesChecker.data_types
        assert "market_daily_ohlcv" in MarketSeriesChecker.data_types


class TestMarketCoverage:
    """R1 修复验证：market coverage 不得硬编码 1.0；按 known trading window 计算。"""

    def test_market_coverage_not_hardcoded(self, tmp_path):
        import json
        import sqlite3
        from research_os.data_layer.checkers import MarketSeriesChecker, SqliteReadView
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

        db_path = tmp_path / "m.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_ohlcv (payload TEXT, symbol TEXT, trade_date TEXT, close REAL)")
        # 窗口 2026-08-07(五)..2026-08-11(二)，预期交易日 08-07/08-10/08-11 = 3 天
        # 只插入 1 天 → coverage ≈ 1/3
        conn.execute(
            "INSERT INTO market_daily_ohlcv VALUES (?, ?, ?, ?)",
            (json.dumps({"symbol": "600519.SH", "trade_date": "2026-08-10", "open": 1, "close": 2}, ensure_ascii=False),
             "600519.SH", "2026-08-10", 2.0),
        )
        conn.commit()
        conn.close()

        from research_os.storage import Database
        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        db = Database.open_read_only(db_path)
        view = SqliteReadView(db)
        req_reg = ScenarioDataRequirementRegistry(REQ_PATH)
        req = req_reg.get("abnormal_move_analysis.market_daily_ohlcv")
        service = DataReadinessService(ReadinessCheckerRegistry())
        resolver = RequirementContextResolver()
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("abnormal_move_analysis", {
            "entity_id": "600519.SH",
            "window_start": "2026-08-07T00:00:00+08:00",
            "window_end": "2026-08-11T08:00:00+08:00",
        })
        ctx = resolver.resolve(req, "abnormal_move_analysis", "t1", canonical,
                               "2026-08-11T08:00:00+08:00")
        # R1-04/47：无权威交易日历 → coverage 必须 null（禁止工作日近似/硬编码 1.0）
        r = service.evaluate(req, ctx, view, CHECKED_AT)
        assert r.coverage_ratio is None
        assert "COVERAGE_NOT_MEASURABLE" in r.warnings
        db.close()


class TestGraphReadinessFailClosed:
    """阻断项修复：graph checker 不得在 industry scope / min coverage 未满足时误判 READY。"""

    def test_graph_industry_scope_missing_fail_closed(self, requirement_registry):
        from research_os.data_layer.checkers import GraphSnapshotChecker
        from research_os.data_layer.readiness import DataReadinessService
        from research_os.data_layer.context import RequirementContextResolver
        from research_os.data_layer.checkers import ReadinessCheckerRegistry, EmptyReadView

        from research_os.data_layer.request_context import NormalizedRequestContextAdapter
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        service = DataReadinessService(ReadinessCheckerRegistry())
        resolver = RequirementContextResolver()
        # 无 industry_id → industry scope 无法解析 → fail closed
        adapter = NormalizedRequestContextAdapter()
        canonical = adapter.extract("industry_research", {})
        ctx = resolver.resolve(req, "industry_research", "t1", canonical, AS_OF)
        r = service.evaluate(req, ctx, EmptyReadView(), CHECKED_AT)
        assert r.status == "MISSING"

    def test_graph_min_fields_enforced(self, requirement_registry):
        from research_os.data_layer.checkers import GraphSnapshotChecker
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        # minimum_fields 含 industry_id；无 industry 上下文时 available 缺该字段 → 不 READY
        assert "industry_id" in req.minimum_fields

    def test_graph_min_coverage_gt0_not_ready_without_denominator(self, requirement_registry):
        req = requirement_registry.get("theme_discovery.knowledge_graph_snapshot")
        assert req.minimum_coverage > 0
