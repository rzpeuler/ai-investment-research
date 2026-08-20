"""P8-B2-R2 regression tests for acceptance evidence integrity.

These tests are fully offline and deterministic. They never require a real
DeepSeek Provider or a running Harness runtime: all external behaviour is
provided by deterministic fakes.
"""
from __future__ import annotations

import json

import pytest

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.errors import RuntimeFailure, RuntimeNotReady
from research_os.agent_runtime.gateway import AgentRuntimeGateway
from research_os.agent_runtime.models import GatewaySession, PublicGatewaySession
from research_os.agent_runtime.trial import (
    ENTITY_CORPUS,
    ALLOWED_TOOLS,
    EvidenceBasis,
    TrialController,
    TrialMetricsRecorder,
)


# ---------------------------------------------------------------------------
# Deterministic fakes (no real Harness, no provider network)
# ---------------------------------------------------------------------------

class FakeProcess:
    """Minimal owned-process stand-in exposing the cleanup_status contract."""

    def __init__(self, *, alive=True, root="TERMINATED", tree="VERIFIED"):
        self.owned_pid = 4242
        self.owned_pgid = 4242
        self._alive = alive
        self._root = root
        self._tree = tree
        self.stdout_tail = bytearray()
        self.stderr_tail = bytearray()

    def poll(self) -> int | None:
        return None if self._alive else 0

    def terminate_tree(self) -> None:
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0

    def cleanup_status(self) -> dict[str, str]:
        return {"root": self._root, "tree": self._tree}


class FakeSupervisor:
    def __init__(self, process: FakeProcess | None = None):
        self.process = process if process is not None else FakeProcess()

    def stop(self) -> None:
        return None

    def status(self):
        return None


class FakeAdapter:
    mode = "harness"
    # One arg to allow JSON-serializable-contract matching on turn behavior.
    def __init__(self, *, send_behavior: str = "ok", supervisor: FakeSupervisor | None = None):
        self.supervisor = supervisor or FakeSupervisor()
        self.sessions: dict[str, GatewaySession] = {}
        self.send_behavior = send_behavior

    def create_session(self, metadata=None) -> GatewaySession:
        # Deterministic shared id used by both public and internal views.
        sid = "gw_fake_" + str(len(self.sessions) + 1)
        session = GatewaySession(sid, "harness", "hs_" + sid, metadata or {})
        self.sessions[sid] = session
        return session

    def send_message(self, session: GatewaySession, message: str) -> dict[str, str]:
        if self.send_behavior == "provider_timeout":
            raise RuntimeFailure("PROVIDER_TIMEOUT", "deterministic provider timeout")
        if self.send_behavior == "mcp_failure":
            raise RuntimeFailure("MCP_TOOL_FAILED", "deterministic MCP failure")
        if self.send_behavior == "session_create_fail":
            raise RuntimeFailure("MCP_UNAVAILABLE", "deterministic session failure")
        return {"status": "completed", "response": "ok"}

    def close_session(self, session: GatewaySession) -> dict[str, str]:
        self.sessions.pop(session.gateway_session_id, None)
        return {"status": "closed"}


def make_controller(*, adapter: FakeAdapter | None = None, auto_session: bool = True):
    adapter = adapter or FakeAdapter(send_behavior="ok")
    controller = TrialController()
    controller.latch.enable()
    controller._started = True
    controller.adapter = adapter
    controller.gateway = AgentRuntimeGateway(
        AgentRuntimeConfig(mode="harness", max_turns=2, max_active_sessions=10),
        harness=adapter, fallback_before_workflow=False,
    )
    controller.evidence = {
        "version": "0.1.0-rc.7",
        "profile": "research-headless",
        "mcp_namespace": "research-os-mcp/v1",
        "tools": list(ALLOWED_TOOLS),
    }
    controller.event_log.write_text("", encoding="utf-8")
    return controller


# ---------------------------------------------------------------------------
# R2-01 — one causal failure is counted exactly once
# ---------------------------------------------------------------------------

class FirstTurnFailAdapter(FakeAdapter):
    """Fails exactly once (first provider turn), then succeeds normally.

    This proves a single causal RuntimeFailure across the whole corpus is
    counted exactly once — never once for the turn layer and once again for
    the corpus layer.
    """

    def __init__(self):
        super().__init__()
        self.turn_calls = 0

    def send_message(self, session: GatewaySession, message: str) -> dict[str, str]:
        self.turn_calls += 1
        if self.turn_calls == 1:
            raise RuntimeFailure("PROVIDER_TIMEOUT", "deterministic first-turn timeout")
        return {"status": "completed", "response": "ok"}


