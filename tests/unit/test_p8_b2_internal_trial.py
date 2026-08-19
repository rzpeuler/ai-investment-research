from __future__ import annotations

import json

import pytest

from research_os.agent_runtime.errors import RuntimeNotReady
from research_os.agent_runtime.trial import (
    LatchState,
    TrialBudget,
    TrialController,
    TrialMetricsRecorder,
    TrialSafetyLatch,
    _tool_counts,
)


def test_trial_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("P8_B2_INTERNAL_TRIAL", raising=False)
    controller = TrialController()
    with pytest.raises(RuntimeNotReady, match="P8_B2_INTERNAL_TRIAL"):
        controller.start()
    controller.stop()


def test_safety_latch_requires_operator_reset_after_trip():
    latch = TrialSafetyLatch()
    assert latch.state is LatchState.DISABLED
    latch.enable()
    latch.admit()
    latch.trip("authority drift")
    with pytest.raises(RuntimeNotReady, match="operator reset"):
        latch.admit()
    with pytest.raises(RuntimeNotReady, match="operator reset"):
        latch.enable()
    latch.operator_reset()
    latch.enable()
    assert latch.state is LatchState.ENABLED


def test_trial_metrics_and_tool_counts_are_bounded():
    recorder = TrialMetricsRecorder("trial-1")
    recorder.record(event_type="turn_completed", session_public_hash="abc", turn_index=1,
                    tool_counts={"get_company_profile": 1})
    rendered = json.dumps(recorder.events)
    assert "full prompt" not in rendered
    assert "full response" not in rendered
    assert _tool_counts([
        {"event_type": "tool_call", "tool_name": "get_company_profile"},
        {"event_type": "tool_call", "tool_name": "check_data_readiness"},
        {"event_type": "tool_call", "tool_name": "graph_write"},
    ]) == {"get_company_profile": 1, "check_data_readiness": 1}


def test_trial_budget_is_explicit_and_bounded():
    budget = TrialBudget()
    assert budget.max_sessions == 10
    assert budget.max_turns == 20
    assert budget.max_tool_calls > budget.max_turns
    assert budget.max_retries == 0
    assert budget.turn_timeout_seconds > 0
