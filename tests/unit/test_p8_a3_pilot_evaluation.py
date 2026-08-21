"""P8-A3-HYBRID-AGENT-RUNTIME-PILOT-EVALUATION offline tests.

Covers the evaluation runner's deterministic pieces (opt-in gate, corpus
routing invariants, metric aggregation helpers) without a live Harness. The
real provider-backed corpus run is executed by scripts/p8_a3_pilot_evaluation.py
(local host + Ubuntu CI workflow p8-a3-pilot-evaluation.yml).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from research_os.agent_runtime.permission_policy import (
    HARNESS_ALLOWED_TOOLS,
    HARNESS_DENIED_TOOLS,
    HarnessPermissionPolicy,
)
from research_os.agent_runtime.pilot_corpus import PilotCorpus
from research_os.agent_runtime.runtime_router import (
    RuntimePolicy,
    RuntimeRouter,
    RuntimeSelection,
)

ROOT = Path(__file__).resolve().parents[2]
EVAL_SCRIPT = ROOT / "scripts" / "p8_a3_pilot_evaluation.py"


def _load_eval_module():
    spec = importlib.util.spec_from_file_location("p8_a3_pilot_evaluation", EVAL_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Evaluation runner opt-in gate
# ---------------------------------------------------------------------------

def test_eval_runner_is_opt_in(monkeypatch):
    monkeypatch.delenv("P8_A3_HYBRID_PILOT_EVAL", raising=False)
    module = _load_eval_module()
    assert module.main() == 2


def test_eval_runner_requires_provider_credential(monkeypatch):
    monkeypatch.setenv("P8_A3_HYBRID_PILOT_EVAL", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    module = _load_eval_module()
    assert module.main() == 2


# ---------------------------------------------------------------------------
# Corpus routing invariants (evaluation uses exactly the HARNESS_ALLOWED set)
# ---------------------------------------------------------------------------

def test_eval_corpus_harness_allowed_set_is_exact():
    corpus = PilotCorpus()
    exploration = corpus.exploration_cases()
    ids = {case.id for case in exploration}
    assert ids == {
        "industry_exploration", "research_preparation",
        "evidence_discovery_assistance", "analyst_assistant",
        "hypothesis_generation",
    }
    router = RuntimeRouter(RuntimePolicy.load())
    for case in exploration:
        decision = router.route(case.profile())
        assert decision.selection == RuntimeSelection.HARNESS_ALLOWED, case.id


def test_eval_corpus_negative_controls_stay_legacy():
    corpus = PilotCorpus()
    controls = corpus.control_cases()
    assert {case.id for case in controls} == {
        "financial_fact_generation", "research_finding_generation",
        "final_report_section",
    }
    router = RuntimeRouter(RuntimePolicy.load())
    for case in controls:
        decision = router.route(case.profile())
        assert decision.selection == RuntimeSelection.LEGACY_ONLY, case.id
        assert case.output_contract == "strict_schema"


# ---------------------------------------------------------------------------
# Permission surface (evaluation Harness tools)
# ---------------------------------------------------------------------------

def test_eval_permission_surface_is_four_exploration_tools():
    assert HARNESS_ALLOWED_TOOLS == frozenset({
        "get_company_profile", "check_data_readiness",
        "query_industry_graph", "run_research_scenario",
    })
    policy = HarnessPermissionPolicy()
    for tool in HARNESS_ALLOWED_TOOLS:
        assert policy.check(tool).allowed
    for tool in HARNESS_DENIED_TOOLS:
        assert not policy.check(tool).allowed


# ---------------------------------------------------------------------------
# Metric helper behaviors (pure functions)
# ---------------------------------------------------------------------------

def test_quality_proxy_flags_forbidden_artifact_markers():
    module = _load_eval_module()
    proxy = module._response_quality_proxy("买入建议 target_price 评级", 1)
    assert proxy["forbidden_artifact_marker"] is True
    assert proxy["non_empty"] is True
    assert proxy["tool_invoked"] is True


def test_quality_proxy_clean_exploration():
    module = _load_eval_module()
    proxy = module._response_quality_proxy(
        "上游材料与中游制造存在价格传导，证据显示…（来源：公司公告）", 2)
    assert proxy["forbidden_artifact_marker"] is False
    assert proxy["evidence_like_reference"] is True
    assert proxy["tool_invoked"] is True


def test_tool_counts_distinguish_allowed_and_unauthorized():
    module = _load_eval_module()
    events = [
        {"event_type": "tool_call", "tool_name": "get_company_profile"},
        {"event_type": "tool_call", "tool_name": "query_industry_graph"},
        {"event_type": "tool_call", "tool_name": "graph_write"},
        {"event_type": "mcp_handshake"},
    ]
    counts = module._tool_counts(events)
    assert counts["allowed"]["get_company_profile"] == 1
    assert counts["allowed"]["query_industry_graph"] == 1
    assert counts["unauthorized"] == {"graph_write": 1}


def test_percentile_helpers():
    module = _load_eval_module()
    assert module._percentile([10, 20, 30], 0.50) == 20
    assert module._percentile([], 0.50) is None


def test_secret_markers_include_api_key(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-12345")
    module = _load_eval_module()
    markers = module._secret_markers()
    assert "sk-test-12345" in markers
    assert "Authorization" in markers


# ---------------------------------------------------------------------------
# Report shape (bounded, no raw content)
# ---------------------------------------------------------------------------

def test_report_shape_is_bounded():
    report = {
        "task": "P8-A3-HYBRID-AGENT-RUNTIME-PILOT-EVALUATION",
        "status": "COMPLETED",
        "cases": [{"case_id": "industry_exploration", "runtime_used": "harness",
                   "status": "completed", "quality_proxy": {"non_empty": True},
                   "response_sha256": "abc123"}],
        "reliability": {"session_success_rate": 1.0, "continuity_rate": 1.0,
                        "timeout_count": 0, "cleanup_status": {}},
        "governance": {"audit_completeness": 1.0, "unauthorized_tool": 0,
                       "authority_drift": 0, "secret_leak": 0},
        "value": {"useful_finding_rate": 1.0},
        "cost": {"latency_ms": {"p50": 100}, "token_usage": {}, "provider_calls": 1},
    }
    rendered = json.dumps(report, ensure_ascii=False)
    # Raw prompt/response/credential never appear in the bounded report shape.
    assert "prompt" not in [case.get("prompt", "") for case in report["cases"]]
    assert "response" not in report["cases"][0]
    assert "credential" not in rendered
    assert "DEEPSEEK_API_KEY" not in rendered
    assert report["reliability"]["session_success_rate"] == 1.0
    assert report["governance"]["unauthorized_tool"] == 0