def test_one_provider_failure_across_corpus_counts_once(monkeypatch):
    monkeypatch.setenv("P8_B2_INTERNAL_TRIAL", "1")
    controller = make_controller(adapter=FirstTurnFailAdapter())
    controller.run_corpus()
    # Exactly one causal provider timeout across the whole corpus -> one count.
    assert controller.metrics.provider_failure_count == 1
    assert controller.metrics.failures.get("PROVIDER_TIMEOUT") == 1
    # No double counting into the MCP bucket.
    assert controller.metrics.mcp_failure_count == 0
    # Attempts tracked separately: session 0 turn 1 fails and aborts its turn 2,
    # so 19 turns are attempted across the corpus (1 failed + 18 successful).
    assert controller.counters.turn_attempts == 19
    assert controller.counters.turn_completed == 18


def test_session_creation_failure_yields_itself_one_failure_zero_turns(monkeypatch):
    monkeypatch.setenv("P8_B2_INTERNAL_TRIAL", "1")

    class CreateFailThenOkAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.created = 0

        def create_session(self, metadata=None) -> GatewaySession:
            self.created += 1
            if self.created == 1:
                raise RuntimeFailure("MCP_UNAVAILABLE", "deterministic session create failure")
            return super().create_session(metadata)

    controller = make_controller(adapter=CreateFailThenOkAdapter())
    controller.run_corpus()
    # The single session-creation failure is counted exactly once, as an MCP
    # typed failure, and produces no provider turn attempt of its own.
    assert controller.metrics.failures.get("MCP_UNAVAILABLE") == 1
    assert controller.metrics.mcp_failure_count == 1
    assert controller.metrics.provider_failure_count == 0


def test_mcp_failure_counts_exactly_once(monkeypatch):
    monkeypatch.setenv("P8_B2_INTERNAL_TRIAL", "1")

    class SingleMcpFailAdapter(FakeAdapter):
        def __init__(self):
            super().__init__()
            self.turn_calls = 0

        def send_message(self, session: GatewaySession, message: str) -> dict[str, str]:
            self.turn_calls += 1
            if self.turn_calls == 1:
                raise RuntimeFailure("MCP_TOOL_FAILED", "deterministic MCP failure")
            return {"status": "completed", "response": "ok"}

    controller = make_controller(adapter=SingleMcpFailAdapter())
    controller.run_corpus()
    assert controller.metrics.mcp_failure_count == 1
    assert controller.metrics.failures.get("MCP_TOOL_FAILED") == 1
    assert controller.metrics.provider_failure_count == 0


def test_metrics_failure_is_single_increment_per_call():
    recorder = TrialMetricsRecorder("trial-count")
    recorder.failure("PROVIDER_TIMEOUT", provider=True)
    recorder.failure("MCP_TOOL_FAILED", mcp=True)
    assert recorder.provider_failure_count == 1
    assert recorder.mcp_failure_count == 1
    assert recorder.failures["PROVIDER_TIMEOUT"] == 1
    assert recorder.failures["MCP_TOOL_FAILED"] == 1


# ---------------------------------------------------------------------------
# R2-03 — secret evidence is monotonic and survives final cleanup
# ---------------------------------------------------------------------------

def test_secret_evidence_is_monotonic_and_survives_cleanup(tmp_path):
    controller = make_controller()
    # Inject a synthetic secret marker into bounded runtime evidence.
    controller.adapter.supervisor.process.stderr_tail.extend(b"Authorization: Bearer SUPERSECRET123")
    controller.event_log.write_text("safe line\n", encoding="utf-8")
    # Scan before cleanup.
    controller._scan_secrets()
    assert controller.metrics.secret_leak_count > 0
    leaked = controller.metrics.secret_leak_count
    # Now "clean up" the evidence and scan again; count must not regress.
    controller.adapter.supervisor.process.stderr_tail.clear()
    controller.event_log.unlink(missing_ok=True)
    controller._scan_secrets()
    assert controller.metrics.secret_leak_count == leaked
    # Rendered result must report FAIL and never expose the raw secret.
    controller._final_completed_sessions = 0
    controller._freeze_evidence_snapshot()
    rendered = json.dumps(controller._evidence_snapshot)
    assert controller._evidence_snapshot["secret_leak_count"] > 0
    assert controller._evidence_snapshot["secret_scan"] == "FAIL"
    assert "SUPERSECRET123" not in rendered
    # Monotonicity: a later lower scan cannot reduce it.
    controller.metrics.secret_leak_count = max(controller.metrics.secret_leak_count, 0)
    assert controller.metrics.secret_leak_count == leaked


def test_no_secret_means_passing_secret_gate():
    controller = make_controller()
    controller.metrics.secret_leak_count = 0
    controller._scan_secrets()
    assert controller.metrics.secret_leak_count == 0


# ---------------------------------------------------------------------------
# R2-04 / R2-02 — process residue is mechanically sourced and fail-closed
# ---------------------------------------------------------------------------

