"""P6-S5 public CLI routing, parity, and fail-closed tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import SCENARIO_CHOICES, cli
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


REAL_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
PHASE6_SCENARIOS = (
    "evening_brief",
    "daily_review",
    "stock_review",
    "industry_research",
    "theme_discovery",
    "earnings_expectation",
    "first_coverage",
)
TASK_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(REAL_SCHEMAS, root / "schemas")
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(root))
    return root


def _write_request(root: Path, payload, name: str = "request.json") -> Path:
    path = root / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _fake_result(task_id: str = TASK_ID, *, status: str = "success", exit_code: int = 0):
    return ScenarioExecutionResult(
        status=status,
        exit_code=exit_code,
        task_id=task_id,
        validation_status="pass",
        message="test result",
    )


def test_cli_scenarios_match_task_schema():
    payload = json.loads((REAL_SCHEMAS / "task.schema.json").read_text(encoding="utf-8"))
    schema_scenarios = set(payload["properties"]["scenario"]["enum"])
    assert set(SCENARIO_CHOICES) == schema_scenarios


@pytest.mark.parametrize("scenario", PHASE6_SCENARIOS)
def test_execute_routes_all_phase6_scenarios(project_root, monkeypatch, scenario):
    seen = []

    def fake_execute(self, actual_scenario, request):
        seen.append((actual_scenario, request))
        return _fake_result()

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = _write_request(
        project_root,
        {"scenario": scenario, "as_of": "2026-08-06T20:00:00+08:00", "marker": scenario},
        f"{scenario}.json",
    )
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", scenario, "--request-file", str(request_path),
    ])

    assert result.exit_code == 0, result.output
    assert seen == [(scenario, {
        "as_of": "2026-08-06T20:00:00+08:00", "marker": scenario,
    })]
    assert json.loads(result.output)["status"] == "success"


@pytest.mark.parametrize("request_payload", [{}, {"task_id": TASK_ID}])
def test_execute_task_id_injects_and_preserves_matching_value(
    project_root, monkeypatch, request_payload,
):
    seen = []

    def fake_execute(self, scenario, request):
        seen.append(request)
        return _fake_result(request["task_id"])

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = _write_request(project_root, request_payload)
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research",
        "--request-file", str(request_path), "--task-id", TASK_ID,
    ])
    assert result.exit_code == 0, result.output
    assert seen == [{"task_id": TASK_ID}]


@pytest.mark.parametrize("raw", ["{not-json", "[]", '"text"', "null"])
def test_execute_rejects_malformed_or_non_object_before_orchestrator(
    project_root, monkeypatch, raw,
):
    called = False

    def fake_execute(self, scenario, request):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = project_root / "bad.json"
    request_path.write_text(raw, encoding="utf-8")
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code != 0
    assert called is False
    assert not (project_root / "reports" / "runs").exists()


def test_execute_rejects_scenario_conflict_before_orchestrator(project_root, monkeypatch):
    called = False

    def fake_execute(self, scenario, request):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = _write_request(project_root, {"scenario": "theme_discovery"})
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code != 0
    assert "scenario 冲突" in result.output
    assert called is False


def test_execute_rejects_task_id_conflict_before_orchestrator(project_root, monkeypatch):
    called = False

    def fake_execute(self, scenario, request):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = _write_request(
        project_root, {"task_id": "66666666-6666-4666-8666-666666666666"},
    )
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
        "--task-id", TASK_ID,
    ])
    assert result.exit_code != 0
    assert "task_id 冲突" in result.output
    assert called is False


def test_insufficient_evidence_is_zero_exit_business_outcome(project_root, monkeypatch):
    monkeypatch.setattr(
        "research_os.cli.main.Orchestrator.execute",
        lambda self, scenario, request: _fake_result(
            status="insufficient_evidence", exit_code=0,
        ),
    )
    request_path = _write_request(project_root, {})
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "insufficient_evidence"


def test_execute_uses_scenario_result_exit_code(project_root, monkeypatch):
    monkeypatch.setattr(
        "research_os.cli.main.Orchestrator.execute",
        lambda self, scenario, request: _fake_result(status="failed", exit_code=5),
    )
    request_path = _write_request(project_root, {})
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code == 5
    assert json.loads(result.output)["exit_code"] == 5


def test_execute_rejects_non_utf8_before_orchestrator(project_root, monkeypatch):
    called = False

    def fake_execute(self, scenario, request):
        nonlocal called
        called = True
        return _fake_result()

    monkeypatch.setattr("research_os.cli.main.Orchestrator.execute", fake_execute)
    request_path = project_root / "non-utf8.json"
    request_path.write_bytes(b"\xff\xfe")
    result = CliRunner().invoke(cli, [
        "execute", "--scenario", "industry_research", "--request-file", str(request_path),
    ])
    assert result.exit_code != 0
    assert "UTF-8" in result.output
    assert called is False


def test_execute_help_lists_public_contract():
    result = CliRunner().invoke(cli, ["execute", "--help"])
    assert result.exit_code == 0, result.output
    for option in ("--scenario", "--request-file", "--task-id"):
        assert option in result.output
