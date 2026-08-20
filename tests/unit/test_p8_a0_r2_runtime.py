import json
import io
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from research_os.agent_runtime.research_capabilities import (
    MAX_RESULT_BYTES,
    TOOLS,
    _authority_db_path,
    bounded,
    check_data_readiness,
    get_company_profile,
)
from research_os.agent_runtime.production_runtime import BoundedOwnedProcess


ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def authority_db(tmp_path, monkeypatch):
    """A dedicated, deterministic authority DB for offline capability tests.

    The real repo-root ``data/sqlite/research.db`` is a git-ignored artifact
    that does not exist in a clean checkout (e.g. CI), so capability tests
    must not depend on it. We instead point the authority DB override at a
    self-contained SQLite file in a temp path.
    """
    db_path = tmp_path / "data" / "sqlite" / "research.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    try:
        # Column layout must mirror the real authority view the capability
        # queries: payload JSON plus a status column with an active marker.
        conn.execute("CREATE TABLE security_profiles (payload TEXT, status TEXT)")
        conn.execute("CREATE TABLE company_profiles (payload TEXT, status TEXT)")
        conn.execute(
            "INSERT INTO security_profiles (payload, status) VALUES (?, ?)",
            (json.dumps({
                "symbol": "600519.SH",
                "exchange": "SH",
                "company_entity_id": "company:maotai",
                "current_name": "贵州茅台",
                "security_type": "common_share",
                "listing_date": "2020-01-01",
                "currency": "CNY",
                "share_class": "A",
            }, ensure_ascii=False), "listed"),
        )
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setattr(
        "research_os.agent_runtime.research_capabilities._authority_db_path",
        lambda: db_path,
    )
    return db_path


def test_authority_path_is_fixed_and_ignores_legacy_environment_override(monkeypatch):
    monkeypatch.setenv("P8_AUTHORITY_DB_PATH", "C:/should/not/be used.db")
    assert _authority_db_path() == ROOT / "data" / "sqlite" / "research.db"


def test_real_company_capability_reads_existing_authority(authority_db):
    result = get_company_profile("600519.SH")
    assert result["status"] == "partial_success"
    assert result["entity_id"] == "company:maotai"
    assert result["security_reference"]["symbol"] == "600519.SH"
    assert result["company_profile"] is None


def test_real_readiness_capability_is_read_only_and_explicit(authority_db):
    result = check_data_readiness("600519.SH", "2026-08-19T00:00:00+08:00")
    assert result["requirement_count"] == len(result["readiness"]) == 7
    assert result["missing_count"] == 7
    assert "research_data_acquisition_disabled" in result["limitations"]


def test_result_bounding_fails_closed():
    result = bounded({"payload": "x" * (MAX_RESULT_BYTES + 1)})
    assert result == {"status": "tool_result_invalid", "reason": "bounded_result_limit_exceeded", "truncated": True}


def test_only_research_tools_are_advertised():
    assert set(TOOLS) == {"get_company_profile", "check_data_readiness"}
    assert "cninfo_fetch" not in TOOLS
    assert "graph_write" not in TOOLS


def test_missing_provider_key_fails_fast_without_starting_harness():
    env = os.environ.copy()
    env.pop("DEEPSEEK_API_KEY", None)
    result = subprocess.run(
        [sys.executable, "scripts/p8_a0_r2_launcher.py", "--timeout", "2"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "PROVIDER_AUTH_MISSING"
    assert "DEEPSEEK_API_KEY" not in result.stdout


def test_research_profile_disables_coding_tools_at_composition_layer():
    profile = (ROOT / "runtime-spike" / "research-profile" / "cordis.patch.yml").read_text(encoding="utf-8")
    for tool_id in ("tool-bash", "tool-pwsh", "tool-fs", "tool-fs-search", "tool-str-replace-editor", "tool-web"):
        assert f"- id: {tool_id}\n  disabled: true" in profile
    assert "@deepseek-ai/dsh-mcp-client" in profile


def test_closed_owned_stream_drain_exits_quietly():
    stream = io.BytesIO(b"owned output")
    stream.close()
    target = bytearray()
    thread = threading.Thread(
        target=BoundedOwnedProcess._drain,
        args=(stream, target),
    )
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
