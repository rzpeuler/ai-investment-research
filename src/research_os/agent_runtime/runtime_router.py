"""P8-A2 Hybrid Agent Runtime Router (deterministic, config-driven, no LLM).

Authority: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN (Decision #82) + P8-ARCH-001
(Decision #80). The router maps a task definition to a runtime decision using
the governance policy artifact (``config/runtime_policy.yaml``). It never calls
an LLM and never makes an implicit choice; every decision is recorded with its
reason (see :mod:`research_os.agent_runtime.pilot_audit`).

Decision space:
  LEGACY_ONLY      - structured artifact / strict-schema output or unlisted task
  HARNESS_ALLOWED  - exploration task on the whitelist (governance flag on)
  HYBRID           - two-phase split (Phase A harness -> Phase B legacy);
                     reserved; no task enabled in this pilot

Rules (P8-A1 §3.2):
  output_contract == strict_schema          -> LEGACY_ONLY (frozen)
  task in exploration whitelist + enabled   -> HARNESS_ALLOWED
  task in hybrid whitelist + enabled        -> HYBRID (split)
  anything else                             -> LEGACY_ONLY (default, fail-closed)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from research_os.agent_runtime.errors import ConfigurationError

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_POLICY_PATH = ROOT / "config" / "runtime_policy.yaml"

# Task types from P8-A1 (extraction / normalization / reasoning / generation).
TASK_TYPES = frozenset({
    "extraction", "normalization", "reasoning", "generation", "exploration",
})
OUTPUT_CONTRACTS = frozenset({"strict_schema", "free_text", "notes"})
RISK_LEVELS = frozenset({"low", "medium", "high"})
AUTHORITY_REQUIREMENTS = frozenset({
    "read_only", "write_artifact", "evidence_binding", "none",
})

# P8-A1 LEGACY_REQUIRED task ids (strict-schema artifacts). These are explicit
# exclusions documented in the policy; the router treats them as unlisted and
# therefore routes to legacy. Kept here only for policy validation (the config
# whitelist must not contain them).
LEGACY_REQUIRED_TASKS = frozenset({
    "financial_fact_generation",
    "research_finding_generation",
    "catalyst_risk_artifact",
    "evidence_binding",
    "final_report_section",
})


class RuntimeSelection(str, Enum):
    LEGACY_ONLY = "LEGACY_ONLY"
    HARNESS_ALLOWED = "HARNESS_ALLOWED"
    HYBRID = "HYBRID"


@dataclass(frozen=True)
class RuntimeDecision:
    """Deterministic router output + auditable reason."""

    selection: RuntimeSelection
    reason: str
    task_id: str = ""
    policy_version: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "runtime_selection": self.selection.value,
            "runtime_selection_reason": self.reason,
            "task_id": self.task_id,
            "policy_version": self.policy_version,
        }


@dataclass(frozen=True)
class TaskProfile:
    """Deterministic task metadata used as router input (never LLM-decided)."""

    task_id: str
    task_type: str = "generation"
    output_contract: str = "strict_schema"
    risk_level: str = "medium"
    authority_requirement: str = "write_artifact"

    def validate(self) -> "TaskProfile":
        if self.task_type not in TASK_TYPES:
            raise ConfigurationError(f"unknown task_type: {self.task_type!r}")
        if self.output_contract not in OUTPUT_CONTRACTS:
            raise ConfigurationError(f"unknown output_contract: {self.output_contract!r}")
        if self.risk_level not in RISK_LEVELS:
            raise ConfigurationError(f"unknown risk_level: {self.risk_level!r}")
        if self.authority_requirement not in AUTHORITY_REQUIREMENTS:
            raise ConfigurationError(f"unknown authority_requirement: {self.authority_requirement!r}")
        return self


@dataclass
class RuntimePolicy:
    """Loaded governance policy artifact (strict validation)."""

    version: str
    default_runtime: str
    strict_schema_runtime: str
    exploration: dict[str, dict[str, Any]] = field(default_factory=dict)
    hybrid: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT_POLICY_PATH) -> "RuntimePolicy":
        if not path.exists():
            raise ConfigurationError(f"runtime policy missing: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise ConfigurationError("runtime policy version is required")
        default = data.get("default_runtime")
        if default != "legacy":
            raise ConfigurationError("default_runtime must be legacy (fail-closed)")
        strict = (data.get("strict_schema") or {}).get("runtime")
        if strict != "legacy":
            raise ConfigurationError("strict_schema runtime must be legacy (frozen)")

        exploration: dict[str, dict[str, Any]] = {}
        for task_id, spec in (data.get("exploration_tasks") or {}).items():
            if not isinstance(spec, dict):
                raise ConfigurationError(f"exploration task {task_id!r} must be an object")
            runtime = spec.get("runtime")
            if runtime not in {"harness", "legacy"}:
                raise ConfigurationError(f"exploration task {task_id!r}: runtime must be harness|legacy")
            if not isinstance(spec.get("enabled"), bool):
                raise ConfigurationError(f"exploration task {task_id!r}: enabled must be boolean")
            if task_id in LEGACY_REQUIRED_TASKS:
                raise ConfigurationError(f"exploration task {task_id!r} is LEGACY_REQUIRED and cannot be whitelisted")
            exploration[task_id] = {"runtime": runtime, "enabled": spec["enabled"]}

        hybrid: dict[str, dict[str, Any]] = {}
        for task_id, spec in (data.get("hybrid_tasks") or {}).items():
            if not isinstance(spec, dict):
                raise ConfigurationError(f"hybrid task {task_id!r} must be an object")
            if spec.get("phase_a") != "harness" or spec.get("phase_b") != "legacy":
                raise ConfigurationError(f"hybrid task {task_id!r}: phases must be harness->legacy")
            if task_id in LEGACY_REQUIRED_TASKS:
                raise ConfigurationError(f"hybrid task {task_id!r} is LEGACY_REQUIRED and cannot be hybrid")
            hybrid[task_id] = {"phase_a": "harness", "phase_b": "legacy"}

        return cls(version=version, default_runtime=default, strict_schema_runtime=strict,
                   exploration=exploration, hybrid=hybrid)

    def is_exploration_enabled(self, task_id: str) -> bool:
        spec = self.exploration.get(task_id)
        return bool(spec and spec.get("enabled") and spec.get("runtime") == "harness")

    def is_hybrid_enabled(self, task_id: str) -> bool:
        return task_id in self.hybrid


class RuntimeRouter:
    """Deterministic task -> runtime decision router (no LLM)."""

    def __init__(self, policy: RuntimePolicy | None = None):
        self.policy = policy or RuntimePolicy.load()

    def route(self, profile: TaskProfile) -> RuntimeDecision:
        profile.validate()
        task_id = profile.task_id
        if profile.output_contract == "strict_schema":
            return RuntimeDecision(
                RuntimeSelection.LEGACY_ONLY,
                f"output_contract=strict_schema requires legacy validator (task={task_id})",
                task_id=task_id, policy_version=self.policy.version)
        if self.policy.is_hybrid_enabled(task_id):
            return RuntimeDecision(
                RuntimeSelection.HYBRID,
                f"task {task_id} is on the hybrid whitelist (phase_a=harness, phase_b=legacy)",
                task_id=task_id, policy_version=self.policy.version)
        if (profile.task_type == "exploration"
                and profile.risk_level in {"low", "medium"}
                and profile.authority_requirement in {"read_only", "none"}
                and self.policy.is_exploration_enabled(task_id)):
            return RuntimeDecision(
                RuntimeSelection.HARNESS_ALLOWED,
                f"task {task_id} is an enabled exploration whitelist task",
                task_id=task_id, policy_version=self.policy.version)
        return RuntimeDecision(
            RuntimeSelection.LEGACY_ONLY,
            f"task {task_id} is not on the harness whitelist (default legacy, fail-closed)",
            task_id=task_id, policy_version=self.policy.version)


def route_task(profile: TaskProfile, policy: RuntimePolicy | None = None) -> RuntimeDecision:
    """Convenience entry: deterministic routing for one task profile."""
    return RuntimeRouter(policy).route(profile)


__all__ = [
    "RuntimeSelection", "RuntimeDecision", "TaskProfile", "RuntimePolicy",
    "RuntimeRouter", "route_task", "TASK_TYPES", "OUTPUT_CONTRACTS",
    "RISK_LEVELS", "AUTHORITY_REQUIREMENTS", "LEGACY_REQUIRED_TASKS",
    "DEFAULT_POLICY_PATH",
]