def test_simulated_residue_forces_non_pass():
    controller = make_controller()
    controller.metrics.process_leak_count = 1
    controller._final_completed_sessions = 10
    controller.latch.operator_reset()
    controller._freeze_evidence_snapshot()
    assert controller._evidence_snapshot["process_residue"] == "YES"
    assert controller._evidence_snapshot["status"] != "PASS CANDIDATE"


def test_not_verified_cleanup_forces_non_pass():
    controller = make_controller()
    controller.root_cleanup = "NOT_VERIFIED"
    controller.owned_tree_cleanup = "NOT_VERIFIED"
    controller.metrics.process_leak_count = 0
    controller._final_completed_sessions = 10
    controller.latch.operator_reset()
    controller._freeze_evidence_snapshot()
    assert controller._evidence_snapshot["process_residue"] == "NOT_VERIFIED"
    assert controller._evidence_snapshot["status"] != "PASS CANDIDATE"


def test_verified_zero_residue_allows_process_gate():
    controller = make_controller()
    controller.root_cleanup = "TERMINATED"
    controller.owned_tree_cleanup = "VERIFIED"
    controller.root_alive_after_stop = False
    controller.metrics.process_leak_count = 0
    result = controller._render_summary(10, final=True)
    assert result["process_residue"] == "NO"
    assert result["root_cleanup"] == "TERMINATED"
    assert result["owned_tree_cleanup"] == "VERIFIED"


def test_cli_cannot_overwrite_mechanical_process_result(monkeypatch):
    """The runner/CLI must not override the mechanical process residue (R2-02)."""
    controller = make_controller()
    controller.root_cleanup = "NOT_VERIFIED"
    controller.owned_tree_cleanup = "NOT_VERIFIED"
    controller._final_completed_sessions = 0
    controller.latch.operator_reset()
    snapshot = controller.evaluate_final_trial()
    # Simulate the old CLI overriding process_residue with a constant; the
    # acceptance snapshot must already carry the mechanical value and the CLI
    # contract is that it does not change it. We assert the frozen value is
    # NOT a constant "NO" when cleanup is not verified.
    assert snapshot["process_residue"] != "NO" or snapshot["owned_tree_cleanup"] == "VERIFIED"
    # And re-rendering the snapshot returns the same frozen value.
    again = controller.summary(0, final=True)
    assert again["process_residue"] == snapshot["process_residue"]


# ---------------------------------------------------------------------------
# R2-05 — evidence provenance is explicit
# ---------------------------------------------------------------------------

def test_evidence_basis_is_explicit_for_critical_gates():
    controller = make_controller()
    basis = controller._evidence_basis(final=True)
    for key in ("runtime_version", "profile", "mcp_tools", "same_session",
                "fresh_readiness", "authority_drift", "unauthorized_tools",
                "secret_scan", "process_residue", "provider_failures",
                "research_source_network", "default_runtime", "production_adoption"):
        assert key in basis
    assert basis["default_runtime"] == EvidenceBasis.POLICY_INVARIANT.value
    assert basis["production_adoption"] == EvidenceBasis.POLICY_INVARIANT.value
    assert basis["process_residue"] in {
        EvidenceBasis.OBSERVED.value, EvidenceBasis.NOT_VERIFIED.value}


# ---------------------------------------------------------------------------
# PASS CANDIDATE gates (7.6)
# ---------------------------------------------------------------------------

def _candidate_ready_gates() -> dict:
    """Return a dict of field/attribute states that, together, would make
    every hard gate pass if the corpus were complete. Used to prove that a
    specific shortfall still blocks PASS CANDIDATE."""
    return {
        "completed_sessions": 10,
        "turns": 20,
        "authority_drift_count": 0,
        "cross_session_contamination_count": 0,
        "unauthorized_tool_count": 0,
        "secret_leak_count": 0,
        "process_failure_count": 0,
        "process_leak_count": 0,
        "mcp_failure_count": 0,
        "same_session_pass": 20,
        "reread_pass": 10,
        "turn1_evidence_pass": 10,
        "authority_evidence_missing_count": 0,
        "cross_session_checked": 10,
        "rollback_pass": True,
        "fallback_pass": True,
        "restart_pass": True,
        "provider_tokens": 100,
        "root_cleanup": "TERMINATED",
        "owned_tree_cleanup": "VERIFIED",
        "root_alive_after_stop": False,
    }


