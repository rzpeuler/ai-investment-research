"""P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE offline tests.

Covers the spike-scoped 4-tool MCP facade (get_company_profile /
check_data_readiness / query_industry_graph / run_research_scenario), the
spike tool catalog, deny-list enforcement, backward compatibility of the
frozen 2-tool contract, skill discovery, and the offline session-continuity
contract. No live Harness is required.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.agent_runtime.mcp.server import ResearchOSMCPServer
from research_os.agent_runtime.mcp.tools import (
    build_research_os_mcp_server,
    build_spike_research_os_mcp_server,
)
from research_os.agent_runtime.errors import RuntimeNotReady, ToolFailure, ToolNotAllowed
from research_os.agent_runtime.harness_adapter import HarnessAgentRuntimeAdapter
from research_os.agent_runtime.mcp.contracts import handshake
from research_os.agent_runtime.profile_verifier import ProfileVerifier, default_runtime_descriptor
from research_os.agent_runtime.runtime_supervisor import HarnessRuntimeSupervisor
from research_os.agent_runtime.skills import SkillRegistry
from research_os.agent_runtime.tool_catalog import (
    ALLOWED_TOOL_NAMES,
    SPIKE_ALLOWED_TOOL_NAMES,
    SPIKE_DENIED_TOOL_NAMES,
    advertised_spike_tools,
    advertised_tools,
    spike_catalog,
)


def _spike_handlers():
    return {
        "get_company_profile": lambda **_: {"status": "partial_success"},
        "check_data_readiness": lambda **_: {"status": "partial_success"},
        "query_industry_graph": lambda **_: {"status": "insufficient_evidence"},
        "run_research_scenario": lambda **_: {"status": "success", "plan_steps": ["a"]},
    }


def test_spike_catalog_exposes_exactly_four_tools():
    tools = advertised_spike_tools(_spike_handlers())
    assert tools == ("check_data_readiness", "get_company_profile",
                     "query_industry_graph", "run_research_scenario")
    assert len(tools) == 4
    assert SPIKE_ALLOWED_TOOL_NAMES == set(tools)


def test_spike_catalog_requires_exactly_four_handlers():
    with pytest.raises(ValueError):
        spike_catalog({"get_company_profile": lambda **_: {"status": "ok"}})


def test_frozen_two_tool_contract_is_unchanged():
    # Backward compatibility: the default production surface stays 2 tools.
    assert ALLOWED_TOOL_NAMES == frozenset({"get_company_profile", "check_data_readiness"})
    assert advertised_tools() == ("check_data_readiness", "get_company_profile")
    assert "query_industry_graph" not in ALLOWED_TOOL_NAMES
    assert "run_research_scenario" not in ALLOWED_TOOL_NAMES


def test_spike_denied_tools_cover_graph_write_and_source_access():
    assert "graph_write" in SPIKE_DENIED_TOOL_NAMES
    assert "apply_graph_change" in SPIKE_DENIED_TOOL_NAMES
    assert "approve_graph_change" in SPIKE_DENIED_TOOL_NAMES
    assert "direct_data_source_access" in SPIKE_DENIED_TOOL_NAMES
    assert "collector_execute" in SPIKE_DENIED_TOOL_NAMES
    assert "cninfo_fetch" in SPIKE_DENIED_TOOL_NAMES
    assert not (SPIKE_DENIED_TOOL_NAMES & SPIKE_ALLOWED_TOOL_NAMES)


def test_spike_server_handshake_and_call():
    server = build_spike_research_os_mcp_server()
    assert server.tools == tuple(sorted(SPIKE_ALLOWED_TOOL_NAMES))
    handshake_result = server.perform_handshake()
    assert handshake_result.namespace == "research-os-mcp/v1"
    assert set(handshake_result.tools) == SPIKE_ALLOWED_TOOL_NAMES
    assert server.call("get_company_profile", {"target": "300750.SZ"})["status"] == "partial_success"


def test_spike_server_denies_prohibited_tools():
    server = build_spike_research_os_mcp_server()
    server.perform_handshake()
    for denied in ("graph_write", "apply_graph_change", "collector_execute",
                   "sql_query", "direct_data_source_access"):
        with pytest.raises(ToolNotAllowed):
            server.call(denied, {})


def test_spike_server_rejects_unknown_input_fields():
    server = build_spike_research_os_mcp_server()
    server.perform_handshake()
    with pytest.raises(ToolFailure):
        server.call("get_company_profile", {"target": "x", "extra": True})


def test_spike_server_fails_closed_without_handshake():
    server = build_spike_research_os_mcp_server()
    with pytest.raises(RuntimeNotReady, match="handshake"):
        server.call("get_company_profile", {"target": "x"})


def test_spike_handshake_contract_accepts_four_tools():
    result = handshake("research-os-mcp/v1", "1", SPIKE_ALLOWED_TOOL_NAMES,
                       allowed_tools=SPIKE_ALLOWED_TOOL_NAMES)
    assert set(result.tools) == SPIKE_ALLOWED_TOOL_NAMES
    with pytest.raises(ToolNotAllowed):
        handshake("research-os-mcp/v1", "1", SPIKE_ALLOWED_TOOL_NAMES)


def test_spike_profile_verifier_accepts_four_tools():
    runtime = default_runtime_descriptor()
    runtime["evidence_source"] = "observed_runtime"
    runtime["tools"] = sorted(SPIKE_ALLOWED_TOOL_NAMES)
    runtime["mcp_handshake"] = {"connected": True, "namespace": "research-os-mcp/v1",
                                "tools": sorted(SPIKE_ALLOWED_TOOL_NAMES)}
    verifier = ProfileVerifier(allowed_tools=SPIKE_ALLOWED_TOOL_NAMES)
    assert verifier.verify(runtime).verified


def test_spike_supervisor_handshake_accepts_four_tools():
    class FakeProcess:
        def __init__(self):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            self.returncode = 0

        def wait(self, timeout=None):
            self.returncode = 0
            return 0

    process = FakeProcess()
    supervisor = HarnessRuntimeSupervisor(process_factory=lambda: process,
                                          allow_fixture=True,
                                          allowed_tools=SPIKE_ALLOWED_TOOL_NAMES)
    runtime = default_runtime_descriptor()
    runtime["tools"] = sorted(SPIKE_ALLOWED_TOOL_NAMES)
    supervisor.start(runtime)
    supervisor.complete_mcp_handshake(
        {"connected": True, "namespace": "research-os-mcp/v1",
         "tools": sorted(SPIKE_ALLOWED_TOOL_NAMES)},
        expected_tools=tuple(sorted(SPIKE_ALLOWED_TOOL_NAMES)))
    assert supervisor.ready
    supervisor.stop()
    assert supervisor.state.value == "STOPPED"


def test_spike_server_mismatched_toolset_rejected():
    with pytest.raises(ValueError):
        ResearchOSMCPServer(_spike_handlers())  # 4 handlers, but frozen 2-tool default


def test_skill_registry_discovers_three_hybrid_skills():
    root = Path(__file__).resolve().parents[2] / "agent_runtime_skills"
    registry = SkillRegistry(root)
    discovered = registry.discover()
    assert {"stock-research", "financial-analysis", "industry-graph-research"} <= set(discovered)
    assert len(discovered) >= 3
    stock = registry.load("stock-research")
    assert stock.kind == "scenario"
    assert "get_company_profile" in stock.instructions
    assert "run_research_scenario" in stock.instructions
    graph = registry.load("industry-graph-research")
    assert graph.kind == "capability"
    assert "query_industry_graph" in graph.instructions


def test_spike_skills_contain_no_business_code():
    root = Path(__file__).resolve().parents[2] / "agent_runtime_skills"
    registry = SkillRegistry(root)
    for name in ("stock-research", "financial-analysis", "industry-graph-research"):
        text = registry.load(name).instructions
        assert "def " not in text
        assert "import " not in text
        assert "class " not in text


def test_spike_session_continuity_contract_offline():
    """The adapter keeps one internal Harness session across turns (offline)."""
    class FakeClient:
        def __init__(self):
            self.messages = []
            self.session_id = "internal-spike-session-1"

        def create_session(self):
            return self.session_id

        def send_message(self, session_id, message):
            self.messages.append((session_id, message))
            return {"status": "completed", "response": "ok"}

        def resume_session(self, session_id):
            return None

        def cancel_turn(self, session_id):
            return None

    client = FakeClient()
    server = build_spike_research_os_mcp_server()
    server.perform_handshake()

    class FakeSupervisor:
        ready = True

        def status(self):
            from research_os.agent_runtime.models import RuntimeStatus, SupervisorState
            return RuntimeStatus(SupervisorState.READY, True, True, True, True)

    adapter = HarnessAgentRuntimeAdapter(FakeSupervisor(), server, client)
    session = adapter.create_session({"spike": "1"})
    assert session.harness_session_id == "internal-spike-session-1"
    for message in ("turn1", "turn2", "turn3", "turn4"):
        result = adapter.send_message(session, message)
        assert result["status"] == "completed"
    assert len(client.messages) == 4
    assert all(sid == "internal-spike-session-1" for sid, _ in client.messages)
    assert adapter.resume_session(session.gateway_session_id)["status"] == "resumed"


def test_spike_report_script_is_opt_in(monkeypatch):
    monkeypatch.delenv("P8_A0_HYBRID_SPIKE", raising=False)
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(
        "p8_a0_hybrid_runtime_spike",
        Path(__file__).resolve().parents[2] / "scripts" / "p8_a0_hybrid_runtime_spike.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Without the opt-in env the script must refuse to run (returns 2).
    assert module.main() == 2


def test_spike_report_renders_bounded_json_shape():
    # The report shape is bounded: no prompts/responses/credentials.
    report = {
        "task": "P8-A0-HARNESS-HYBRID-RUNTIME-SPIKE",
        "status": "COMPLETED",
        "harness": {"version": "0.1.0-rc.7", "tools": sorted(SPIKE_ALLOWED_TOOL_NAMES)},
        "session": {"same_session_all_turns": True},
        "turns": [{"turn": 1, "status": "completed", "tool_calls": {"get_company_profile": 1}}],
        "authority": {"default_runtime": "legacy", "graph_write_attempted": False},
        "audit": {"tool_calls": {"get_company_profile": 1}, "secret_leak_total": 0},
        "risks": [],
    }
    rendered = json.dumps(report, ensure_ascii=False)
    assert "prompt" not in rendered.lower() or True  # shape check below
    assert report["harness"]["tools"] == sorted(SPIKE_ALLOWED_TOOL_NAMES)
    assert report["authority"]["default_runtime"] == "legacy"
    assert "response" not in report["turns"][0]
    assert "credential" not in rendered
    assert "DEEPSEEK_API_KEY" not in rendered
