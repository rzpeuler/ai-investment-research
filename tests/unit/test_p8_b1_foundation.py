from __future__ import annotations

import json
from pathlib import Path

import pytest

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.errors import ConfigurationError, RuntimeNotReady, ToolFailure, ToolNotAllowed
from research_os.agent_runtime.gateway import AgentRuntimeGateway
from research_os.agent_runtime.harness_adapter import HarnessAgentRuntimeAdapter
from research_os.agent_runtime.mcp.server import ResearchOSMCPServer
from research_os.agent_runtime.models import SupervisorState
from research_os.agent_runtime.observability import EventRecorder, redact
from research_os.agent_runtime.profile_verifier import ProfileVerifier, default_runtime_descriptor
from research_os.agent_runtime.profile_verifier import FORBIDDEN_COMPONENT_IDS_RC7
from research_os.agent_runtime.production_runtime import OfficialHarnessClient, sanitize_public_result
from research_os.agent_runtime.runtime_supervisor import HarnessRuntimeSupervisor
from research_os.agent_runtime.tool_catalog import ALLOWED_TOOL_NAMES, advertised_tools
from research_os.agent_runtime.legacy_adapter import LegacyAgentRuntimeAdapter


class FakeProcess:
    def __init__(self):
        self.returncode = None
        self.terminated = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 0

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class FakeHarnessClient:
    def __init__(self):
        self.messages: list[tuple[str, str]] = []
        self.cancelled: list[str] = []

    def create_session(self):
        return "internal-session-1"

    def send_message(self, session_id, message):
        self.messages.append((session_id, message))
        return {"status": "accepted", "message": message}

    def resume_session(self, session_id):
        return None

    def cancel_turn(self, session_id):
        self.cancelled.append(session_id)


def ready_supervisor():
    supervisor = HarnessRuntimeSupervisor(process_factory=FakeProcess, allow_fixture=True)
    supervisor.start(default_runtime_descriptor())
    supervisor.complete_mcp_handshake({"connected": True, "namespace": "research-os-mcp/v1",
                                       "tools": ["check_data_readiness", "get_company_profile"]})
    return supervisor


def test_default_config_is_legacy_and_client_cannot_override(monkeypatch):
    monkeypatch.delenv("AGENT_RUNTIME_MODE", raising=False)
    monkeypatch.delenv("agent_runtime_mode", raising=False)
    assert AgentRuntimeConfig.from_env().mode == "legacy"
    with pytest.raises(ConfigurationError):
        AgentRuntimeConfig.from_request({"runtime_mode": "harness"})


def test_config_rejects_floating_or_wrong_harness_version():
    with pytest.raises(ConfigurationError):
        AgentRuntimeConfig(harness_version="latest").validate()
    with pytest.raises(ConfigurationError):
        AgentRuntimeConfig(mode="other").validate()


def test_profile_verifier_is_exact_and_fail_closed():
    verified = ProfileVerifier().verify(default_runtime_descriptor(), allow_fixture=True)
    assert verified.verified
    extra = default_runtime_descriptor()
    extra["tools"] = sorted(ALLOWED_TOOL_NAMES | {"graph_write"})
    with pytest.raises(RuntimeNotReady) as exc:
        ProfileVerifier().verify(extra)
    assert exc.value.code == "PROFILE_POLICY_MISMATCH"


def test_public_result_sanitizer_removes_internal_session_id_recursively():
    secret = "internal-session-secret-123"
    result = sanitize_public_result({
        "status": "completed",
        "response": {"text": "ok", "nested": {"session_id": secret}},
        "session_id": secret,
    }, forbidden_values=(secret,))
    rendered = json.dumps(result)
    assert "session_id" not in rendered
    assert secret not in rendered
    assert set(result) == {"status", "response"}


