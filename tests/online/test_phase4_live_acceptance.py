"""Phase 4.1 两个真实成功和一个受控降级案例；默认跳过。"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from research_os.acceptance.phase4_live import (
    load_phase4_acceptance_config,
    run_phase4_case,
    write_phase4_acceptance_summary,
)

pytestmark = pytest.mark.online


def _enabled() -> None:
    if os.environ.get("RESEARCH_PHASE4_ACCEPTANCE") != "1":
        pytest.skip("需要 RESEARCH_PHASE4_ACCEPTANCE=1")
    if os.environ.get("RESEARCH_LLM_ONLINE") != "1":
        pytest.skip("需要 RESEARCH_LLM_ONLINE=1")
    if not os.environ.get("DEEPSEEK_API_KEY"):
        pytest.skip("需要 DEEPSEEK_API_KEY")


@pytest.mark.parametrize(
    ("case_id", "expected_status"),
    [
        ("stable_consumer_600519", "success"),
        ("complex_manufacturing_300750", "success"),
        ("controlled_missing_688981", "insufficient_data"),
    ],
)
def test_phase4_live_end_to_end_acceptance(case_id: str, expected_status: str) -> None:
    _enabled()
    root = Path(__file__).resolve().parents[2]
    configured = {
        case["case_id"]: case for case in load_phase4_acceptance_config(root)["cases"]
    }
    assert configured[case_id]["expected_status"] == expected_status
    result = run_phase4_case(root, case_id=case_id)
    summary_path = write_phase4_acceptance_summary(
        root, case_id=case_id, result=result, expected_status=expected_status)
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert result.exit_code in ({0} if expected_status == "success" else {3})
    assert summary["report_status"] == expected_status
    assert summary["prohibited_output_hits"] == []
    if expected_status == "success":
        assert summary["provider_live"] is True
        assert summary["provider_id"] == "deepseek"
        assert summary["official_documents"] >= 2
        assert summary["core_financial_evidence_qualified"] is True
        assert set(summary["mandatory_semantic_tasks"].values()) == {"pass"}
        assert summary["validator_status"] in {"pass", "pass_with_warnings"}
