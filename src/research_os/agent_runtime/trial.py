"""Bounded, internal-only P8-B2 Harness trial controller."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .config import AgentRuntimeConfig
from .errors import RuntimeFailure, RuntimeNotReady
from .gateway import AgentRuntimeGateway
from .legacy_adapter import LegacyAgentRuntimeAdapter
from .production_runtime import ROOT, build_production_harness_adapter


TRIAL_ENV = "P8_B2_INTERNAL_TRIAL"
ALLOWED_TOOLS = frozenset({"get_company_profile", "check_data_readiness"})
ENTITY_CORPUS = (
    ("600519.SH", "Kweichow Moutai"),
    ("300750.SZ", "CATL"),
) * 5
ENTITY_ALIASES = {
    "600519.SH": frozenset({"600519.SH", "600519", "Kweichow Moutai", "贵州茅台", "茅台"}),
    "300750.SZ": frozenset({"300750.SZ", "300750", "CATL", "宁德时代"}),
}
PASS_CANDIDATE = "PASS CANDIDATE"
PARTIAL = "PARTIAL"


class EvidenceBasis(str, Enum):
    """Provenance distinction for acceptance fields.

    A value must never *look* mechanically observed when it is only a static
    policy assertion.
    """

    OBSERVED = "OBSERVED"
    DERIVED_FROM_OBSERVED_RUNTIME = "DERIVED_FROM_OBSERVED_RUNTIME"
    POLICY_INVARIANT = "POLICY_INVARIANT"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_VERIFIED = "NOT_VERIFIED"


class LatchState(str, Enum):
    ENABLED = "ENABLED"
    TRIPPED = "TRIPPED"
    DISABLED = "DISABLED"


class TrialSafetyLatch:
    def __init__(self) -> None:
        self.state = LatchState.DISABLED
        self.reason: str | None = None

    def enable(self) -> None:
        if self.state is LatchState.TRIPPED:
            raise RuntimeNotReady("TRIAL_LATCH_TRIPPED", "operator reset is required")
        self.state = LatchState.ENABLED
        self.reason = None

    def admit(self) -> None:
        if self.state is not LatchState.ENABLED:
            detail = "operator reset is required" if self.state is LatchState.TRIPPED else f"trial latch is {self.state.value}"
            raise RuntimeNotReady("TRIAL_ADMISSION_DENIED", detail)

    def trip(self, reason: str) -> None:
        self.state = LatchState.TRIPPED
        self.reason = reason[:160]

    def operator_reset(self) -> None:
        self.state = LatchState.DISABLED
        self.reason = None


@dataclass(frozen=True)
class TrialBudget:
    max_sessions: int = 10
    max_turns: int = 20
    max_tool_calls: int = 60
    # Governance decision P8-B2-LIVE-01-BUDGET-DECISION-01 (Option B):
    # raised from 200_000 to 1_000_000 based on observed provider usage
    # (23.8k-44.3k tokens/turn; 20 turns ≈ 476k-886k). See
    # docs/tasks/p8-b2-live-01-budget-decision.md.
    max_provider_tokens: int = 1_000_000
    max_retries: int = 0
    turn_timeout_seconds: int = 300
    warning_ratio: float = 0.8


@dataclass
class TrialCounters:
    session_create_attempts: int = 0
    session_create_success: int = 0
    turn_attempts: int = 0
    turn_completed: int = 0
    sessions: int = 0
    turns: int = 0
    tool_calls: int = 0
    provider_tokens: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0
    retries: int = 0


class TrialMetricsRecorder:
    """Bounded aggregate recorder; raw prompts/responses never enter it."""

    def __init__(self, trial_id: str):
        self.trial_id = trial_id
        self.events: list[dict[str, Any]] = []
        self.counters = TrialCounters()
        self.failures: dict[str, int] = {}
        self.same_session_pass = 0
        self.reread_pass = 0
        self.authority_drift_count = 0
        self.cross_session_contamination_count = 0
        self.unauthorized_tool_count = 0
        self.secret_leak_count = 0
        self.process_failure_count = 0
        self.process_leak_count = 0
        self.mcp_failure_count = 0
        self.provider_failure_count = 0
        self.fallback_count = 0
        self.budget_warning_emitted = False
        self.turn1_evidence_pass = 0
        self.turn2_readiness_pass = 0
        self.authority_evidence_missing_count = 0
        self.internal_session_ids: set[str] = set()
        self.cross_session_checked = 0
        self.session_entity_map: dict[str, str] = {}
        self.session_creation_latencies_ms: list[int] = []
        self.turn_latencies_ms: list[int] = []

    def record(self, **event: Any) -> None:
        forbidden = {"full_prompt", "prompt", "full_response", "response", "raw_payload", "credential", "reasoning"}
        bounded = {"trial_run_id": self.trial_id}
        bounded.update({key: value for key, value in event.items() if key not in forbidden})
        self.events.append(bounded)

    def failure(self, code: str, *, provider: bool = False, mcp: bool = False) -> None:
        """Record one causal failure exactly once.

        This is the single counting authority for typed failures. Callers
        (the corpus-level handler) must invoke it at most once per causal
        exception; attempt counters separately track attempts.
        """
        self.failures[code] = self.failures.get(code, 0) + 1
        self.provider_failure_count += int(provider)
        self.mcp_failure_count += int(mcp)


def _hash_public_session(trial_id: str, public_id: str) -> str:
    return hashlib.sha256(f"{trial_id}:{public_id}".encode()).hexdigest()[:16]


def _read_event_log(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            events.append(item)
    return events


def _tool_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts = {name: 0 for name in ALLOWED_TOOLS}
    successful = {"success", "partial_success", "insufficient_evidence", "data_degraded"}
    for event in events:
        name = event.get("tool_name")
        if event.get("event_type") == "tool_call" and event.get("status", "success") in successful and name in counts:
            counts[name] += 1
    return counts


def _usage_from_result(result: dict[str, Any]) -> int:
    usage = (result.get("operational_metadata") or {}).get("usage") or {}
    total = usage.get("total_tokens")
    if isinstance(total, int) and total >= 0:
        return total
    values = [usage.get("input_tokens"), usage.get("output_tokens"), usage.get("cached_tokens")]
    if all(isinstance(value, int) and value >= 0 for value in values if value is not None):
        return sum(value for value in values if isinstance(value, int))
    return 0


def _usage_components(result: dict[str, Any]) -> dict[str, int]:
    usage = (result.get("operational_metadata") or {}).get("usage") or {}
    return {name: int(usage[name]) for name in ("input_tokens", "output_tokens", "cached_tokens")
            if isinstance(usage.get(name), int) and usage[name] >= 0}


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


def _contains_secret(text: str, markers: list[str]) -> bool:
    return any(marker and marker in text for marker in markers)


class TrialController:
    def __init__(self, *, budget: TrialBudget | None = None, trial_id: str | None = None):
        self.budget = budget or TrialBudget()
        self.trial_id = trial_id or f"b2-{uuid.uuid4().hex}"
        self.latch = TrialSafetyLatch()
        self.metrics = TrialMetricsRecorder(self.trial_id)
        self.counters = self.metrics.counters
        self.adapter = None
        self.gateway: AgentRuntimeGateway | None = None
        self.evidence: dict[str, Any] | None = None
        event_fd, event_name = tempfile.mkstemp(prefix="p8-b2-events-", suffix=".jsonl")
        os.close(event_fd)
        self.event_log = Path(event_name)
        self._previous_event_log: str | None = None
        self._started = False
        self.rollback_pass = False
        self.fallback_pass = False
        self.restart_pass = False
        self.owned_root_pid: int | None = None
        self.root_alive_after_stop: bool | None = None
        self.owned_descendant_count_after_stop: int | None = None
        self.owned_tree_cleanup: str | None = None
        self.root_cleanup: str | None = None
        self.usage_fields: set[str] = set()
        self.authority_entity_ids: dict[str, str] = {}
        self._evidence_snapshot: dict[str, Any] | None = None
        self._final_completed_sessions: int | None = None

    def _require_opt_in(self) -> None:
        if os.environ.get(TRIAL_ENV) != "1":
            raise RuntimeNotReady("TRIAL_NOT_ENABLED", f"set {TRIAL_ENV}=1 for internal trial")

    def start(self) -> dict[str, Any]:
        self._require_opt_in()
        self.latch.enable()
        self._previous_event_log = os.environ.get("P8_B1_EVENT_LOG")
        os.environ["P8_B1_EVENT_LOG"] = str(self.event_log)
        config = AgentRuntimeConfig(mode="harness", max_turns=2,
                                    max_active_sessions=self.budget.max_sessions,
                                    turn_timeout_seconds=self.budget.turn_timeout_seconds)
        try:
            self.adapter, self.evidence = build_production_harness_adapter(config, require_credential=True)
            self._preflight_entities()
            self.gateway = AgentRuntimeGateway(config, harness=self.adapter, fallback_before_workflow=False)
            self._started = True
            self.metrics.record(event_type="trial_started", runtime_version=self.evidence["version"],
                                profile=self.evidence["profile"], mcp_namespace=self.evidence["mcp_namespace"])
            return {"status": "started", "trial_run_id": self.trial_id,
                    "runtime_version": self.evidence["version"], "profile": self.evidence["profile"]}
        except Exception:
            self.metrics.process_failure_count += 1
            self.latch.trip("runtime admission failed")
            self.stop()
            raise

    def _preflight_entities(self) -> None:
        from .mcp.tools import build_research_os_mcp_server
        authority = build_research_os_mcp_server()
        authority.perform_handshake()
        for symbol, _name in (ENTITY_CORPUS[0], ENTITY_CORPUS[1]):
            result = authority.call("get_company_profile", {"target": symbol}, f"preflight-{symbol}")
            reference = (result.get("security_reference") or {}).get("symbol")
            if result.get("status") not in {"success", "partial_success"} or reference != symbol:
                raise RuntimeNotReady("AUTHORITY_PREFLIGHT_FAILED", f"entity authority unavailable: {symbol}")
            if isinstance(result.get("entity_id"), str):
                self.authority_entity_ids[symbol] = result["entity_id"]

    def _admit_session(self) -> None:
        self.latch.admit()
        if self.counters.sessions >= self.budget.max_sessions:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "trial session budget exhausted")

    def _admit_turn(self) -> None:
        self.latch.admit()
        if self.counters.turns >= self.budget.max_turns:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "trial turn budget exhausted")
        ratios = (
            self.counters.turns / self.budget.max_turns,
            self.counters.tool_calls / self.budget.max_tool_calls,
            self.counters.provider_tokens / self.budget.max_provider_tokens,
        )
        if any(ratio >= 1 for ratio in ratios):
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "trial budget exhausted")

    def _budget_check(self) -> None:
        ratios = [
            self.counters.turns / self.budget.max_turns,
            self.counters.tool_calls / self.budget.max_tool_calls,
            self.counters.provider_tokens / self.budget.max_provider_tokens,
        ]
        if max(ratios) > 1:
            raise RuntimeNotReady("RESOURCE_BUDGET_EXCEEDED", "trial budget exhausted")
        if max(ratios) >= self.budget.warning_ratio and not self.metrics.budget_warning_emitted:
            self.metrics.record(event_type="budget_warning", utilization=round(max(ratios), 3))
            self.metrics.budget_warning_emitted = True

    def _run_turn(self, public_session: Any, entity: tuple[str, str], turn_index: int, prompt: str) -> dict[str, Any]:
        self._admit_turn()
        self.counters.turn_attempts += 1
        if self.gateway is None or self.adapter is None:
            raise RuntimeNotReady("TRIAL_NOT_STARTED", "trial runtime is not started")
        before_events = _read_event_log(self.event_log)
        before_internal = self.adapter.sessions[public_session.gateway_session_id].harness_session_id
        started = time.monotonic()
        try:
            result = self.gateway.send_message(public_session.gateway_session_id, prompt)
        except RuntimeFailure as exc:
            # NOTE: counting is deferred to the single corpus-level owner to
            # avoid double counting one causal failure (R2-01). Only bounded
            # evidence is recorded here.
            self.metrics.record(event_type="turn_failure", session_public_hash=_hash_public_session(self.trial_id, public_session.gateway_session_id),
                                turn_index=turn_index, code=exc.code)
            raise
        after_events = _read_event_log(self.event_log)
        after_internal = self.adapter.sessions[public_session.gateway_session_id].harness_session_id
        duration_ms = round((time.monotonic() - started) * 1000)
        new_events = after_events[len(before_events):]
        counts = _tool_counts(new_events)
        unauthorized = sum(1 for event in new_events if event.get("event_type") == "tool_call"
                           and event.get("tool_name") not in ALLOWED_TOOLS)
        authority_events = [event for event in new_events if event.get("event_type") == "tool_call"]
        authority_statuses = {"success", "partial_success", "insufficient_evidence", "data_degraded"}
        self.metrics.mcp_failure_count += sum(
            1 for event in authority_events if event.get("status") not in authority_statuses
        )
        for event in authority_events:
            if event.get("status") not in authority_statuses:
                continue
            authority = event.get("authority") if isinstance(event.get("authority"), dict) else {}
            authority_target = authority.get("security_reference") or authority.get("entity_id")
            target = authority_target
            target_text = str(target) if target is not None else ""
            known = set(ENTITY_ALIASES.get(entity[0], frozenset({entity[0]})))
            if entity[0] in self.authority_entity_ids:
                known.add(self.authority_entity_ids[entity[0]])
            if target_text and not any(reference in target_text for reference in known):
                self.metrics.authority_drift_count += 1
            if not target_text:
                self.metrics.authority_evidence_missing_count += 1
        self.counters.turns += 1
        self.counters.turn_completed += 1
        self.metrics.turn_latencies_ms.append(duration_ms)
        self.counters.tool_calls += sum(counts.values()) + unauthorized
        self.counters.provider_tokens += _usage_from_result(result)
        usage = _usage_components(result)
        self.usage_fields.update(usage)
        self.counters.input_tokens += usage.get("input_tokens", 0)
        self.counters.output_tokens += usage.get("output_tokens", 0)
        self.counters.cached_tokens += usage.get("cached_tokens", 0)
        same_session = bool(before_internal and before_internal == after_internal)
        if same_session:
            self.metrics.same_session_pass += 1
        if turn_index == 2 and counts["check_data_readiness"] >= 1:
            self.metrics.reread_pass += 1
            self.metrics.turn2_readiness_pass += 1
        if turn_index == 1 and counts["get_company_profile"] >= 1 and counts["check_data_readiness"] >= 1:
            self.metrics.turn1_evidence_pass += 1
        public_hash = _hash_public_session(self.trial_id, public_session.gateway_session_id)
        self.metrics.session_entity_map[public_hash] = entity[0]
        response_text = str(result.get("response", ""))
        for other_symbol, other_name in ENTITY_CORPUS:
            if other_symbol != entity[0] and (other_symbol in response_text or other_name in response_text):
                self.metrics.cross_session_contamination_count += 1
        self.metrics.unauthorized_tool_count += unauthorized
        self.metrics.record(
            event_type="turn_completed",
            session_public_hash=public_hash,
            turn_index=turn_index, entity=entity[0], runtime_version=self.evidence["version"],
            profile=self.evidence["profile"], provider_status=result.get("status"),
            tool_counts=counts, unauthorized_tool_count=unauthorized,
            same_session=same_session, duration_ms=duration_ms,
            usage_reported=bool((result.get("operational_metadata") or {}).get("usage")),
        )
        self._budget_check()
        return result

    def run_session(self, entity: tuple[str, str]) -> dict[str, Any]:
        self._admit_session()
        self.counters.session_create_attempts += 1
        if self.gateway is None or self.adapter is None:
            raise RuntimeNotReady("TRIAL_NOT_STARTED", "trial runtime is not started")
        session_started = time.monotonic()
        public_session = self.gateway.create_session({"trial_run_id": self.trial_id, "entity": entity[0]})
        self.metrics.session_creation_latencies_ms.append(round((time.monotonic() - session_started) * 1000))
        internal = self.adapter.sessions[public_session.gateway_session_id].harness_session_id
        if not internal or internal in self.metrics.internal_session_ids:
            self.metrics.cross_session_contamination_count += 1
        self.metrics.internal_session_ids.add(internal or "")
        self.metrics.cross_session_checked += 1
        self.counters.sessions += 1
        self.counters.session_create_success += 1
        self.metrics.record(event_type="session_created",
                            session_public_hash=_hash_public_session(self.trial_id, public_session.gateway_session_id),
                            entity=entity[0], internal_mapping_present=bool(internal))
        try:
            first = self._run_turn(public_session, entity, 1,
                                   f"For {entity[0]} {entity[1]}, call get_company_profile once and check_data_readiness once. Return a short structured summary.")
            second = self._run_turn(public_session, entity, 2,
                                    "In this same session, call check_data_readiness exactly once now and report the fresh result. Do not use cached results.")
            return {"status": "completed", "public_session": public_session,
                    "first": first, "second": second}
        finally:
            self.gateway.close_session(public_session.gateway_session_id)

    def run_corpus(self) -> dict[str, Any]:
        self._require_opt_in()
        if not self._started:
            self.start()
        completed = 0
        for entity in ENTITY_CORPUS:
            try:
                self.run_session(entity)
                completed += 1
            except RuntimeFailure as exc:
                self.metrics.failure(exc.code, provider=exc.code.startswith("PROVIDER"),
                                     mcp=exc.code.startswith("MCP"))
                if exc.code in {"PROFILE_POLICY_MISMATCH", "MCP_UNAVAILABLE", "HARNESS_BOOT_FAILED"}:
                    self.latch.trip(exc.code)
                    break
        self._completed_sessions = completed
        result = self.summary(completed, final=False)
        result["status"] = "IN_PROGRESS"
        return result

    def rollback_drill(self) -> dict[str, Any]:
        class FailingHarness:
            mode = "harness"

            def create_session(self, metadata=None):
                raise RuntimeNotReady("MCP_UNAVAILABLE", "controlled rollback fixture")

        fallback_gateway = AgentRuntimeGateway(
            AgentRuntimeConfig(mode="harness", max_turns=2, max_active_sessions=1),
            legacy=LegacyAgentRuntimeAdapter(project_root=ROOT),
            harness=FailingHarness(), fallback_before_workflow=True,
        )
        routed = fallback_gateway.create_session({"trial_run_id": self.trial_id, "rollback": "1"})
        fallback_reason = fallback_gateway._fallback_reasons.get(routed.gateway_session_id)
        legacy_response = fallback_gateway.send_message(routed.gateway_session_id, "rollback readiness probe")
        self.metrics.fallback_count += int(routed.runtime_mode == "legacy" and bool(fallback_reason))
        self.fallback_pass = bool(routed.runtime_mode == "legacy" and fallback_reason == "MCP_UNAVAILABLE"
                                  and isinstance(legacy_response, dict))
        fallback_gateway.close_session(routed.gateway_session_id)
        self.latch.trip("controlled rollback drill")
        denied = False
        try:
            self._admit_session()
        except RuntimeNotReady:
            denied = True
        self.rollback_pass = denied
        return {"rollback_latch": "PASS" if denied else "FAIL", "new_admission_denied": denied,
                "real_legacy_fallback": "PASS" if self.fallback_pass else "FAIL",
                "fallback_reason": fallback_reason}

    def restart_drill(self) -> dict[str, Any]:
        """Terminate only the owned runtime root, then restart and re-verify it."""
        if self.adapter is None:
            return {"crash_restart": "FAIL"}
        owned_process = self.adapter.supervisor.process
        if owned_process is None:
            return {"crash_restart": "FAIL"}
        terminate_tree = getattr(owned_process, "terminate_tree", None)
        if callable(terminate_tree):
            terminate_tree()
        else:
            owned_process.terminate()
        self.adapter.supervisor.stop()
        self.adapter = None
        self.gateway = None
        try:
            self.latch.operator_reset()
            self.start()
            self.restart_pass = True
            return {"crash_restart": "PASS", "runtime_reverified": True}
        except RuntimeFailure as exc:
            # start() already records the admission failure (process_failure /
            # typed). Do not double count the same causal restart failure here.
            self.restart_pass = False
            return {"crash_restart": "FAIL", "runtime_reverified": False}

    def operator_reset(self) -> None:
        self.latch.operator_reset()

    def _process_residue(self) -> str:
        """Mechanical source for the owned process-tree residue gate.

        Three-state, mechanically consistent (R2-04 / rework 3-4):
          - owned_tree_cleanup == ``VERIFIED`` -> ``NO`` (tree proven gone)
          - owned_tree_cleanup == ``FAILED``   -> ``YES`` (real process leak)
          - root still alive, or recorded leak  -> ``YES``
          - otherwise (tree ``NOT_VERIFIED``)   -> ``NOT_VERIFIED`` (fail-closed)
        ``NO`` is only possible when the owned process tree is mechanically
        proven empty; ``FAILED`` is always surfaced as a real residue.
        """
        tree = self.owned_tree_cleanup
        if tree == "FAILED":
            return "YES"
        if tree == "VERIFIED":
            return "NO"
        if self.root_cleanup == "ALIVE" or self.metrics.process_leak_count > 0:
            return "YES"
        return "NOT_VERIFIED"

    def _evidence_basis(self, *, final: bool) -> dict[str, str]:
        """Classify acceptance-field provenance from evidence that actually exists.

        Values reflect whether observational evidence was produced for this
        trial, not static configuration intent:
          - OBSERVED                         evidence actually recorded
          - DERIVED_FROM_OBSERVED_RUNTIME    derived from an observed running
                                             Harness for this trial
          - POLICY_INVARIANT                 a policy/authorization constant
                                             (never claimed as observed)
          - NOT_AVAILABLE / NOT_VERIFIED     evidence did not exist/verified
        """
        runtime_observed = bool(self.evidence and self.evidence.get("version"))
        runtime_derived = EvidenceBasis.DERIVED_FROM_OBSERVED_RUNTIME.value if runtime_observed else EvidenceBasis.NOT_AVAILABLE.value
        runs_observed = final and self.counters.turn_completed > 0
        observed = EvidenceBasis.OBSERVED.value if runs_observed else EvidenceBasis.NOT_AVAILABLE.value
        secret_observed = final or self._started
        process_leak = self.owned_tree_cleanup
        process_basis = (
            EvidenceBasis.OBSERVED.value
            if process_leak in {"VERIFIED", "FAILED"}
            else EvidenceBasis.NOT_VERIFIED.value
        )
        return {
            "runtime_version": runtime_derived,
            "profile": runtime_derived,
            "mcp_namespace": runtime_derived,
            "mcp_tools": runtime_derived,
            "same_session": observed,
            "fresh_readiness": observed,
            "turn1_tool_evidence": observed,
            "authority_drift": observed,
            "unauthorized_tools": observed,
            "secret_scan": EvidenceBasis.OBSERVED.value if secret_observed else EvidenceBasis.NOT_AVAILABLE.value,
            "process_residue": process_basis,
            "provider_failures": EvidenceBasis.OBSERVED.value if (final or self.metrics.failures) else EvidenceBasis.NOT_AVAILABLE.value,
            "mcp_failures": EvidenceBasis.OBSERVED.value if (final or self.metrics.mcp_failure_count) else EvidenceBasis.NOT_AVAILABLE.value,
            "research_data_network": EvidenceBasis.POLICY_INVARIANT.value,
            "research_source_network": EvidenceBasis.POLICY_INVARIANT.value,
            "internal_session_leak": EvidenceBasis.NOT_VERIFIED.value,
            "graph_mutation_count": EvidenceBasis.POLICY_INVARIANT.value,
            "sql_tool_count": EvidenceBasis.POLICY_INVARIANT.value,
            "frontend_changed": EvidenceBasis.POLICY_INVARIANT.value,
            "default_runtime": EvidenceBasis.POLICY_INVARIANT.value,
            "production_adoption": EvidenceBasis.POLICY_INVARIANT.value,
        }

    def evaluate_final_trial(self) -> dict[str, Any]:
        """Evaluate the official post-fix acceptance corpus.

        Finalization sequence (single authority, R2-02/R2-03/R2-04):
          collect final runtime evidence
          → perform final secret scan      (inside ``summary``'s freeze path)
          → perform owned process cleanup  (``stop``)
          → mechanically observe cleanup   (``stop``)
          → freeze evidence snapshot
          → render summary / return
          → delete temporary raw artifacts (after snapshot is frozen)
        """
        if self._evidence_snapshot is None:
            completed = getattr(self, "_completed_sessions", None)
            if completed is None:
                completed = 0
            self._final_completed_sessions = completed
            self.stop()  # cleanup + final secret scan + observe residue
            self._freeze_evidence_snapshot()
        return self._evidence_snapshot

    def finalize_fail_closed(self, reason: str) -> dict[str, Any]:
        """Produce a complete fail-closed evidence snapshot after a
        boot/start/run failure, even when the runtime never became available.

        This satisfies the acceptance requirement that a failed trial still
        renders the full acceptance field set with explicit evidence basis,
        rather than a bare error object. ``stop()`` is invoked to (attempt)
        owned cleanup and free the temporary event log; the frozen snapshot
        reflects the mechanically available evidence only.
        """
        if self._evidence_snapshot is None:
            self._final_completed_sessions = 0
            self.latch.trip("trial failed closed")
            self.stop()
            self._freeze_evidence_snapshot()
            assert self._evidence_snapshot is not None
        # Non-authoritative metadata: may be added, never changes hard gates.
        snapshot = dict(self._evidence_snapshot)
        snapshot["error_code"] = reason
        snapshot["status"] = "PARTIAL"
        return snapshot

    def _freeze_evidence_snapshot(self) -> None:
        """Freeze the final acceptance evidence snapshot once; later renders
        format it but must not change acceptance fields."""
        if self._evidence_snapshot is not None:
            return
        completed = self._final_completed_sessions
        if completed is None:
            completed = self._completed_sessions
        self._ev_render = self._render_summary(completed, final=True)
        # Deep-copy the mutable render so live state changes cannot leak in.
        self._evidence_snapshot = json.loads(json.dumps(self._ev_render))
        self._ev_render = None

    def summary(self, completed_sessions: int, *, final: bool = True) -> dict[str, Any]:
        if self._evidence_snapshot is not None:
            # Report layer may format a frozen snapshot; it may not change it.
            return dict(self._evidence_snapshot)
        return self._render_summary(completed_sessions, final=final)

    def _render_summary(self, completed_sessions: int, *, final: bool = True) -> dict[str, Any]:
        self._scan_secrets()
        hard_pass = (
            completed_sessions >= self.budget.max_sessions
            and self.counters.turns >= self.budget.max_turns
            and self.metrics.authority_drift_count == 0
            and self.metrics.cross_session_contamination_count == 0
            and self.metrics.unauthorized_tool_count == 0
            and self.metrics.secret_leak_count == 0
            and self.metrics.process_failure_count == 0
            and self.metrics.process_leak_count == 0
            and self.metrics.mcp_failure_count == 0
            and self.evidence is not None
            and self.evidence.get("version") == "0.1.0-rc.7"
            and self.evidence.get("profile") == "research-headless"
            and set(self.evidence.get("tools", ())) == ALLOWED_TOOLS
            and self.metrics.same_session_pass == self.counters.turns
            and self.metrics.reread_pass == completed_sessions
            and self.metrics.turn1_evidence_pass == completed_sessions
            and self.metrics.authority_drift_count == 0
            and self.metrics.authority_evidence_missing_count == 0
            and self.metrics.cross_session_checked == completed_sessions
            and self.rollback_pass
            and self.fallback_pass
            and self.restart_pass
            and self.counters.provider_tokens > 0
            and self._process_residue() == "NO"
        )
        usage_reported = self.counters.provider_tokens > 0
        return {
            "status": "PASS CANDIDATE" if final and hard_pass else ("PARTIAL" if final else "IN_PROGRESS"),
            "trial_run_id": self.trial_id,
            "runtime_version": self.evidence["version"] if self.evidence else "NOT_AVAILABLE",
            "profile": self.evidence["profile"] if self.evidence else "NOT_AVAILABLE",
            "mcp_namespace": self.evidence["mcp_namespace"] if self.evidence else "NOT_AVAILABLE",
            "mcp_tools": list(self.evidence["tools"]) if self.evidence else [],
            "trial_sessions": completed_sessions,
            "trial_turns": self.counters.turns,
            "session_create_attempts": self.counters.session_create_attempts,
            "session_create_success": self.counters.session_create_success,
            "turn_attempts": self.counters.turn_attempts,
            "turn_completed": self.counters.turn_completed,
            "same_session_pass": self.metrics.same_session_pass,
            "turn2_reread_pass": self.metrics.reread_pass,
            "turn1_tool_evidence_pass": self.metrics.turn1_evidence_pass,
            "authority_evidence_missing_count": self.metrics.authority_evidence_missing_count,
            "authority_drift_count": self.metrics.authority_drift_count,
            "cross_session_contamination_count": self.metrics.cross_session_contamination_count,
            "unauthorized_tool_count": self.metrics.unauthorized_tool_count,
            "secret_leak_count": self.metrics.secret_leak_count,
            "secret_scan": "PASS" if self.metrics.secret_leak_count == 0 else "FAIL",
            "process_failure_count": self.metrics.process_failure_count,
            "provider_failures": self.metrics.provider_failure_count,
            "mcp_failures": self.metrics.mcp_failure_count,
            "fallback_count": self.metrics.fallback_count,
            "real_legacy_fallback": "PASS" if self.fallback_pass else "NOT_RUN",
            "typed_failures": self.metrics.failures,
            "total_input_tokens": self.counters.input_tokens if "input_tokens" in self.usage_fields else "NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME",
            "total_output_tokens": self.counters.output_tokens if "output_tokens" in self.usage_fields else "NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME",
            "total_cached_tokens": self.counters.cached_tokens if "cached_tokens" in self.usage_fields else "NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME",
            "total_tokens": self.counters.provider_tokens if usage_reported else "NOT_REPORTED",
            "provider_reported_cost": "NOT_AVAILABLE_FROM_ACCEPTED_RUNTIME",
            "budget_utilization": {
                "sessions": round(self.counters.sessions / self.budget.max_sessions, 3),
                "turns": round(self.counters.turns / self.budget.max_turns, 3),
                "tool_calls": round(self.counters.tool_calls / self.budget.max_tool_calls, 3),
                "provider_tokens": round(self.counters.provider_tokens / self.budget.max_provider_tokens, 3),
            },
            "session_creation_latency_ms": {
                "p50": _percentile(self.metrics.session_creation_latencies_ms, 0.50),
                "p95": _percentile(self.metrics.session_creation_latencies_ms, 0.95),
            },
            "turn_latency_ms": {
                "p50": _percentile(self.metrics.turn_latencies_ms, 0.50),
                "p95": _percentile(self.metrics.turn_latencies_ms, 0.95),
            },
            "research_data_network": "OFF",
            "rollback_latch": "PASS" if self.rollback_pass else "NOT_RUN",
            "crash_restart": "PASS" if self.restart_pass else "NOT_RUN",
            "internal_session_leak": "NOT_VERIFIED",
            "process_leak_count": self.metrics.process_leak_count,
            "research_source_network": "OFF",
            "graph_mutation_count": 0,
            "sql_tool_count": 0,
            "frontend_changed": "NO",
            "process_residue": self._process_residue(),
            "root_cleanup": self.root_cleanup or "NOT_STARTED",
            "owned_tree_cleanup": self.owned_tree_cleanup or "NOT_VERIFIED",
            "default_runtime": "legacy",
            "production_adoption": "NOT_AUTHORIZED",
            "evidence_basis": self._evidence_basis(final=final),
        }

    def _scan_secrets(self) -> None:
        """Scan bounded runtime evidence for known secret markers.

        Secret evidence is monotonic (R2-03): a positive finding anywhere in
        the trial lifecycle must not later become zero because artifacts were
        cleaned up. We only ever take the maximum across scans so cleanup never
        erases an earlier positive result. Raw secret values are never stored;
        only the bounded count retained.
        """
        candidates = [os.environ.get("DEEPSEEK_API_KEY", ""), "Authorization", "Bearer ", "Cookie", "password"]
        haystacks = [_read_event_log(self.event_log).__repr__()]
        if self.adapter is not None and self.adapter.supervisor.process is not None:
            owned = self.adapter.supervisor.process
            haystacks.extend((bytes(owned.stdout_tail).decode(errors="replace"),
                              bytes(owned.stderr_tail).decode(errors="replace")))
        found = sum(1 for marker in candidates if _contains_secret("\n".join(haystacks), [marker]))
        self.metrics.secret_leak_count = max(self.metrics.secret_leak_count, found)

    def stop(self) -> None:
        """Finalize owned process cleanup and (re)observe cleanup evidence.

        Order matters for acceptance evidence integrity:
          1. final secret scan (before artifacts are deleted)
          2. owned process-tree cleanup
          3. mechanical observation of cleanup result
          4. release references
        Delete temporary raw artifacts only after the evidence snapshot has
        been frozen (see ``evaluate_final_trial``).
        """
        self._scan_secrets()
        if self.adapter is not None:
            owned = self.adapter.supervisor.process
            if owned is not None:
                self.owned_root_pid = owned.owned_pid if hasattr(owned, "owned_pid") else owned.process.pid
            # Terminate only the owned process tree.
            if owned is not None:
                terminate = getattr(owned, "terminate_tree", None)
                if callable(terminate):
                    terminate()
            self.adapter.supervisor.stop()
            if owned is not None:
                self.root_alive_after_stop = owned.poll() is None
                status = getattr(owned, "cleanup_status", None)
                if callable(status):
                    status = status()
                    self.root_cleanup = status.get("root")
                    self.owned_tree_cleanup = status.get("tree")
                else:
                    self.root_cleanup = "NOT_VERIFIED"
                    self.owned_tree_cleanup = "NOT_VERIFIED"
                self.owned_descendant_count_after_stop = int(self.root_alive_after_stop)
                # A mechanically proven leak: root still alive OR owned-tree
                # cleanup reports FAILED (group proven non-empty).
                tree_failed = self.owned_tree_cleanup == "FAILED"
                self.metrics.process_leak_count = int(
                    self.root_alive_after_stop or tree_failed
                )
        self.adapter = None
        self.gateway = None
        self._started = False
        if self._previous_event_log is None:
            os.environ.pop("P8_B1_EVENT_LOG", None)
        else:
            os.environ["P8_B1_EVENT_LOG"] = self._previous_event_log
        if os.environ.get("P8_B2_KEEP_EVENT_LOG") == "1":
            return
        try:
            self.event_log.unlink()
        except (FileNotFoundError, PermissionError):
            pass

    def __enter__(self) -> "TrialController":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.stop()
