"""P8-A3-R1-HARNESS-EXPLORATION-CONTROL tests.

Covers the Exploration Execution Contract: config loading, missing-contract
refusal, turn/tool budget exits, deterministic completion detection, empty-data
no-retry, and governance invariants. All offline (no live Harness).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_os.agent_runtime.errors import ConfigurationError
from research_os.agent_runtime.exploration_contract import (
    ExplorationContract,
    ExplorationContractRegistry,
)
from research_os.agent_runtime.exploration_controller import (
    DEFAULT_MARKER_ALIASES,
    ExplorationController,
    build_contract_prompt,
    build_follow_up_prompt,
    detect_completion,
)
from research_os.agent_runtime.permission_policy import (
    HARNESS_ALLOWED_TOOLS,
    HarnessPermissionPolicy,
)
from research_os.agent_runtime.pilot_audit import RuntimeLineage


def _contract(task_id: str = "industry_exploration", **overrides) -> ExplorationContract:
    values = dict(
        task_id=task_id,
        objective="生成产业链风险探索笔记",
        allowed_tools=("query_industry_graph", "get_company_profile"),
        max_turns=3,
        max_tool_calls=6,
        turn_timeout_seconds=120,
        required_fields=("findings", "unanswered_questions", "next_actions"),
        empty_data_policy="record_data_gap_and_stop",
        failure_condition="达到 budget 仍未完成 -> exploration_incomplete",
        policy_version="1.0.0",
    )
    values.update(overrides)
    return ExplorationContract(**values)


# ---------------------------------------------------------------------------
# Contract tests
# ---------------------------------------------------------------------------

def test_contract_registry_loads_all_harness_allowed_tasks():
    registry = ExplorationContractRegistry()
    assert registry.version == "1.0.0"
    # Every HARNESS_ALLOWED task from the pilot corpus has a contract.
    from research_os.agent_runtime.pilot_corpus import PilotCorpus
    for case in PilotCorpus().exploration_cases():
        assert registry.has(case.id), case.id
        contract = registry.get(case.id)
        assert contract.max_turns >= 1
        assert contract.max_tool_calls >= 1
        assert contract.required_fields
        # Allowed tools stay within the Harness allowlist.
        assert set(contract.allowed_tools) <= HARNESS_ALLOWED_TOOLS


def test_contract_registry_missing_contract_refuses():
    registry = ExplorationContractRegistry()
    with pytest.raises(ConfigurationError, match="contract missing"):
        registry.get("no_such_task")


def test_contract_registry_rejects_tool_outside_allowlist(tmp_path):
    path = tmp_path / "exploration_policy.yaml"
    path.write_text("""
version: "1.0.0"
tasks:
  bad_task:
    objective: "x"
    allowed_tools: ["graph_write"]
    max_turns: 2
    max_tool_calls: 4
    turn_timeout_seconds: 60
    completion_rule:
      required_fields: ["findings"]
    empty_data_policy: record_data_gap_and_stop
    failure_condition: "budget -> incomplete"
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="exceed Harness allowlist"):
        ExplorationContractRegistry(path)


