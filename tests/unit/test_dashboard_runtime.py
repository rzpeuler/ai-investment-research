from concurrent.futures import ThreadPoolExecutor
from threading import get_ident

import pytest

from research_os.dashboard.models import ChatRequest, ChatResult
from research_os.dashboard import runtime


def test_runtime_provider_creation_failure_is_safe_and_observable(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-only-secret")
    monkeypatch.setattr(runtime, "get_provider_config", lambda *args: type("Config", (), {"configured": True})())
    monkeypatch.setattr(runtime, "create_provider", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("bad config")))
    app, configured, status = runtime.build_dashboard_runtime(tmp_path)
    assert configured is False and status == "configuration_error"
    meta = app.dispatch("GET", "/api/meta", {})[2].decode("utf-8")
    assert "configuration_error" not in meta
    health = app.dispatch("GET", "/api/health", {})[2].decode("utf-8")
    assert "configuration_error" not in health
    assert "test-only-secret" not in meta


def test_per_request_runtime_owns_database_in_worker_thread(monkeypatch, tmp_path):
    owners = []
    class Db:
        def __init__(self, path): self.owner = get_ident(); owners.append(self.owner)
        def initialize(self): pass
        def close(self): pass
    class Orch:
        def __init__(self, root, db): self.db = db
        def close(self): pass
    class Service:
        def __init__(self, root, db, orchestrator, llm_client):
            assert db.owner == get_ident()
        def handle(self, request):
            return ChatResult("clarification", "ok")
    monkeypatch.setattr(runtime, "Database", Db)
    monkeypatch.setattr(runtime, "Orchestrator", Orch)
    monkeypatch.setattr(runtime, "ChatService", Service)
    service = runtime._PerRequestChatService(tmp_path, None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.handle, [ChatRequest("x"), ChatRequest("y")]))
    assert [item.message for item in results] == ["ok", "ok"]
    assert len(owners) == 2


def test_per_request_runtime_closes_database_when_construction_fails(monkeypatch, tmp_path):
    events = []
    class Db:
        def __init__(self, path): events.append("created")
        def initialize(self): events.append("initialized")
        def close(self): events.append("closed")
    monkeypatch.setattr(runtime, "Database", Db)
    monkeypatch.setattr(runtime, "Orchestrator", lambda root, db: (_ for _ in ()).throw(RuntimeError("boom")))
    service = runtime._PerRequestChatService(tmp_path, None)
    with pytest.raises(RuntimeError, match="boom"):
        service.handle(ChatRequest("x"))
    assert events == ["created", "initialized", "closed"]


def test_per_request_runtime_closes_database_when_initialize_fails(monkeypatch, tmp_path):
    events = []
    class Db:
        def __init__(self, path): events.append("created")
        def initialize(self): events.append("initialized"); raise RuntimeError("init")
        def close(self): events.append("closed")
    monkeypatch.setattr(runtime, "Database", Db)
    service = runtime._PerRequestChatService(tmp_path, None)
    with pytest.raises(RuntimeError, match="init"):
        service.handle(ChatRequest("x"))
    assert events == ["created", "initialized", "closed"]
