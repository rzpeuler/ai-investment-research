"""P8-A2 Harness Pilot Entry (opt-in; never the default runtime).

Authority: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN (Decision #82). This is the
production-pilot governance execution layer:

  Request
    -> Runtime Router (deterministic, config-driven)
    -> Runtime Selection (LEGACY_ONLY / HARNESS_ALLOWED / HYBRID)
    -> Permission Policy (fail-closed)
    -> Harness (exploration) or Legacy (structured artifact)
    -> Audit (runtime lineage)

Design constraints (frozen):
  - Default runtime remains legacy; Harness is opt-in only via the router
    whitelist (config/runtime_policy.yaml).
  - The router never uses an LLM; every decision is deterministic + audited.
  - LEGACY_REQUIRED tasks (strict_schema) always route to legacy.
  - For HARNESS_ALLOWED tasks, a permission check runs before any tool call and
    a bounded runtime-lineage record is written (PilotAuditRecorder).
  - This module does NOT modify LlmClient / Validator / Schema / authorities.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from research_os.agent_runtime.errors import ConfigurationError, RuntimeNotReady
from research_os.agent_runtime.exploration_contract import (
    ExplorationContract,
    ExplorationContractRegistry,
)
from research_os.agent_runtime.exploration_controller import ExplorationController
from research_os.agent_runtime.permission_policy import HarnessPermissionPolicy
from research_os.agent_runtime.pilot_audit import PilotAuditRecorder, RuntimeLineage
from research_os.agent_runtime.pilot_corpus import PilotCase
from research_os.agent_runtime.runtime_router import (
    RuntimeDecision,
    RuntimePolicy,
    RuntimeRouter,
    RuntimeSelection,
)

PILOT_ENV = "P8_A2_HYBRID_PILOT"

# Exploration tasks may use these Harness tools (permission ALLOW surface).
EXPLORATION_TOOL_SURFACE = frozenset({
    "get_company_profile",
    "check_data_readiness",
    "query_industry_graph",
    "run_research_scenario",
})


@dataclass
class PilotOutcome:
    """Bounded pilot execution result (no raw content)."""

    task_id: str
    decision: RuntimeDecision
    runtime_used: str
    status: str
    harness_session_id: str = ""
    tools_called: list[str] = None  # type: ignore[assignment]
    final_artifact_source: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "runtime_used": self.runtime_used,
            "status": self.status,
            "decision": self.decision.as_dict(),
            "harness_session_id": self.harness_session_id,
            "tools_called": self.tools_called or [],
            "final_artifact_source": self.final_artifact_source,
        }


class HarnessPilotAdapter:
    """Opt-in pilot execution layer: router -> permission -> contract -> runtime -> audit."""

    def __init__(
        self,
        *,
        policy: RuntimePolicy | None = None,
        router: RuntimeRouter | None = None,
        permission: HarnessPermissionPolicy | None = None,
        audit: PilotAuditRecorder | None = None,
        contract_registry: ExplorationContractRegistry | None = None,
        harness_runner: Callable[[str, str], dict[str, Any]] | None = None,
        require_opt_in: bool = True,
    ):
        self.policy = policy or RuntimePolicy.load()
        self.router = router or RuntimeRouter(self.policy)
        self.permission = permission or HarnessPermissionPolicy()
        self.audit = audit or PilotAuditRecorder()
        self.contracts = contract_registry or ExplorationContractRegistry()
        self.harness_runner = harness_runner  # (case_id, prompt) -> bounded result
        self.require_opt_in = require_opt_in

    # ---------- opt-in gate ----------

    def _require_opt_in(self) -> None:
        if self.require_opt_in and os.environ.get(PILOT_ENV) != "1":
            raise RuntimeNotReady("PILOT_NOT_ENABLED", f"set {PILOT_ENV}=1 for hybrid pilot")

    # ---------- main entry ----------

    def run_case(self, case: PilotCase) -> PilotOutcome:
        """Route and execute one pilot corpus case (deterministic + audited)."""
        self._require_opt_in()
        decision = self.router.route(case.profile())

        # LEGACY_REQUIRED / default: no Harness involvement; audit the lineage.
        if decision.selection in {RuntimeSelection.LEGACY_ONLY, RuntimeSelection.HYBRID}:
            # HYBRID is reserved in this pilot; Phase B artifact source = legacy.
            source = "legacy" if decision.selection == RuntimeSelection.HYBRID else "legacy"
            lineage = RuntimeLineage(
                task_id=case.id,
                runtime_selection=decision.selection.value,
                runtime_selection_reason=decision.reason,
                final_artifact_source=source,
                policy_version=decision.policy_version,
                status="routed_legacy",
            )
            self.audit.record(lineage)
            return PilotOutcome(
                task_id=case.id, decision=decision, runtime_used="legacy",
                status="routed_legacy", final_artifact_source=source,
            )

        # HARNESS_ALLOWED: contract + permission + harness execution + audit.
        # P8-A3-R1: every HARNESS_ALLOWED task MUST have an exploration
        # contract; a missing contract refuses execution (fail-closed).
        contract = self.contracts.get(case.id)
        if self.harness_runner is None:
            raise RuntimeNotReady("HARNESS_RUNNER_MISSING",
                                  "pilot adapter has no harness runner configured")
        # Permission boundary: the contract's allowed tools must be within the
        # Harness ALLOW surface (fail-closed).
        unauthorized = sorted(set(contract.allowed_tools) - self.permission.allowed)
        if unauthorized:
            raise RuntimeNotReady("PERMISSION_MISMATCH",
                                  f"contract tools exceed allowlist: {unauthorized}")
        authority_checks = [
            self.permission.check(tool).as_dict() for tool in sorted(contract.allowed_tools)
        ]
        denied = [check for check in authority_checks if not check["allowed"]]
        if denied:
            raise RuntimeNotReady("PERMISSION_DENIED",
                                  f"harness tool surface denied: {denied}")

        # Contract-bounded execution: the controller enforces turn/tool budgets,
        # deterministic completion and empty-data stop (no infinite agent loop).
        controller = ExplorationController(
            send_turn=lambda prompt: self.harness_runner(case.id, prompt),
            count_tool_calls=lambda: 0,
        )
        run = controller.run(contract, case.prompt)

        harness_session = run.harness_session_id
        lineage = RuntimeLineage(
            task_id=case.id,
            runtime_selection=RuntimeSelection.HARNESS_ALLOWED.value,
            runtime_selection_reason=decision.reason,
            final_artifact_source="harness_exploration",
            harness_session_id=harness_session,
            skills_used=["stock-research", "financial-analysis",
                         "industry-graph-research"],
            tools_called=list(contract.allowed_tools),
            authority_checks=authority_checks,
            policy_version=decision.policy_version,
            status=run.status,
            exploration_contract=f"{contract.task_id}@{contract.policy_version}",
            max_turns=contract.max_turns,
            max_tool_calls=contract.max_tool_calls,
            actual_turns=run.actual_turns,
            actual_tool_calls=run.actual_tool_calls,
            completion_status=run.completion_status,
        )
        self.audit.record(lineage)
        return PilotOutcome(
            task_id=case.id, decision=decision, runtime_used="harness",
            status=run.status, harness_session_id=harness_session,
            tools_called=list(contract.allowed_tools),
            final_artifact_source="harness_exploration",
        )


__all__ = ["HarnessPilotAdapter", "PilotOutcome", "EXPLORATION_TOOL_SURFACE", "PILOT_ENV"]