def test_contract_registry_rejects_missing_required_fields(tmp_path):
    path = tmp_path / "exploration_policy.yaml"
    path.write_text("""
version: "1.0.0"
tasks:
  bad_task:
    objective: "x"
    allowed_tools: ["get_company_profile"]
    max_turns: 2
    max_tool_calls: 4
    turn_timeout_seconds: 60
    completion_rule:
      required_fields: []
    empty_data_policy: record_data_gap_and_stop
    failure_condition: "budget -> incomplete"
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="required_fields"):
        ExplorationContractRegistry(path)


# ---------------------------------------------------------------------------
# Contract-bounded prompt
# ---------------------------------------------------------------------------

def test_contract_prompt_injects_boundary():
    contract = _contract()
    prompt = build_contract_prompt(contract, "任务描述内容")
    assert "objective:" in prompt
    assert "max_turns: 3" in prompt
    assert "max_tool_calls: 6" in prompt
    assert "required_output_fields" in prompt
    assert "empty_data_rule" in prompt
    assert "stop_condition" in prompt
    assert "任务描述内容" in prompt


def test_follow_up_prompt_is_bounded():
    contract = _contract()
    follow_up = build_follow_up_prompt(contract, 2)
    assert "turn 2/3" in follow_up
    assert "findings" in follow_up
    assert "不要调用更多工具" in follow_up


# ---------------------------------------------------------------------------
# Completion detection (deterministic, no LLM)
# ---------------------------------------------------------------------------

def test_completion_detects_required_markers():
    contract = _contract()
    assert detect_completion(
        "findings: 上游涨价; unanswered_questions: 传导时滞; next_actions: 跟踪产能",
        contract)
    assert not detect_completion("只有部分结论", contract)


def test_completion_uses_chinese_aliases():
    contract = _contract()
    assert detect_completion(
        "发现：价格传导; 待验证问题：传导时滞; 下一步：跟踪数据", contract)


# ---------------------------------------------------------------------------
# Budget tests (turn / tool exit, no infinite loop)
# ---------------------------------------------------------------------------

def test_controller_completes_on_first_turn_with_markers():
    calls = []

    def send_turn(prompt):
        calls.append(prompt)
        return {"status": "completed",
                "response": "findings: x; unanswered_questions: y; next_actions: z"}

    controller = ExplorationController(send_turn=send_turn, count_tool_calls=lambda: 0)
    result = controller.run(_contract(), "base")
    assert result.status == "completed"
    assert result.completion_status == "completed"
    assert result.actual_turns == 1
    assert len(calls) == 1  # no infinite loop


def test_controller_exits_on_turn_budget_exhausted():
    calls = []

    def send_turn(prompt):
        calls.append(prompt)
        return {"status": "completed", "response": "无结论"}

    contract = _contract(max_turns=2)
    controller = ExplorationController(send_turn=send_turn, count_tool_calls=lambda: 0)
    result = controller.run(contract, "base")
    assert result.status == "exploration_incomplete"
    assert result.completion_status == "budget_exhausted"
    assert result.actual_turns == 2
    assert len(calls) == 2  # bounded, no infinite loop


def test_controller_exits_on_tool_budget_exhausted():
    tool_counts = iter([3, 3])  # 3 + 3 >= 6 -> stop after turn 2

    def send_turn(prompt):
        return {"status": "completed", "response": "无结论"}

    contract = _contract(max_tool_calls=6)
    controller = ExplorationController(
        send_turn=send_turn, count_tool_calls=lambda: next(tool_counts))
    result = controller.run(contract, "base")
    assert result.status == "exploration_incomplete"
    assert result.completion_status == "budget_exhausted"
    assert result.actual_tool_calls == 6


def test_controller_budget_exit_is_bounded_not_infinite():
    calls = []

    def send_turn(prompt):
        calls.append(prompt)
        return {"status": "completed", "response": "无结论"}

    contract = _contract(max_turns=5, max_tool_calls=100)
    controller = ExplorationController(send_turn=send_turn, count_tool_calls=lambda: 0)
    result = controller.run(contract, "base")
    assert result.actual_turns == 5
    assert len(calls) == 5  # hard turn bound
    assert result.status == "exploration_incomplete"


# ---------------------------------------------------------------------------
# Empty data tests (no infinite retry)
# ---------------------------------------------------------------------------

def test_controller_stops_on_data_gap():
    calls = []

    def send_turn(prompt):
        calls.append(prompt)
        return {"status": "completed", "response": "无结论",
                "tool_results": {"query_industry_graph": {"status": "insufficient_evidence"}}}

    controller = ExplorationController(send_turn=send_turn, count_tool_calls=lambda: 1)
    result = controller.run(_contract(), "base")
    assert result.status == "data_gap_stop"
    assert result.completion_status == "data_gap"
    assert result.data_gaps == ["query_industry_graph:insufficient_evidence"]
    assert len(calls) == 1  # no auto-retry


def test_controller_data_gap_list_form():
    def send_turn(prompt):
        return {"status": "completed", "response": "无结论",
                "tool_results": [{"tool": "get_company_profile", "status": "data_degraded"}]}

    controller = ExplorationController(send_turn=send_turn, count_tool_calls=lambda: 1)
    result = controller.run(_contract(), "base")
    assert result.status == "data_gap_stop"
    assert "get_company_profile:data_degraded" in result.data_gaps


# ---------------------------------------------------------------------------
# Governance tests
# ---------------------------------------------------------------------------

def test_permission_still_fail_closed():
    policy = HarnessPermissionPolicy()
    for tool in HARNESS_ALLOWED_TOOLS:
        assert policy.check(tool).allowed
    for denied in ("graph_write", "evidence_mutation", "financial_fact_creation",
                   "direct_data_source_access"):
        assert not policy.check(denied).allowed


def test_audit_lineage_has_exploration_control_fields():
    lineage = RuntimeLineage(
        task_id="industry_exploration",
        runtime_selection="HARNESS_ALLOWED",
        runtime_selection_reason="whitelist",
        final_artifact_source="harness_exploration",
        exploration_contract="industry_exploration@1.0.0",
        max_turns=3, max_tool_calls=6,
        actual_turns=1, actual_tool_calls=2,
        completion_status="completed",
    )
    payload = lineage.as_dict()
    assert payload["exploration_contract"] == "industry_exploration@1.0.0"
    assert payload["max_turns"] == 3
    assert payload["max_tool_calls"] == 6
    assert payload["actual_turns"] == 1
    assert payload["actual_tool_calls"] == 2
    assert payload["completion_status"] == "completed"
    assert payload["final_artifact_source"] == "harness_exploration"
    # Raw content never enters.
    rendered = str(payload)
    assert "credential" not in rendered
    assert "prompt" not in payload


def test_negative_controls_have_no_exploration_contract():
    """financial_fact / research_finding / final_report are LEGACY_REQUIRED and
    must NOT have an exploration contract (they never enter Harness)."""
    registry = ExplorationContractRegistry()
    for task_id in ("financial_fact_generation", "research_finding_generation",
                    "final_report_section"):
        assert not registry.has(task_id), task_id


def test_contract_marker_aliases_cover_required_fields():
    contract = _contract()
    for field_name in contract.required_fields:
        assert field_name in DEFAULT_MARKER_ALIASES, field_name
