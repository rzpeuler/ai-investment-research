"""P8-A2-HYBRID-AGENT-RUNTIME-PILOT-IMPLEMENTATION tests.

Covers the deterministic Runtime Router, the config-driven Runtime Policy, the
fail-closed Permission Policy, the runtime-lineage Audit extension, the Pilot
Corpus (exploration only + negative controls), and the Harness Pilot adapter
wiring. All tests are offline (no live Harness).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.agent_runtime.errors import ConfigurationError, RuntimeNotReady
from research_os.agent_runtime.permission_policy import (
    HARNESS_ALLOWED_TOOLS,
    HARNESS_DENIED_TOOLS,
    HarnessPermissionPolicy,
)
from research_os.agent_runtime.pilot_adapter import HarnessPilotAdapter, PILOT_ENV
from research_os.agent_runtime.pilot_audit import PilotAuditRecorder, RuntimeLineage
from research_os.agent_runtime.pilot_corpus import PilotCorpus
from research_os.agent_runtime.runtime_router import (
    LEGACY_REQUIRED_TASKS,
    RuntimePolicy,
    RuntimeRouter,
    RuntimeSelection,
    TaskProfile,
)


# ---------------------------------------------------------------------------
# Runtime Policy (config-driven)
# ---------------------------------------------------------------------------

def test_runtime_policy_loads_from_config_artifact():
    policy = RuntimePolicy.load()
    assert policy.version == "1.0.0"
    assert policy.default_runtime == "legacy"
    assert policy.strict_schema_runtime == "legacy"
    # Exploration whitelist is present and enabled.
    assert policy.is_exploration_enabled("industry_exploration")
    assert policy.is_exploration_enabled("hypothesis_generation")
    # Hybrid is reserved (none enabled in this pilot).
    assert not policy.is_hybrid_enabled("stock_research_report")


def test_runtime_policy_rejects_legacy_required_task_in_whitelist(tmp_path):
    path = tmp_path / "runtime_policy.yaml"
    path.write_text("""
version: "1.0.0"
default_runtime: legacy
strict_schema:
  runtime: legacy
exploration_tasks:
  financial_fact_generation:
    runtime: harness
    enabled: true
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="LEGACY_REQUIRED"):
        RuntimePolicy.load(path)


def test_runtime_policy_rejects_non_legacy_default(tmp_path):
    path = tmp_path / "runtime_policy.yaml"
    path.write_text("""
version: "1.0.0"
default_runtime: harness
strict_schema:
  runtime: legacy
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="default_runtime must be legacy"):
        RuntimePolicy.load(path)


def test_runtime_policy_rejects_strict_schema_harness(tmp_path):
    path = tmp_path / "runtime_policy.yaml"
    path.write_text("""
version: "1.0.0"
default_runtime: legacy
strict_schema:
  runtime: harness
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="strict_schema runtime must be legacy"):
        RuntimePolicy.load(path)


# ---------------------------------------------------------------------------
# Runtime Router (deterministic, no LLM)
# ---------------------------------------------------------------------------

def test_router_strict_schema_always_legacy():
    router = RuntimeRouter()
    for task_type in ("extraction", "reasoning", "generation", "exploration"):
        decision = router.route(TaskProfile(
            task_id="financial_fact_generation", task_type=task_type,
            output_contract="strict_schema", risk_level="low",
            authority_requirement="read_only"))
        assert decision.selection == RuntimeSelection.LEGACY_ONLY
        assert "strict_schema" in decision.reason


def test_router_exploration_whitelist_routes_harness():
    router = RuntimeRouter()
    decision = router.route(TaskProfile(
        task_id="industry_exploration", task_type="exploration",
        output_contract="notes", risk_level="medium",
        authority_requirement="read_only"))
    assert decision.selection == RuntimeSelection.HARNESS_ALLOWED


def test_router_unlisted_task_defaults_legacy():
    router = RuntimeRouter()
    decision = router.route(TaskProfile(
        task_id="unknown_task", task_type="exploration",
        output_contract="free_text", risk_level="low",
        authority_requirement="read_only"))
    assert decision.selection == RuntimeSelection.LEGACY_ONLY
    assert "not on the harness whitelist" in decision.reason


