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
    """Phase5 current status docs must reflect PASS; M10 must be PASS;
    no stale pre-merge/in-progress claims in current-status docs."""
    readme = _read("README.md")
    current = _read("docs/project-state/CURRENT_STATE.md")
    next_phase = _read("docs/project-state/NEXT_PHASE.md")
    limitations = _read("docs/project-state/KNOWN_LIMITATIONS.md")
    phase5_task = _read("docs/tasks/phase5-industry-knowledge-graph.md")

    # ── CURRENT-STATE DOCUMENTS ──
    # Phase5 terminal state assertions
    assert "Phase 5" in readme and "PASS" in readme, "README must reflect Phase5 PASS"
    assert "M0-M10" in readme, "README must state M0-M10 PASS"
    assert "| Phase 5 | PASS |" in current, "CURRENT_STATE must reflect Phase5 PASS"
    assert "Phase 5 implementation：PASS" in next_phase, "NEXT_PHASE must reflect Phase5 PASS"
    assert "Phase 5" in limitations and ("PASS" in limitations or "CLOSED" in limitations), \
        "KNOWN_LIMITATIONS must reflect Phase5 terminal state"
    assert "Phase 5 = CLOSED / PASS" in limitations, \
        "KNOWN_LIMITATIONS must explicitly state Phase 5 = CLOSED / PASS"
    # KNOWN_LIMITATIONS header must not contain Phase5 BLOCKED
    lim_header = "\n".join(limitations.split("\n")[:30])
    assert "Phase 5 = BLOCKED" not in lim_header and "Phase 5 = BLOCKED" != lim_header.strip(), \
        "KNOWN_LIMITATIONS header must not declare Phase5 BLOCKED"
    assert "NOT_AUTHORIZED" in limitations, "KNOWN_LIMITATIONS must reflect Phase6 NOT_AUTHORIZED"
    assert "**IMPLEMENTATION_STATUS: COMPLETE**" in phase5_task
    # No stale pre-merge artifacts in CURRENT_STATE or NEXT_PHASE surface
    assert "Draft PR #6" not in current, "CURRENT_STATE must not reference Draft PR #6"
    assert "Draft PR #6" not in next_phase, "NEXT_PHASE must not reference Draft PR #6"
    # Merge facts present
    assert "1e1d4f9" in current, "CURRENT_STATE must record PR5C master SHA"
    assert "2c55c55" in current, "CURRENT_STATE must record post-hotfix master SHA"
    assert "1087520" in current, "CURRENT_STATE must record final governance master SHA"
    # NEXT_PHASE: M10 must be PASS, not IN_PROGRESS
    assert "M10 Deterministic JSON Mirror + E2E Acceptance" in next_phase
    assert "AUTHORIZED / IN_PROGRESS" not in next_phase
    # No malformed empty PR status
    for text in (current, next_phase):
        assert "（）。" not in text, "Malformed empty PR status found"
        assert "Draft PR #6" not in text
        assert "AUTHORIZED / IN_PROGRESS" not in text
    # Merge facts in NEXT_PHASE
    assert "MERGED" in next_phase, "NEXT_PHASE must document PR5C merged"

    # No stale pre-merge claims in current-status docs (header sections only)
    for text in (readme, current, next_phase):
        assert "M10 AUTHORIZED / IN_PROGRESS" not in text
        assert "M10 IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE" not in text
        assert "M10 NOT_AUTHORIZED" not in text
        assert "PARTIAL_SUCCESS / READY_FOR_INDEPENDENT_ACCEPTANCE" not in text
    # Taskbook: only check header (first 20 lines); historical entries have old states
    taskbook_header = "\n".join(phase5_task.split("\n")[:20])
    assert "M10 IMPLEMENTED / AWAITING_INDEPENDENT_ACCEPTANCE" not in taskbook_header
    assert "M10 NOT_AUTHORIZED" not in taskbook_header

    # Historical docs: may reflect their own state (legacy check)
    phase4 = _read("docs/tasks/phase4-full-research-capability.md")
    assert "PASS" in phase4 or "PASSED" in phase4 or \
           "SATISFIED" in phase4 or "COMPLETED" in phase4


def test_baseline_readme_does_not_claim_to_be_current():
    baseline = _read("docs/baselines/README.md")
    assert "唯一当前有效" in baseline
    assert "不参与覆盖当前规范" in baseline
