"""P8-B2-ENV-01 offline regression tests for trial environment readiness.

These tests are fully offline and deterministic. They never require a real
DeepSeek Provider, a real Harness binary or a running MCP server: every
external boundary of the readiness probe is provided by deterministic fakes.
"""
from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

import pytest

from research_os.agent_runtime.environment_readiness import (
    AUTHORIZED_TOOLS,
    ENVIRONMENT_READINESS_PROBE_ONLY,
    FORMAL_ACCEPTANCE_TURN,
    ReadinessVerdict,
    TrialEnvironmentReadinessProbe,
)
from research_os.agent_runtime.errors import RuntimeNotReady


# ---------------------------------------------------------------------------
# Deterministic fakes
# ---------------------------------------------------------------------------

def _default_evidence() -> dict:
    tools = ("check_data_readiness", "get_company_profile")
    return {
        "evidence_source": "observed_runtime",
        "version": "0.1.0-rc.7",
        "profile": "research-headless",
        "mcp_namespace": "research-os-mcp/v1",
        "tools": tools,
        "mcp_handshake": {"connected": True, "namespace": "research-os-mcp/v1",
                          "tools": tools, "protocol_version": "1"},
        "observed_component_ids": [],
        "disabled_component_ids": [],
        "enabled_component_ids": [],
        "absent_forbidden_component_ids": [],
        "denied_components": [],
        "disabled_components": [],
    }


class FakeEvidenceProbe:
    def __init__(self, evidence: dict | None = None, error: Exception | None = None):
        self._evidence = dict(evidence or _default_evidence())
        self._error = error

    def observe(self) -> dict:
        if self._error is not None:
            raise self._error
        return dict(self._evidence)


class FakeOwnedProcess:
    def __init__(self, *, cleanup: dict | None = None, stderr_tail: bytes = b""):
        self.owned_pid = 9001
        self.owned_pgid = 9001
        self.stdout_tail = bytearray()
        self.stderr_tail = bytearray(stderr_tail)
        self._cleanup = dict(cleanup or {"root": "TERMINATED", "tree": "VERIFIED"})
        self._terminated = False

    def poll(self) -> int | None:
        return None if not self._terminated else 0

    def terminate_tree(self) -> None:
        self._terminated = True

    def terminate(self) -> None:
        self._terminated = True

    def wait(self, timeout=None) -> int:
        self._terminated = True
        return 0

    def cleanup_status(self) -> dict[str, str]:
        return dict(self._cleanup)


class FakeSupervisor:
    def __init__(self, process: FakeOwnedProcess | None = None,
                 start_error: Exception | None = None):
        self.process = process if process is not None else FakeOwnedProcess()
        self.start_error = start_error
        self.started = False
        self.handshaken = False
        self.stopped = False

    def start(self, descriptor, require_credential: bool = False):
        if self.start_error is not None:
            raise self.start_error
        self.started = True
        return self.process

    def complete_mcp_handshake(self, evidence: dict) -> None:
        self.handshaken = True

    def stop(self) -> None:
        self.stopped = True


FAKE_PROVIDER_OK = {"connected": True, "probe_type": ENVIRONMENT_READINESS_PROBE_ONLY,
                    "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN, "usage": {}}
FAKE_PROVIDER_DOWN = {"connected": False, "error_type": "provider_5xx",
                      "probe_type": ENVIRONMENT_READINESS_PROBE_ONLY,
                      "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN}


def _binary_name() -> str:
    return "dsh.cmd" if os.name == "nt" else "dsh"


def make_probe(tmp_path: Path, *, env: dict | None = None, version: str = "0.1.0-rc.7",
               evidence: dict | None = None, cleanup: dict | None = None,
               provider_result: dict | None = None, secret_tail: bytes = b"",
               harness_missing: bool = False, start_error: Exception | None = None):
    """Build a probe wired to deterministic fakes plus a fake package root."""
    package = tmp_path / "agent_runtime"
    if not harness_missing:
        (package / "node_modules" / ".bin").mkdir(parents=True)
        (package / "node_modules" / ".bin" / _binary_name()).write_text("", encoding="utf-8")
        (package / "package.json").write_text(
            json.dumps({"dependencies": {"@deepseek-ai/dsh": "0.1.0-rc.7"}}), encoding="utf-8")
        (package / "package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/@deepseek-ai/dsh": {"version": "0.1.0-rc.7"}}}),
            encoding="utf-8")
    owned = FakeOwnedProcess(cleanup=cleanup, stderr_tail=secret_tail)
    supervisor = FakeSupervisor(process=owned, start_error=start_error)

    def provider_probe(env_):
        return dict(provider_result) if provider_result is not None else dict(FAKE_PROVIDER_OK)

    probe = TrialEnvironmentReadinessProbe(
        package_root=package,
        repo_root=tmp_path,
        env=env if env is not None else {"DEEPSEEK_API_KEY": "fake-key-12345"},
        version_runner=lambda binary: (0, version),
        evidence_probe=FakeEvidenceProbe(evidence),
        supervisor=supervisor,
        provider_probe=provider_probe,
        node_available=True,
    )
    return probe, supervisor, owned


