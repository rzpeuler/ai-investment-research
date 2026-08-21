"""P8-A2 Harness Permission Policy (fail-closed).

Authority: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN (Decision #82) + P8-ARCH-001
(Decision #80). Enforces the Harness tool permission boundary:

  ALLOW (READ / exploration):
    get_company_profile, check_data_readiness, query_industry_graph,
    run_research_scenario (bounded trigger only)

  DENY:
    graph_write / graph_apply / graph_approve / apply_graph_change
    evidence mutation
    financial_fact_creation
    direct_source_access / collector / sql

The policy is fail-closed: any tool not explicitly allowed is denied, and any
denied capability attempted raises :class:`PermissionError`. This is a pure
deterministic check; it never consults an LLM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Explicit Harness ALLOW surface (READ / exploration only).
HARNESS_ALLOWED_TOOLS = frozenset({
    "get_company_profile",
    "check_data_readiness",
    "query_industry_graph",
    "run_research_scenario",
})

# Explicit Harness DENY surface (authority / write / source access).
HARNESS_DENIED_TOOLS = frozenset({
    # Graph write authority
    "graph_write", "graph_apply", "graph_approve", "apply_graph_change",
    "approve_graph_change",
    # Evidence authority
    "evidence_mutation", "evidence_write", "evidence_create",
    "evidence_update", "evidence_delete",
    # Financial fact authority
    "financial_fact_creation", "financial_fact_write", "financial_fact_create",
    # Source / collector / sql access
    "direct_source_access", "direct_data_source_access",
    "cninfo_fetch", "nbs_fetch", "sina_fetch", "collector_execute",
    "sql_query", "execute_sql", "query_db", "read_table",
    # Report artifact authority
    "final_report_section_write",
})

# Capability-class mapping used by the pilot corpus to express intent.
CAPABILITY_DENIED = {
    "graph_write": frozenset({"graph_write", "graph_apply", "graph_approve",
                              "apply_graph_change", "approve_graph_change"}),
    "evidence_mutation": frozenset({"evidence_mutation", "evidence_write",
                                    "evidence_create", "evidence_update",
                                    "evidence_delete"}),
    "financial_fact_creation": frozenset({"financial_fact_creation",
                                          "financial_fact_write",
                                          "financial_fact_create"}),
    "direct_source_access": frozenset({"direct_source_access",
                                       "direct_data_source_access",
                                       "cninfo_fetch", "nbs_fetch", "sina_fetch",
                                       "collector_execute", "sql_query",
                                       "execute_sql", "query_db", "read_table"}),
}


@dataclass(frozen=True)
class PermissionCheck:
    allowed: bool
    tool: str
    reason: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"allowed": self.allowed, "tool": self.tool, "reason": self.reason}


class HarnessPermissionPolicy:
    """Fail-closed Harness tool permission policy."""

    def __init__(self, allowed: frozenset[str] = HARNESS_ALLOWED_TOOLS,
                 denied: frozenset[str] = HARNESS_DENIED_TOOLS):
        self.allowed = frozenset(allowed)
        self.denied = frozenset(denied)
        # Fail-closed: an allowed tool must never also be denied.
        overlap = self.allowed & self.denied
        if overlap:
            raise ValueError(f"permission policy conflict: {sorted(overlap)}")

    def check(self, tool: str) -> PermissionCheck:
        """Return the deterministic permission verdict for one tool call."""
        if not isinstance(tool, str) or not tool:
            return PermissionCheck(False, str(tool), "tool name must be non-empty")
        if tool in self.denied:
            return PermissionCheck(False, tool, "tool is denied by Harness permission policy")
        if tool in self.allowed:
            return PermissionCheck(True, tool, "tool is allowed for Harness exploration")
        return PermissionCheck(False, tool, "tool is not on the Harness allowlist (fail-closed)")

    def enforce(self, tool: str) -> None:
        """Raise :class:`PermissionError` if the tool call is not allowed."""
        verdict = self.check(tool)
        if not verdict.allowed:
            raise PermissionError(f"harness permission denied: {tool} ({verdict.reason})")

    def check_capability(self, capability: str) -> PermissionCheck:
        """Check a denied capability class (graph_write / evidence_mutation /
        financial_fact_creation / direct_source_access)."""
        targets = CAPABILITY_DENIED.get(capability)
        if targets is None:
            return PermissionCheck(False, capability, "unknown denied capability")
        return PermissionCheck(False, capability,
                               "denied capability: " + "|".join(sorted(targets)))


__all__ = [
    "HARNESS_ALLOWED_TOOLS", "HARNESS_DENIED_TOOLS", "CAPABILITY_DENIED",
    "PermissionCheck", "HarnessPermissionPolicy",
]
