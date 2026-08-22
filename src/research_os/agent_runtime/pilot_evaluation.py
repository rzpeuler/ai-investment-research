"""Deterministic P8-A4 pilot evaluation helpers.

This module creates a human-review template and validates reviewer input. It
does not assign qualitative scores, infer usefulness, or admit any output to a
formal research artifact. Forbidden-output detection is a bounded safety
signal for pilot reporting only.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean, median
from typing import Any, Iterable

from research_os.agent_runtime.errors import ConfigurationError

EVALUATION_VERSION = "1.0.0"
SCORE_FIELDS = (
    "research_usefulness",
    "exploration_quality",
    "actionability",
)

# Unicode escapes keep the source encoding-independent on Windows.
FORBIDDEN_ARTIFACT_MARKERS = (
    "target_price", "fair_value", "buy rating", "sell rating",
    "position advice", "FinancialFact", "ResearchFinding", "FinalReport",
    "graph_write", "\u76ee\u6807\u4ef7", "\u4e70\u5165\u8bc4\u7ea7",
    "\u5356\u51fa\u8bc4\u7ea7", "\u4ed3\u4f4d\u5efa\u8bae", "\u4e70\u5165\u5efa\u8bae",
    "\u5356\u51fa\u5efa\u8bae",
)


@dataclass(frozen=True)
class HumanEvaluation:
    """One optional human evaluation; scores remain reviewer-owned."""

    case_id: str
    research_usefulness: int | None = None
    exploration_quality: int | None = None
    actionability: int | None = None
    noise_rate: float | None = None
    reviewer: str = ""
    reviewed_at: str = ""
    notes: str = ""

    def validate(self) -> None:
        if not self.case_id:
            raise ConfigurationError("human evaluation case_id is required")
        for field_name in SCORE_FIELDS:
            value = getattr(self, field_name)
            if value is not None and (not isinstance(value, int) or not 1 <= value <= 5):
                raise ConfigurationError(f"{field_name} must be an integer from 1 to 5")
        if self.noise_rate is not None and (
            not isinstance(self.noise_rate, (int, float)) or not 0 <= self.noise_rate <= 1
        ):
            raise ConfigurationError("noise_rate must be between 0 and 1")

    def as_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "case_id": self.case_id,
            "research_usefulness": self.research_usefulness,
            "exploration_quality": self.exploration_quality,
            "actionability": self.actionability,
            "noise_rate": self.noise_rate,
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "notes": self.notes,
        }


def build_human_evaluation_template(case_ids: Iterable[str]) -> dict[str, Any]:
    """Build a pending, reviewer-editable evaluation document."""
    normalized = list(case_ids)
    if not normalized or len(set(normalized)) != len(normalized):
        raise ConfigurationError("human evaluation case ids must be non-empty and unique")
    return {
        "evaluation_version": EVALUATION_VERSION,
        "status": "PENDING_REVIEW",
        "reviewer": "",
        "cases": [HumanEvaluation(case_id=case_id).as_dict() for case_id in normalized],
    }


def validate_human_evaluation_document(
    document: dict[str, Any], expected_case_ids: Iterable[str]
) -> list[HumanEvaluation]:
    """Validate reviewer input and return typed records; no score inference."""
    if not isinstance(document, dict) or document.get("evaluation_version") != EVALUATION_VERSION:
        raise ConfigurationError("human evaluation version is invalid")
    rows = document.get("cases")
    if not isinstance(rows, list):
        raise ConfigurationError("human evaluation cases must be a list")
    expected = list(expected_case_ids)
    if {row.get("case_id") for row in rows if isinstance(row, dict)} != set(expected):
        raise ConfigurationError("human evaluation cases do not match exploration corpus")
    evaluations = []
    for row in rows:
        if not isinstance(row, dict):
            raise ConfigurationError("human evaluation row must be an object")
        evaluation = HumanEvaluation(
            case_id=row.get("case_id", ""),
            research_usefulness=row.get("research_usefulness"),
            exploration_quality=row.get("exploration_quality"),
            actionability=row.get("actionability"),
            noise_rate=row.get("noise_rate"),
            reviewer=row.get("reviewer", document.get("reviewer", "")),
            reviewed_at=row.get("reviewed_at", ""),
            notes=row.get("notes", ""),
        )
        evaluation.validate()
        evaluations.append(evaluation)
    return evaluations


def aggregate_human_evaluations(evaluations: Iterable[HumanEvaluation]) -> dict[str, Any]:
    """Aggregate only scores explicitly supplied by a human reviewer."""
    rows = list(evaluations)
    for evaluation in rows:
        evaluation.validate()
    scored = [row for row in rows if all(getattr(row, field) is not None for field in SCORE_FIELDS)]
    result: dict[str, Any] = {
        "status": "PENDING_REVIEW" if not scored else "REVIEWED",
        "cases": len(rows),
        "scored_cases": len(scored),
        "research_usefulness": None,
        "exploration_quality": None,
        "actionability": None,
        "noise_rate": None,
    }
    for field_name in SCORE_FIELDS:
        values = [getattr(row, field_name) for row in scored]
        if values:
            result[field_name] = {"mean": round(mean(values), 3), "median": median(values)}
    noise_values = [row.noise_rate for row in rows if row.noise_rate is not None]
    if noise_values:
        result["noise_rate"] = {"mean": round(mean(noise_values), 3), "median": median(noise_values)}
    return result


def forbidden_artifact_hits(text: str) -> list[str]:
    """Return deterministic forbidden markers found in bounded pilot output."""
    value = text or ""
    return sorted({marker for marker in FORBIDDEN_ARTIFACT_MARKERS if marker.lower() in value.lower()})


__all__ = [
    "EVALUATION_VERSION",
    "FORBIDDEN_ARTIFACT_MARKERS",
    "HumanEvaluation",
    "aggregate_human_evaluations",
    "build_human_evaluation_template",
    "forbidden_artifact_hits",
    "validate_human_evaluation_document",
]
