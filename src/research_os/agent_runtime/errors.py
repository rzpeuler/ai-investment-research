"""Typed, fail-closed failures for the Agent Runtime foundation."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeFailure(Exception):
    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ConfigurationError(RuntimeFailure):
    def __init__(self, message: str):
        super().__init__("CONFIGURATION_ERROR", message)


class RuntimeNotReady(RuntimeFailure):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(code, message, retryable)


class ToolNotAllowed(RuntimeFailure):
    def __init__(self, name: str):
        super().__init__("MCP_TOOL_NOT_ALLOWED", f"tool is not allowed: {name}")


class ToolFailure(RuntimeFailure):
    def __init__(self, message: str, retryable: bool = False):
        super().__init__("MCP_TOOL_FAILED", message, retryable)


class SessionFailure(RuntimeFailure):
    def __init__(self, code: str, message: str):
        super().__init__(code, message)
