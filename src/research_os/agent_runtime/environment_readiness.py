"""P8-B2-ENV-01: provider-backed internal trial environment readiness probe.

This module mechanically verifies that the already-accepted P8-B2 trial
implementation can execute its formal provider-backed corpus safely. It is
explicitly an environment-readiness mechanism, not an acceptance engine:

  - it never admits a session or a turn;
  - it never increments trial/session/turn/tool/token counters;
  - every provider-backed probe is marked ENVIRONMENT_READINESS_PROBE_ONLY and
    FORMAL_ACCEPTANCE_TURN = NO, and never counts toward the formal 10-session /
    20-turn corpus (P8-B2-LIVE-01).

The probe reuses the accepted P8-B2 trial infrastructure (ProductionEvidenceProbe,
HarnessProcessFactory, HarnessRuntimeSupervisor, the owned process-tree cleanup
mechanism and the R2 evidence vocabulary) instead of introducing a parallel
runtime, MCP server, provider SDK or orchestration layer.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from .config import EXPECTED_HARNESS_VERSION, MCP_NAMESPACE
from .errors import RuntimeFailure, RuntimeNotReady
from .production_runtime import (
    PACKAGE_ROOT,
    ROOT,
    BoundedOwnedProcess,
    HarnessProcessFactory,
    ProductionEvidenceProbe,
)
from .runtime_supervisor import HarnessRuntimeSupervisor

TASK_ID = "P8-B2-ENV-01"
ENVIRONMENT_READINESS_PROBE_ONLY = "ENVIRONMENT_READINESS_PROBE_ONLY"
FORMAL_ACCEPTANCE_TURN = "NO"

HARNESS_PACKAGE = "@deepseek-ai/dsh"
EXPECTED_PROFILE = "research-headless"
# Frozen P8-B2 MCP boundary (mirrors the accepted trial contract).
AUTHORIZED_TOOLS = frozenset({"get_company_profile", "check_data_readiness"})

HARNESS_AVAILABLE = "HARNESS_AVAILABLE"
HARNESS_VERSION_VERIFIED = "HARNESS_VERSION_VERIFIED"
PROVIDER_CREDENTIAL_PRESENT = "PROVIDER_CREDENTIAL_PRESENT"
PROVIDER_CONNECTIVITY_VERIFIED = "PROVIDER_CONNECTIVITY_VERIFIED"
MCP_SERVER_BOOT_VERIFIED = "MCP_SERVER_BOOT_VERIFIED"
MCP_NAMESPACE_VERIFIED = "MCP_NAMESPACE_VERIFIED"
MCP_TOOLSET_VERIFIED = "MCP_TOOLSET_VERIFIED"
RUNTIME_PROFILE_VERIFIED = "RUNTIME_PROFILE_VERIFIED"
PROCESS_CLEANUP_VERIFIED = "PROCESS_CLEANUP_VERIFIED"
SECRET_HYGIENE_VERIFIED = "SECRET_HYGIENE_VERIFIED"

ALL_GATES = (
    HARNESS_AVAILABLE,
    HARNESS_VERSION_VERIFIED,
    PROVIDER_CREDENTIAL_PRESENT,
    PROVIDER_CONNECTIVITY_VERIFIED,
    MCP_SERVER_BOOT_VERIFIED,
    MCP_NAMESPACE_VERIFIED,
    MCP_TOOLSET_VERIFIED,
    RUNTIME_PROFILE_VERIFIED,
    PROCESS_CLEANUP_VERIFIED,
    SECRET_HYGIENE_VERIFIED,
)

# Evidence vocabulary stays consistent with the accepted R2 trial (trial.py).
class EvidenceBasis(str, Enum):
    OBSERVED = "OBSERVED"
    DERIVED_FROM_OBSERVED_RUNTIME = "DERIVED_FROM_OBSERVED_RUNTIME"
    POLICY_INVARIANT = "POLICY_INVARIANT"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_VERIFIED = "NOT_VERIFIED"


class ReadinessVerdict(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"
    FAIL = "FAIL"
    # Fail-closed classification: cleanup could not be mechanically proven, so
    # the gate is treated as a hard FAIL for formal-trial readiness.
    FAIL_CLOSED = "FAIL_CLOSED"


@dataclass(frozen=True)
class ReadinessGate:
    name: str
    status: str            # YES | NO | NOT_VERIFIED
    evidence_basis: str
    verdict: str           # one of ReadinessVerdict
    detail: str = ""
    fail_closed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "evidence_basis": self.evidence_basis,
            "verdict": self.verdict,
            "detail": self.detail,
            "fail_closed": self.fail_closed,
        }


def _gate(name: str, status: str, basis: str, verdict: str, detail: str = "",
          fail_closed: bool = False) -> ReadinessGate:
    return ReadinessGate(name, status, basis, verdict, detail, fail_closed)


def probe_deepseek_connectivity(
    env: dict[str, str] | None = None,
    *,
    config_path: Path | None = None,
    timeout_seconds: int = 30,
    max_output_tokens: int = 256,
) -> dict[str, Any]:
    """Minimal, bounded DeepSeek connectivity probe.

    Exactly one tiny provider request (no retries), clearly marked as an
    environment-readiness probe that never counts toward the formal corpus.
    The output budget must comfortably exceed the flash model's reasoning
    prefix (observed ~32 reasoning tokens) or the JSON content is truncated.
    """
    from research_os.llm.models import LlmRequest
    from research_os.llm.provider_config import load_provider_config
    from research_os.llm.providers.deepseek import DeepSeekChatCompletionsProvider

    env = env if env is not None else os.environ
    path = config_path or (ROOT / "config" / "llm_providers.yaml")
    config = load_provider_config(path, "deepseek")
    bounded = dataclasses.replace(config, timeout_seconds=timeout_seconds,
                                  max_output_tokens=max_output_tokens)
    provider = DeepSeekChatCompletionsProvider(bounded)
    request = LlmRequest(
        call_id="env-readiness-connectivity",
        task_id=TASK_ID,
        module="environment_readiness",
        prompt='Return a JSON object: {"ok": true}',
        prompt_hash=hashlib.sha256(b"environment-readiness-connectivity").hexdigest()[:16],
        requested_model_class="flash",
        output_schema_name="environment_readiness_probe",
        timeout_seconds=timeout_seconds,
    )
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    result = provider.complete_json(request, schema)
    bounded_out: dict[str, Any] = {
        "probe_type": ENVIRONMENT_READINESS_PROBE_ONLY,
        "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN,
        "connected": bool(result.get("ok")),
        "provider": result.get("provider"),
        "model_id": result.get("model_id"),
        "usage": result.get("usage") if isinstance(result.get("usage"), dict) else {},
    }
    if not result.get("ok"):
        bounded_out["error_type"] = result.get("error_type") or "provider_error"
    return bounded_out


class TrialEnvironmentReadinessProbe:
    """Mechanically verifies P8-B2 formal-trial environment prerequisites.

    All external boundaries (version command, observed-runtime evidence probe,
    owned-process supervisor, provider connectivity probe) are injectable so
    the gate logic is fully testable offline with deterministic fakes.
    """

    def __init__(
        self,
        *,
        package_root: Path | None = None,
        repo_root: Path | None = None,
        env: dict[str, str] | None = None,
        version_runner: Callable[[Path], tuple[int, str]] | None = None,
        evidence_probe: Any | None = None,
        supervisor: Any | None = None,
        provider_probe: Callable[[dict[str, str]], dict[str, Any]] | None = None,
        node_available: bool | None = None,
    ):
        self.package_root = Path(package_root) if package_root is not None else PACKAGE_ROOT
        self.repo_root = Path(repo_root) if repo_root is not None else ROOT
        self.env = dict(os.environ if env is None else env)
        self.dsh = self.package_root / "node_modules" / ".bin" / ("dsh.cmd" if os.name == "nt" else "dsh")
        self._version_runner = version_runner or self._default_version_runner
        self._evidence_probe = evidence_probe or ProductionEvidenceProbe(self.package_root, self.repo_root)
        self._supervisor = supervisor
        self._provider_probe = provider_probe or (lambda env_: probe_deepseek_connectivity(env_))
        self._node_available = shutil.which("node") is not None if node_available is None else node_available
        self._gates: dict[str, ReadinessGate] = {}
        self._observed_version: str | None = None
        self._observed_profile: str | None = None
        self._observed_namespace: str | None = None
        self._observed_tools: tuple[str, ...] = ()
        self._mcp_handshake: dict[str, Any] | None = None
        self._observe_error: str | None = None
        self._boot_error: str | None = None
        self._boot_ok = False
        self._cleanup: dict[str, Any] | None = None
        self._owned_tails: tuple[str, str] = ("", "")
        self._connectivity_result: dict[str, Any] | None = None
        self._haystacks: list[str] = []
        self._secret_markers_found = 0
        self._node_available = shutil.which("node") is not None

    # ------------------------------------------------------------------
    # Injectable defaults
    # ------------------------------------------------------------------

    def _default_version_runner(self, binary: Path) -> tuple[int, str]:
        result = subprocess.run([str(binary), "--version"], capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=30, check=False)
        return result.returncode, result.stdout.strip()

    def _default_supervisor(self) -> HarnessRuntimeSupervisor:
        from .config import AgentRuntimeConfig
        factory = HarnessProcessFactory(self.package_root, self.repo_root)
        return HarnessRuntimeSupervisor(config=AgentRuntimeConfig(mode="harness"),
                                        process_factory=factory)

    # ------------------------------------------------------------------
    # Static (no side-effect) gates
    # ------------------------------------------------------------------

    def _gate_harness_available(self) -> ReadinessGate:
        binary_ok = self.dsh.exists()
        detail = (f"dsh binary {'present' if binary_ok else 'MISSING'} at {self.dsh}; "
                  f"node {'present' if self._node_available else 'MISSING'}")
        if not binary_ok or not self._node_available:
            return _gate(HARNESS_AVAILABLE, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.BLOCKED.value, detail)
        return _gate(HARNESS_AVAILABLE, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, detail)

    def _package_pin(self) -> str | None:
        try:
            payload = json.loads((self.package_root / "package.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        deps = payload.get("dependencies") if isinstance(payload, dict) else None
        pin = deps.get(HARNESS_PACKAGE) if isinstance(deps, dict) else None
        return str(pin) if isinstance(pin, str) else None

    def _lockfile_pin(self) -> str | None:
        try:
            payload = json.loads((self.package_root / "package-lock.json").read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return None
        packages = payload.get("packages") if isinstance(payload, dict) else {}
        entry = packages.get(f"node_modules/{HARNESS_PACKAGE}") if isinstance(packages, dict) else None
        version = entry.get("version") if isinstance(entry, dict) else None
        return str(version) if isinstance(version, str) else None

    def _gate_harness_version(self, binary_ok: bool) -> ReadinessGate:
        if not binary_ok:
            return _gate(HARNESS_VERSION_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, "harness executable unavailable")
        package_pin = self._package_pin()
        lockfile_pin = self._lockfile_pin()
        if package_pin != EXPECTED_HARNESS_VERSION or lockfile_pin != EXPECTED_HARNESS_VERSION:
            return _gate(HARNESS_VERSION_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"package.json pin={package_pin!r} lockfile pin={lockfile_pin!r} "
                         f"expected={EXPECTED_HARNESS_VERSION!r}")
        try:
            returncode, stdout = self._version_runner(self.dsh)
        except Exception as exc:  # noqa: BLE001 — version probe failure is bounded evidence
            return _gate(HARNESS_VERSION_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"dsh --version failed: {type(exc).__name__}")
        self._observed_version = stdout or None
        self._haystacks.append(stdout)
        if returncode != 0 or not stdout:
            return _gate(HARNESS_VERSION_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, "dsh --version did not report a version")
        if stdout != EXPECTED_HARNESS_VERSION:
            return _gate(HARNESS_VERSION_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"observed version {stdout!r} != expected {EXPECTED_HARNESS_VERSION!r}")
        return _gate(HARNESS_VERSION_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value,
                     "dsh --version and committed package/lockfile pins match 0.1.0-rc.7")

    def _gate_credential(self) -> ReadinessGate:
        present = bool(self.env.get("DEEPSEEK_API_KEY"))
        if not present:
            return _gate(PROVIDER_CREDENTIAL_PRESENT, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.BLOCKED.value, "DEEPSEEK_API_KEY is absent from the environment")
        return _gate(PROVIDER_CREDENTIAL_PRESENT, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, "DEEPSEEK_API_KEY present (value never exposed)")

    def _gate_provider_connectivity(self, credential_present: bool) -> ReadinessGate:
        if not credential_present:
            return _gate(PROVIDER_CONNECTIVITY_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, "provider credential absent; probe skipped")
        try:
            result = self._provider_probe(self.env)
        except Exception as exc:  # noqa: BLE001 — probe failure is bounded evidence
            self._connectivity_result = {"connected": False,
                                         "error_type": type(exc).__name__,
                                         "probe_type": ENVIRONMENT_READINESS_PROBE_ONLY,
                                         "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN}
            self._haystacks.append(repr(self._connectivity_result))
            return _gate(PROVIDER_CONNECTIVITY_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.BLOCKED.value, "provider connectivity probe raised an exception")
        self._connectivity_result = result
        self._haystacks.append(repr(result))
        if result.get("connected") is True:
            return _gate(PROVIDER_CONNECTIVITY_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.READY.value, "bounded provider-backed probe succeeded")
        error_type = result.get("error_type") or "unknown"
        return _gate(PROVIDER_CONNECTIVITY_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.BLOCKED.value, f"provider connectivity failed: {error_type}")

    # ------------------------------------------------------------------
    # Observed-runtime gates
    # ------------------------------------------------------------------

    def _observe(self) -> dict[str, Any] | None:
        try:
            return self._evidence_probe.observe()
        except RuntimeFailure as exc:
            self._observe_error = exc.code
            return None
        except Exception as exc:  # noqa: BLE001
            self._observe_error = type(exc).__name__
            return None

    def _record_observed(self, evidence: dict[str, Any] | None) -> None:
        if not evidence:
            return
        self._observed_version = str(evidence.get("version") or "")
        self._observed_profile = str(evidence.get("profile") or "")
        self._observed_namespace = str(evidence.get("mcp_namespace") or "")
        tools = evidence.get("tools")
        self._observed_tools = tuple(sorted(str(t) for t in tools)) if isinstance(tools, (list, tuple)) else ()
        handshake = evidence.get("mcp_handshake")
        self._mcp_handshake = handshake if isinstance(handshake, dict) else {}
        self._haystacks.append(repr(evidence))

    def _gate_runtime_profile(self, evidence: dict[str, Any] | None) -> ReadinessGate:
        if not evidence:
            reason = self._observe_error or "runtime observation unavailable"
            return _gate(RUNTIME_PROFILE_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"runtime observation unavailable: {reason}")
        if self._observed_version != EXPECTED_HARNESS_VERSION:
            return _gate(RUNTIME_PROFILE_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"observed runtime version {self._observed_version!r} != {EXPECTED_HARNESS_VERSION!r}")
        if self._observed_profile != EXPECTED_PROFILE:
            return _gate(RUNTIME_PROFILE_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"observed runtime profile {self._observed_profile!r} != {EXPECTED_PROFILE!r}")
        return _gate(RUNTIME_PROFILE_VERIFIED, "YES",
                     EvidenceBasis.DERIVED_FROM_OBSERVED_RUNTIME.value,
                     ReadinessVerdict.READY.value, "observed runtime version/profile match the frozen contract")

    def _gate_mcp_server_boot(self, evidence: dict[str, Any] | None) -> ReadinessGate:
        if not evidence:
            reason = self._observe_error or "runtime observation unavailable"
            return _gate(MCP_SERVER_BOOT_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"MCP server not observed: {reason}")
        if not self._mcp_handshake or self._mcp_handshake.get("connected") is not True:
            return _gate(MCP_SERVER_BOOT_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.BLOCKED.value, "Research OS MCP server did not complete handshake")
        return _gate(MCP_SERVER_BOOT_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, "Research OS MCP server booted and handshook")

    def _gate_mcp_namespace(self, evidence: dict[str, Any] | None) -> ReadinessGate:
        if not evidence:
            reason = self._observe_error or "runtime observation unavailable"
            return _gate(MCP_NAMESPACE_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"MCP namespace not observed: {reason}")
        handshake_namespace = self._mcp_handshake.get("namespace")
        if self._observed_namespace != MCP_NAMESPACE or handshake_namespace != MCP_NAMESPACE:
            return _gate(MCP_NAMESPACE_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"observed namespace {self._observed_namespace!r} handshake "
                         f"{handshake_namespace!r} != expected {MCP_NAMESPACE!r}")
        return _gate(MCP_NAMESPACE_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, f"MCP namespace is {MCP_NAMESPACE}")

    def _gate_mcp_toolset(self, evidence: dict[str, Any] | None) -> ReadinessGate:
        if not evidence:
            reason = self._observe_error or "runtime observation unavailable"
            return _gate(MCP_TOOLSET_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"MCP toolset not observed: {reason}")
        observed = set(self._observed_tools)
        handshake_tools = self._mcp_handshake.get("tools", ())
        handshake_set = set(str(t) for t in handshake_tools) if isinstance(handshake_tools, (list, tuple)) else set()
        missing = AUTHORIZED_TOOLS - observed
        unauthorized = observed - AUTHORIZED_TOOLS
        in_process_ok = self._in_process_mcp_handshake_ok()
        detail = (f"observed tools={sorted(observed)} count={len(observed)} "
                  f"missing={sorted(missing)} unauthorized={sorted(unauthorized)} "
                  f"in_process_handshake={'verified' if in_process_ok else 'FAILED'}")
        if missing or unauthorized or len(observed) != len(AUTHORIZED_TOOLS) or not in_process_ok:
            return _gate(MCP_TOOLSET_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value, detail)
        if handshake_set != AUTHORIZED_TOOLS:
            return _gate(MCP_TOOLSET_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value, f"{detail} handshake_tools={sorted(handshake_set)}")
        return _gate(MCP_TOOLSET_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, detail)

    def _in_process_mcp_handshake_ok(self) -> bool:
        """The exact-tool in-process MCP boundary the trial gateway uses."""
        try:
            from .mcp.tools import build_research_os_mcp_server
            server = build_research_os_mcp_server()
            server.perform_handshake()
            return tuple(server.tools) == tuple(sorted(AUTHORIZED_TOOLS))
        except Exception:  # noqa: BLE001 — handshake mismatch is recorded as gate detail
            return False

    # ------------------------------------------------------------------
    # Boot + owned-process cleanup (accepted R2 mechanism)
    # ------------------------------------------------------------------

    def _boot_and_cleanup(self, evidence: dict[str, Any] | None) -> None:
        supervisor = self._supervisor if self._supervisor is not None else self._default_supervisor()
        owned: BoundedOwnedProcess | None = None
        try:
            supervisor.start(evidence, require_credential=False)
            owned = supervisor.process
            supervisor.complete_mcp_handshake(self._mcp_handshake or {})
            self._boot_ok = owned is not None
        except RuntimeFailure as exc:
            self._boot_error = exc.code
            self._boot_ok = False
        except Exception as exc:  # noqa: BLE001
            self._boot_error = type(exc).__name__
            self._boot_ok = False
        finally:
            if owned is not None:
                terminate = getattr(owned, "terminate_tree", None)
                if callable(terminate):
                    terminate()
                elif hasattr(owned, "terminate"):
                    owned.terminate()
            try:
                supervisor.stop()
            except Exception:  # noqa: BLE001 — supervisor drain is best-effort after owned cleanup
                pass
            if owned is not None:
                status_fn = getattr(owned, "cleanup_status", None)
                self._cleanup = status_fn() if callable(status_fn) else {"root": "NOT_VERIFIED", "tree": "NOT_VERIFIED"}
                stdout_tail = getattr(owned, "stdout_tail", None)
                stderr_tail = getattr(owned, "stderr_tail", None)
                self._owned_tails = (
                    bytes(stdout_tail).decode(errors="replace") if isinstance(stdout_tail, (bytes, bytearray)) else "",
                    bytes(stderr_tail).decode(errors="replace") if isinstance(stderr_tail, (bytes, bytearray)) else "",
                )
                self._haystacks.extend(self._owned_tails)

    def _gate_process_cleanup(self, boot_attempted: bool) -> ReadinessGate:
        if not boot_attempted:
            return _gate(PROCESS_CLEANUP_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, "harness executable unavailable; boot skipped")
        if not self._boot_ok:
            reason = self._boot_error or "unknown"
            if reason in {"PROFILE_POLICY_MISMATCH", "RUNTIME_VERSION_MISMATCH"}:
                return _gate(PROCESS_CLEANUP_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                             ReadinessVerdict.FAIL.value, f"harness boot rejected runtime: {reason}")
            return _gate(PROCESS_CLEANUP_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                         ReadinessVerdict.BLOCKED.value, f"harness boot failed: {reason}")
        cleanup = self._cleanup or {}
        root = cleanup.get("root")
        tree = cleanup.get("tree")
        if root == "ALIVE" or tree == "FAILED":
            return _gate(PROCESS_CLEANUP_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value,
                         f"process residue proven: root={root} tree={tree}")
        if root == "TERMINATED" and tree == "VERIFIED":
            return _gate(PROCESS_CLEANUP_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.READY.value,
                         "owned process tree mechanically proven gone")
        return _gate(PROCESS_CLEANUP_VERIFIED, "NOT_VERIFIED", EvidenceBasis.NOT_VERIFIED.value,
                     ReadinessVerdict.FAIL_CLOSED.value,
                     f"cleanup cannot be mechanically proven (root={root} tree={tree})", fail_closed=True)

    # ------------------------------------------------------------------
    # Secret hygiene
    # ------------------------------------------------------------------

    def _scan_markers(self, haystacks: list[str]) -> int:
        markers = ["Authorization", "Bearer ", "Cookie", "password", self.env.get("DEEPSEEK_API_KEY", "")]
        joined = "\n".join(haystacks)
        return sum(1 for marker in markers if marker and marker in joined)

    def _gate_secret_hygiene(self) -> ReadinessGate:
        if not self._haystacks:
            self._secret_markers_found = 0
            return _gate(SECRET_HYGIENE_VERIFIED, "YES", EvidenceBasis.NOT_AVAILABLE.value,
                         ReadinessVerdict.READY.value, "no runtime evidence was collected to leak")
        found = self._scan_markers(self._haystacks)
        self._secret_markers_found = found
        if found:
            return _gate(SECRET_HYGIENE_VERIFIED, "NO", EvidenceBasis.OBSERVED.value,
                         ReadinessVerdict.FAIL.value, f"{found} secret marker(s) found in bounded evidence")
        return _gate(SECRET_HYGIENE_VERIFIED, "YES", EvidenceBasis.OBSERVED.value,
                     ReadinessVerdict.READY.value, "no secret markers in any bounded probe evidence")

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    def probe(self) -> dict[str, Any]:
        self._gates = {}
        self._observed_version = None
        self._observed_profile = None
        self._observed_namespace = None
        self._observed_tools = ()
        self._mcp_handshake = None
        self._observe_error = None
        self._boot_error = None
        self._boot_ok = False
        self._cleanup = None
        self._owned_tails = ("", "")
        self._connectivity_result = None
        self._haystacks = []
        self._secret_markers_found = 0

        harness = self._gate_harness_available()
        binary_ok = harness.status == "YES"
        self._gates[harness.name] = harness

        version = self._gate_harness_version(binary_ok)
        self._gates[version.name] = version

        credential = self._gate_credential()
        self._gates[credential.name] = credential

        connectivity = self._gate_provider_connectivity(credential.status == "YES")
        self._gates[connectivity.name] = connectivity

        evidence = self._observe() if binary_ok else None
        self._record_observed(evidence)

        profile = self._gate_runtime_profile(evidence)
        self._gates[profile.name] = profile
        mcp_boot = self._gate_mcp_server_boot(evidence)
        self._gates[mcp_boot.name] = mcp_boot
        mcp_ns = self._gate_mcp_namespace(evidence)
        self._gates[mcp_ns.name] = mcp_ns
        mcp_tools = self._gate_mcp_toolset(evidence)
        self._gates[mcp_tools.name] = mcp_tools

        if binary_ok:
            self._boot_and_cleanup(evidence)
        process = self._gate_process_cleanup(binary_ok)
        self._gates[process.name] = process

        secret = self._gate_secret_hygiene()
        self._gates[secret.name] = secret

        result = self._compose_result()
        # Final self-check: the composed report itself must not expose secrets.
        if self._scan_markers([json.dumps(result, ensure_ascii=False, sort_keys=True)]):
            result["security"]["secret_hygiene"] = "FAIL"
            result["security"]["secret_markers_found"] = max(self._secret_markers_found, 1)
            result["gates"][SECRET_HYGIENE_VERIFIED]["status"] = "NO"
            result["gates"][SECRET_HYGIENE_VERIFIED]["verdict"] = ReadinessVerdict.FAIL.value
            result["gates"][SECRET_HYGIENE_VERIFIED]["detail"] = "secret marker found in composed readiness report"
            result["blockers"].append({"gate": SECRET_HYGIENE_VERIFIED, "verdict": ReadinessVerdict.FAIL.value,
                                       "detail": "secret marker found in composed readiness report"})
            result["result"] = self._overall_verdict()
            result["readiness_gates"][SECRET_HYGIENE_VERIFIED] = ReadinessVerdict.FAIL.value
        return result

    def _overall_verdict(self) -> str:
        verdicts = [gate.verdict for gate in self._gates.values()]
        if any(v in {ReadinessVerdict.FAIL.value, ReadinessVerdict.FAIL_CLOSED.value} for v in verdicts):
            return "FAIL"
        if any(v == ReadinessVerdict.BLOCKED.value for v in verdicts):
            return "BLOCKED"
        return "READY"

    def _process_residue(self) -> str:
        tree = (self._cleanup or {}).get("tree")
        root = (self._cleanup or {}).get("root")
        if tree == "FAILED" or root == "ALIVE":
            return "YES"
        if tree == "VERIFIED":
            return "NO"
        return "NOT_VERIFIED"

    def _compose_result(self) -> dict[str, Any]:
        connectivity_gate = self._gates[PROVIDER_CONNECTIVITY_VERIFIED]
        process_gate = self._gates[PROCESS_CLEANUP_VERIFIED]
        secret_gate = self._gates[SECRET_HYGIENE_VERIFIED]
        toolset_gate = self._gates[MCP_TOOLSET_VERIFIED]
        observed = set(self._observed_tools)
        unauthorized = sorted(observed - AUTHORIZED_TOOLS)
        cleanup = self._cleanup or {}
        blockers = [
            {"gate": name, "verdict": gate.verdict, "detail": gate.detail}
            for name, gate in self._gates.items()
            if gate.verdict != ReadinessVerdict.READY.value
        ]
        return {
            "task_id": TASK_ID,
            "result": self._overall_verdict(),
            "environment_readiness_probe_only": True,
            "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN,
            "formal_corpus_untouched": True,
            "harness": {
                "package": HARNESS_PACKAGE,
                "expected_version": EXPECTED_HARNESS_VERSION,
                "observed_version": self._observed_version,
                "package_pin_verified": self._package_pin() == EXPECTED_HARNESS_VERSION,
                "lockfile_pin_verified": self._lockfile_pin() == EXPECTED_HARNESS_VERSION,
                "executable_available": self._gates[HARNESS_AVAILABLE].status,
                "executable_boot_verified": "YES" if self._boot_ok else "NO",
                "installation_method": "npm ci from committed agent_runtime/package-lock.json",
                "evidence_basis": EvidenceBasis.OBSERVED.value if self._boot_ok else EvidenceBasis.NOT_VERIFIED.value,
            },
            "provider": {
                "approved_credential_present": self._gates[PROVIDER_CREDENTIAL_PRESENT].status,
                "credential_value_exposed": "NO",
                "connectivity_probe_attempted": "YES" if self._connectivity_result is not None else "NO",
                "connectivity_verified": connectivity_gate.status,
                "probe_marker": ENVIRONMENT_READINESS_PROBE_ONLY,
                "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN,
                "error_type": (self._connectivity_result or {}).get("error_type"),
            },
            "runtime": {
                "version": self._observed_version,
                "profile": self._observed_profile,
                "expected_profile": EXPECTED_PROFILE,
                "evidence_basis": self._gates[RUNTIME_PROFILE_VERIFIED].evidence_basis,
            },
            "mcp": {
                "server_boot": self._gates[MCP_SERVER_BOOT_VERIFIED].status,
                "namespace": self._observed_namespace or self._gates[MCP_NAMESPACE_VERIFIED].detail,
                "expected_namespace": MCP_NAMESPACE,
                "tool_count": len(self._observed_tools),
                "tools": sorted(self._observed_tools),
                "authorized_tools": sorted(AUTHORIZED_TOOLS),
                "unauthorized_tool_count": len(unauthorized),
                "evidence_basis": toolset_gate.evidence_basis,
            },
            "process": {
                "root_terminated": (cleanup.get("root") == "TERMINATED") if cleanup else "NOT_STARTED",
                "owned_tree_cleanup": cleanup.get("tree", "NOT_VERIFIED"),
                "process_residue": self._process_residue(),
                "evidence_basis": process_gate.evidence_basis,
            },
            "security": {
                "secret_hygiene": secret_gate.status,
                "secret_markers_found": self._secret_markers_found,
                "secret_diff_scan": "run before commit",
                "evidence_basis": secret_gate.evidence_basis,
            },
            "gates": {name: gate.to_dict() for name, gate in self._gates.items()},
            "readiness_gates": {name: gate.verdict for name, gate in self._gates.items()},
            "blockers": blockers,
        }
