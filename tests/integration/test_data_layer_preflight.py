"""P7-D1 Orchestrator integration tests.

覆盖：Plan 中央权威、data_requirement_ids、preflight 在 Runner 前、
普通数据不足不 gate Runner、config error gate、artifacts 持久化、
dry-run 零副作用、Router/网络/LLM 禁止。
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import textwrap
from types import SimpleNamespace

import pytest

from research_os.orchestrator import Orchestrator
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.orchestrator.runners import DEFAULT_SCENARIOS
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

ROOT = Path(__file__).resolve().parents[2]


class _StubRunner:
    scenario = "morning_brief"
    version = "1.0.0"

    def __init__(self, record: dict):
        self.record = record
        self.executed = False

    def validate_request(self, request):
        return request

    def build_plan(self, request, context):
        # legacy 字段故意写错，验证中央权威胜出
        return {"steps": ["s1"], "data_requirements": ["totally_wrong_requirement"]}

    def execute(self, request, context):
        self.executed = True
        self.record["preflight_present"] = "data_preflight" in context
        self.record["preflight_readiness"] = len(context.get("data_preflight", object()).readiness)
        return ScenarioExecutionResult(
            status="success", exit_code=0, task_id=context["task"].task_id,
        )


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "project"
    (root / "reports").mkdir(parents=True)
    return root


def _registry_with_stub(record):
    reg = ScenarioRegistry()
    reg.register(_StubRunner(record))
    return reg


class TestPlanAuthority:
    def test_plan_data_requirements_from_central_registry(self, project):
        orch = Orchestrator(project)
        task = orch.create_task(scenario="morning_brief", as_of="2026-08-11T08:00:00+08:00")
        plan = orch.create_plan(task, {"report_date": "2026-08-11"})
        central = ScenarioDataRequirementRegistry(
            ROOT / "registry" / "scenario_data_requirements.yaml")
        expected_types = []
        seen = set()
        for r in central.for_scenario("morning_brief"):
            if r.data_type not in seen:
                expected_types.append(r.data_type)
                seen.add(r.data_type)
        assert plan.data_requirements == expected_types
        assert plan.data_requirement_ids == [r.requirement_id for r in central.for_scenario("morning_brief")]

    def test_runner_legacy_requirement_non_authoritative(self, project):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        task = orch.create_task(scenario="morning_brief", as_of="2026-08-11T08:00:00+08:00")
        plan = orch.create_plan(task, {"report_date": "2026-08-11"})
        assert "totally_wrong_requirement" not in plan.data_requirements
        assert "totally_wrong_requirement" not in plan.data_requirement_ids
        assert plan.data_requirements  # 中央权威非空

    def test_plan_authority_all_10_scenarios(self, project):
        central = ScenarioDataRequirementRegistry(
            ROOT / "registry" / "scenario_data_requirements.yaml")
        for scenario in ("morning_brief", "evening_brief", "daily_review",
                         "abnormal_move_analysis", "stock_research_report",
                         "first_coverage", "stock_review", "industry_research",
                         "theme_discovery", "earnings_expectation"):
            orch = Orchestrator(project)
            task = orch.create_task(scenario=scenario, as_of="2026-08-11T08:00:00+08:00")
            plan = orch.create_plan(task, {})
            expected_ids = [r.requirement_id for r in central.for_scenario(scenario)]
            assert plan.data_requirement_ids == expected_ids, scenario


class TestPreflightIntegration:
    def test_preflight_before_runner(self, project):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0
        assert record["preflight_present"] is True
        assert record["preflight_readiness"] == 5

    def test_missing_data_does_not_gate_runner(self, project):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0
        assert record["preflight_present"] is True  # runner 仍被调用

    def test_config_error_gates_runner(self, project):
        from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
        from research_os.data_layer.checkers import ReadinessCheckerRegistry
        from research_os.data_layer.preflight import DataPreflightService

        req_reg = ScenarioDataRequirementRegistry(ROOT / "registry" / "scenario_data_requirements.yaml")
        cap_reg = AcquisitionCapabilityRegistry(
            ROOT / "registry" / "data_acquisition_capabilities.yaml", req_reg, ROOT)
        preflight = DataPreflightService(req_reg, cap_reg, ReadinessCheckerRegistry([]))
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record), preflight=preflight)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 2
        assert "CONTROL_PLANE_CONFIGURATION_ERROR" in result.message
        assert record.get("preflight_present") is not True  # runner 未被调用


class TestArtifacts:
    def test_non_dry_run_artifacts_persisted(self, project):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        result = orch.execute("morning_brief", {"report_date": "2026-08-11"})
        assert result.exit_code == 0
        from research_os.orchestrator.run_directory import RunDirectory
        run_dir = RunDirectory(project / "reports" / "runs", result.task_id)
        assert (run_dir.root / "data_readiness_before.jsonl").exists()
        assert (run_dir.root / "data_gaps.jsonl").exists()
        assert (run_dir.root / "acquisition_plan.json").exists()

    def test_artifacts_schema_valid(self, project):
        from research_os.validators.schema_validator import validate_instance
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        result = orch.execute("morning_brief", {"report_date": "2026-08-11"})
        run_dir = Path(result.run_dir)
        for line in (run_dir / "data_readiness_before.jsonl").read_text(encoding="utf-8").splitlines():
            assert validate_instance(json.loads(line), "data_readiness") == []
        for line in (run_dir / "data_gaps.jsonl").read_text(encoding="utf-8").splitlines():
            assert validate_instance(json.loads(line), "data_gap") == []
        plan = json.loads((run_dir / "acquisition_plan.json").read_text(encoding="utf-8"))
        assert validate_instance(plan, "acquisition_plan") == []

    def test_dry_run_no_artifacts(self, project):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert not (project / "reports" / "runs").exists()
        assert result.task_id


class TestNetworkAndLLMProhibition:
    def test_preflight_never_calls_router(self, project, monkeypatch):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))

        def boom(*args, **kwargs):
            raise AssertionError("Router 被调用")

        monkeypatch.setattr("research_os.routing.router.Router.resolve", boom)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0

    def test_preflight_never_calls_llm(self, project, monkeypatch):
        record = {}
        orch = Orchestrator(project, registry=_registry_with_stub(record))

        def boom(*args, **kwargs):
            raise AssertionError("LLM 被调用")

        monkeypatch.setattr("research_os.llm.client.LlmClient.generate_json", boom)
        result = orch.execute("morning_brief", {"dry_run": True, "report_date": "2026-08-11"})
        assert result.exit_code == 0

    def test_default_foundation_calls_no_collector_llm_provider_or_graph_writer(
        self, project, monkeypatch,
    ):
        from research_os.collectors.government.nbs import NbsCollector
        from research_os.collectors.market.sina_quote import SinaQuoteCollector
        from research_os.collectors.news.cls import ClsMetadataCollector
        from research_os.collectors.official.cninfo import CninfoCollector
        from research_os.knowledge.repository import GraphRepository
        from research_os.llm.client import LlmClient
        from research_os.llm.providers.deepseek import DeepSeekChatCompletionsProvider

        def boom(*args, **kwargs):
            raise AssertionError("P7-D2 default path crossed a forbidden boundary")

        for collector_type in (
            ClsMetadataCollector, CninfoCollector, SinaQuoteCollector, NbsCollector,
        ):
            for method in ("healthcheck", "discover", "fetch", "normalize"):
                monkeypatch.setattr(collector_type, method, boom)
        monkeypatch.setattr(LlmClient, "generate_json", boom)
        monkeypatch.setattr(DeepSeekChatCompletionsProvider, "complete_json", boom)
        for method in (
            "append_node", "append_edge", "append_review", "append_application",
            "seed_ontology",
        ):
            monkeypatch.setattr(GraphRepository, method, boom)

        orch = Orchestrator(project)
        result = orch.execute(
            "morning_brief", {"dry_run": True, "report_date": "2026-08-11"},
        )
        assert result.exit_code == 0
        orch.close()

    def test_fresh_default_process_does_not_import_real_collector_modules(self, project):
        script = textwrap.dedent(
            f"""
            import builtins
            import pathlib
            import tempfile

            forbidden = (
                "research_os.collectors.news",
                "research_os.collectors.official",
                "research_os.collectors.market",
                "research_os.collectors.government",
                "research_os.collectors.stub",
            )
            original_import = builtins.__import__
            def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
                if any(name == prefix or name.startswith(prefix + ".") for prefix in forbidden):
                    raise AssertionError("real Collector module imported: " + name)
                return original_import(name, globals, locals, fromlist, level)
            builtins.__import__ = guarded_import

            from research_os.orchestrator import Orchestrator
            with tempfile.TemporaryDirectory() as directory:
                root = pathlib.Path(directory)
                orchestrator = Orchestrator(root)
                result = orchestrator.execute(
                    "morning_brief",
                    {{"dry_run": True, "report_date": "2026-08-11"}},
                )
                assert result.exit_code == 0, result
                orchestrator.close()
            """
        )
        completed = subprocess.run(
            [sys.executable, "-c", script], cwd=ROOT, text=True,
            capture_output=True, timeout=60, check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr


def test_production_capability_registry_has_no_business_sufficient_entry():
    from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry

    requirements = ScenarioDataRequirementRegistry(
        ROOT / "registry" / "scenario_data_requirements.yaml",
    )
    capabilities = AcquisitionCapabilityRegistry(
        ROOT / "registry" / "data_acquisition_capabilities.yaml",
        scenario_requirements=requirements,
        repo_root=ROOT,
    )
    promoted = [
        item.data_type for item in capabilities.all()
        if item.automatic_acquisition_lifecycle == "BUSINESS_SUFFICIENT"
    ]
    assert promoted == []


@pytest.mark.parametrize("scenario", DEFAULT_SCENARIOS)
def test_all_ten_registered_runner_results_pass_through_closed_foundation(
    project, monkeypatch, scenario,
):
    """Exercise every production Runner registration while isolating its business body."""
    orchestrator = Orchestrator(project)
    runner = orchestrator.registry.get(scenario)
    marker = f"runner-owned:{scenario}"
    expected_status = f"sentinel:{scenario}"
    expected_exit = DEFAULT_SCENARIOS.index(scenario) + 10

    runner.validate_request = lambda request: {
        "dry_run": True, "as_of": "2026-08-16T08:00:00+08:00",
    }
    runner.build_plan = lambda request, context: {"steps": ["sentinel"]}
    runner.execute = lambda request, context: ScenarioExecutionResult(
        status=expected_status,
        exit_code=expected_exit,
        task_id=context["task"].task_id,
        missing_data=[marker],
        message=marker,
    )
    monkeypatch.setattr(
        orchestrator,
        "_request_context",
        lambda: SimpleNamespace(
            extract=lambda selected, request: SimpleNamespace(task_entities=[]),
        ),
    )

    result = orchestrator.execute(scenario, {})
    assert result.status == expected_status
    assert result.exit_code == expected_exit
    assert result.missing_data == [marker]
    assert result.message == marker
    assert not (project / "reports" / "runs").exists()
    orchestrator.close()