def test_router_exploration_high_risk_stays_legacy():
    router = RuntimeRouter()
    decision = router.route(TaskProfile(
        task_id="industry_exploration", task_type="exploration",
        output_contract="notes", risk_level="high",
        authority_requirement="read_only"))
    assert decision.selection == RuntimeSelection.LEGACY_ONLY


def test_router_legacy_required_tasks_never_harness():
    router = RuntimeRouter()
    for task_id in LEGACY_REQUIRED_TASKS:
        decision = router.route(TaskProfile(
            task_id=task_id, task_type="reasoning",
            output_contract="strict_schema", risk_level="high",
            authority_requirement="write_artifact"))
        assert decision.selection == RuntimeSelection.LEGACY_ONLY, task_id


def test_router_decision_is_auditable():
    router = RuntimeRouter()
    decision = router.route(TaskProfile(
        task_id="evidence_discovery_assistance", task_type="exploration",
        output_contract="free_text", risk_level="medium",
        authority_requirement="read_only"))
    payload = decision.as_dict()
    assert payload["runtime_selection"] == "HARNESS_ALLOWED"
    assert payload["runtime_selection_reason"]
    assert payload["policy_version"] == "1.0.0"


def test_router_rejects_invalid_task_profile():
    router = RuntimeRouter()
    with pytest.raises(ConfigurationError):
        router.route(TaskProfile(task_id="x", task_type="unknown_type"))


# ---------------------------------------------------------------------------
# Permission Policy (fail-closed)
# ---------------------------------------------------------------------------

def test_permission_allows_exploration_tools():
    policy = HarnessPermissionPolicy()
    assert HARNESS_ALLOWED_TOOLS == frozenset({
        "get_company_profile", "check_data_readiness",
        "query_industry_graph", "run_research_scenario",
    })
    for tool in HARNESS_ALLOWED_TOOLS:
        assert policy.check(tool).allowed


def test_permission_denies_authority_tools():
    policy = HarnessPermissionPolicy()
    for tool in ("graph_write", "graph_apply", "graph_approve", "apply_graph_change",
                 "evidence_mutation", "financial_fact_creation",
                 "direct_data_source_access", "collector_execute", "sql_query"):
        verdict = policy.check(tool)
        assert not verdict.allowed, tool
        with pytest.raises(PermissionError):
            policy.enforce(tool)


def test_permission_fails_closed_on_unknown_tool():
    policy = HarnessPermissionPolicy()
    assert not policy.check("unknown_tool").allowed
    with pytest.raises(PermissionError):
        policy.enforce("unknown_tool")


def test_permission_denied_capabilities_complete():
    policy = HarnessPermissionPolicy()
    for capability in ("graph_write", "evidence_mutation",
                       "financial_fact_creation", "direct_source_access"):
        verdict = policy.check_capability(capability)
        assert not verdict.allowed
        assert capability in verdict.reason


def test_permission_policy_rejects_allow_deny_overlap():
    with pytest.raises(ValueError, match="conflict"):
        HarnessPermissionPolicy(allowed=frozenset({"graph_write"}), denied=frozenset({"graph_write"}))


# ---------------------------------------------------------------------------
# Audit Extension (runtime lineage)
# ---------------------------------------------------------------------------

def test_audit_records_runtime_lineage(tmp_path):
    recorder = PilotAuditRecorder(audit_dir=tmp_path)
    lineage = RuntimeLineage(
        task_id="industry_exploration",
        runtime_selection="HARNESS_ALLOWED",
        runtime_selection_reason="enabled exploration whitelist task",
        final_artifact_source="harness_exploration",
        harness_session_id="sess-1",
        skills_used=["stock-research"],
        tools_called=["get_company_profile", "query_industry_graph"],
        authority_checks=[{"allowed": True, "tool": "get_company_profile"}],
        policy_version="1.0.0",
    )
    recorder.record(lineage)
    records = recorder.records()
    assert len(records) == 1
    assert records[0]["runtime_selection"] == "HARNESS_ALLOWED"
    assert records[0]["final_artifact_source"] == "harness_exploration"
    # Raw content never enters the record.
    rendered = json.dumps(records)
    assert "prompt" not in rendered.lower() or "prompt" not in records[0]
    assert "credential" not in rendered


