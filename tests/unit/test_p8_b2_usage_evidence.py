"""P8-B2-LIVE-01-REPAIR-02: provider usage evidence extraction regression tests.

The pinned dsh rc.7 runtime reports usage under camelCase tokenUsage keys
(uncachedInputTokens / outputTokens / cacheReadTokens / cacheWriteTokens).
These deterministic offline tests lock the mapping into the evidence
vocabulary (input_tokens / output_tokens / cached_tokens / cache_read_tokens /
cache_write_tokens / total_tokens) and the no-inference rule.
"""
from __future__ import annotations

import pytest

from research_os.agent_runtime.production_runtime import _extract_usage


def _dsh_payload(**token_usage) -> dict:
    return {
        "result": {
            "projections": {
                "values": {
                    "tokenUsage": token_usage,
                    "sessionStats": {"decodeTokens": token_usage.get("outputTokens", 0)},
                }
            }
        }
    }


def test_dsh_fields_are_mapped_to_evidence_vocabulary():
    payload = _dsh_payload(uncachedInputTokens=27672, outputTokens=1264,
                           cacheReadTokens=15360, cacheWriteTokens=0)
    usage = _extract_usage(payload)
    assert usage["input_tokens"] == 27672 + 15360 + 0
    assert usage["output_tokens"] == 1264
    assert usage["cached_tokens"] == 15360 + 0
    assert usage["cache_read_tokens"] == 15360
    assert usage["cache_write_tokens"] == 0
    assert usage["total_tokens"] == 27672 + 1264 + 15360 + 0


def test_total_tokens_follows_taskbook_formula():
    usage = _extract_usage(_dsh_payload(uncachedInputTokens=10, outputTokens=2,
                                        cacheReadTokens=3, cacheWriteTokens=4))
    assert usage["total_tokens"] == 10 + 2 + 3 + 4 == 19


def test_missing_optional_dsh_fields_are_handled_safely():
    # Only uncached + output reported: input has no cache components, cached = 0.
    usage = _extract_usage(_dsh_payload(uncachedInputTokens=100, outputTokens=5))
    assert usage["input_tokens"] == 100
    assert usage["output_tokens"] == 5
    assert usage["cached_tokens"] == 0
    assert usage["cache_read_tokens"] == 0
    assert usage["cache_write_tokens"] == 0
    assert usage["total_tokens"] == 105


def test_zero_usage_is_reported_as_zero_not_inferred():
    usage = _extract_usage(_dsh_payload(uncachedInputTokens=0, outputTokens=0,
                                        cacheReadTokens=0, cacheWriteTokens=0))
    assert usage["input_tokens"] == 0
    assert usage["output_tokens"] == 0
    assert usage["total_tokens"] == 0


def test_no_usage_fields_returns_empty():
    assert _extract_usage({"events": [{"type": "text", "text": "ok"}]}) == {}
    assert _extract_usage({}) == {}


def test_existing_snake_case_fields_still_recognized():
    payload = {"usage": {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}}
    usage = _extract_usage(payload)
    assert usage["input_tokens"] == 11
    assert usage["output_tokens"] == 7
    assert usage["total_tokens"] == 18


def test_non_numeric_and_bool_values_are_ignored():
    payload = _dsh_payload(uncachedInputTokens="27672", outputTokens=True,
                           cacheReadTokens=5, cacheWriteTokens=None)
    usage = _extract_usage(payload)
    # Only the numeric cacheReadTokens contributes; string/bool/None ignored.
    assert usage.get("input_tokens") == 5
    assert usage.get("output_tokens") == 0
    assert usage.get("total_tokens") == 5


def test_no_secret_exposure_in_usage_evidence():
    # String values (the only place secrets could ride) never enter usage.
    payload = _dsh_payload(uncachedInputTokens=1, outputTokens=1,
                           cacheReadTokens=1, cacheWriteTokens=0)
    payload["result"]["projections"]["values"]["tokenUsage"]["raw"] = "Bearer SECRET123"
    usage = _extract_usage(payload)
    assert all(isinstance(value, (int, float)) for value in usage.values())
    assert "SECRET123" not in str(usage)
    assert "Bearer" not in str(usage)


def test_usage_from_nested_listing_shape():
    # The dsh session.list shape: items[].projections.values.tokenUsage
    payload = {"items": [{"projections": {"values": {"tokenUsage": {
        "uncachedInputTokens": 20, "outputTokens": 3,
        "cacheReadTokens": 7, "cacheWriteTokens": 1}}}}]}
    usage = _extract_usage(payload)
    assert usage["total_tokens"] == 20 + 3 + 7 + 1
