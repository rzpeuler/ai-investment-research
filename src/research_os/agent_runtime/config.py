"""Validated Agent Runtime configuration with a legacy-safe default."""
from __future__ import annotations

import os
from dataclasses import dataclass

from .errors import ConfigurationError

EXPECTED_HARNESS_VERSION = "0.1.0-rc.7"
MCP_NAMESPACE = "research-os-mcp/v1"
DEFAULT_RUNTIME_MODE = "legacy"
RUNTIME_MODES = frozenset({"legacy", "harness"})
MAX_TURNS = 20
MAX_ACTIVE_SESSIONS = 128
MAX_TOOL_RESULT_BYTES = 64 * 1024


def _int_env(name: str, default: int, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if not minimum <= parsed <= maximum:
        raise ConfigurationError(f"{name} outside bounded range")
    return parsed


@dataclass(frozen=True)
class AgentRuntimeConfig:
    mode: str = DEFAULT_RUNTIME_MODE
    harness_version: str = EXPECTED_HARNESS_VERSION
    profile: str = "research-headless"
    mcp_namespace: str = MCP_NAMESPACE
    max_turns: int = MAX_TURNS
    max_active_sessions: int = MAX_ACTIVE_SESSIONS
    tool_result_limit: int = MAX_TOOL_RESULT_BYTES
    turn_timeout_seconds: int = 300
    provider_timeout_seconds: int = 60
    max_tool_calls: int = 8
    max_provider_retries: int = 2
    idle_session_timeout_seconds: int = 1800
    provider_token_budget: int = 8192

    def validate(self) -> "AgentRuntimeConfig":
        if self.mode not in RUNTIME_MODES:
            raise ConfigurationError(f"unsupported agent_runtime_mode: {self.mode}")
        if self.harness_version != EXPECTED_HARNESS_VERSION:
            raise ConfigurationError("Harness version must be pinned to 0.1.0-rc.7")
        if self.profile != "research-headless":
            raise ConfigurationError("unsupported production research profile")
        if self.mcp_namespace != MCP_NAMESPACE:
            raise ConfigurationError("unsupported MCP namespace")
        for name, value, minimum in (
            ("max_turns", self.max_turns, 1),
            ("max_active_sessions", self.max_active_sessions, 1),
            ("tool_result_limit", self.tool_result_limit, 1),
            ("turn_timeout_seconds", self.turn_timeout_seconds, 1),
            ("provider_timeout_seconds", self.provider_timeout_seconds, 1),
            ("max_tool_calls", self.max_tool_calls, 1),
            ("max_provider_retries", self.max_provider_retries, 0),
            ("idle_session_timeout_seconds", self.idle_session_timeout_seconds, 1),
            ("provider_token_budget", self.provider_token_budget, 1),
        ):
            if value < minimum:
                raise ConfigurationError(f"{name} must be positive/bounded")
        return self

    @classmethod
    def from_env(cls) -> "AgentRuntimeConfig":
        config = cls(
            mode=os.getenv("AGENT_RUNTIME_MODE", os.getenv("agent_runtime_mode", DEFAULT_RUNTIME_MODE)),
            harness_version=os.getenv("HARNESS_RUNTIME_VERSION", EXPECTED_HARNESS_VERSION),
            profile=os.getenv("HARNESS_PROFILE", "research-headless"),
            mcp_namespace=os.getenv("MCP_NAMESPACE", MCP_NAMESPACE),
            max_turns=_int_env("AGENT_MAX_TURNS", MAX_TURNS, 1, MAX_TURNS),
            max_active_sessions=_int_env("AGENT_MAX_ACTIVE_SESSIONS", MAX_ACTIVE_SESSIONS, 1, MAX_ACTIVE_SESSIONS),
            tool_result_limit=_int_env("AGENT_TOOL_RESULT_LIMIT", MAX_TOOL_RESULT_BYTES, 1, MAX_TOOL_RESULT_BYTES),
            turn_timeout_seconds=_int_env("AGENT_TURN_TIMEOUT_SECONDS", 300, 1, 3600),
            provider_timeout_seconds=_int_env("AGENT_PROVIDER_TIMEOUT_SECONDS", 60, 1, 3600),
            max_tool_calls=_int_env("AGENT_MAX_TOOL_CALLS", 8, 1, 100),
            max_provider_retries=_int_env("AGENT_MAX_PROVIDER_RETRIES", 2, 0, 5),
            idle_session_timeout_seconds=_int_env("AGENT_IDLE_SESSION_TIMEOUT_SECONDS", 1800, 1, 86400),
            provider_token_budget=_int_env("AGENT_PROVIDER_TOKEN_BUDGET", 8192, 1, 100000),
        )
        return config.validate()

    @classmethod
    def from_request(cls, request: dict[str, object] | None = None) -> "AgentRuntimeConfig":
        """Load server config and reject client runtime selection."""
        request = request or {}
        if "runtime_mode" in request or "agent_runtime_mode" in request:
            raise ConfigurationError("client runtime override is denied")
        return cls.from_env()
