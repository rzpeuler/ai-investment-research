from concurrent.futures import ThreadPoolExecutor

from research_os.dashboard.session import IN_MEMORY_ONLY, SessionStore


def test_session_store_is_memory_only_and_trims_complete_turns(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = SessionStore(max_turns=20)
    assert store.storage_policy == IN_MEMORY_ONLY
    for index in range(25):
        store.record_turn("alpha", {"message": f"q{index}"}, {"state": "executed"})
    recent = store.recent("alpha")
    assert len(recent) == 20
    assert recent[0]["request"]["message"] == "q5"
    assert recent[-1]["request"]["message"] == "q24"
    assert store.recent("beta") == []
    assert list(tmp_path.iterdir()) == []


def test_session_store_concurrent_sessions_do_not_mix():
    store = SessionStore(max_turns=20)
    def write(session_id):
        for index in range(30):
            store.record_turn(session_id, {"message": str(index)}, {"state": "executed"})
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write, ("alpha", "beta")))
    assert len(store.recent("alpha")) == len(store.recent("beta")) == 20
    assert {turn["session_id"] for turn in store.recent("alpha")} == {"alpha"}
    assert {turn["session_id"] for turn in store.recent("beta")} == {"beta"}


def _semantic_response(scenario, draft=True):
    return {
        "status": "clarification",
        "recognized": {"scenario": scenario},
        "draft": {"complete": False} if draft else None,
        "minimal_request": None,
    }


def test_session_store_lru_bounds_high_cardinality_and_preserves_recent_access():
    store = SessionStore(max_sessions=8)
    for index in range(100):
        name = f"s{index}"
        assert store.try_begin(name); store.end(name)
    assert store.session_count == 8
    assert set(store.session_ids) == {f"s{index}" for index in range(92, 100)}
    assert store.recent("s92") == []  # touch oldest so s93 becomes eviction target
    assert store.try_begin("final"); store.end("final")
    assert store.session_count == 8
    assert "s92" in store.session_ids and "s93" not in store.session_ids


def test_session_store_never_evicts_inflight_session():
    store = SessionStore(max_sessions=2)
    assert store.try_begin("pinned")
    assert store.try_begin("old"); store.end("old")
    assert store.try_begin("new"); store.end("new")
    assert "pinned" in store.session_ids and "old" not in store.session_ids
    store.end("pinned")


def test_semantic_context_is_same_scenario_only_and_not_exposed_in_recent():
    store = SessionStore(max_sessions=4)
    assert store.try_begin("s")
    store.record_turn("s", {"message": "贵州茅台FY2027", "selected_scenario": "earnings_expectation"},
                      _semantic_response("earnings_expectation"))
    store.end("s")
    context = store.context("s", "earnings_expectation")
    assert context == {"scenario": "earnings_expectation", "user_messages": ["贵州茅台FY2027"]}
    assert "user_messages" not in str(store.recent("s"))
    assert store.context("s", "stock_review") == {"scenario": None, "user_messages": []}