def test_official_client_send_message_result_has_no_internal_session_id(monkeypatch):
    client = OfficialHarnessClient("http://127.0.0.1:1")
    internal = "internal-session-secret-123"

    def rpc(method, payload):
        if method == "session.prompt":
            return {"accepted": True}
        if method == "session.history":
            return {"events": [{"event": {"data": "prompt"}}, {"event": {"data": "answer"}}]}
        if method == "session.list":
            return {"items": [{"sessionId": internal, "running": False}]}
        raise AssertionError(method)

    monkeypatch.setattr(client, "_rpc", rpc)
    result = client.send_message(internal, "hello")
    assert internal not in json.dumps(result)
    assert set(result) == {"status", "response"}


def test_profile_verifier_fail_closed_for_enabled_or_missing_component_evidence():
    runtime = default_runtime_descriptor()
    runtime["evidence_source"] = "observed_runtime"
    runtime["mcp_handshake"] = {"connected": True, "namespace": "research-os-mcp/v1",
                                 "tools": ["check_data_readiness", "get_company_profile"]}
    runtime["enabled_component_ids"] = ["tool-bash"]
    with pytest.raises(RuntimeNotReady, match="enabled"):
        ProfileVerifier().verify(runtime)

    runtime = default_runtime_descriptor()
    runtime["evidence_source"] = "observed_runtime"
    runtime["mcp_handshake"] = {"connected": True, "namespace": "research-os-mcp/v1",
                                 "tools": ["check_data_readiness", "get_company_profile"]}
    runtime["disabled_component_ids"] = []
    runtime["observed_component_ids"] = ["agent"]
    runtime["absent_forbidden_component_ids"] = []
    with pytest.raises(RuntimeNotReady, match="incomplete"):
        ProfileVerifier().verify(runtime)


def test_profile_verifier_allows_complete_verified_absence_only():
    runtime = default_runtime_descriptor()
    runtime.update({
        "evidence_source": "observed_runtime",
        "observed_component_ids": ["agent"],
        "disabled_component_ids": [],
        "enabled_component_ids": [],
        "absent_forbidden_component_ids": sorted({
            component_id for ids in FORBIDDEN_COMPONENT_IDS_RC7.values() for component_id in ids
        }),
        "mcp_handshake": {"connected": True, "namespace": "research-os-mcp/v1",
                          "tools": ["check_data_readiness", "get_company_profile"]},
    })
    assert ProfileVerifier().verify(runtime).verified


def test_supervisor_separates_process_alive_from_ready_and_owns_cleanup():
    process = FakeProcess()
    supervisor = HarnessRuntimeSupervisor(process_factory=lambda: process, allow_fixture=True)
    status = supervisor.start(default_runtime_descriptor())
    assert status.process_alive and not status.ready
    assert supervisor.state is SupervisorState.STARTING
    supervisor.complete_mcp_handshake({"connected": True, "namespace": "research-os-mcp/v1",
                                       "tools": ["check_data_readiness", "get_company_profile"]})
    assert supervisor.ready
    supervisor.stop()
    assert process.terminated
    assert supervisor.state is SupervisorState.STOPPED


def test_fabricated_descriptor_cannot_create_ready_without_fixture_mode():
    supervisor = HarnessRuntimeSupervisor(process_factory=FakeProcess)
    with pytest.raises(RuntimeNotReady, match="fabricated"):
        supervisor.start(default_runtime_descriptor())


def test_ready_requires_actual_handshake_evidence():
    supervisor = HarnessRuntimeSupervisor(process_factory=FakeProcess, allow_fixture=True)
    supervisor.start(default_runtime_descriptor())
    with pytest.raises(RuntimeNotReady, match="handshake evidence"):
        supervisor.mark_mcp_ready()


