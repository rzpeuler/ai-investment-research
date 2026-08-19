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

    def verify(self, runtime: dict[str, Any]) -> ProfileVerification:
        version = runtime.get("version")
        if version != self.expected_version:
            raise RuntimeNotReady("RUNTIME_VERSION_MISMATCH", f"expected {self.expected_version}, got {version!r}")
        identity = runtime.get("profile")
        if identity != EXPECTED_PROFILE:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "unexpected profile identity")
        denied = set(runtime.get("denied_components", ()))
        if not DENIED_COMPONENTS.issubset(denied):
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "required denied capabilities are missing")
        if any(runtime.get("enabled_components", {}).get(component, False) for component in DENIED_COMPONENTS):
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "denied capability is enabled")
        if runtime.get("mcp_namespace") != MCP_NAMESPACE:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "unexpected MCP namespace")
        tools = frozenset(runtime.get("tools", ()))
        if tools != ALLOWED_TOOL_NAMES:
            raise RuntimeNotReady("PROFILE_POLICY_MISMATCH", "Tool allowlist is not exact")
        return ProfileVerification(True, True, True, True, identity)


def default_runtime_descriptor(version: str = EXPECTED_HARNESS_VERSION) -> dict[str, Any]:
    return {
        "version": version,
        "profile": EXPECTED_PROFILE,
        "mcp_namespace": MCP_NAMESPACE,
        "denied_components": sorted(DENIED_COMPONENTS),
        "enabled_components": {component: False for component in DENIED_COMPONENTS},
        "tools": sorted(ALLOWED_TOOL_NAMES),
    }
