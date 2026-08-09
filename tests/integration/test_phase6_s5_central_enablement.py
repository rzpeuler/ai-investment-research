"""P6-S5 default registry and seven-scenario public-entry acceptance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.orchestrator import Orchestrator, RunDirectory
from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES, DEFAULT_SCENARIOS
from research_os.orchestrator.runners.morning_brief import MorningBriefScenarioRunner
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.storage import Database


PHASE6_REQUESTS = {
    "evening_brief": {
        "report_date": "2026-08-06", "as_of": "2026-08-06T20:00:00+08:00", "force": True,
    },
    "daily_review": {
        "review_business_date": "2026-08-06", "as_of": "2026-08-06T20:00:00+08:00",
        "previous_cutoff": "2026-08-05T20:00:00+08:00", "force": True,
    },
    "stock_review": {
        "entity": "company:solar", "review_start": "2026-08-06",
        "review_end": "2026-08-06", "as_of": "2026-08-06T20:00:00+08:00",
        "previous_cutoff": "2026-08-05T20:00:00+08:00", "force": True,
    },
    "industry_research": {
        "industry_id": "sw1:semi", "industry_name": "Semiconductors",
        "as_of": "2026-08-06T20:00:00+08:00", "depth": "standard", "force": True,
    },
    "theme_discovery": {
        "as_of": "2026-08-06T20:00:00+08:00", "discovery_mode": "keyword_sweep",
        "keywords": ["AI"], "force": True,
    },
    "earnings_expectation": {
        "company_entity_id": "company:600000.SH", "as_of": "2025-08-01T12:00:00+08:00",
        "forecast_period": {
            "start": "2025-01-01", "end": "2026-12-31", "periods": ["FY2025", "FY2026"],
        },
        "assumptions": [{
            "driver": "revenue_growth", "value": "0.10", "unit": "ratio",
            "period": "annual", "source_type": "user_input", "source_ref_ids": [],
            "evidence_ids": [], "confidence": 0.7, "invalidates_when": "new disclosure",
            "known_at": "2025-08-01T12:00:00+08:00",
        }],
    },
    "first_coverage": {
        "company_entity_id": "company:600000.SH",
        "security_entity_id": "security:600000.SH",
        "industry_id": "sw1:semi", "industry_name": "Semiconductors",
        "as_of": "2025-08-01T12:00:00+08:00",
    },
}


def _database(root: Path) -> Database:
    database = Database(root / "data" / "sqlite" / "research.db")
    database.initialize()
    return database


def _task_schema_scenarios() -> set[str]:
    schema = Path(__file__).resolve().parents[2] / "schemas" / "task.schema.json"
    payload = json.loads(schema.read_text(encoding="utf-8"))
    return set(payload["properties"]["scenario"]["enum"])


def test_default_registry_matches_task_schema_and_has_unique_runner_ids(tmp_path):
    orchestrator = Orchestrator(tmp_path)
    try:
        ids = [runner_type.scenario for runner_type in DEFAULT_RUNNER_TYPES]
        assert len(ids) == len(set(ids))
        assert tuple(ids) == DEFAULT_SCENARIOS
        assert set(orchestrator.registry.names()) == _task_schema_scenarios()
        for runner_type in DEFAULT_RUNNER_TYPES:
            runner = orchestrator.registry.get(runner_type.scenario)
            assert type(runner) is runner_type
            assert runner.scenario == runner_type.scenario
    finally:
        orchestrator.close()


def test_custom_registry_remains_isolated(tmp_path):
    registry = ScenarioRegistry()
    registry.register(MorningBriefScenarioRunner())
    orchestrator = Orchestrator(tmp_path, registry=registry)
    try:
        assert tuple(orchestrator.registry.names()) == ("morning_brief",)
    finally:
        orchestrator.close()


@pytest.mark.parametrize("scenario", tuple(PHASE6_REQUESTS))
def test_seven_scenarios_execute_through_default_registry_non_dry_run(tmp_path, scenario):
    root = tmp_path / scenario
    database = _database(root)
    orchestrator = Orchestrator(root, db=database)
    try:
        result = orchestrator.execute(scenario, dict(PHASE6_REQUESTS[scenario]))
        assert result.status in {
            "success", "partial_success", "degraded", "insufficient_evidence",
        }, result.message
        assert result.exit_code == 0
        run_dir = Path(result.run_dir)
        filenames = {path.name for path in run_dir.iterdir()}
        expected = {
            "task.json", "plan.json", "validation.json", "scenario_execution_result.json",
            f"{scenario}_request.json", f"{scenario}_run.json",
        }
        assert expected.issubset(filenames)
        assert "run.json" not in filenames

        task = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        request = json.loads((run_dir / f"{scenario}_request.json").read_text(encoding="utf-8"))
        run = json.loads((run_dir / f"{scenario}_run.json").read_text(encoding="utf-8"))
        execution = json.loads(
            (run_dir / "scenario_execution_result.json").read_text(encoding="utf-8")
        )
        assert {
            task["task_id"], plan["task_id"], request["task_id"], run["task_id"],
            execution["task_id"], result.task_id,
        } == {result.task_id}
    finally:
        orchestrator.close()


@pytest.mark.parametrize("scenario", tuple(PHASE6_REQUESTS))
def test_lineage_gate_rejects_each_phase6_scenario(tmp_path, scenario):
    task_id = "77777777-7777-4777-8777-777777777777"
    run_dir = RunDirectory(tmp_path / "reports" / "runs", task_id)
    run_dir.create()
    run_dir.write_json(f"{scenario}_run.json", {"task_id": "WRONG"})
    with pytest.raises(ValueError, match="Task ID 断链"):
        Orchestrator._validate_business_lineage(run_dir, task_id)


def test_real_cli_e2e_uses_default_industry_runner(tmp_path, monkeypatch):
    root = tmp_path / "cli-project"
    source_schemas = Path(__file__).resolve().parents[2] / "schemas"
    import shutil

    shutil.copytree(source_schemas, root / "schemas")
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(root))
    request_path = root / "industry-request.json"
    request_path.write_text(json.dumps(PHASE6_REQUESTS["industry_research"]), encoding="utf-8")

    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"] == "insufficient_evidence"
    assert payload["exit_code"] == 0
    run_dir = Path(payload["run_dir"])
    persisted = json.loads(
        (run_dir / "scenario_execution_result.json").read_text(encoding="utf-8")
    )
    for key in ("task_id", "status", "exit_code", "run_id", "validation_status"):
        assert persisted[key] == payload[key]
