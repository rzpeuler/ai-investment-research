"""Owned Harness process lifecycle and readiness admission."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Sequence
from typing import Any, Protocol

from .config import AgentRuntimeConfig
from .errors import ConfigurationError, RuntimeNotReady
from .models import RuntimeStatus, SupervisorState
from .observability import EventRecorder
from .profile_verifier import ProfileVerifier


class OwnedProcess(Protocol):
    def poll(self) -> int | None: ...
    def terminate(self) -> None: ...
    def wait(self, timeout: float | None = None) -> int: ...


class HarnessRuntimeSupervisor:
    def __init__(
        self,
        config: AgentRuntimeConfig | None = None,
        process_factory: Callable[[], OwnedProcess] | None = None,
        recorder: EventRecorder | None = None,
        allow_fixture: bool = False,
    ):
        self.config = (config or AgentRuntimeConfig()).validate()
        self.process_factory = process_factory
        self.recorder = recorder or EventRecorder()
        self.verifier = ProfileVerifier(self.config.harness_version)
        self.allow_fixture = allow_fixture
        self.process: OwnedProcess | None = None
        self.state = SupervisorState.STOPPED
        self._verification = {"version_verified": False, "profile_verified": False, "mcp_verified": False}
        self.failure_code: str | None = None

    def _status(self) -> RuntimeStatus:
        alive = self.process is not None and self.process.poll() is None
        return RuntimeStatus(
            state=self.state,
            process_alive=alive,
            profile_verified=self._verification["profile_verified"],
            mcp_verified=self._verification["mcp_verified"],
            version_verified=self._verification["version_verified"],
            failure_code=self.failure_code,
        )

    def status(self) -> RuntimeStatus:
        if self.state is SupervisorState.READY and not self._status().process_alive:
            self.state = SupervisorState.FAILED
            self.failure_code = "HARNESS_BOOT_FAILED"
        return self._status()

    @property
    def ready(self) -> bool:
        return self.status().ready

    def preflight_provider_credential(self, env: dict[str, str] | None = None) -> str:
        values = env if env is not None else os.environ
        key = values.get("DEEPSEEK_API_KEY")
        if not key:
            raise RuntimeNotReady("PROVIDER_AUTH_MISSING", "provider credential is absent")
        self.recorder.known_secrets.add(key)
        return key

    def start(self, descriptor: dict[str, Any] | None = None, require_credential: bool = False) -> RuntimeStatus:
        if self.state in {SupervisorState.STARTING, SupervisorState.READY}:
            return self.status()
        self.config.validate()
        self.state = SupervisorState.STARTING
        self.failure_code = None
        self._verification = {"version_verified": False, "profile_verified": False, "mcp_verified": False}
        try:
            if require_credential:
                self.preflight_provider_credential()
            if self.process_factory is None:
                raise RuntimeNotReady("HARNESS_BOOT_FAILED", "no supervisor-owned Harness process factory configured")
            self.process = self.process_factory()
            if self.process.poll() is not None:
                raise RuntimeNotReady("HARNESS_BOOT_FAILED", "Harness process exited during startup")
            if descriptor is None:
                raise RuntimeNotReady("HARNESS_BOOT_FAILED", "runtime descriptor unavailable")
            if descriptor.get("evidence_source") != "observed_runtime" and not self.allow_fixture:
                raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "fabricated runtime evidence cannot admit READY")
            verification = self.verifier.verify(descriptor, allow_fixture=self.allow_fixture)
            self._verification["version_verified"] = verification.version_verified
            self._verification["profile_verified"] = verification.profile_verified
            self.recorder.record("runtime_profile_verified", version=self.config.harness_version, profile=verification.identity)
            self.state = SupervisorState.STARTING
            return self.status()
        except RuntimeNotReady as exc:
            self.failure_code = exc.code
            self.state = SupervisorState.FAILED
            self._cleanup_owned_process()
            raise
        except Exception as exc:
            self.failure_code = "HARNESS_BOOT_FAILED"
            self.state = SupervisorState.FAILED
            self._cleanup_owned_process()
            raise RuntimeNotReady(self.failure_code, str(exc)) from exc

    def complete_mcp_handshake(self, handshake_evidence: dict[str, Any]) -> RuntimeStatus:
        if self.state is not SupervisorState.STARTING or not self._status().process_alive:
            raise RuntimeNotReady("MCP_UNAVAILABLE", "runtime is not alive for MCP handshake")
        if not handshake_evidence.get("connected") or handshake_evidence.get("namespace") != self.config.mcp_namespace:
            raise RuntimeNotReady("MCP_UNAVAILABLE", "MCP handshake evidence is invalid")
        if tuple(sorted(handshake_evidence.get("tools", ()))) != ("check_data_readiness", "get_company_profile"):
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "MCP Tool evidence is not exact")
        self._verification["mcp_verified"] = True
        self.state = SupervisorState.READY
        self.recorder.record("runtime_ready", version=self.config.harness_version)
        return self.status()

    def mark_mcp_ready(self, handshake_evidence: dict[str, Any] | None = None) -> RuntimeStatus:
        """Compatibility alias; readiness still requires actual handshake evidence."""
        if handshake_evidence is None:
            raise RuntimeNotReady("MCP_UNAVAILABLE", "handshake evidence is required")
        return self.complete_mcp_handshake(handshake_evidence)

    def _cleanup_owned_process(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        try:
            if process.poll() is None:
                terminate = getattr(process, "terminate_tree", None)
                if callable(terminate):
                    terminate()
                else:
                    process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if hasattr(process, "process"):
                        process.process.kill()
        except Exception:
            # The supervisor only touches its own process object; failure is recorded by state.
            pass

    def drain(self) -> RuntimeStatus:
        if self.state in {SupervisorState.STOPPED, SupervisorState.FAILED}:
            self._cleanup_owned_process()
            self.state = SupervisorState.STOPPED
            return self.status()
        self.state = SupervisorState.DRAINING
        self.recorder.record("runtime_draining")
        self._cleanup_owned_process()
        self.state = SupervisorState.STOPPED
        return self.status()

    def stop(self) -> RuntimeStatus:
        return self.drain()
