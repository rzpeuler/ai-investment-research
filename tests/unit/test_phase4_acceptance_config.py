"""Phase 4.1 验收清单的离线治理测试。"""
from __future__ import annotations

from pathlib import Path

from research_os.acceptance.phase4_live import load_phase4_acceptance_config
from research_os.financials.evidence_binding import CORE_FINANCIAL_CODES


def test_phase4_acceptance_matrix_is_versioned_and_complete() -> None:
    root = Path(__file__).resolve().parents[2]
    config = load_phase4_acceptance_config(root)
    cases = config["cases"]
    assert config["provider_id"] == "deepseek"
    assert config["required_successes"] == 2
    assert [case["expected_status"] for case in cases].count("success") == 2
    assert any(case["expected_status"] == "insufficient_data" for case in cases)
    assert {case["category"] for case in cases} == {
        "stable_consumer", "complex_manufacturing", "controlled_missing",
    }
    for case in cases:
        if case["expected_status"] != "success":
            continue
        assert len(case["documents"]) == 2
        for document in case["documents"]:
            assert set(document["facts"]) == set(CORE_FINANCIAL_CODES)
            assert document["source_id"] == "cninfo"
            assert document["source_url"].lower().endswith(".pdf")
            assert document["published_at"] <= config["as_of"]


def test_acceptance_config_contains_no_secret_value() -> None:
    root = Path(__file__).resolve().parents[2]
    text = (root / "config" / "equity_research_acceptance.yaml").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "deepseek_api_key" not in lowered
    assert "authorization" not in lowered
    assert "bearer " not in lowered
