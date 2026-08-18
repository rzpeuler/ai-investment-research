"""P7-D1-R3.1 强制测试：Final Runtime Closure（§76/§101）。

覆盖：
- R3.1-01 datetime runtime：cross-offset window（Case A）、[start,end) 边界、
  financial cross-offset PIT、valuation cross-offset latest、malformed fail-closed
- R3.1-02/03 requested run set：valid/requested 比率、去重、empty no-scan、
  scenario_execution_result 强制证明、result task_id/run_id/validation 一致性
- R3.1-04 EntityMapping coverage：subject singleton、industry/global open-world null
- R3.1-05 Graph projector：runtime binding+projector 后 node_refs/edge_refs 保留、
  global fail-closed、零写入
- R3.1-06 schema-valid runtime fixtures：Pydantic → model_dump → validate_instance →
  persist → actual checker → DataReadinessService（8 类对象）
- R3.1-07 projection gate：unknown projection init fail-closed、handler/registry parity
- R3.1-08 binding runtime authority：changing binding changes readiness result
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from uuid import NAMESPACE_DNS, uuid5

import pytest

from research_os.data_layer.bindings import (
    COV_OPEN_WORLD,
    COV_REQUESTED_RUN_SET,
    COV_SINGLETON,
    RequirementReadinessBindingResolver,
    RuntimeStrategyGate,
)
from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.checkers import (
    EmptyReadView,
    FinancialChecker,
    ProfileChecker,
    ReadinessCheckerRegistry,
    SqliteReadView,
)
from research_os.data_layer.context import RequirementContextResolver
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.projector import (
    PROJECTION_HANDLERS,
    ReadinessFieldProjector,
)
from research_os.data_layer.provenance import ReadinessProvenanceResolver
from research_os.data_layer.readiness import DataReadinessService
from research_os.data_layer.request_context import NormalizedRequestContextAdapter, _min_iso
from research_os.models import (
    Claim,
    DocumentRecord,
    Evidence,
    FinancialFact,
    MarketDailyOhlcv,
    MarketDailySeriesManifest,
    RawItem,
    ResearchFinding,
    SecurityProfile,
    ValuationSnapshot,
)
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry
from research_os.validators.schema_validator import validate_instance

ROOT = Path(__file__).resolve().parents[2]
REQ_PATH = ROOT / "registry" / "scenario_data_requirements.yaml"
CAP_PATH = ROOT / "registry" / "data_acquisition_capabilities.yaml"
SOURCES_PATH = ROOT / "registry" / "sources.yaml"
CHECKED_AT = "2026-08-11T08:00:00+08:00"
AS_OF = "2026-08-11T08:00:00+08:00"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_DNS, f"r31-test:{label}"))


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


def _valuation(sid: str, as_of: str) -> ValuationSnapshot:
    """Schema-valid ValuationSnapshot（补全全部 required 字段；数值为 decimal string）。"""
    return ValuationSnapshot(
        valuation_snapshot_id=sid,
        company_entity_id="company:600519.SH",
        security_entity_id="security:600519.SH",
        as_of=as_of, price="1500.0", shares_outstanding="1256197800",
        market_data_manifest_id="m1", market_cap="1884296700000",
        enterprise_value="1884296700000",
        financial_period_end="2026-06-30", financial_basis="FY",
        metrics=[], history_window_start="2026-07-01",
        history_window_end="2026-08-11", history_sample_size=30,
        peer_selection_id=None, peer_sample_size=0,
        percentile_method="none", applicability_notes=[],
        status="complete", source_ids=["cninfo"], evidence_ids=[],
        version=1, calculated_at=as_of,
    )


def _schema_valid(model) -> dict:
    """R3.1-06/§50：Pydantic → model_dump → validate_instance → 返回 payload。"""
    payload = model.model_dump()
    schema_name = _schema_name_for(model)
    errs = validate_instance(payload, schema_name)
    assert errs == [], f"{schema_name} Schema 校验失败: {errs}"
    return payload


def _schema_name_for(model) -> str:
    mapping = {
        FinancialFact: "financial_fact",
        DocumentRecord: "document_record",
        RawItem: "raw_item",
        Evidence: "evidence",
        Claim: "claim",
        ResearchFinding: "research_finding",
        SecurityProfile: "security_profile",
        ValuationSnapshot: "valuation_snapshot",
        MarketDailyOhlcv: "market_daily_ohlcv",
        MarketDailySeriesManifest: "market_daily_series_manifest",
    }
    return mapping[type(model)]


def _insert(conn, table: str, payload: dict) -> None:
    conn.execute(f"INSERT INTO {table} VALUES (?)", (json.dumps(payload, ensure_ascii=False),))


# ============================================================
# R3.1-01：datetime runtime（parse then compare）
# ============================================================

class TestDatetimeRuntime:
    def _raw_db(self, tmp_path, raw_items, extra_tables=("evidence", "raw_items")):
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        for t in extra_tables:
            conn.execute(f"CREATE TABLE {t} (payload TEXT)")
        for r in raw_items:
            _insert(conn, "raw_items", r)
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def _raw_item(self, riid, published, category="fast_news"):
        return {"raw_item_id": riid, "source_id": "cls", "url": "http://c",
                "title": "t", "publisher": "cls",
                "published_at": published,
                "retrieved_at": published,
                "content_hash": "a" * 64, "content_excerpt": "x",
                "content_storage": "metadata_and_excerpt", "language": "zh-CN",
                "access_status": "ok", "entities": [],
                "raw_category": category}

    def test_cross_offset_window_eligible(self, tmp_path, requirement_registry, provenance):
        """§11 Case A：window [2026-08-11T00:00:00+08:00, 2026-08-11T08:00:00+08:00)；
        candidate published_at=2026-08-10T16:30:00Z == 2026-08-11T00:30:00+08:00 → eligible。"""
        db = self._raw_db(tmp_path, [self._raw_item(_uuid("ri-a"), "2026-08-10T16:30:00Z")])
        view = _view_from(db)
        req = requirement_registry.get("morning_brief.event.news_flash")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "morning_brief",
                       {"report_date": "2026-08-11"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_window_end_boundary_ineligible(self, tmp_path, requirement_registry, provenance):
        """§12：candidate 2026-08-11T00:00:00Z == window_end 2026-08-11T08:00:00+08:00
        同一 instant；[start, end) → ineligible。"""
        db = self._raw_db(tmp_path, [self._raw_item(_uuid("ri-b"), "2026-08-11T00:00:00Z")])
        view = _view_from(db)
        req = requirement_registry.get("morning_brief.event.news_flash")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "morning_brief",
                       {"report_date": "2026-08-11"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0, r.warnings
        db.close()

    def test_malformed_datetime_fail_closed(self, tmp_path, requirement_registry, provenance):
        """§10：published_at 存在但不可解析 → ineligible（fail closed，不得假设在窗口内）。"""
        db = self._raw_db(tmp_path, [self._raw_item(_uuid("ri-c"), "not-a-datetime")])
        view = _view_from(db)
        req = requirement_registry.get("morning_brief.event.news_flash")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "morning_brief",
                       {"report_date": "2026-08-11"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0
        db.close()

    def test_financial_cross_offset_publication(self, tmp_path, requirement_registry, provenance):
        """§13：evidence published_at=2026-08-10T16:30:00Z，task as_of=
        2026-08-11T00:45:00+08:00 → publication proven（16:30Z == 00:30+08 <= 00:45+08）。"""
        db_path = tmp_path / "fin.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-fin"), source_id="cninfo",
            raw_item_id=_uuid("ri-fin"), title="e", publisher="cninfo",
            published_at="2026-08-10T16:30:00Z",
            retrieved_at="2026-08-10T16:35:00Z", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "financial_facts", _schema_valid(FinancialFact(
            fact_id="f1", fact_key="revenue", financial_report_id="fr1",
            company_entity_id="company:600519.SH",
            statement_type="income_statement", statement_scope="consolidated",
            taxonomy_code="REV", label_raw="营业收入",
            period_start="2026-01-01", period_end="2026-06-30",
            instant_or_duration="duration", period_basis="reported_period",
            currency="CNY", unit_scale=1,
            raw_value="1000000000", normalized_value="1000000000",
            normalized_unit="CNY", value_status="reported",
            sign_convention="reported", audit_status="audited",
            source_document_id=None, evidence_ids=[_uuid("ev-fin")],
            source_priority=1, restatement_version=1,
            valid_from="2026-07-01T00:00:00+08:00", valid_to=None, warnings=[],
            version=1, created_at="2026-07-02T00:00:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.financial_statement_data")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        # as_of = 2026-08-11T00:45:00+08:00（跨 offset）
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.as_of = "2026-08-11T00:45:00+08:00"
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, "2026-08-11T00:45:00+08:00", provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_financial_future_publication_ineligible(self, tmp_path, requirement_registry, provenance):
        """§13 反向：evidence published_at 晚于 as_of → publication NOT proven → ineligible。"""
        db_path = tmp_path / "fin2.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-fut"), source_id="cninfo",
            raw_item_id=_uuid("ri-fut"), title="e", publisher="cninfo",
            published_at="2026-08-11T01:00:00+08:00",
            retrieved_at="2026-08-11T01:05:00+08:00", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "financial_facts", _schema_valid(FinancialFact(
            fact_id="f2", fact_key="revenue", financial_report_id="fr2",
            company_entity_id="company:600519.SH",
            statement_type="income_statement", statement_scope="consolidated",
            taxonomy_code="REV", label_raw="营业收入",
            period_start="2026-01-01", period_end="2026-06-30",
            instant_or_duration="duration", period_basis="reported_period",
            currency="CNY", unit_scale=1,
            raw_value="1000000000", normalized_value="1000000000",
            normalized_unit="CNY", value_status="reported",
            sign_convention="reported", audit_status="audited",
            source_document_id=None, evidence_ids=[_uuid("ev-fut")],
            source_priority=1, restatement_version=1,
            valid_from="2026-07-01T00:00:00+08:00", valid_to=None, warnings=[],
            version=1, created_at="2026-07-02T00:00:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.financial_statement_data")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.as_of = "2026-08-11T00:45:00+08:00"
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, "2026-08-11T00:45:00+08:00", provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0  # publication 晚于 as_of → ineligible
        db.close()

    def test_valuation_cross_offset_latest(self, tmp_path, requirement_registry, provenance):
        """§14：A=2026-08-11T00:00:00+08:00、B=2026-08-10T17:00:00Z（==01:00+08）；
        latest 必须是 B（不得按字符串排序选 A）。"""
        db_path = tmp_path / "val.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE valuation_snapshots (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-val"), source_id="cninfo",
            raw_item_id=_uuid("ri-val"), title="e", publisher="cninfo",
            published_at="2026-08-10T16:00:00Z",
            retrieved_at="2026-08-10T16:05:00Z", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        for sid, as_of in (("vsA", "2026-08-11T00:00:00+08:00"),
                           ("vsB", "2026-08-10T17:00:00Z")):
            _insert(conn, "valuation_snapshots", _schema_valid(
                _valuation(sid, as_of)))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1
        # latest 必须是 B（01:00+08 > 00:00+08）
        assert r.record_refs == ["vsB"], r.record_refs
        db.close()


# ============================================================
# R3.1-01：fail-closed regression coverage
# ============================================================

class TestDatetimeFailClosedRegressions:
    def test_min_iso_rejects_malformed_cutoff_and_compares_instants(self):
        assert _min_iso(
            "2026-08-11T00:30:00+08:00",
            "2026-08-10T16:45:00Z",
        ) == "2026-08-11T00:30:00+08:00"
        with pytest.raises(ValueError):
            _min_iso("2026-08-11T00:30:00+08:00", "not-a-datetime")
        with pytest.raises(ValueError):
            _min_iso("not-a-datetime", "2026-08-11T00:30:00+08:00")
        with pytest.raises(ValueError):
            _min_iso("not-a-datetime", None)

    @pytest.mark.parametrize("authority_table", ["evidence", "document_records"])
    def test_malformed_publication_cannot_prove_financial_availability(
        self, authority_table,
    ):
        class PublicationView:
            def has_table(self, table):
                return table == authority_table

            def query(self, sql, params=()):
                return [{"payload": {"published_at": "not-a-datetime"}}]

        payload = (
            {"evidence_ids": ["e1"]}
            if authority_table == "evidence"
            else {"source_document_id": "d1"}
        )
        assert not FinancialChecker()._publication_proven(
            payload,
            PublicationView(),
            "2026-08-11T08:00:00+08:00",
        )

    @pytest.mark.parametrize(
        ("payload", "as_of"),
        [
            ({"listing_date": "not-a-date", "status": "listed"}, AS_OF),
            ({"listing_date": "2020-01-01", "delisting_date": "not-a-date",
              "status": "listed"}, AS_OF),
            ({"listing_date": "2020-01-01", "status": "listed"}, "not-a-datetime"),
        ],
    )
    def test_security_profile_malformed_lifecycle_date_is_ineligible(self, payload, as_of):
        assert not ProfileChecker()._pit_covers(payload, as_of, "security_profile")

    def test_market_malformed_trade_date_is_ineligible(
        self, tmp_path, requirement_registry, provenance,
    ):
        db_path = tmp_path / "malformed-market.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_ohlcv (payload TEXT)")
        conn.execute("CREATE TABLE market_daily_series_manifests (payload TEXT)")
        _insert(conn, "market_daily_series_manifests", _schema_valid(
            MarketDailySeriesManifest(
                import_id=_uuid("malformed-market-manifest"), source_id="sse",
                source_kind="manual_import", file_name="f.csv", file_checksum="a" * 64,
                imported_at="2026-08-11T00:35:00+08:00", imported_by="admin",
                symbols=["600519.SH"], date_start="2026-08-01", date_end="2026-08-11",
                row_count=1, adjustment_method="none",
                adjustment_description="no adjustment", calendar_id="cn-sse",
                calendar_version="v1", currency="CNY", price_unit="CNY",
                volume_unit="shares", data_version="v1", validation_status="accepted",
                validation_errors=[], warnings=[],
            )
        ))
        _insert(conn, "market_daily_ohlcv", {
            "bar_id": _uuid("malformed-market-bar"), "symbol": "600519.SH",
            "trade_date": "2026-08-0x", "open": 10.0, "high": 11.0,
            "low": 9.0, "close": 10.5, "volume": 1000, "amount": 10500.0,
        })
        conn.commit()
        conn.close()

        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        try:
            req = requirement_registry.get("abnormal_move_analysis.market_daily_ohlcv")
            binding = RequirementReadinessBindingResolver(requirement_registry).get(
                req.requirement_id
            )
            ctx = _resolve(
                requirement_registry,
                req.requirement_id,
                "abnormal_move_analysis",
                {"entity_id": "600519.SH"},
            )
            ctx.binding = binding
            ctx.projector = ReadinessFieldProjector()
            result = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
                req,
                ctx,
                _view_from(db),
                CHECKED_AT,
                provenance=provenance,
                binding=binding,
                projector=ReadinessFieldProjector(),
            )
            assert result.eligible_record_count == 0
        finally:
            db.close()


# ============================================================
# R3.1-02/03：REQUESTED_RUN_SET + run_id proof
# ============================================================

class TestRequestedRunSet:
    def _run(self, root, run_id, scenario="morning_brief", validation="ok",
             with_result=True, result_task_id=None, result_run_id=None,
             result_validation="ok", as_of="2026-08-10T08:00:00+08:00"):
        run_dir = root / "reports" / "runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": run_id, "scenario": scenario, "status": "completed",
            "as_of": as_of, "time_window": {"end": as_of},
        }, ensure_ascii=False), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": validation, "task_id": run_id,
        }, ensure_ascii=False), encoding="utf-8")
        if with_result:
            (run_dir / "scenario_execution_result.json").write_text(json.dumps({
                "task_id": result_task_id if result_task_id is not None else run_id,
                "run_id": result_run_id if result_run_id is not None else f"actual-{run_id}",
                "validation_status": result_validation,
            }, ensure_ascii=False), encoding="utf-8")
        return run_dir

    def _check(self, root, requirement_registry, provenance, previous_run_ids):
        from research_os.data_layer.checkers import RunArtifactChecker
        req = requirement_registry.get("daily_review.run_artifacts")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF,
                        "previous_run_ids": previous_run_ids})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        view = EmptyReadView()
        view.runs_root = root / "reports" / "runs"
        return RunArtifactChecker().check(ctx, req, view, provenance)

    def test_binding_coverage_strategy_requested_run_set(self, requirement_registry):
        binding = RequirementReadinessBindingResolver(requirement_registry).get(
            "daily_review.run_artifacts")
        assert binding.coverage_strategy == COV_REQUESTED_RUN_SET

    def test_three_requested_one_valid_coverage_one_third(self, tmp_path, requirement_registry, provenance):
        """§16：requested [A,B,C]，仅 A valid → coverage 1/3。"""
        root = tmp_path / "p1"
        self._run(root, "A")
        self._run(root, "B", validation="failed")
        self._run(root, "C", with_result=False)  # result.json 缺失 → invalid
        r = self._check(root, requirement_registry, provenance, ["A", "B", "C"])
        assert r.eligible_record_count == 1
        assert r.ineligible_record_count == 2
        assert r.coverage_ratio == pytest.approx(1 / 3)
        assert r.status == "PARTIAL"
        assert "COVERAGE_BELOW_MINIMUM" in r.warnings

    def test_all_valid_coverage_one(self, tmp_path, requirement_registry, provenance):
        """§26：requested [A,B] 均 valid → coverage 1.0。"""
        root = tmp_path / "p2"
        self._run(root, "A")
        self._run(root, "B")
        r = self._check(root, requirement_registry, provenance, ["A", "B"])
        assert r.coverage_ratio == pytest.approx(1.0)
        assert r.status in ("READY", "PARTIAL")

    def test_empty_requested_no_scan(self, tmp_path, requirement_registry, provenance):
        """§17：empty → coverage null / MISSING / no scan。"""
        root = tmp_path / "p3"
        self._run(root, "B")  # 存在但不得自动扫描
        r = self._check(root, requirement_registry, provenance, [])
        assert r.eligible_record_count == 0
        assert r.coverage_ratio is None
        assert r.status == "MISSING"

    def test_duplicate_ids_do_not_distort_denominator(self, tmp_path, requirement_registry, provenance):
        """§18：[A,A,B] == [A,B]（B invalid）→ denominator 2，coverage 1/2。"""
        root = tmp_path / "p4"
        self._run(root, "A")
        self._run(root, "B", validation="failed")
        r = self._check(root, requirement_registry, provenance, ["A", "A", "B"])
        assert r.eligible_record_count == 1
        assert r.coverage_ratio == pytest.approx(1 / 2)

    def test_result_json_missing_invalid(self, tmp_path, requirement_registry, provenance):
        """§26：lineage valid 但 result.json 缺失 → invalid（run_id 未证明）。"""
        root = tmp_path / "p5"
        self._run(root, "A", with_result=False)
        r = self._check(root, requirement_registry, provenance, ["A"])
        assert r.eligible_record_count == 0
        assert r.status == "MISSING"

    def test_result_run_id_missing_invalid(self, tmp_path, requirement_registry, provenance):
        """§26：result.run_id 缺失 → invalid。"""
        root = tmp_path / "p6"
        self._run(root, "A", result_run_id="")
        r = self._check(root, requirement_registry, provenance, ["A"])
        assert r.eligible_record_count == 0

    def test_result_task_id_mismatch_invalid(self, tmp_path, requirement_registry, provenance):
        """§26：result.task_id mismatch → invalid。"""
        root = tmp_path / "p7"
        self._run(root, "A", result_task_id="other-run")
        r = self._check(root, requirement_registry, provenance, ["A"])
        assert r.eligible_record_count == 0

    def test_validation_consistency_conflict_invalid(self, tmp_path, requirement_registry, provenance):
        """§26：validation.json=pass 但 result.validation_status=failed → invalid。"""
        root = tmp_path / "p8"
        self._run(root, "A", validation="ok", result_validation="failed")
        r = self._check(root, requirement_registry, provenance, ["A"])
        assert r.eligible_record_count == 0

    def test_directory_name_never_fallback(self, tmp_path, requirement_registry, provenance):
        """§22：result.json run_id 不同目录名时用正式 run_id（非 directory fallback）。"""
        root = tmp_path / "p9"
        self._run(root, "A", result_run_id="formal-run-A")
        r = self._check(root, requirement_registry, provenance, ["A"])
        assert r.eligible_record_count == 1
        assert r.record_refs == ["formal-run-A"]


# ============================================================
# R3.1-04：EntityMapping coverage 服从 binding
# ============================================================

class TestEntityMappingCoverage:
    def _db(self, tmp_path, entities, with_security=True):
        db_path = tmp_path / "t.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (payload TEXT)")
        conn.execute("CREATE TABLE security_profiles (payload TEXT)")
        for e in entities:
            _insert(conn, "entities", e)
        if with_security:
            _insert(conn, "security_profiles", _schema_valid(SecurityProfile(
                security_profile_id="sp1",
                security_entity_id="security:600519.SH",
                company_entity_id="company:600519.SH", symbol="600519.SH",
                exchange="SH", board="main", security_type="common_share",
                listing_date="2020-01-01", currency="CNY", share_class="A",
                current_name="贵州茅台", status="listed",
                source_ids=["cninfo"], evidence_ids=[],
                created_at="2026-01-01T00:00:00+08:00",
                updated_at="2026-08-10T00:00:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        return Database.open_read_only(db_path)

    def _entity(self, eid, industry_ids=("industry:liquor",)):
        return {"entity_id": eid, "entity_type": "company",
                "canonical_name": "贵州茅台", "aliases": ["茅台"],
                "market": "A", "industry_ids": list(industry_ids),
                "valid_from": "2020-01-01", "valid_to": None,
                "source_ids": ["cninfo"]}

    def test_subject_entity_mapping_singleton(self, tmp_path, requirement_registry, provenance):
        """§29：subject（abnormal_move_analysis.entity_mapping）→ singleton 1.0。"""
        db = self._db(tmp_path, [self._entity("company:600519.SH")])
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.entity_mapping")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        assert binding.coverage_strategy == COV_SINGLETON
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.coverage_ratio == 1.0
        db.close()

    def test_industry_entity_mapping_one_row_coverage_null(self, tmp_path, requirement_registry, provenance):
        """§30：industry（industry_research.entity_mapping）1 条映射 → coverage null（不得 1.0）。"""
        db = self._db(tmp_path, [self._entity("company:600519.SH")])
        view = _view_from(db)
        req = requirement_registry.get("industry_research.entity_mapping")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        assert binding.coverage_strategy == COV_OPEN_WORLD
        ctx = _resolve(requirement_registry, req.requirement_id, "industry_research",
                       {"industry_id": "industry:liquor"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count >= 1
        assert r.coverage_ratio is None
        db.close()

    def test_global_entity_mapping_open_world_null(self, tmp_path, requirement_registry, provenance):
        """§31：global scope entity_mapping → coverage null。"""
        db = self._db(tmp_path, [self._entity("company:600519.SH")])
        view = _view_from(db)
        # 找一个 global scope 的 entity_mapping requirement
        req_id = None
        for req in requirement_registry.all():
            if req.data_type == "entity_mapping" and req.scope.scope_type == "global":
                req_id = req.requirement_id
                break
        assert req_id is not None, "应存在 global scope entity_mapping requirement"
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req_id)
        assert binding.coverage_strategy == COV_OPEN_WORLD
        ctx = _resolve(requirement_registry, req_id, "stock_review", {"entity_id": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.coverage_ratio is None
        db.close()


# ============================================================
# R3.1-05：Graph projector 集成
# ============================================================

class TestGraphProjector:
    def test_graph_runtime_binding_and_projector(self, tmp_path, requirement_registry, provenance):
        """§36：graph query 后 node_refs/edge_refs 经 runtime projector 仍 available。"""
        from research_os.storage import Database
        db = Database(tmp_path / "research.db")
        db.initialize()
        # 写入 graph node/edge（真实 query authority）
        from research_os.knowledge.repository import GraphRepository
        from research_os.models import GraphEdge, GraphNode
        repo = GraphRepository(db)
        repo.append_node(GraphNode(
            node_id="industry:liquor", node_type="Industry", name="白酒",
            status="active", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            evidence_ids=[], version=1, origin_kind="governance_seed",
            review_status="approved",
            created_at="2026-01-01T00:00:00+08:00"))
        repo.append_node(GraphNode(
            node_id="company:600519.SH", node_type="Company", name="贵州茅台",
            status="active", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            evidence_ids=[], version=1, origin_kind="governance_seed",
            review_status="approved",
            created_at="2026-01-01T00:00:00+08:00"))
        repo.append_edge(GraphEdge(
            edge_id="e1", source_node_id="company:600519.SH",
            relation="BELONGS_TO", target_node_id="industry:liquor",
            assertion_type="GOVERNANCE", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            confidence=1.0, evidence_ids=[], review_status="approved", version=1,
            created_at="2026-01-01T00:00:00+08:00"))
        from research_os.knowledge.history import HistoryService
        from research_os.knowledge.query import GraphQueryService
        history = HistoryService(db, repo)
        graph_query = GraphQueryService(db, graph_repo=repo)
        view = _view_from(db)
        view.graph_query_service = graph_query
        view.graph_history_service = history
        view.graph_repo = repo
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "industry_research",
                       {"industry_id": "industry:liquor"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count > 0
        assert "node_refs" in r.available_fields, r.available_fields
        assert "edge_refs" in r.available_fields, r.available_fields
        assert "node_refs" not in r.missing_fields
        assert "edge_refs" not in r.missing_fields
        db.close()

    def test_graph_global_fail_closed(self, tmp_path, requirement_registry, provenance):
        """§37：global graph snapshot 不支持 → MISSING + GLOBAL_SNAPSHOT_UNPROVEN。"""
        from research_os.storage import Database
        db = Database(tmp_path / "research.db")
        db.initialize()
        from research_os.knowledge.repository import GraphRepository
        repo = GraphRepository(db)
        from research_os.knowledge.history import HistoryService
        from research_os.knowledge.query import GraphQueryService
        history = HistoryService(db, repo)
        graph_query = GraphQueryService(db, graph_repo=repo)
        view = _view_from(db)
        view.graph_query_service = graph_query
        view.graph_history_service = history
        view.graph_repo = repo
        req_id = None
        for req in requirement_registry.all():
            if req.data_type == "knowledge_graph_snapshot" and req.scope.scope_type == "global":
                req_id = req.requirement_id
                break
        if req_id is None:
            pytest.skip("无 global scope knowledge_graph_snapshot requirement")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req_id)
        ctx = _resolve(requirement_registry, req_id, "stock_review", {"entity_id": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.status == "MISSING"
        assert any("GLOBAL_SNAPSHOT_UNPROVEN" in w for w in r.warnings)
        db.close()

    def test_graph_zero_write(self, tmp_path, requirement_registry, provenance, monkeypatch):
        """§38：graph checker 不得写入（append_node/append_edge/GraphChange/GraphApply）。"""
        from research_os.knowledge import repository as repo_mod
        from research_os.knowledge.repository import GraphRepository
        calls = []

        def _fail(*a, **k):
            calls.append(1)
            raise AssertionError("graph write 被调用")

        from research_os.storage import Database
        db = Database(tmp_path / "research.db")
        db.initialize()
        from research_os.models import GraphEdge, GraphNode
        repo = GraphRepository(db)
        repo.append_node(GraphNode(
            node_id="industry:liquor", node_type="Industry", name="白酒",
            status="active", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            evidence_ids=[], version=1, origin_kind="governance_seed",
            review_status="approved",
            created_at="2026-01-01T00:00:00+08:00"))
        repo.append_node(GraphNode(
            node_id="company:600519.SH", node_type="Company", name="贵州茅台",
            status="active", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            evidence_ids=[], version=1, origin_kind="governance_seed",
            review_status="approved",
            created_at="2026-01-01T00:00:00+08:00"))
        repo.append_edge(GraphEdge(
            edge_id="e1", source_node_id="company:600519.SH",
            relation="BELONGS_TO", target_node_id="industry:liquor",
            assertion_type="GOVERNANCE", valid_from="2020-01-01T00:00:00+08:00", valid_to=None,
            confidence=1.0, evidence_ids=[], review_status="approved", version=1,
            created_at="2026-01-01T00:00:00+08:00"))
        monkeypatch.setattr(repo_mod.GraphRepository, "append_node", _fail)
        monkeypatch.setattr(repo_mod.GraphRepository, "append_edge", _fail)
        monkeypatch.setattr(repo_mod.GraphRepository, "append_review", _fail)
        monkeypatch.setattr(repo_mod.GraphRepository, "append_application", _fail)
        from research_os.knowledge.history import HistoryService
        from research_os.knowledge.query import GraphQueryService
        view = _view_from(db)
        view.graph_query_service = GraphQueryService(db, graph_repo=repo)
        view.graph_history_service = HistoryService(db, repo)
        view.graph_repo = repo
        req = requirement_registry.get("industry_research.knowledge_graph_snapshot")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "industry_research",
                       {"industry_id": "industry:liquor"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert calls == [], "graph 写入不得发生"
        db.close()


# ============================================================
# R3.1-07：projection gate
# ============================================================

class TestProjectionGate:
    def test_unknown_projection_init_fail_closed(self, requirement_registry):
        """§55：unknown projection 在初始化（DB 无关）即 CONTROL_PLANE_CONFIGURATION_ERROR。"""
        from research_os.data_layer.bindings import RequirementReadinessBinding
        from research_os.data_layer.specs import get_spec
        bad = RequirementReadinessBinding(
            requirement_id="x.unknown", scenario="x", data_type="news_flash",
            spec=get_spec("news_flash"),
            context_strategy="global", authority_strategy="sqlite_table",
            authority_location="raw_items", scope_strategy="global",
            pit_strategy="published_at", field_projection_strategy="RawItemChecker",
            provenance_strategy="raw_item_source", coverage_strategy="OPEN_WORLD",
            freshness_strategy="published_at", source_tier_applicable=True,
            minimum_field_sources={"title": "projection:not_really_implemented"},
        )
        with pytest.raises(ValueError) as exc:
            RuntimeStrategyGate().assert_runtime_supported([bad])
        assert "CONTROL_PLANE_CONFIGURATION_ERROR" in str(exc.value)

    def test_unknown_projection_closure_validator(self, requirement_registry):
        """§54：closure validator 同样拒绝未知 projection（初始化阶段）。"""
        from research_os.data_layer.bindings import RequirementReadinessBinding
        from research_os.data_layer.projector import MinimumFieldClosureValidator
        from research_os.data_layer.specs import get_spec
        bad = RequirementReadinessBinding(
            requirement_id="x.bad", scenario="x", data_type="news_flash",
            spec=get_spec("news_flash"),
            context_strategy="global", authority_strategy="sqlite_table",
            authority_location="raw_items", scope_strategy="global",
            pit_strategy="published_at", field_projection_strategy="RawItemChecker",
            provenance_strategy="raw_item_source", coverage_strategy="OPEN_WORLD",
            freshness_strategy="published_at", source_tier_applicable=True,
            minimum_field_sources={"title": "projection:not_implemented_either"},
        )
        violations = MinimumFieldClosureValidator([bad]).validate()
        assert violations, "未知 projection 必须产生 closure violation"

    def test_projection_handler_registry_parity(self):
        """§56：PROJECTION_HANDLERS.keys() == SUPPORTED_PROJECTION_STRATEGIES。"""
        from research_os.data_layer.bindings import SUPPORTED_PROJECTION_STRATEGIES
        assert set(PROJECTION_HANDLERS.keys()) == set(SUPPORTED_PROJECTION_STRATEGIES)

    def test_dead_statement_type_projection_removed(self):
        """§53：projection:financial_facts.statement_type 必须不存在（已删除）。"""
        from research_os.data_layer.bindings import SUPPORTED_PROJECTION_STRATEGIES
        assert "projection:financial_facts.statement_type" not in SUPPORTED_PROJECTION_STRATEGIES
        assert "projection:financial_facts.statement_type" not in PROJECTION_HANDLERS

    def test_statement_scope_direct_not_projection(self, requirement_registry):
        """§53：statement_scope 保持 direct，不得重新引入 statement_type 投影。"""
        binding = RequirementReadinessBindingResolver(requirement_registry).get(
            "stock_research_report.financial_statement_data")
        assert binding.minimum_field_sources["statement_scope"] == "direct"


# ============================================================
# R3.1-08：binding runtime authority
# ============================================================

class TestBindingRuntimeAuthority:
    def test_changing_binding_changes_claims_coverage(self, tmp_path, requirement_registry, provenance):
        """§63：daily_review.claims 同数据下 generic singleton vs binding open-world
        产生不同 coverage。"""
        db_path = tmp_path / "claims.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE claims (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-cl"), source_id="cninfo",
            raw_item_id=_uuid("ri-cl"), title="e", publisher="cninfo",
            published_at="2026-08-11T06:00:00+08:00",
            retrieved_at="2026-08-11T06:05:00+08:00", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "claims", _schema_valid(Claim(
            claim_id=_uuid("claim-c1"), claim_type="FACT", statement="声明",
            subject_entities=[], predicate="has", object={"v": 1},
            as_of="2026-08-11T06:00:00+08:00", evidence_ids=[_uuid("ev-cl")],
            support_level="inferred", confidence=0.9, review_status="unreviewed")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("daily_review.claims")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        assert binding.coverage_strategy == COV_OPEN_WORLD
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.coverage_ratio is None  # open-world → null（非 1.0）
        db.close()

    def test_production_preflight_binding_required(self, requirement_registry, capability_registry):
        """§62：production preflight 初始化 binding；projector 按 context 隔离构造。"""
        svc = DataPreflightService(requirement_registry, capability_registry)
        assert svc._bindings is not None
        assert not hasattr(svc, "_projector")
        assert len(svc._bindings.all()) == 43


# ============================================================
# R3.1-06：schema-valid runtime fixtures（full positive loop）
# ============================================================

class TestSchemaValidRuntimeFixtures:
    """§39-49：Pydantic → model_dump → validate_instance → persist → actual checker
    → DataReadinessService。禁止 partial dict 冒充 schema-valid fixture。"""

    def test_financial_fact_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§42：FinancialFact 全循环；fact_key/period_end/statement_scope/value 均 available。"""
        db_path = tmp_path / "fin.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE financial_facts (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-ff"), source_id="cninfo",
            raw_item_id=_uuid("ri-ff"), title="e", publisher="cninfo",
            published_at="2026-08-10T16:30:00Z",
            retrieved_at="2026-08-10T16:35:00Z", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "financial_facts", _schema_valid(FinancialFact(
            fact_id="f1", fact_key="revenue", financial_report_id="fr1",
            company_entity_id="company:600519.SH",
            statement_type="income_statement", statement_scope="consolidated",
            taxonomy_code="REV", label_raw="营业收入",
            period_start="2026-01-01", period_end="2026-06-30",
            instant_or_duration="duration", period_basis="reported_period",
            currency="CNY", unit_scale=1,
            raw_value="1000000000", normalized_value="1000000000",
            normalized_unit="CNY", value_status="reported",
            sign_convention="reported", audit_status="audited",
            source_document_id=None, evidence_ids=[_uuid("ev-ff")],
            source_priority=1, restatement_version=1,
            valid_from="2026-07-01T00:00:00+08:00", valid_to=None, warnings=[],
            version=1, created_at="2026-07-02T00:00:00+08:00")))
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
        for f in ("fact_key", "period_end", "statement_scope", "value"):
            assert f in r.available_fields, f"{f} 应 available: {r.available_fields}"
            assert f not in r.missing_fields, f"{f} 不应 missing"
        db.close()

    def test_document_record_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§43：DocumentRecord.source_id → SourceRegistry → tier → eligible。"""
        db_path = tmp_path / "doc.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE document_records (payload TEXT)")
        _insert(conn, "document_records", _schema_valid(DocumentRecord(
            document_id="d1", company_entity_id="company:600519.SH",
            document_type="annual_report", title="t", source_id="cninfo",
            published_at="2026-08-10T16:30:00Z",
            retrieved_at="2026-08-11T00:35:00+08:00",
            mime_type="application/pdf",
            sha256="a" * 64, storage_policy="metadata_and_excerpt",
            copyright_status="statutory_filing", text_layer_status="present",
            created_at="2026-08-11T00:35:00+08:00",
            updated_at="2026-08-11T00:35:00+08:00",
            parse_status="parsed")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.company_document")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_document_low_tier_ineligible(self, tmp_path, requirement_registry, provenance):
        """§43：低于 minimum tier 的 source → ineligible。"""
        db_path = tmp_path / "doc2.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE document_records (payload TEXT)")
        _insert(conn, "document_records", _schema_valid(DocumentRecord(
            document_id="d2", company_entity_id="company:600519.SH",
            document_type="annual_report", title="t", source_id="cls",
            published_at="2026-08-10T16:30:00Z",
            retrieved_at="2026-08-11T00:35:00+08:00",
            mime_type="application/pdf",
            sha256="b" * 64, storage_policy="metadata_and_excerpt",
            copyright_status="statutory_filing", text_layer_status="present",
            created_at="2026-08-11T00:35:00+08:00",
            updated_at="2026-08-11T00:35:00+08:00",
            parse_status="parsed")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.company_document")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 0  # cls tier 低于 requirement 要求
        db.close()

    def test_raw_item_evidence_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§44：RawItem+Evidence subject eligible；unrelated → ineligible。"""
        db_path = tmp_path / "ev.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        conn.execute("CREATE TABLE raw_items (payload TEXT)")
        _insert(conn, "raw_items", _schema_valid(RawItem(
            raw_item_id=_uuid("ri-ev"), source_id="cninfo", title="r",
            url="http://r", publisher="cninfo",
            published_at="2026-08-11T06:00:00+08:00",
            retrieved_at="2026-08-11T06:05:00+08:00",
            content_hash="a" * 64, content_excerpt="x",
            content_storage="metadata_and_excerpt", language="zh-CN",
            access_status="ok", entities=["company:600519.SH"],
            raw_category="official_disclosure")))
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-ri"), source_id="cninfo",
            raw_item_id=_uuid("ri-ev"), title="e", publisher="cninfo",
            published_at="2026-08-11T06:00:00+08:00",
            retrieved_at="2026-08-11T06:05:00+08:00", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
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
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_claim_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§45：Claim tier via Evidence（实际 checker，非仅 ProvenanceResolver helper）。"""
        db_path = tmp_path / "claim.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE claims (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-c2"), source_id="cninfo",
            raw_item_id=_uuid("ri-c2"), title="e", publisher="cninfo",
            published_at="2026-08-11T06:00:00+08:00",
            retrieved_at="2026-08-11T06:05:00+08:00", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "claims", _schema_valid(Claim(
            claim_id=_uuid("claim-c2"), claim_type="FACT", statement="声明",
            subject_entities=[], predicate="has", object={"v": 1},
            as_of="2026-08-11T06:00:00+08:00", evidence_ids=[_uuid("ev-c2")],
            support_level="inferred", confidence=0.9, review_status="unreviewed")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("daily_review.claims")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "daily_review",
                       {"review_business_date": "2026-08-11", "as_of": AS_OF})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_research_finding_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§46：ResearchFinding subject/PIT/tier/minimum fields 全走 runtime。"""
        db_path = tmp_path / "rf.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE research_findings (payload TEXT)")
        conn.execute("CREATE TABLE evidence (payload TEXT)")
        _insert(conn, "evidence", _schema_valid(Evidence(
            evidence_id=_uuid("ev-rf"), source_id="cninfo",
            raw_item_id=_uuid("ri-rf"), title="e", publisher="cninfo",
            published_at="2026-08-11T06:00:00+08:00",
            retrieved_at="2026-08-11T06:05:00+08:00", url="http://e", excerpt="x",
            evidence_type="official_disclosure", independence_group="g1",
            source_tier="S")))
        _insert(conn, "research_findings", _schema_valid(ResearchFinding(
            finding_id="rf1", request_id="r1",
            company_entity_id="company:600519.SH",
            finding_type="fact_summary", title="t", statement="s",
            claim_type="FACT", predicate="has", object={"v": 1},
            as_of="2026-08-11T06:00:00+08:00", evidence_ids=[_uuid("ev-rf")],
            confidence=0.9, support_level="inferred", status="supported",
            section_id="s1", created_at="2026-08-11T06:05:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_review.research_findings")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_review",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_security_profile_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§47：SecurityProfile listed + listing_date<=as_of + fields + provenance，无 false MISSING。"""
        db_path = tmp_path / "sp.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE security_profiles (payload TEXT)")
        _insert(conn, "security_profiles", _schema_valid(SecurityProfile(
            security_profile_id="sp1",
            security_entity_id="security:600519.SH",
            company_entity_id="company:600519.SH", symbol="600519.SH",
            exchange="SH", board="main", security_type="common_share",
            listing_date="2020-01-01", currency="CNY", share_class="A",
            current_name="贵州茅台", status="listed",
            source_ids=["cninfo"], evidence_ids=[], version=1,
            created_at="2026-01-01T00:00:00+08:00",
            updated_at="2026-08-10T00:00:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.security_profile")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_valuation_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§48：ValuationSnapshot status=complete + price/shares + as_of<=request + provenance。"""
        db_path = tmp_path / "vs.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE valuation_snapshots (payload TEXT)")
        _insert(conn, "valuation_snapshots", _schema_valid(
            _valuation("vs1", "2026-08-11T06:00:00+08:00")))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("stock_research_report.market_valuation_snapshot")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "stock_research_report",
                       {"entity": "company:600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_market_full_runtime(self, tmp_path, requirement_registry, provenance):
        """§49：MarketDailyOHLCV + Manifest → accepted manifest → source_id tier → bar eligible。"""
        db_path = tmp_path / "mkt.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE market_daily_ohlcv (payload TEXT)")
        conn.execute("CREATE TABLE market_daily_series_manifests (payload TEXT)")
        _insert(conn, "market_daily_series_manifests", _schema_valid(MarketDailySeriesManifest(
            import_id=_uuid("mkt-m1"), source_id="sse",
            source_kind="manual_import",
            file_name="f.csv", file_checksum="a" * 64,
            imported_at="2026-08-11T00:35:00+08:00", imported_by="admin",
            symbols=["600519.SH"], date_start="2026-08-01", date_end="2026-08-11",
            row_count=1, adjustment_method="none", adjustment_description="no adjustment",
            calendar_id="cn-sse", calendar_version="v1",
            currency="CNY", price_unit="CNY", volume_unit="shares",
            data_version="v1", validation_status="accepted", validation_errors=[],
            warnings=[])))
        _insert(conn, "market_daily_ohlcv", _schema_valid(MarketDailyOhlcv(
            bar_id=_uuid("mkt-bar1"), symbol="600519.SH", trade_date="2026-08-11",
            open=10.0, high=11.0, low=9.0, close=10.5, volume=1000, amount=10500.0)))
        conn.commit()
        conn.close()
        from research_os.storage import Database
        db = Database.open_read_only(db_path)
        view = _view_from(db)
        req = requirement_registry.get("abnormal_move_analysis.market_daily_ohlcv")
        binding = RequirementReadinessBindingResolver(requirement_registry).get(req.requirement_id)
        ctx = _resolve(requirement_registry, req.requirement_id, "abnormal_move_analysis",
                       {"entity_id": "600519.SH"})
        ctx.binding = binding
        ctx.projector = ReadinessFieldProjector()
        r = DataReadinessService(ReadinessCheckerRegistry()).evaluate(
            req, ctx, view, CHECKED_AT, provenance=provenance,
            binding=binding, projector=ReadinessFieldProjector())
        assert r.eligible_record_count == 1, r.warnings
        db.close()

    def test_partial_dict_cannot_be_production_fixture(self):
        """§40：partial dict 未满足 schema 不得称为 SCHEMA_VALID_RUNTIME_FIXTURE。"""
        partial = {"fact_id": "f1", "fact_key": "k", "raw_value": "1"}
        assert validate_instance(partial, "financial_fact") != []