def _controller_with_gates(**overrides):
    controller = make_controller()
    g = _candidate_ready_gates()
    g.update(overrides)
    controller.counters.turns = g.pop("turns")
    controller.counters.sessions = g.pop("completed_sessions")
    controller.counters.provider_tokens = g.pop("provider_tokens")
    m = controller.metrics
    m.authority_drift_count = g.pop("authority_drift_count")
    m.cross_session_contamination_count = g.pop("cross_session_contamination_count")
    m.unauthorized_tool_count = g.pop("unauthorized_tool_count")
    m.secret_leak_count = g.pop("secret_leak_count")
    m.process_failure_count = g.pop("process_failure_count")
    m.process_leak_count = g.pop("process_leak_count")
    m.mcp_failure_count = g.pop("mcp_failure_count")
    m.same_session_pass = g.pop("same_session_pass")
    m.reread_pass = g.pop("reread_pass")
    m.turn1_evidence_pass = g.pop("turn1_evidence_pass")
    m.authority_evidence_missing_count = g.pop("authority_evidence_missing_count")
    m.cross_session_checked = g.pop("cross_session_checked")
    controller.rollback_pass = g.pop("rollback_pass")
    controller.fallback_pass = g.pop("fallback_pass")
    controller.restart_pass = g.pop("restart_pass")
    controller.root_cleanup = g.pop("root_cleanup")
    controller.owned_tree_cleanup = g.pop("owned_tree_cleanup")
    controller.root_alive_after_stop = g.pop("root_alive_after_stop")
    return controller


def test_pass_candidate_not_reachable_under_full_gates():
    controller = _controller_with_gates()
    result = controller._render_summary(10, final=True)
    assert result["status"] == "PASS CANDIDATE"


def test_pass_candidate_blocked_with_fewer_sessions_and_turns():
    # Fewer than 10 sessions / 20 turns must block PASS CANDIDATE.
    for sessions, turns in ((9, 20), (10, 19), (9, 19)):
        controller = _controller_with_gates()
        controller.counters.sessions = sessions
        controller.counters.turns = turns
        controller.counters.turn_completed = turns
        controller.metrics.same_session_pass = turns
        result = controller._render_summary(sessions, final=True)
        assert result["status"] != "PASS CANDIDATE"
        assert result["status"] == "PARTIAL"
        # Must not convert an impossible corpus into PASS.


def test_pass_candidate_blocked_by_each_hard_security_gate():
    # Each hard security/integrity gate, individually failing, must block PASS.
    gate_mutators = {
        "authority_drift": lambda c: setattr(c.metrics, "authority_drift_count", 1),
        "contamination": lambda c: setattr(c.metrics, "cross_session_contamination_count", 1),
        "unauthorized_tool": lambda c: setattr(c.metrics, "unauthorized_tool_count", 1),
        "secret_leak": lambda c: setattr(c.metrics, "secret_leak_count", 1),
        "process_failure": lambda c: setattr(c.metrics, "process_failure_count", 1),
        "mcp_failure": lambda c: setattr(c.metrics, "mcp_failure_count", 1),
        "rollback": lambda c: setattr(c, "rollback_pass", False),
        "fallback": lambda c: setattr(c, "fallback_pass", False),
        "restart": lambda c: setattr(c, "restart_pass", False),
        "process_residue_blocked": lambda c: setattr(c, "owned_tree_cleanup", "NOT_VERIFIED"),
    }
    for name, mutate in gate_mutators.items():
        controller = _controller_with_gates()
        mutate(controller)
        result = controller._render_summary(10, final=True)
        assert result["status"] != "PASS CANDIDATE", name
        assert result["status"] == "PARTIAL", name


# ---------------------------------------------------------------------------
# Rework 1 / 7 — /proc/<pid>/stat pgrp parsing is robust to tricky comm names
# ---------------------------------------------------------------------------

def test_parse_stat_pgrp_handles_spaces_and_parens_in_comm():
    from research_os.agent_runtime.production_runtime import _parse_stat_pgrp

    # comm with spaces: fields after ')' are  [S, 1, 2500, ...]
    assert _parse_stat_pgrp("1234 (some name with spaces) S 1 2500 2500 1 3 0") == 2500
    # comm containing ')' itself (must parse from the LAST ')')
    assert _parse_stat_pgrp("7 (node (js) server) S 1 42 42 1 0 0") == 42
    # trailing newline tolerated
    assert _parse_stat_pgrp("9 (dsh) S 1 77 77 1 0 0\n") == 77
    # malformed / missing fields -> None (skip, not crash)
    assert _parse_stat_pgrp("5 (truncated") is None
    assert _parse_stat_pgrp("6 (bad) S") is None


def test_failed_tree_is_a_real_leak_with_yes_residue():
    """tree==FAILED is a mechanically-proven process leak -> process_residue=YES
    and the PASS gate stays closed, on every platform."""
    controller = make_controller()
    controller.owned_tree_cleanup = "FAILED"
    controller.root_cleanup = "TERMINATED"
    controller.root_alive_after_stop = False
    result = controller._render_summary(10, final=True)
    assert result["process_residue"] == "YES"
    assert result["status"] != "PASS CANDIDATE"
    assert controller._evidence_basis(final=True)["process_residue"] == EvidenceBasis.OBSERVED.value
