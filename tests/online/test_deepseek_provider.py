"""DeepSeek 最小在线探测；不保存 Prompt、响应全文或凭证。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_os.llm.probe import probe_provider

pytestmark = pytest.mark.online


def test_deepseek_flash_probe_live():
    if os.environ.get("RESEARCH_LLM_ONLINE") != "1":
        pytest.skip("需要 RESEARCH_LLM_ONLINE=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("需要 DEEPSEEK_API_KEY")
    root = Path(__file__).resolve().parents[2]
    result = probe_provider(root, provider_id="deepseek", model_class="flash", live=True)
    payload = result.model_dump()
    assert result.configured is True
    assert result.reachable is True, result.sanitized_error
    assert result.authentication_status == "ok"
    assert result.flash_model_resolved == "deepseek-v4-flash"
    assert result.pro_model_resolved == "deepseek-v4-pro"
    serialized = json.dumps(payload, ensure_ascii=False).lower()
    assert "authorization" not in serialized
    assert "bearer " not in serialized