def test_supervisor_requires_credential_before_start(monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    supervisor = HarnessRuntimeSupervisor(process_factory=FakeProcess, allow_fixture=True)
    with pytest.raises(RuntimeNotReady) as exc:
        supervisor.start(default_runtime_descriptor(), require_credential=True)
    assert exc.value.code == "PROVIDER_AUTH_MISSING"
    assert supervisor.process is None


def test_mcp_handshake_and_exact_two_read_tools():
    server = ResearchOSMCPServer({
        "get_company_profile": lambda **_: {"status": "partial_success"},
        "check_data_readiness": lambda **_: {"status": "partial_success"},
    })
    assert advertised_tools() == ("check_data_readiness", "get_company_profile")
    assert server.perform_handshake().namespace == "research-os-mcp/v1"
    assert server.call("get_company_profile", {"target": "600519.SH"})["status"] == "partial_success"
    with pytest.raises(ToolNotAllowed):
        server.call("graph_write", {})
    with pytest.raises(ToolFailure):
        server.call("check_data_readiness", {"target": "x", "extra": True})


def test_mcp_fails_closed_on_large_result():
    server = ResearchOSMCPServer({
        "get_company_profile": lambda **_: {"payload": "x" * (64 * 1024)},
        "check_data_readiness": lambda **_: {"status": "partial_success"},
    })
    server.perform_handshake()
    with pytest.raises(ToolFailure, match="TOOL_RESULT_TOO_LARGE"):
        server.call("get_company_profile", {"target": "x"})


def test_harness_gateway_uses_opaque_session_and_continuation():
    client = FakeHarnessClient()
    adapter = HarnessAgentRuntimeAdapter(
        ready_supervisor(),
        ResearchOSMCPServer({
            "get_company_profile": lambda **_: {"status": "partial_success"},
            "check_data_readiness": lambda **_: {"status": "partial_success"},
        }),
        client,
    )
    adapter.mcp.perform_handshake()
    gateway = AgentRuntimeGateway(AgentRuntimeConfig(mode="harness"), harness=adapter)
    session = gateway.create_session()
    assert session.gateway_session_id.startswith("gw_")
    assert session.gateway_session_id != session.harness_session_id
    assert gateway.send_message(session.gateway_session_id, "continue")["status"] == "accepted"
    gateway.resume_session(session.gateway_session_id)
    gateway.cancel_turn(session.gateway_session_id)
    assert client.messages == [("internal-session-1", "continue")]
    assert client.cancelled == ["internal-session-1"]


def test_harness_admission_failure_falls_back_once_before_workflow():
    class BrokenHarness:
        def create_session(self, _metadata=None):
            raise RuntimeNotReady("MCP_UNAVAILABLE", "fixture unavailable")

    gateway = AgentRuntimeGateway(
        AgentRuntimeConfig(mode="harness"),
        legacy=LegacyAgentRuntimeAdapter(),
        harness=BrokenHarness(),
    )
    session = gateway.create_session()
    result = gateway.send_message(session.gateway_session_id, "hello")
    assert result["fallback_reason"] == "MCP_UNAVAILABLE"
    assert session.runtime_mode == "legacy"


def test_gateway_enforces_turn_and_active_session_limits():
    config = AgentRuntimeConfig(mode="legacy", max_turns=1, max_active_sessions=1)
    gateway = AgentRuntimeGateway(config)
    session = gateway.create_session()
    gateway.send_message(session.gateway_session_id, "one")
    with pytest.raises(RuntimeNotReady, match="turn limit"):
        gateway.send_message(session.gateway_session_id, "two")
    with pytest.raises(RuntimeNotReady, match="active session"):
        gateway.create_session()
    assert gateway.close_session(session.gateway_session_id)["status"] == "closed"
    replacement = gateway.create_session()
    assert replacement.gateway_session_id


def test_secret_redaction_is_field_and_value_aware():
    secret = "sk-test-secret-value"
    result = redact({"api_key": secret, "message": f"Authorization: Bearer {secret}"}, {secret})
    assert result == {"api_key": "[REDACTED]", "message": "[REDACTED]"}
    recorder = EventRecorder({secret})
    event = recorder.record("request", api_key=secret, target="600519.SH")
    assert secret not in json.dumps(event)


def test_profile_asset_is_pinned_and_production_default_is_off():
    profile = json.loads(Path("agent_runtime/profiles/research-headless.json").read_text(encoding="utf-8"))
    assert profile["runtime_version"] == "0.1.0-rc.7"
    assert profile["allowed_tools"] == ["get_company_profile", "check_data_readiness"]
    assert json.loads(Path("agent_runtime/package.json").read_text(encoding="utf-8"))["dependencies"]["@deepseek-ai/dsh"] == "0.1.0-rc.7"
