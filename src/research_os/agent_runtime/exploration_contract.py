"""P8-A3-R1 Exploration Execution Contract loader (config-driven, strict).

Authority: P8-A3-R1-HARNESS-EXPLORATION-CONTROL. Loads and strictly validates
``config/exploration_policy.yaml``. Every HARNESS_ALLOWED task MUST have an
exploration contract; a missing contract causes execution to be refused
(fail-closed). The contract is a governance artifact: modifications require an
independent taskbook + Sol authorization.

Contract fields (P8-A3-R1):
  objective            - bounded exploration objective
  allowed_tools        - subset of the Harness ALLOW surface for this task
  max_turns            - hard agent-turn budget
  max_tool_calls       - hard tool-call budget
  turn_timeout_seconds - per-turn wall-clock budget
  completion_rule      - deterministic completion markers (checked WITHOUT LLM)
  empty_data_policy    - empty/insufficient tool result policy (no infinite retry)
  failure_condition    - budget-exhaustion outcome
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from research_os.agent_runtime.errors import ConfigurationError
from research_os.agent_runtime.permission_policy import HARNESS_ALLOWED_TOOLS

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXPLORATION_POLICY_PATH = ROOT / "config" / "exploration_policy.yaml"

EMPTY_DATA_POLICIES = frozenset({"record_data_gap_and_stop"})


@dataclass(frozen=True)
class ExplorationContract:
    """Deterministic execution contract for one HARNESS_ALLOWED task."""

    task_id: str
    objective: str
    allowed_tools: tuple[str, ...]
    max_turns: int
    max_tool_calls: int
    turn_timeout_seconds: int
    required_fields: tuple[str, ...]
    empty_data_policy: str
    failure_condition: str
    policy_version: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "objective": self.objective,
            "allowed_tools": list(self.allowed_tools),
            "max_turns": self.max_turns,
            "max_tool_calls": self.max_tool_calls,
            "turn_timeout_seconds": self.turn_timeout_seconds,
            "required_fields": list(self.required_fields),
            "empty_data_policy": self.empty_data_policy,
            "failure_condition": self.failure_condition,
            "policy_version": self.policy_version,
        }

    def completion_markers(self) -> list[str]:
        """Deterministic output markers used by the completion detector."""
        return list(self.required_fields)


class ExplorationContractRegistry:
    """Strictly validated exploration contract registry."""

    def __init__(self, path: Path = DEFAULT_EXPLORATION_POLICY_PATH):
        self.path = Path(path)
        if not self.path.exists():
            raise ConfigurationError(f"exploration policy missing: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise ConfigurationError("exploration policy version is required")
        self.version = version
        self._contracts: dict[str, ExplorationContract] = {}
        for task_id, spec in (data.get("tasks") or {}).items():
            self._contracts[task_id] = self._validate(task_id, spec, version)
        if not self._contracts:
            raise ConfigurationError("exploration policy has no tasks")

    @staticmethod
    def _validate(task_id: str, spec: Any, version: str) -> ExplorationContract:
        if not isinstance(spec, dict):
            raise ConfigurationError(f"exploration task {task_id!r} must be an object")
        objective = spec.get("objective")
        if not isinstance(objective, str) or not objective.strip():
            raise ConfigurationError(f"task {task_id}: objective is required")
        allowed_tools = spec.get("allowed_tools")
        if not isinstance(allowed_tools, list) or not allowed_tools:
            raise ConfigurationError(f"task {task_id}: allowed_tools must be a non-empty list")
        if not all(isinstance(tool, str) and tool for tool in allowed_tools):
            raise ConfigurationError(f"task {task_id}: allowed_tools must be strings")
        unknown_tools = set(allowed_tools) - HARNESS_ALLOWED_TOOLS
        if unknown_tools:
            raise ConfigurationError(
                f"task {task_id}: allowed_tools exceed Harness allowlist: {sorted(unknown_tools)}")
        max_turns = spec.get("max_turns")
        max_tool_calls = spec.get("max_tool_calls")
        turn_timeout = spec.get("turn_timeout_seconds")
        if not all(isinstance(value, int) and value >= 1 for value in (max_turns, max_tool_calls, turn_timeout)):
            raise ConfigurationError(
                f"task {task_id}: max_turns / max_tool_calls / turn_timeout_seconds must be positive ints")
        completion = spec.get("completion_rule")
        if not isinstance(completion, dict):
            raise ConfigurationError(f"task {task_id}: completion_rule is required")
        required_fields = completion.get("required_fields")
        if not isinstance(required_fields, list) or not required_fields:
            raise ConfigurationError(
                f"task {task_id}: completion_rule.required_fields must be a non-empty list")
        if not all(isinstance(field_, str) and field_ for field_ in required_fields):
            raise ConfigurationError(f"task {task_id}: required_fields must be strings")
        empty_data_policy = spec.get("empty_data_policy")
        if empty_data_policy not in EMPTY_DATA_POLICIES:
            raise ConfigurationError(
                f"task {task_id}: empty_data_policy must be one of {sorted(EMPTY_DATA_POLICIES)}")
        failure_condition = spec.get("failure_condition")
        if not isinstance(failure_condition, str) or not failure_condition.strip():
            raise ConfigurationError(f"task {task_id}: failure_condition is required")
        return ExplorationContract(
            task_id=task_id, objective=objective,
            allowed_tools=tuple(allowed_tools),
            max_turns=int(max_turns), max_tool_calls=int(max_tool_calls),
            turn_timeout_seconds=int(turn_timeout),
            required_fields=tuple(required_fields),
            empty_data_policy=empty_data_policy,
            failure_condition=failure_condition,
            policy_version=version,
        )

    def get(self, task_id: str) -> ExplorationContract:
        try:
            return self._contracts[task_id]
        except KeyError as exc:
            raise ConfigurationError(
                f"exploration contract missing for task {task_id!r} (refusing execution)") from exc

    def has(self, task_id: str) -> bool:
        return task_id in self._contracts

    def all(self) -> list[ExplorationContract]:
        return list(self._contracts.values())


__all__ = ["ExplorationContract", "ExplorationContractRegistry",
           "DEFAULT_EXPLORATION_POLICY_PATH"]
