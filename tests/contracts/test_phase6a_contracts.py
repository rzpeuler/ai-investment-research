"""Phase 6A R2 contract tests — isolated registry, schema loadability, task_id lineage."""
from __future__ import annotations
import pytest
from research_os.validators.schema_validator import SCHEMA_NAMES, validate_instance


class TestSchemaRegistered:
    def test_all_6a_schemas_in_names(self):
        for name in ("industry_research_request", "industry_research_run",
                     "theme_discovery_request", "theme_discovery_run"):
            assert name in SCHEMA_NAMES

    def test_all_6a_schemas_loadable(self):
        from research_os.validators.schema_validator import load_schema
        for name in ("industry_research_request", "industry_research_run",
                     "theme_discovery_request", "theme_discovery_run"):
            s = load_schema(name)
            assert s is not None


class TestIsolatedRegistry:
    def test_registry_injection(self):
        from research_os.orchestrator.scenario_registry import ScenarioRegistry
        from research_os.orchestrator.runners.industry_research import IndustryResearchScenarioRunner
        from research_os.orchestrator.runners.theme_discovery import ThemeDiscoveryScenarioRunner
        registry = ScenarioRegistry()
        registry.register(IndustryResearchScenarioRunner())
        registry.register(ThemeDiscoveryScenarioRunner())
        assert "industry_research" in registry.names()
        assert "theme_discovery" in registry.names()


class TestFailClosed:
    def test_industry_runner_missing_as_of(self):
        from research_os.orchestrator.runners.industry_research import IndustryResearchScenarioRunner
        runner = IndustryResearchScenarioRunner()
        with pytest.raises(ValueError):
            runner.validate_request({"industry_id": "test"})

    def test_theme_runner_missing_as_of(self):
        from research_os.orchestrator.runners.theme_discovery import ThemeDiscoveryScenarioRunner
        runner = ThemeDiscoveryScenarioRunner()
        with pytest.raises(ValueError):
            runner.validate_request({})


class TestIndustryRunnerSchemaParity:
    def test_payload_passes_schema(self):
        from research_os.utils.id import new_uuid
        payload = {
            "request_id": new_uuid(), "task_id": "task-test",
            "industry_id": "sw1:semi", "industry_name": "测试",
            "as_of": "2026-06-01T00:00:00+08:00", "as_of_basis": "user_provided",
            "timezone": "Asia/Shanghai", "depth": "standard",
            "deterministic_only": True, "live": False, "dry_run": False, "force": False,
            "source_policy": "public_first", "status": "validated", "warnings": [],
            "rule_versions": {}, "requested_at": "2026-06-01T00:00:00+08:00",
            "version": 1,
        }
        errors = validate_instance(payload, "industry_research_request")
        assert errors == [], f"Schema errors: {errors}"
