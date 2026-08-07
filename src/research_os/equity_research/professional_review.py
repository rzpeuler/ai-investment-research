"""确定性、证据约束的专业评审。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

REVIEW_RULES_VERSION = "1.0.0"
DEFAULT_RULES_PATH = Path(__file__).resolve().parents[3] / "config" / "professional_review.yaml"
DIMENSIONS = [
    "fundamental_quality", "growth_sustainability", "cycle_position", "financial_quality",
    "competitive_advantage", "valuation_constraint", "event_reliability", "industry_trend",
    "short_counter_evidence", "information_completeness", "evidence_quality",
]


def build_professional_review(*, coverage: Dict[str, Any],
                              evidence_tiers_by_id: Dict[str, str],
                              evidence_by_dimension: Dict[str, List[str]],
                              risks: List[dict], catalysts: List[dict],
                              conflicts: List[str],
                              rules_path: Optional[Path] = None) -> Dict[str, Any]:
    """相同输入与规则版本产生相同分数；缺数据直接扣分。"""
    rules: Dict[str, Any] = {}
    selected_rules_path = Path(rules_path) if rules_path and Path(rules_path).exists() else DEFAULT_RULES_PATH
    if selected_rules_path.exists():
        rules = yaml.safe_load(selected_rules_path.read_text(encoding="utf-8")) or {}
        configured_dimensions = rules.get("dimensions") or []
        if configured_dimensions != DIMENSIONS:
            raise ValueError("professional_review 维度配置与代码契约不一致")
    version = str(rules.get("version") or REVIEW_RULES_VERSION)
    base = rules.get("base_scores") or {}
    missing_score = int(rules.get("missing_data_score", 0))
    score_range = rules.get("score_range") or [0, 5]
    score_min, score_max = int(score_range[0]), int(score_range[1])
    completeness = sum(bool(v) for v in coverage.values()) / max(len(coverage), 1)
    evidence_tiers = list(evidence_tiers_by_id.values())
    high_tier = sum(t in ("S", "A") for t in evidence_tiers)
    evidence_score = missing_score if not evidence_tiers else min(
        score_max,
        int(base.get("evidence_base", 1))
        + min(high_tier, int(base.get("evidence_high_tier_bonus", 1)))
        + int(len(evidence_tiers) >= 3) * int(base.get("evidence_three_items_bonus", 1)),
    )
    scores = {
        "fundamental_quality": int(base.get("financial_present", 3)) if coverage.get("financial") else missing_score,
        "growth_sustainability": int(base.get("growth_financial_present", 2)) if coverage.get("financial") else missing_score,
        "cycle_position": int(base.get("cycle_competition_present", 2)) if coverage.get("competition") else missing_score,
        "financial_quality": int(base.get("financial_present", 3)) if coverage.get("financial") else missing_score,
        "competitive_advantage": int(base.get("competition_present", 3)) if coverage.get("competition") else missing_score,
        "valuation_constraint": int(base.get("valuation_present", 3)) if coverage.get("valuation") else missing_score,
        "event_reliability": min(score_max, len(catalysts)),
        "industry_trend": int(base.get("competition_present", 3)) if coverage.get("competition") else missing_score,
        "short_counter_evidence": min(score_max, len(risks) + len(conflicts)),
        "information_completeness": int(completeness * score_max),
        "evidence_quality": evidence_score,
    }
    items = []
    for dimension in DIMENSIONS:
        score = max(score_min, min(score_max, scores[dimension]))
        supporting_ids = list(dict.fromkeys(evidence_by_dimension.get(dimension, [])))
        items.append({
            "dimension": dimension, "score": score,
            "deduction_reasons": [] if score >= 3 else ["结构化数据或证据覆盖不足"],
            "supporting_evidence_ids": supporting_ids if score else [],
            "counter_examples": conflicts[:3],
            "evidence_gaps": [] if score >= 3 and supporting_ids else [dimension],
            "next_question": f"补充并核验 {dimension} 的原始证据",
        })
    return {"rules_version": version, "items": items,
            "total_score": sum(i["score"] for i in items),
            "investment_action": None}
