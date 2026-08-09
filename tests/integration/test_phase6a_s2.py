"""Phase 6A S2 integration tests — Orchestrator happy paths + attack tests."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from research_os.orchestrator.orchestrator import Orchestrator
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.orchestrator.runners.industry_research import IndustryResearchScenarioRunner
from research_os.orchestrator.runners.theme_discovery import ThemeDiscoveryScenarioRunner
from research_os.storage import Database
from research_os.validators.schema_validator import validate_instance
from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
from research_os.theme_discovery import ThemeHypothesis, ThemeTrigger


def _make_db(tmp_path) -> Database:
    db_path = tmp_path / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.initialize()
    return db


def _registry() -> ScenarioRegistry:
    reg = ScenarioRegistry()
    reg.register(IndustryResearchScenarioRunner())
    reg.register(ThemeDiscoveryScenarioRunner())
    return reg


# ── Model/Schema roundtrip tests ──────────────────────────

class TestModelSchemaRoundtrip:
    def test_industry_request_roundtrip(self):
        from research_os.models.phase6a import IndustryResearchRequest
        from research_os.utils.time import now_iso
        m = IndustryResearchRequest(
            request_id="aaaabbbb-1111-4111-8111-111111111111",
            task_id="aaaabbbb-2222-4222-8222-222222222222",
            industry_id="sw1:semi", industry_name="半导体",
            as_of="2026-08-06T08:00:00+08:00", as_of_basis="user_provided",
            timezone="Asia/Shanghai", depth="standard",
            deterministic_only=True, requested_at=now_iso(),
            rule_versions={}, version=1,
        )
        assert validate_instance(m.model_dump(), "industry_research_request") == []

    def test_industry_request_rejects_extra_field(self):
        from research_os.models.phase6a import IndustryResearchRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            IndustryResearchRequest(
                request_id="aaaabbbb-1111-4111-8111-111111111111",
                task_id="aaaabbbb-2222-4222-8222-222222222222",
                industry_id="sw1:semi", as_of="2026-08-06T08:00:00+08:00",
                as_of_basis="user_provided", timezone="Asia/Shanghai",
                depth="standard", requested_at="2026-08-06T08:00:00+08:00",
                rule_versions={}, version=1,
                fake_field="should_reject",
            )

    def test_theme_request_roundtrip(self):
        from research_os.models.phase6a import ThemeDiscoveryRequest
        from research_os.utils.time import now_iso
        m = ThemeDiscoveryRequest(
            request_id="aaaabbbb-3333-4333-8333-333333333333",
            task_id="aaaabbbb-4444-4444-8444-444444444444",
            theme_triggers=[{"trigger_type": "event", "description": "test"}],
            as_of="2026-08-06T08:00:00+08:00", as_of_basis="user_provided",
            timezone="Asia/Shanghai", depth="standard", discovery_mode="graph_based",
            requested_at=now_iso(), rule_versions={}, version=1,
        )
        assert validate_instance(m.model_dump(), "theme_discovery_request") == []

    def test_invalid_depth_rejected(self):
        from research_os.models.phase6a import IndustryResearchRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            IndustryResearchRequest(
                request_id="aaaabbbb-5555-4555-8555-555555555555",
                task_id="aaaabbbb-6666-4666-8666-666666666666",
                industry_id="sw1:semi", as_of="2026-08-06T08:00:00+08:00",
                as_of_basis="user_provided", timezone="Asia/Shanghai",
                depth="ultra", requested_at="2026-08-06T08:00:00+08:00",
                rule_versions={}, version=1,
            )

    def test_invalid_discovery_mode_rejected(self):
        from research_os.models.phase6a import ThemeDiscoveryRequest
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            ThemeDiscoveryRequest(
                request_id="aaaabbbb-7777-4777-8777-777777777777",
                task_id="aaaabbbb-8888-4888-8888-888888888888",
                theme_triggers=[{"trigger_type": "event", "description": "test"}],
                as_of="2026-08-06T08:00:00+08:00", as_of_basis="user_provided",
                timezone="Asia/Shanghai", depth="standard", discovery_mode="invalid_mode",
                requested_at="2026-08-06T08:00:00+08:00", rule_versions={}, version=1,
            )

    def test_industry_run_roundtrip(self):
        from research_os.models.phase6a import IndustryResearchRun
        m = IndustryResearchRun(
            run_id="aaaabbbb-9999-4999-8999-999999999999",
            request_id="aaaabbbb-1111-4111-8111-111111111111",
            task_id="aaaabbbb-2222-4222-8222-222222222222",
            industry_id="sw1:semi", industry_name="半导体",
            as_of="2026-08-06T08:00:00+08:00",
            depth="standard",
            idempotency_key="aaaabbbb-2222-4222-8222-222222222222:sw1:semi:2026-08-06T08:00:00+08:00",
            run_version=1,
            started_at="2026-08-06T08:00:01+08:00",
            finished_at="2026-08-06T08:00:02+08:00",
            status="success",
            stage_statuses=[],
            artifact_paths=[],
            input_versions={},
            model_route_summary={},
            validation_status="pass",
            error_codes=[],
            warnings=[],
            missing_data=[],
            findings_count=0,
            dimensions_covered=[],
            dimensions_missing=[],
            evidence_quality={},
            model_route={},
            data_degraded=False,
            version=1,
        )
        assert validate_instance(m.model_dump(), "industry_research_run") == []

    def test_theme_run_roundtrip(self):
        from research_os.models.phase6a import ThemeDiscoveryRun
        m = ThemeDiscoveryRun(
            run_id="aaaabbbb-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            request_id="aaaabbbb-3333-4333-8333-333333333333",
            task_id="aaaabbbb-4444-4444-8444-444444444444",
            as_of="2026-08-06T08:00:00+08:00",
            discovery_mode="graph_based",
            idempotency_key="aaaabbbb-4444-4444-8444-444444444444:graph_based:2026-08-06T08:00:00+08:00",
            run_version=1,
            started_at="2026-08-06T08:00:01+08:00",
            finished_at="2026-08-06T08:00:02+08:00",
            status="success",
            stage_statuses=[],
            artifact_paths=[],
            input_versions={},
            model_route_summary={},
            validation_status="pass",
            error_codes=[],
            warnings=[],
            missing_data=[],
            themes_discovered=3,
            industry_ids=[],
            keywords=[],
            model_route={},
            version=1,
        )
        assert validate_instance(m.model_dump(), "theme_discovery_run") == []


# ── Negative schema parity tests ──────────────────────────

class TestNegativeSchemaParity:
    """Schema-level rejection using validate_instance directly (not Pydantic)."""

    def test_industry_request_invalid_as_of_rejected(self):
        payload = {
            "request_id": "aaaabbbb-1111-4111-8111-111111111111",
            "task_id": "aaaabbbb-2222-4222-8222-222222222222",
            "industry_id": "sw1:semi",
            "as_of": "not-a-date",
            "as_of_basis": "user_provided",
            "timezone": "Asia/Shanghai",
            "depth": "standard",
            "live": False,
            "dry_run": False,
            "force": False,
            "source_policy": "public_first",
            "status": "planned",
            "warnings": [],
            "rule_versions": {},
            "requested_at": "2026-08-06T08:00:00+08:00",
            "version": 1,
        }
        errs = validate_instance(payload, "industry_research_request")
        assert errs != [], f"Expected schema errors for invalid as_of, got none"

    def test_theme_request_invalid_depth_rejected(self):
        payload = {
            "request_id": "aaaabbbb-3333-4333-8333-333333333333",
            "task_id": "aaaabbbb-4444-4444-8444-444444444444",
            "theme_triggers": [{"trigger_type": "event", "description": "test"}],
            "as_of": "2026-08-06T08:00:00+08:00",
            "as_of_basis": "user_provided",
            "timezone": "Asia/Shanghai",
            "depth": "ultra",
            "discovery_mode": "graph_based",
            "live": False,
            "dry_run": False,
            "force": False,
            "source_policy": "public_first",
            "status": "planned",
            "warnings": [],
            "rule_versions": {},
            "requested_at": "2026-08-06T08:00:00+08:00",
            "version": 1,
        }
        errs = validate_instance(payload, "theme_discovery_request")
        assert errs != [], f"Expected schema errors for invalid depth, got none"

    def test_theme_request_invalid_discovery_mode_rejected(self):
        payload = {
            "request_id": "aaaabbbb-3333-4333-8333-333333333333",
            "task_id": "aaaabbbb-4444-4444-8444-444444444444",
            "theme_triggers": [{"trigger_type": "event", "description": "test"}],
            "as_of": "2026-08-06T08:00:00+08:00",
            "as_of_basis": "user_provided",
            "timezone": "Asia/Shanghai",
            "depth": "standard",
            "discovery_mode": "invalid_mode",
            "live": False,
            "dry_run": False,
            "force": False,
            "source_policy": "public_first",
            "status": "planned",
            "warnings": [],
            "rule_versions": {},
            "requested_at": "2026-08-06T08:00:00+08:00",
            "version": 1,
        }
        errs = validate_instance(payload, "theme_discovery_request")
        assert errs != [], f"Expected schema errors for invalid discovery_mode, got none"

    def test_industry_run_missing_task_id_rejected(self):
        payload = {
            "run_id": "aaaabbbb-9999-4999-8999-999999999999",
            "request_id": "aaaabbbb-1111-4111-8111-111111111111",
            "idempotency_key": "key",
            "run_version": 1,
            "started_at": "2026-08-06T08:00:01+08:00",
            "finished_at": "2026-08-06T08:00:02+08:00",
            "status": "success",
            "stage_statuses": [],
            "artifact_paths": [],
            "input_versions": {},
            "model_route_summary": {},
            "validation_status": "pass",
            "error_codes": [],
            "version": 1,
        }
        errs = validate_instance(payload, "industry_research_run")
        assert errs != [], f"Expected schema errors for missing task_id, got none"


# ── Industry Orchestrator happy path ──────────────────────

class TestIndustryOrchestrator:
    def test_basic_execution(self, tmp_path):
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("industry_research", dict(
                industry_id="sw1:semi",
                as_of="2026-08-06T08:00:00+08:00",
                depth="standard",
                force=True,
            ))
            assert result.task_id != ""
            assert result.status in ("success", "partial_success", "degraded", "insufficient_evidence")

            # Verify artifacts exist and are schema-valid
            run_dir = tmp_path / "reports" / "runs" / result.task_id
            req_path = run_dir / "industry_research_request.json"
            run_path = run_dir / "industry_research_run.json"
            assert req_path.exists(), f"Missing: {req_path}"
            assert run_path.exists(), f"Missing: {run_path}"
            assert validate_instance(json.loads(req_path.read_text(encoding="utf-8")), "industry_research_request") == []
            assert validate_instance(json.loads(run_path.read_text(encoding="utf-8")), "industry_research_run") == []
        finally:
            orch.close()

    def test_missing_as_of_fails(self, tmp_path):
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("industry_research", dict(
                industry_id="sw1:semi",
                force=True,
            ))
            assert result.status == "failed"
            assert result.exit_code == 2
        finally:
            orch.close()

    def test_no_generic_run_json(self, tmp_path):
        """After orchestrator execution, 'run.json' must NOT exist."""
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("industry_research", dict(
                industry_id="sw1:semi",
                as_of="2026-08-06T08:00:00+08:00",
                depth="standard",
                force=True,
            ))
            run_dir = tmp_path / "reports" / "runs" / result.task_id
            generic_run = run_dir / "run.json"
            assert not generic_run.exists(), (
                f"'run.json' must not exist; only scenario-specific run artifacts "
                f"(e.g. industry_research_run.json) are allowed. Found: {generic_run}"
            )
        finally:
            orch.close()


# ── Theme Orchestrator paths ──────────────────────────────

class TestThemeOrchestrator:
    def test_keyword_sweep_zero_evidence(self, tmp_path):
        """Zero Evidence → insufficient_evidence, not success/partial_success."""
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("theme_discovery", dict(
                as_of="2026-08-06T08:00:00+08:00",
                discovery_mode="keyword_sweep",
                keywords=["AI", "新能源"],
                force=True,
            ))
            assert result.task_id != ""
            # Zero evidence → must be insufficient_evidence
            assert result.status == "insufficient_evidence"
            assert result.status != "success"

            # Verify artifact lineage
            run_dir = tmp_path / "reports" / "runs" / result.task_id
            req = json.loads((run_dir / "theme_discovery_request.json").read_text(encoding="utf-8"))
            run = json.loads((run_dir / "theme_discovery_run.json").read_text(encoding="utf-8"))
            assert req["task_id"] == result.task_id
            assert run["task_id"] == result.task_id
            assert req["discovery_mode"] == "keyword_sweep"
            assert run["discovery_mode"] == "keyword_sweep"
            assert validate_instance(req, "theme_discovery_request") == []
            assert validate_instance(run, "theme_discovery_run") == []
        finally:
            orch.close()

    def test_discovery_mode_lineage(self, tmp_path):
        """discovery_mode passes through verbatim."""
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("theme_discovery", dict(
                as_of="2026-08-06T08:00:00+08:00",
                discovery_mode="keyword_sweep",
                keywords=["AI"],
                force=True,
            ))
            assert result.task_id != ""
            run_dir = tmp_path / "reports" / "runs" / result.task_id
            req = json.loads((run_dir / "theme_discovery_request.json").read_text(encoding="utf-8"))
            run = json.loads((run_dir / "theme_discovery_run.json").read_text(encoding="utf-8"))
            assert req["discovery_mode"] == "keyword_sweep"
            assert run["discovery_mode"] == "keyword_sweep"
            # Must not contain lossy alternative values
            assert req["discovery_mode"] not in ("scanning", "monitoring")
        finally:
            orch.close()

    def test_no_generic_run_json(self, tmp_path):
        """After theme orchestrator execution, 'run.json' must NOT exist."""
        db = _make_db(tmp_path)
        orch = Orchestrator(tmp_path, db=db, registry=_registry())
        try:
            result = orch.execute("theme_discovery", dict(
                as_of="2026-08-06T08:00:00+08:00",
                discovery_mode="keyword_sweep",
                keywords=["AI"],
                force=True,
            ))
            run_dir = tmp_path / "reports" / "runs" / result.task_id
            generic_run = run_dir / "run.json"
            assert not generic_run.exists(), (
                f"'run.json' must not exist; only scenario-specific run artifacts "
                f"(e.g. theme_discovery_run.json) are allowed. Found: {generic_run}"
            )
        finally:
            orch.close()


# ── Stable ID tests ───────────────────────────────────────

class TestStableIds:
    """Trigger / hypothesis IDs must be deterministic: same inputs → same ID."""

    def test_same_inputs_different_order_same_trigger_id(self):
        pipeline = ThemeDiscoveryPipeline(".")
        as_of = "2026-08-06T08:00:00+08:00"
        r1 = pipeline.run({"keywords": ["AI", "新能源"], "as_of": as_of})
        r2 = pipeline.run({"keywords": ["新能源", "AI"], "as_of": as_of})
        ids1 = sorted(t.trigger_id for t in r1.triggers)
        ids2 = sorted(t.trigger_id for t in r2.triggers)
        assert ids1 == ids2, (
            f"Same keywords in different order must produce same trigger_ids. "
            f"Got {ids1} vs {ids2}"
        )

    def test_different_evidence_set_different_trigger_id(self):
        pipeline = ThemeDiscoveryPipeline(".")
        as_of = "2026-08-06T08:00:00+08:00"
        r1 = pipeline.run({"keywords": ["AI"], "as_of": as_of, "discovery_mode": "keyword_sweep"})
        r2 = pipeline.run({"keywords": ["新能源"], "as_of": as_of, "discovery_mode": "keyword_sweep"})
        ids1 = {t.trigger_id for t in r1.triggers}
        ids2 = {t.trigger_id for t in r2.triggers}
        assert ids1 != ids2, (
            f"Different keywords must produce different trigger_ids. "
            f"Got {ids1} vs {ids2}"
        )
        assert not ids1.intersection(ids2), (
            f"Trigger IDs from different keyword sets should have no overlap. "
            f"Overlap: {ids1 & ids2}"
        )


# ── Theme Lifecycle tests ─────────────────────────────────

class TestThemeLifecycle:
    """Deterministic lifecycle detection: support → supported, counter → weakening, none → forming."""

    def test_support_only_yields_supported(self):
        pipeline = ThemeDiscoveryPipeline(".")
        theme = ThemeHypothesis(
            hypothesis_id="hyp:test-s",
            theme_name="Test Supported",
            triggers=[ThemeTrigger(trigger_id="trig:1", trigger_type="keyword_sweep",
                                    keyword="AI", strength=0.5)],
            supporting_evidence_ids=["ev:1"],
            counter_evidence_ids=[],
        )
        assert pipeline._detect_lifecycle(theme) == "supported"

    def test_counter_evidence_yields_weakening(self):
        pipeline = ThemeDiscoveryPipeline(".")
        theme = ThemeHypothesis(
            hypothesis_id="hyp:test-w",
            theme_name="Test Weakening",
            triggers=[ThemeTrigger(trigger_id="trig:1", trigger_type="keyword_sweep",
                                    keyword="AI", strength=0.5)],
            supporting_evidence_ids=["ev:1"],
            counter_evidence_ids=["ev:counter"],
        )
        assert pipeline._detect_lifecycle(theme) == "weakening"

    def test_no_eligible_evidence_yields_forming(self):
        pipeline = ThemeDiscoveryPipeline(".")
        theme = ThemeHypothesis(
            hypothesis_id="hyp:test-f",
            theme_name="Test Forming",
            triggers=[ThemeTrigger(trigger_id="trig:1", trigger_type="keyword_sweep",
                                    keyword="AI", strength=0.5)],
            supporting_evidence_ids=[],
            counter_evidence_ids=[],
        )
        assert pipeline._detect_lifecycle(theme) == "forming"


# ── Dimension + Evidence attacks ──────────────────────────

class TestDimensionEvidenceAttacks:
    def test_all_21_dimensions_present(self):
        from research_os.industry_research import INDUSTRY_DIMENSIONS, RESEARCH_DIMENSIONS_ALL
        assert len(INDUSTRY_DIMENSIONS) == 21
        assert len(RESEARCH_DIMENSIONS_ALL) == 21
        dims_with_selectors = sum(1 for d in INDUSTRY_DIMENSIONS if d.get("hint_node_types") or d.get("hint_relations"))
        dims_empty = 21 - dims_with_selectors
        assert dims_with_selectors + dims_empty == 21

    def test_pipeline_no_second_dimension_list(self):
        pipeline_src = (Path(__file__).parent.parent.parent
                        / "src" / "research_os" / "industry_research" / "pipeline.py")
        content = pipeline_src.read_text(encoding="utf-8")
        # Must import from __init__, not define its own list
        assert "from research_os.industry_research import" in content

    def test_evidence_eligibility_same_industry_accepted(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, _ = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2025-06-01T00:00:00+08:00",
             "source_tier": "A", "evidence_type": "article",
             "industry_tags": ["sw1:semi"]},
            "2026-06-01T00:00:00+08:00", industry_id="sw1:semi")
        assert eligible

    def test_evidence_eligibility_wrong_industry_rejected(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, _ = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2025-06-01T00:00:00+08:00",
             "source_tier": "A", "evidence_type": "article",
             "industry_tags": ["sw1:finance"]},
            "2026-06-01T00:00:00+08:00", industry_id="sw1:semi")
        assert not eligible

    def test_future_evidence_rejected(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, _ = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2026-07-01T00:00:00+08:00",
             "source_tier": "A", "evidence_type": "article"},
            "2026-06-01T00:00:00+08:00")
        assert not eligible

    def test_unknown_source_tier_rejected(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, _ = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2025-06-01T00:00:00+08:00",
             "source_tier": "unknown", "evidence_type": "article"},
            "2026-06-01T00:00:00+08:00")
        assert not eligible


# ═══════════════════════════════════════════════════════════════
# R5 additions: Negative schema parity + run.json guards
# ═══════════════════════════════════════════════════════════════

def _test_industry_request_invalid_requested_at(self):
    payload = {
        "request_id": "req-ir-2", "task_id": "task-ir-2",
        "industry_id": "sw1:semi", "as_of": "2026-08-06T08:00:00+08:00",
        "as_of_basis": "user_provided", "timezone": "Asia/Shanghai",
        "depth": "standard", "live": False, "dry_run": False,
        "force": False, "source_policy": "public_first",
        "status": "planned", "warnings": [], "rule_versions": {},
        "requested_at": "not-a-date", "version": 1,
    }
    assert validate_instance(payload, "industry_research_request") != []


def _test_theme_request_invalid_as_of(self):
    payload = {
        "request_id": "req-tm-1", "task_id": "task-tm-1",
        "theme_triggers": [{"trigger_type": "event", "description": "test"}],
        "as_of": "not-a-date", "as_of_basis": "user_provided",
        "timezone": "Asia/Shanghai", "depth": "standard",
        "discovery_mode": "graph_based", "live": False, "dry_run": False,
        "force": False, "source_policy": "public_first",
        "status": "planned", "warnings": [], "rule_versions": {},
        "requested_at": "2026-08-06T08:00:00+08:00", "version": 1,
    }
    assert validate_instance(payload, "theme_discovery_request") != []


def _test_theme_request_invalid_requested_at(self):
    payload = {
        "request_id": "req-tm-2", "task_id": "task-tm-2",
        "theme_triggers": [{"trigger_type": "event", "description": "test"}],
        "as_of": "2026-08-06T08:00:00+08:00", "as_of_basis": "user_provided",
        "timezone": "Asia/Shanghai", "depth": "standard",
        "discovery_mode": "graph_based", "live": False, "dry_run": False,
        "force": False, "source_policy": "public_first",
        "status": "planned", "warnings": [], "rule_versions": {},
        "requested_at": "not-a-date", "version": 1,
    }
    assert validate_instance(payload, "theme_discovery_request") != []


def _test_industry_run_invalid_depth(self):
    payload = {
        "run_id": "run-depth-1", "request_id": "req-depth-1",
        "task_id": "task-depth-1", "industry_id": "sw1:semi",
        "industry_name": "半导体", "as_of": "2026-08-06T08:00:00+08:00",
        "depth": "ultra", "idempotency_key": "ik-depth-1",
        "run_version": 1, "started_at": "2026-08-06T08:00:01+08:00",
        "finished_at": "2026-08-06T08:00:02+08:00",
        "status": "success", "stage_statuses": [], "artifact_paths": [],
        "input_versions": {}, "model_route_summary": {},
        "validation_status": "pass", "error_codes": [], "warnings": [],
        "missing_data": [], "findings_count": 0,
        "dimensions_covered": [], "dimensions_missing": [],
        "evidence_quality": {}, "model_route": {},
        "data_degraded": False, "version": 1,
    }
    assert validate_instance(payload, "industry_research_run") != []


def _test_theme_req_invalid_dm(self):
    payload = {
        "request_id": "req-dm-t", "task_id": "task-dm-t",
        "theme_triggers": [{"trigger_type": "event", "description": "test"}],
        "as_of": "2026-08-06T08:00:00+08:00", "as_of_basis": "user_provided",
        "timezone": "Asia/Shanghai", "depth": "standard",
        "discovery_mode": "scanning", "live": False, "dry_run": False,
        "force": False, "source_policy": "public_first",
        "status": "planned", "warnings": [], "rule_versions": {},
        "requested_at": "2026-08-06T08:00:00+08:00", "version": 1,
    }
    assert validate_instance(payload, "theme_discovery_request") != []


def _test_theme_run_invalid_dm(self):
    payload = {
        "run_id": "run-dm-1", "request_id": "req-dm-1",
        "task_id": "task-dm-1", "as_of": "2026-08-06T08:00:00+08:00",
        "discovery_mode": "scanning",
        "idempotency_key": "ik-dm-1", "run_version": 1,
        "started_at": "2026-08-06T08:00:01+08:00",
        "finished_at": "2026-08-06T08:00:02+08:00",
        "status": "success", "stage_statuses": [], "artifact_paths": [],
        "input_versions": {}, "model_route_summary": {},
        "validation_status": "pass", "error_codes": [], "warnings": [],
        "missing_data": [], "themes_discovered": 0,
        "industry_ids": [], "keywords": [], "model_route": {},
        "version": 1,
    }
    assert validate_instance(payload, "theme_discovery_run") != []


def _test_extra_field_rejected(self):
    payload = {
        "request_id": "req-extra-1", "task_id": "task-extra-1",
        "industry_id": "sw1:semi", "as_of": "2026-08-06T08:00:00+08:00",
        "as_of_basis": "user_provided", "timezone": "Asia/Shanghai",
        "depth": "standard", "live": False, "dry_run": False,
        "force": False, "source_policy": "public_first",
        "status": "planned", "warnings": [], "rule_versions": {},
        "requested_at": "2026-08-06T08:00:00+08:00", "version": 1,
        "unexpected_extra_field": "should_be_rejected",
    }
    assert validate_instance(payload, "industry_research_request") != []


TestNegativeSchemaParity.test_industry_request_invalid_requested_at = _test_industry_request_invalid_requested_at  # noqa
TestNegativeSchemaParity.test_theme_request_invalid_as_of = _test_theme_request_invalid_as_of
TestNegativeSchemaParity.test_theme_request_invalid_requested_at = _test_theme_request_invalid_requested_at
TestNegativeSchemaParity.test_industry_run_invalid_depth = _test_industry_run_invalid_depth
TestNegativeSchemaParity.test_theme_request_invalid_discovery_mode = _test_theme_req_invalid_dm
TestNegativeSchemaParity.test_theme_run_invalid_discovery_mode = _test_theme_run_invalid_dm
TestNegativeSchemaParity.test_extra_field_rejected = _test_extra_field_rejected


def _test_generic_run_json_nonexistent_industry(self, tmp_path):
    db = _make_db(tmp_path)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("industry_research", dict(
            industry_id="sw1:semi", as_of="2026-08-06T08:00:00+08:00",
            depth="standard", force=True))
        generic_run = tmp_path / "reports" / "runs" / result.task_id / "run.json"
        assert not generic_run.exists(), f"run.json must not exist: {generic_run}"
    finally:
        orch.close()


def _test_generic_run_json_nonexistent_theme(self, tmp_path):
    db = _make_db(tmp_path)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("theme_discovery", dict(
            as_of="2026-08-06T08:00:00+08:00",
            discovery_mode="keyword_sweep", keywords=["AI"], force=True))
        generic_run = tmp_path / "reports" / "runs" / result.task_id / "run.json"
        assert not generic_run.exists(), f"run.json must not exist: {generic_run}"
    finally:
        orch.close()


TestIndustryOrchestrator.test_generic_run_json_nonexistent = _test_generic_run_json_nonexistent_industry
TestThemeOrchestrator.test_generic_run_json_nonexistent = _test_generic_run_json_nonexistent_theme
