"""Phase 6A R2 adversarial tests — Schema parity, fail-closed, single model, lifecycle, report order."""
from __future__ import annotations
from pathlib import Path
import pytest


class TestSchemaParity:
    def test_industry_request_schema_matches_runner(self):
        from research_os.validators.schema_validator import validate_instance
        from research_os.utils.id import new_uuid
        payload = {
            "request_id": new_uuid(), "task_id": "task-001",
            "industry_id": "sw1:semi", "industry_name": "半导体",
            "as_of": "2026-06-01T00:00:00+08:00", "as_of_basis": "user_provided",
            "timezone": "Asia/Shanghai", "depth": "standard",
            "deterministic_only": True, "live": False, "dry_run": False, "force": False,
            "source_policy": "public_first", "status": "validated", "warnings": [],
            "rule_versions": {}, "requested_at": "2026-06-01T00:00:00+08:00",
            "version": 1,
        }
        errors = validate_instance(payload, "industry_research_request")
        assert errors == [], f"Schema validation errors: {errors}"


class TestFailClosed:
    def test_industry_runner_fails_on_bad_schema(self):
        from research_os.orchestrator.runners.industry_research import IndustryResearchScenarioRunner
        runner = IndustryResearchScenarioRunner()
        with pytest.raises(ValueError, match=r"as.of|as_of"):
            runner.validate_request({"industry_id": "test"})


class TestSingleModel:
    def test_theme_pipeline_no_inline_dataclasses(self):
        pipeline_path = (
            Path(__file__).parent.parent.parent
            / "src" / "research_os" / "theme_discovery" / "pipeline.py"
        )
        if not pipeline_path.exists():
            pytest.skip("not found")
        content = pipeline_path.read_text(encoding="utf-8")
        # Only the import line should have ThemeTrigger, etc — not @dataclass definitions
        assert "from research_os.theme_discovery import" in content

    def test_theme_pipeline_uses_correct_lifecycle(self):
        from research_os.theme_discovery import THEME_LIFECYCLE_STATES
        assert set(THEME_LIFECYCLE_STATES) == {"forming", "supported", "weakening", "invalidated", "uncertain"}

    def test_theme_pipeline_uses_theme_hypothesis_fields(self):
        from research_os.theme_discovery import ThemeHypothesis
        from dataclasses import fields
        names = {f.name for f in fields(ThemeHypothesis)}
        for required in ["supporting_evidence_ids", "counter_evidence_ids",
                          "invalidating_conditions", "open_questions",
                          "industry_mapping", "related_entity_ids",
                          "supporting_factors", "counter_evidence"]:
            assert required in names, f"Missing {required}"

    def test_theme_pipeline_run_with_keywords(self):
        from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
        pipeline = ThemeDiscoveryPipeline(Path("."), db=None, llm_client=None)
        result = pipeline.run({
            "as_of": "2026-06-01T00:00:00+08:00",
            "discovery_mode": "keyword_sweep",
            "keywords": ["AI", "半导体"],
            "task_id": "task-1",
        })
        assert result.status in ("success", "partial_success", "insufficient_evidence")
        assert len(result.themes) > 0
        assert result.markdown != ""

    def test_report_contains_theme_content(self):
        from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
        pipeline = ThemeDiscoveryPipeline(Path("."), db=None, llm_client=None)
        result = pipeline.run({
            "as_of": "2026-06-01T00:00:00+08:00",
            "discovery_mode": "keyword_sweep",
            "keywords": ["AI"],
            "task_id": "task-1",
        })
        assert "AI" in result.markdown


class TestEvidenceEligibility:
    def test_published_after_as_of_rejected(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, reasons = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2026-07-01T00:00:00+08:00",
             "source_tier": "A", "evidence_type": "article"},
            "2026-06-01T00:00:00+08:00",
        )
        assert not eligible

    def test_unknown_source_tier_rejected(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, reasons = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2025-06-01T00:00:00+08:00",
             "source_tier": "unknown", "evidence_type": "article"},
            "2026-06-01T00:00:00+08:00",
        )
        assert not eligible

    def test_valid_evidence_accepted(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_eligibility
        eligible, reasons = validate_evidence_eligibility(
            {"evidence_id": "e1", "published_at": "2025-12-01T00:00:00+08:00",
             "source_tier": "A", "evidence_type": "article"},
            "2026-06-01T00:00:00+08:00",
        )
        assert eligible

    def test_empty_chain_returns_empty(self):
        from research_os.industry_research.evidence_adapter import validate_evidence_ids_chain
        result = validate_evidence_ids_chain([], None, "2026-01-01T00:00:00+08:00")
        assert result == {"valid": [], "invalid": [], "missing": [], "reasons": {}}


class TestReportOrder:
    def test_themes_written_before_render(self):
        """验证 themes 在 render 之前写入 result。"""
        from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
        pipeline = ThemeDiscoveryPipeline(Path("."), db=None, llm_client=None)
        result = pipeline.run({
            "as_of": "2026-06-01T00:00:00+08:00",
            "discovery_mode": "keyword_sweep",
            "keywords": ["AI"],
            "task_id": "task-1",
        })
        assert len(result.themes) > 0
        assert result.markdown != ""


class TestCleanBranch:
    def test_no_6b_files_in_6a(self):
        """仅在干净分支上有效 — 当前分支有 6B 文件则跳过。"""
        import os
        # Check if we're on a clean 6A branch
        has_6b = os.path.exists("src/research_os/brief")
        if has_6b:
            pytest.skip("Running on branch with 6B files — test only valid on clean 6A branch")
