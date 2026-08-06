"""集中状态判定与确定性专业评审。"""
from __future__ import annotations

from research_os.equity_research.professional_review import build_professional_review
from research_os.equity_research.status import ResearchCoverage, evaluate_research_status


def _coverage(**overrides):
    values = dict(
        comparable_years=2, financial_coverage=True, evidence_coverage=True,
        business_coverage=True, competition_coverage=True, risk_coverage=True,
        catalyst_coverage=True, counter_evidence_coverage=True,
        market_debate_coverage=True, valuation_applicable_or_explained=True,
        semantic_coverage=True, source_quality_adequate=True, as_of_known=True,
        validator_status="pass", source_conflict=False,
    )
    values.update(overrides)
    return ResearchCoverage(**values)


def test_success_requires_every_core_module():
    assert evaluate_research_status(_coverage()).status == "success"
    decision = evaluate_research_status(_coverage(competition_coverage=False))
    assert decision.status == "degraded"
    assert "industry_competition" in decision.missing_core_modules


def test_validator_failure_is_failed():
    assert evaluate_research_status(_coverage(validator_status="fail")).status == "failed"


def test_professional_review_is_reproducible_and_has_no_action(tmp_path):
    rules = tmp_path / "review.yaml"
    rules.write_text(
        """version: 'test-v1'
score_range: [0, 5]
missing_data_score: 0
base_scores: {}
dimensions:
  - fundamental_quality
  - growth_sustainability
  - cycle_position
  - financial_quality
  - competitive_advantage
  - valuation_constraint
  - event_reliability
  - industry_trend
  - short_counter_evidence
  - information_completeness
  - evidence_quality
""",
        encoding="utf-8",
    )
    kwargs = dict(
        coverage={"financial": True, "competition": False, "valuation": False},
        evidence_tiers=["C"], evidence_ids=["evidence-1"], risks=[], catalysts=[],
        conflicts=[], rules_path=rules,
    )
    first = build_professional_review(**kwargs)
    second = build_professional_review(**kwargs)
    assert first == second
    assert first["rules_version"] == "test-v1"
    assert first["investment_action"] is None
    assert all(0 <= item["score"] <= 5 for item in first["items"])
    assert all("deduction_reasons" in item and "next_question" in item for item in first["items"])
