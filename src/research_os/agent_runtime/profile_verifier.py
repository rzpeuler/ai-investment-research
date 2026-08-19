"""Mechanical verification of the research-only Harness profile."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import EXPECTED_HARNESS_VERSION, MCP_NAMESPACE
from .errors import RuntimeNotReady
from .tool_catalog import ALLOWED_TOOL_NAMES

EXPECTED_PROFILE = "research-headless"
DENIED_COMPONENTS = frozenset({
    "bash", "pwsh", "filesystem_write", "filesystem_editor", "filesystem_search",
    "jobs", "subagent", "workflow_coding_tools", "todo", "coding_goal_tools",
    "direct_web", "web_search", "arbitrary_subprocess",
})

FORBIDDEN_COMPONENT_IDS_RC7 = {
    "bash": frozenset({"tool-bash"}),
    "pwsh": frozenset({"tool-pwsh"}),
    "filesystem_write": frozenset({"tool-fs"}),
    "filesystem_editor": frozenset({"tool-str-replace-editor"}),
    "filesystem_search": frozenset({"tool-fs-search"}),
    "jobs": frozenset({"tool-jobs"}),
    "subagent": frozenset({"tool-subagent", "tool-subagent-control"}),
    "workflow_coding_tools": frozenset({"tool-workflow"}),
    "todo": frozenset({"tool-todo"}),
    "coding_goal_tools": frozenset({"tool-goal"}),
    "direct_web": frozenset({"tool-web"}),
    "web_search": frozenset({"web-search-deepseek"}),
    "arbitrary_subprocess": frozenset({"tool-bash", "tool-pwsh"}),
}


@dataclass(frozen=True)
class ProfileVerification:
    version_verified: bool
    profile_verified: bool
    mcp_verified: bool
    tools_verified: bool
    identity: str

    @property
    def verified(self) -> bool:
        return all((self.version_verified, self.profile_verified, self.mcp_verified, self.tools_verified))


class ProfileVerifier:
    def __init__(self, expected_version: str = EXPECTED_HARNESS_VERSION):
        self.expected_version = expected_version

    def verify(self, runtime: dict[str, Any], *, allow_fixture: bool = False) -> ProfileVerification:
        if runtime.get("evidence_source") != "observed_runtime" and not allow_fixture:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "runtime evidence is not observed")
        version = runtime.get("version")
        if version != self.expected_version:
            raise RuntimeNotReady("RUNTIME_VERSION_MISMATCH", f"expected {self.expected_version}, got {version!r}")
        identity = runtime.get("profile")
        if identity != EXPECTED_PROFILE:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "unexpected profile identity")
        denied = set(runtime.get("denied_components", ()))
        disabled = set(runtime.get("disabled_components", ()))
        if allow_fixture and not disabled:
            disabled = denied
        if not allow_fixture:
            observed_ids = set(runtime.get("observed_component_ids", ()))
            disabled_ids = set(runtime.get("disabled_component_ids", ()))
            enabled_ids = set(runtime.get("enabled_component_ids", ()))
            absent_ids = set(runtime.get("absent_forbidden_component_ids", ()))
            if not observed_ids or not (disabled_ids | enabled_ids | absent_ids).issubset(observed_ids | absent_ids):
                raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "runtime component inventory is incomplete")
            for capability, component_ids in FORBIDDEN_COMPONENT_IDS_RC7.items():
                if component_ids & enabled_ids:
                    raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", f"forbidden capability is enabled: {capability}")
                if not (component_ids & disabled_ids or component_ids.issubset(absent_ids)):
                    raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", f"forbidden capability evidence is incomplete: {capability}")
        elif not DENIED_COMPONENTS.issubset(denied) or not DENIED_COMPONENTS.issubset(disabled):
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "required denied capabilities are missing")
        if any(runtime.get("enabled_components", {}).get(component, False) for component in DENIED_COMPONENTS):
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "denied capability is enabled")
        if runtime.get("mcp_namespace") != MCP_NAMESPACE:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "unexpected MCP namespace")
        handshake = runtime.get("mcp_handshake") or {}
        if not allow_fixture and (handshake.get("connected") is not True or handshake.get("namespace") != MCP_NAMESPACE):
            raise RuntimeNotReady("MCP_UNAVAILABLE", "actual MCP handshake evidence is missing")
        tools = frozenset(handshake.get("tools", runtime.get("tools", ())))
        if tools != ALLOWED_TOOL_NAMES:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "Tool allowlist is not exact")
        return ProfileVerification(True, True, True, True, identity)


def default_runtime_descriptor(version: str = EXPECTED_HARNESS_VERSION) -> dict[str, Any]:
    return {
        "evidence_source": "fixture",
        "version": version,
        "profile": EXPECTED_PROFILE,
        "mcp_namespace": MCP_NAMESPACE,
        "denied_components": sorted(DENIED_COMPONENTS),
        "enabled_components": {component: False for component in DENIED_COMPONENTS},
        "observed_component_ids": sorted({item for items in FORBIDDEN_COMPONENT_IDS_RC7.values() for item in items}),
        "disabled_component_ids": sorted({item for items in FORBIDDEN_COMPONENT_IDS_RC7.values() for item in items}),
        "enabled_component_ids": [],
        "absent_forbidden_component_ids": [],
        "tools": sorted(ALLOWED_TOOL_NAMES),
    }
