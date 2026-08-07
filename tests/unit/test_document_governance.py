"""权威顺序与阶段状态文档一致性。"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_engineering_guide_is_current_and_task_cannot_override():
    guide = _read("docs/engineering-guide.md")
    agents = _read("AGENTS.md")
    task = _read("docs/tasks/phase4-equity-research.md")
    assert "版本：V1.1" in guide
    assert "当前唯一有效工程基线" in guide
    assert "engineering-guide.md` → `docs/project-state/DECISIONS.md" in agents
    assert "仅细化" in task
    assert "冲突时按本任务书执行" not in task


def test_phase_status_documents_are_consistent():
    files = [
        _read("README.md"), _read("docs/project-state/CURRENT_STATE.md"),
        _read("docs/project-state/NEXT_PHASE.md"),
        _read("docs/project-state/KNOWN_LIMITATIONS.md"),
        _read("docs/tasks/phase4-full-research-capability.md"),
    ]
    for text in files:
        assert "PASS" in text
        assert "BLOCKED" in text
        assert "PARTIAL_SUCCESS / READY_FOR_INDEPENDENT_ACCEPTANCE" not in text


def test_baseline_readme_does_not_claim_to_be_current():
    baseline = _read("docs/baselines/README.md")
    assert "唯一当前有效" in baseline
    assert "不参与覆盖当前规范" in baseline
