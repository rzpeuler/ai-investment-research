"""P8-A4 expanded pilot corpus, contract, evaluation, and governance tests."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research_os.agent_runtime.errors import ConfigurationError
from research_os.agent_runtime.exploration_contract import ExplorationContractRegistry
from research_os.agent_runtime.permission_policy import HarnessPermissionPolicy
from research_os.agent_runtime.pilot_audit import PilotAuditRecorder, RuntimeLineage
from research_os.agent_runtime.pilot_corpus import PilotCorpus
from research_os.agent_runtime.pilot_evaluation import (
    HumanEvaluation,
    aggregate_human_evaluations,
    build_human_evaluation_template,
    forbidden_artifact_hits,
    validate_human_evaluation_document,
)
from research_os.agent_runtime.runtime_router import RuntimePolicy, RuntimeRouter, RuntimeSelection

ROOT = Path(__file__).resolve().parents[2]
EVAL_SCRIPT = ROOT / "scripts" / "p8_a4_expanded_pilot.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("p8_a4_expanded_pilot", EVAL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_expanded_corpus_has_20_exploration_and_5_controls():
    corpus = PilotCorpus()
    assert len(corpus.all()) == 25
    assert len(corpus.exploration_cases()) == 20
    assert len(corpus.control_cases()) == 5
    assert {case.category for case in corpus.exploration_cases()} >= {
        "exploration", "preparation", "discovery", "analyst"
    }
    assert all(case.expected == "HARNESS_ALLOWED" for case in corpus.exploration_cases())
    assert all(case.expected == "LEGACY_ONLY" for case in corpus.control_cases())


def test_every_expanded_harness_case_has_complete_contract_and_routes_harness():
    corpus = PilotCorpus()
    contracts = ExplorationContractRegistry()
    router = RuntimeRouter(RuntimePolicy.load())
    for case in corpus.exploration_cases():
        contract = contracts.get(case.id)
        assert contract.objective
        assert contract.allowed_tools
        assert contract.max_turns >= 1
        assert contract.max_tool_calls >= 1
        assert contract.required_fields
        assert contract.empty_data_policy == "record_data_gap_and_stop"
        assert contract.failure_condition
        assert router.route(case.profile()).selection == RuntimeSelection.HARNESS_ALLOWED


def test_contract_registry_stays_fail_closed_for_missing_expanded_case(tmp_path):
    path = tmp_path / "policy.yaml"
    path.write_text(
        """
version: "1.0.0"
tasks:
  one:
    objective: bounded
    allowed_tools: [get_company_profile]
    max_turns: 1
    max_tool_calls: 1
    turn_timeout_seconds: 1
    completion_rule:
      required_fields: [findings]
    empty_data_policy: record_data_gap_and_stop
    failure_condition: stop
""",
        encoding="utf-8",
    )
    registry = ExplorationContractRegistry(path)
    with pytest.raises(ConfigurationError, match="contract missing"):
        registry.get("missing_expanded_case")


def test_expanded_contract_tools_are_permission_subsets():
    permission = HarnessPermissionPolicy()
    contracts = ExplorationContractRegistry()
    for contract in contracts.all():
        assert set(contract.allowed_tools) <= permission.allowed


def test_audit_completeness_for_full_expanded_corpus(tmp_path):
    corpus = PilotCorpus()
    audit = PilotAuditRecorder(audit_dir=tmp_path)
    for case in corpus.all():
        audit.record(RuntimeLineage(
            task_id=case.id,
            runtime_selection=case.expected,
            runtime_selection_reason="test",
            final_artifact_source=("harness_exploration" if case.expected == "HARNESS_ALLOWED" else "legacy"),
            status="test",
        ))
    assert len(audit.records()) == 25
    assert len({record["task_id"] for record in audit.records()}) == 25


def test_human_evaluation_template_is_pending_and_validates():
    ids = ["industry_exploration", "research_preparation"]
    template = build_human_evaluation_template(ids)
    assert template["status"] == "PENDING_REVIEW"
    evaluations = validate_human_evaluation_document(template, ids)
    aggregate = aggregate_human_evaluations(evaluations)
    assert aggregate["status"] == "PENDING_REVIEW"
    assert aggregate["scored_cases"] == 0


def test_human_evaluation_rejects_out_of_range_score():
    evaluation = HumanEvaluation(case_id="case", research_usefulness=6)
    with pytest.raises(ConfigurationError, match="1 to 5"):
        evaluation.validate()


def test_human_evaluation_aggregates_only_explicit_scores():
    evaluations = [
        HumanEvaluation(case_id="a", research_usefulness=4, exploration_quality=3,
                         actionability=5, noise_rate=0.1),
        HumanEvaluation(case_id="b"),
    ]
    result = aggregate_human_evaluations(evaluations)
    assert result["status"] == "REVIEWED"
    assert result["scored_cases"] == 1
    assert result["research_usefulness"]["mean"] == 4
    assert result["noise_rate"]["mean"] == 0.1


def test_forbidden_artifact_detection_is_deterministic():
    hits = forbidden_artifact_hits("target_price and 目标价 should never enter exploration output")
    assert hits == ["target_price", "目标价"]
    assert forbidden_artifact_hits("findings; unanswered_questions; next_actions") == []


def test_a4_runner_is_opt_in(monkeypatch):
    monkeypatch.delenv("P8_A4_HYBRID_PILOT_EVAL", raising=False)
    module = _load_eval_module()
    assert module.main() == 2


def test_a4_runner_emits_degraded_report_without_provider(monkeypatch, tmp_path):
    monkeypatch.setenv("P8_A4_HYBRID_PILOT_EVAL", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    module = _load_eval_module()
    module.REPORT_PATH = tmp_path / "p8_a4.json"
    module.HUMAN_EVALUATION_PATH = tmp_path / "human.json"
    assert module.main() == 0
    report = json.loads(module.REPORT_PATH.read_text(encoding="utf-8"))
    assert report["degradation"] == "DATA_DEGRADED"
    assert report["corpus"] == {"total": 25, "exploration": 20, "controls": 5}
    assert report["reliability"]["session_attempted"] == 0
    assert report["governance"]["unauthorized_tool"] == 0
    assert json.loads(module.HUMAN_EVALUATION_PATH.read_text(encoding="utf-8"))["status"] == "PENDING_REVIEW"
