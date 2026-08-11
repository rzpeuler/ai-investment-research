"""Dashboard dependency assembly using existing project factories."""
from __future__ import annotations

from pathlib import Path

from research_os.dashboard.app import DashboardApplication
from research_os.dashboard.chat_service import ChatService
from research_os.dashboard.session import SessionStore
from research_os.llm.client import LlmClient
from research_os.llm.provider_factory import create_provider, get_provider_config
from research_os.orchestrator import Orchestrator
from research_os.storage import Database


class _PerRequestChatService:
    """Creates SQLite-owned services in the HTTP worker that uses them."""

    def __init__(self, root: Path, provider):
        self.root = root
        self.provider = provider

    def handle(self, request, conversation_context=None):
        db = None
        try:
            db = Database(self.root / "data" / "sqlite" / "research.db")
            db.initialize()
            orchestrator = Orchestrator(self.root, db=db)
            client = LlmClient(
                provider=self.provider, db=db, configured=self.provider is not None,
            )
            return ChatService(self.root, db, orchestrator, llm_client=client).handle(
                request, conversation_context=conversation_context,
            )
        finally:
            if db is not None:
                db.close()


def build_dashboard_runtime(project_root: str | Path):
    root = Path(project_root)
    # Apply existing migrations before accepting traffic, then release the
    # connection. Worker threads open and own their respective connections.
    bootstrap_db = None
    try:
        bootstrap_db = Database(root / "data" / "sqlite" / "research.db")
        bootstrap_db.initialize()
    finally:
        if bootstrap_db is not None:
            bootstrap_db.close()
    llm_configured = False
    provider_status = "not_configured"
    provider = None
    credential_secrets = ()
    try:
        config = get_provider_config(root, "deepseek")
        credential_secrets = tuple(value for value in (config.api_key(),) if value)
        llm_configured = bool(config.configured)
        if llm_configured:
            provider = create_provider(root, provider_id="deepseek", live=True)
            provider_status = "configured"
    except Exception:
        llm_configured = False
        provider_status = "configuration_error"
    service = _PerRequestChatService(root, provider)
    app = DashboardApplication(
        root, service, SessionStore(), llm_configured=llm_configured,
        credential_secrets=credential_secrets,
    )
    return app, llm_configured, provider_status
