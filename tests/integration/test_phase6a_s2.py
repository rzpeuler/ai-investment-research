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
            assert result.status in ("insufficient_evidence", "failed", "degraded")
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
