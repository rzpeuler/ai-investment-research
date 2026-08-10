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
