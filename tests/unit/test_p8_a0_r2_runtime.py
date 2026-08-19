import json
import os
import subprocess
import sys
from pathlib import Path

from research_os.agent_runtime.research_capabilities import (
    MAX_RESULT_BYTES,
    TOOLS,
    bounded,
    check_data_readiness,
    get_company_profile,
)


ROOT = Path(__file__).resolve().parents[2]


def test_real_company_capability_reads_existing_authority():
    result = get_company_profile("600519.SH")
    assert result["status"] == "partial_success"
    assert result["entity_id"] == "company:maotai"
    assert result["security_reference"]["symbol"] == "600519.SH"
    assert result["company_profile"] is None


def test_real_readiness_capability_is_read_only_and_explicit():
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