def test_audit_can_answer_artifact_source(tmp_path):
    recorder = PilotAuditRecorder(audit_dir=tmp_path)
    recorder.record(RuntimeLineage(
        task_id="research_finding_generation",
        runtime_selection="LEGACY_ONLY",
        runtime_selection_reason="strict_schema",
        final_artifact_source="legacy"))
    recorder.record(RuntimeLineage(
        task_id="industry_exploration",
        runtime_selection="HARNESS_ALLOWED",
        runtime_selection_reason="whitelist",
        final_artifact_source="harness_exploration"))
    assert recorder.artifact_source("research_finding_generation") == "legacy"
    assert recorder.artifact_source("industry_exploration") == "harness_exploration"
    assert recorder.artifact_source("missing_task") is None


def test_audit_query_by_runtime(tmp_path):
    recorder = PilotAuditRecorder(audit_dir=tmp_path)
    recorder.record(RuntimeLineage(task_id="a", runtime_selection="LEGACY_ONLY",
                                   runtime_selection_reason="x", final_artifact_source="legacy"))
    recorder.record(RuntimeLineage(task_id="b", runtime_selection="HARNESS_ALLOWED",
                                   runtime_selection_reason="y", final_artifact_source="harness_exploration"))
    assert len(recorder.query(runtime_selection="HARNESS_ALLOWED")) == 1
    assert len(recorder.query(task_id="a")) == 1


def test_audit_requires_task_id(tmp_path):
    recorder = PilotAuditRecorder(audit_dir=tmp_path)
    with pytest.raises(ValueError, match="task_id"):
        recorder.record(RuntimeLineage(task_id="", runtime_selection="LEGACY_ONLY",
                                       runtime_selection_reason="x", final_artifact_source="legacy"))


# ---------------------------------------------------------------------------
# Pilot Corpus
# ---------------------------------------------------------------------------

def test_pilot_corpus_contains_exploration_and_controls():
    corpus = PilotCorpus()
    exploration = corpus.exploration_cases()
    controls = corpus.control_cases()
    assert len(exploration) >= 4
    assert len(controls) >= 3
    ids = {case.id for case in exploration}
    assert {"industry_exploration", "research_preparation",
            "evidence_discovery_assistance", "analyst_assistant"} <= ids
    # Corpus never contains strict-schema generation as a Harness task.
    for case in exploration:
        assert case.output_contract != "strict_schema"
        assert case.expected == "HARNESS_ALLOWED"
    for case in controls:
        assert case.output_contract == "strict_schema"
        assert case.expected == "LEGACY_ONLY"


