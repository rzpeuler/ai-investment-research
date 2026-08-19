"""P8-A0 agent-runtime spike boundary.

This package is deliberately a control-plane adapter.  It does not own Research
OS state, source routing, evidence, or graph writes.
"""

from .boundary import HarnessBoundary, ResearchOSToolFacade
from .config import AgentRuntimeConfig
from .gateway import AgentRuntimeGateway
from .errors import RuntimeFailure
from .harness_adapter import HarnessAgentRuntimeAdapter
from .legacy_adapter import LegacyAgentRuntimeAdapter
from .models import GatewaySession, RuntimeStatus, SupervisorState
from .profile import ResearchAgentProfile
from .profile_verifier import ProfileVerifier
from .runtime_supervisor import HarnessRuntimeSupervisor
from .session import DurableSession
from .skills import SkillRegistry

__all__ = [
    "DurableSession",
    "AgentRuntimeConfig",
    "AgentRuntimeGateway",
    "HarnessBoundary",
    "HarnessAgentRuntimeAdapter",
    "HarnessRuntimeSupervisor",
    "GatewaySession",
    "LegacyAgentRuntimeAdapter",
    "ProfileVerifier",
    "ResearchAgentProfile",
    "ResearchOSToolFacade",
    "RuntimeFailure",
    "RuntimeStatus",
    "SkillRegistry",
    "SupervisorState",
]
