"""Schema-driven conversational research core (transport independent)."""

from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.models import ChatRequest, ChatResult
from research_os.dashboard.scenario_specs import CHAT_SCENARIO_SPECS, ScenarioChatSpec

__all__ = ["ChatRequest", "ChatResult", "ChatService", "CHAT_SCENARIO_SPECS", "ScenarioChatSpec"]