def _gate(result: dict, name: str) -> dict:
    return result["gates"][name]


# ---------------------------------------------------------------------------
# Required offline scenarios (taskbook section 19)
# ---------------------------------------------------------------------------

def test_harness_missing_is_blocked(tmp_path):
    probe, _, _ = make_probe(tmp_path, harness_missing=True)
    result = probe.probe()
    assert result["result"] == "BLOCKED"
    assert _gate(result, "HARNESS_AVAILABLE")["status"] == "NO"
    assert _gate(result, "HARNESS_AVAILABLE")["verdict"] == ReadinessVerdict.BLOCKED.value


def test_harness_wrong_version_is_fail(tmp_path):
    probe, _, _ = make_probe(tmp_path, version="9.9.9")
    result = probe.probe()
    assert result["result"] == "FAIL"
    assert _gate(result, "HARNESS_VERSION_VERIFIED")["verdict"] == ReadinessVerdict.FAIL.value
    assert _gate(result, "HARNESS_VERSION_VERIFIED")["status"] == "NO"


def test_credential_missing_is_blocked(tmp_path):
    probe, _, _ = make_probe(tmp_path, env={})
    result = probe.probe()
    assert result["result"] == "BLOCKED"
    assert _gate(result, "PROVIDER_CREDENTIAL_PRESENT")["status"] == "NO"
    assert _gate(result, "PROVIDER_CONNECTIVITY_VERIFIED")["verdict"] == ReadinessVerdict.BLOCKED.value
    assert result["provider"]["approved_credential_present"] == "NO"
    assert result["provider"]["credential_value_exposed"] == "NO"


def test_provider_connectivity_unavailable_is_blocked(tmp_path):
    probe, _, _ = make_probe(tmp_path, provider_result=FAKE_PROVIDER_DOWN)
    result = probe.probe()
    assert result["result"] == "BLOCKED"
    assert _gate(result, "PROVIDER_CONNECTIVITY_VERIFIED")["status"] == "NO"
    assert _gate(result, "PROVIDER_CONNECTIVITY_VERIFIED")["verdict"] == ReadinessVerdict.BLOCKED.value


def test_mcp_namespace_mismatch_is_fail(tmp_path):
    evidence = _default_evidence()
    evidence["mcp_namespace"] = "research-os-mcp/v2"
    evidence["mcp_handshake"] = {**evidence["mcp_handshake"], "namespace": "research-os-mcp/v2"}
    probe, _, _ = make_probe(tmp_path, evidence=evidence)
    result = probe.probe()
    assert result["result"] == "FAIL"
    assert _gate(result, "MCP_NAMESPACE_VERIFIED")["verdict"] == ReadinessVerdict.FAIL.value


def test_missing_authorized_tool_is_fail(tmp_path):
    evidence = _default_evidence()
    evidence["tools"] = ("check_data_readiness",)
    evidence["mcp_handshake"] = {**evidence["mcp_handshake"], "tools": ("check_data_readiness",)}
    probe, _, _ = make_probe(tmp_path, evidence=evidence)
    result = probe.probe()
    assert result["result"] == "FAIL"
    gate = _gate(result, "MCP_TOOLSET_VERIFIED")
    assert gate["verdict"] == ReadinessVerdict.FAIL.value
    assert "get_company_profile" in gate["detail"]


def test_additional_unauthorized_tool_is_fail(tmp_path):
    evidence = _default_evidence()
    evidence["tools"] = ("check_data_readiness", "get_company_profile", "graph_query")
    evidence["mcp_handshake"] = {**evidence["mcp_handshake"],
                                 "tools": ("check_data_readiness", "get_company_profile", "graph_query")}
    probe, _, _ = make_probe(tmp_path, evidence=evidence)
    result = probe.probe()
    assert result["result"] == "FAIL"
    gate = _gate(result, "MCP_TOOLSET_VERIFIED")
    assert gate["verdict"] == ReadinessVerdict.FAIL.value
    assert result["mcp"]["unauthorized_tool_count"] == 1
    assert result["mcp"]["tool_count"] == 3


def test_cleanup_not_verified_fails_closed(tmp_path):
    probe, _, _ = make_probe(tmp_path, cleanup={"root": "TERMINATED", "tree": "NOT_VERIFIED"})
    result = probe.probe()
    assert result["result"] == "FAIL"
    gate = _gate(result, "PROCESS_CLEANUP_VERIFIED")
    assert gate["verdict"] == ReadinessVerdict.FAIL_CLOSED.value
    assert gate["fail_closed"] is True
    assert result["process"]["process_residue"] == "NOT_VERIFIED"


def test_process_residue_yes_is_fail(tmp_path):
    probe, _, _ = make_probe(tmp_path, cleanup={"root": "TERMINATED", "tree": "FAILED"})
    result = probe.probe()
    assert result["result"] == "FAIL"
    gate = _gate(result, "PROCESS_CLEANUP_VERIFIED")
    assert gate["verdict"] == ReadinessVerdict.FAIL.value
    assert result["process"]["process_residue"] == "YES"