def test_pilot_corpus_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "corpus.yaml"
    path.write_text("""
version: "1.0.0"
cases:
  - id: a
    category: exploration
    task_type: exploration
    output_contract: notes
    risk_level: low
    authority_requirement: read_only
    prompt: "p"
    expected: HARNESS_ALLOWED
  - id: a
    category: exploration
    task_type: exploration
    output_contract: notes
    risk_level: low
    authority_requirement: read_only
    prompt: "p"
    expected: HARNESS_ALLOWED
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="duplicate"):
        PilotCorpus(path)


def test_pilot_corpus_rejects_strict_schema_as_harness(tmp_path):
    path = tmp_path / "corpus.yaml"
    path.write_text("""
version: "1.0.0"
cases:
  - id: bad
    category: exploration
    task_type: generation
    output_contract: strict_schema
    risk_level: high
    authority_requirement: write_artifact
    prompt: "p"
    expected: HARNESS_ALLOWED
""", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="LEGACY_ONLY"):
        PilotCorpus(path)


# ---------------------------------------------------------------------------
# Harness Pilot Adapter (Router -> Permission -> Runtime -> Audit)
# ---------------------------------------------------------------------------

def _offline_harness_runner(case_id: str, prompt: str) -> dict:
    return {"status": "completed", "harness_session_id": f"sess-{case_id}",
            "skills_used": ["stock-research"],
            "tools_called": ["get_company_profile", "query_industry_graph"]}


def test_pilot_adapter_requires_opt_in(monkeypatch, tmp_path):
    monkeypatch.delenv(PILOT_ENV, raising=False)
    adapter = HarnessPilotAdapter(audit=PilotAuditRecorder(audit_dir=tmp_path),
                                  harness_runner=_offline_harness_runner)
    with pytest.raises(RuntimeNotReady, match="PILOT_NOT_ENABLED"):
        adapter.run_case(PilotCorpus().get("industry_exploration"))


def test_pilot_adapter_routes_exploration_to_harness(monkeypatch, tmp_path):
    monkeypatch.setenv(PILOT_ENV, "1")
    adapter = HarnessPilotAdapter(audit=PilotAuditRecorder(audit_dir=tmp_path),
                                  harness_runner=_offline_harness_runner)
    outcome = adapter.run_case(PilotCorpus().get("industry_exploration"))
    assert outcome.runtime_used == "harness"
    assert outcome.decision.selection.value == "HARNESS_ALLOWED"
    assert outcome.final_artifact_source == "harness_exploration"
    assert outcome.harness_session_id == "sess-industry_exploration"


def test_pilot_adapter_routes_strict_schema_to_legacy(monkeypatch, tmp_path):
    monkeypatch.setenv(PILOT_ENV, "1")
    adapter = HarnessPilotAdapter(audit=PilotAuditRecorder(audit_dir=tmp_path),
                                  harness_runner=_offline_harness_runner)
    outcome = adapter.run_case(PilotCorpus().get("financial_fact_generation"))
    assert outcome.runtime_used == "legacy"
    assert outcome.final_artifact_source == "legacy"
    # No harness session was created for a legacy-routed task.
    assert not outcome.harness_session_id


def test_pilot_adapter_audits_every_case(monkeypatch, tmp_path):
    monkeypatch.setenv(PILOT_ENV, "1")
    audit = PilotAuditRecorder(audit_dir=tmp_path)
    adapter = HarnessPilotAdapter(audit=audit, harness_runner=_offline_harness_runner)
    corpus = PilotCorpus()
    for case in corpus.all():
        adapter.run_case(case)
    records = audit.records()
    assert len(records) == len(corpus.all())
    # Every record carries the lineage fields.
    for record in records:
        assert record["runtime_selection"] in {"LEGACY_ONLY", "HARNESS_ALLOWED", "HYBRID"}
        assert record["runtime_selection_reason"]
        assert record["final_artifact_source"]
        assert "harness_session_id" in record
        assert "skills_used" in record
        assert "tools_called" in record
        assert "authority_checks" in record


def test_pilot_adapter_rejects_permission_surface_mismatch(monkeypatch, tmp_path):
    monkeypatch.setenv(PILOT_ENV, "1")
    # A policy with a too-narrow allowlist must fail the harness path closed.
    from research_os.agent_runtime.permission_policy import HarnessPermissionPolicy
    narrow = HarnessPermissionPolicy(allowed=frozenset({"get_company_profile"}))
    adapter = HarnessPilotAdapter(audit=PilotAuditRecorder(audit_dir=tmp_path),
                                  permission=narrow,
                                  harness_runner=_offline_harness_runner)
    with pytest.raises(RuntimeNotReady, match="PERMISSION_MISMATCH"):
        adapter.run_case(PilotCorpus().get("industry_exploration"))


def test_pilot_runner_script_is_opt_in(monkeypatch):
    monkeypatch.delenv(PILOT_ENV, raising=False)
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "p8_a2_hybrid_pilot",
        Path(__file__).resolve().parents[2] / "scripts" / "p8_a2_hybrid_pilot.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    assert module.main() == 2
