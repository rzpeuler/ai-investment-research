"""Stable gateway and runtime value objects."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SupervisorState(str, Enum):
    STARTING = "STARTING"
    READY = "READY"
    DRAINING = "DRAINING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


@dataclass(frozen=True)
class RuntimeStatus:
    state: SupervisorState
    process_alive: bool
    profile_verified: bool
    mcp_verified: bool
    version_verified: bool
    failure_code: str | None = None

    @property
    def ready(self) -> bool:
        return self.state is SupervisorState.READY and all((
            self.process_alive, self.profile_verified, self.mcp_verified, self.version_verified,
        ))


@dataclass(frozen=True)
class GatewaySession:
    gateway_session_id: str
    runtime_mode: str
    harness_session_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PublicGatewaySession:
    """Stable caller-facing session view; internal Harness identity is absent."""

    gateway_session_id: str
    runtime_mode: str
    status: str
    metadata: dict[str, str] = field(default_factory=dict)


PUBLIC_SESSION_METADATA_KEYS = frozenset({"acceptance"})


def to_public_session(session: GatewaySession, *, status: str = "active") -> PublicGatewaySession:
    metadata = {
        key: value for key, value in session.metadata.items()
        if key in PUBLIC_SESSION_METADATA_KEYS
    }
    return PublicGatewaySession(
        gateway_session_id=session.gateway_session_id,
        runtime_mode=session.runtime_mode,
        status=status,
        metadata=metadata,
    )


@dataclass(frozen=True)
class ToolCallResult:
    status: str
    payload: dict[str, Any]
    tool: str
    request_id: str