def test_secret_evidence_positive_is_fail(tmp_path):
    probe, _, _ = make_probe(tmp_path, secret_tail=b"Authorization: Bearer SUPERSECRET123")
    result = probe.probe()
    assert result["result"] == "FAIL"
    gate = _gate(result, "SECRET_HYGIENE_VERIFIED")
    assert gate["verdict"] == ReadinessVerdict.FAIL.value
    assert gate["status"] == "NO"
    rendered = json.dumps(result, ensure_ascii=False)
    assert "SUPERSECRET123" not in rendered


def test_all_gates_mechanically_verified_is_ready(tmp_path):
    probe, supervisor, owned = make_probe(tmp_path)
    result = probe.probe()
    assert result["result"] == "READY"
    for name, verdict in result["readiness_gates"].items():
        assert verdict == ReadinessVerdict.READY.value, name
    assert result["blockers"] == []
    assert result["harness"]["observed_version"] == "0.1.0-rc.7"
    assert result["harness"]["executable_boot_verified"] == "YES"
    assert result["mcp"]["tool_count"] == 2
    assert result["mcp"]["unauthorized_tool_count"] == 0
    assert result["process"]["root_terminated"] is True
    assert result["process"]["owned_tree_cleanup"] == "VERIFIED"
    assert result["process"]["process_residue"] == "NO"
    assert result["provider"]["approved_credential_present"] == "YES"
    assert result["provider"]["connectivity_verified"] == "YES"
    assert result["provider"]["credential_value_exposed"] == "NO"
    # The owned process was actually terminated through the accepted mechanism.
    assert owned._terminated is True
    assert supervisor.started is True
    assert supervisor.handshaken is True
    assert supervisor.stopped is True


def test_probe_cannot_increment_formal_acceptance_counters(tmp_path):
    from research_os.agent_runtime.trial import TrialCounters

    before = TrialCounters()
    probe, _, _ = make_probe(tmp_path)
    assert not hasattr(probe, "metrics")
    assert not hasattr(probe, "counters")
    result = probe.probe()
    after = TrialCounters()
    assert result["environment_readiness_probe_only"] is True
    assert result["formal_acceptance_turn"] == "NO"
    assert result["formal_corpus_untouched"] is True
    # No acceptance-counter field may appear in the readiness result.
    for forbidden in ("trial_sessions", "turns", "session_create_attempts",
                      "turn_attempts", "tool_calls", "provider_tokens"):
        assert forbidden not in result, forbidden
    assert dataclasses.asdict(before) == dataclasses.asdict(after)


# ---------------------------------------------------------------------------
# Additional mechanical guarantees
# ---------------------------------------------------------------------------

def test_provider_probe_is_marked_probe_only():
    from research_os.agent_runtime.environment_readiness import probe_deepseek_connectivity
    with pytest.raises(Exception):
        # Never actually called offline; only the marker contract is checked.
        probe_deepseek_connectivity(env={}, config_path=Path("does-not-exist.yaml"))
    assert ENVIRONMENT_READINESS_PROBE_ONLY == "ENVIRONMENT_READINESS_PROBE_ONLY"
    assert FORMAL_ACCEPTANCE_TURN == "NO"


def test_harness_boot_failure_is_blocked(tmp_path):
    probe, _, _ = make_probe(tmp_path, start_error=RuntimeNotReady(
        "HARNESS_BOOT_FAILED", "deterministic boot failure"))
    result = probe.probe()
    assert result["result"] == "BLOCKED"
    assert result["harness"]["executable_boot_verified"] == "NO"


def test_every_gate_has_explicit_evidence_basis(tmp_path):
    probe, _, _ = make_probe(tmp_path)
    result = probe.probe()
    allowed_bases = {"OBSERVED", "DERIVED_FROM_OBSERVED_RUNTIME",
                     "POLICY_INVARIANT", "NOT_AVAILABLE", "NOT_VERIFIED"}
    assert set(result["gates"]) == {
        "HARNESS_AVAILABLE", "HARNESS_VERSION_VERIFIED", "PROVIDER_CREDENTIAL_PRESENT",
        "PROVIDER_CONNECTIVITY_VERIFIED", "MCP_SERVER_BOOT_VERIFIED",
        "MCP_NAMESPACE_VERIFIED", "MCP_TOOLSET_VERIFIED", "RUNTIME_PROFILE_VERIFIED",
        "PROCESS_CLEANUP_VERIFIED", "SECRET_HYGIENE_VERIFIED",
    }
    for name, gate in result["gates"].items():
        assert gate["evidence_basis"] in allowed_bases, name
        assert gate["status"] in {"YES", "NO", "NOT_VERIFIED"}, name
        assert gate["verdict"] in {"READY", "BLOCKED", "FAIL", "FAIL_CLOSED"}, name
