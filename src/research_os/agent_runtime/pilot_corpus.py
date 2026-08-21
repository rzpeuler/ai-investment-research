"""P8-A2 Hybrid Agent Runtime Pilot Corpus loader (strict).

Authority: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN (Decision #82). Loads and
strictly validates ``config/harness_pilot_corpus.yaml``. The corpus contains
ONLY exploration tasks (HARNESS_ALLOWED) plus negative controls that must
route to LEGACY_ONLY. It never contains FinancialFact / ResearchFinding /
final report generation as Harness tasks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from research_os.agent_runtime.errors import ConfigurationError
from research_os.agent_runtime.runtime_router import TaskProfile

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS_PATH = ROOT / "config" / "harness_pilot_corpus.yaml"

# Categories allowed in the exploration corpus (no artifact-generation classes).
ALLOWED_CATEGORIES = frozenset({"exploration", "preparation", "discovery", "analyst", "control"})


@dataclass(frozen=True)
class PilotCase:
    id: str
    category: str
    task_type: str
    output_contract: str
    risk_level: str
    authority_requirement: str
    prompt: str
    expected: str

    def profile(self) -> TaskProfile:
        return TaskProfile(
            task_id=self.id,
            task_type=self.task_type,
            output_contract=self.output_contract,
            risk_level=self.risk_level,
            authority_requirement=self.authority_requirement,
        )


class PilotCorpus:
    """Strictly validated exploration corpus."""

    def __init__(self, path: Path = DEFAULT_CORPUS_PATH):
        self.path = Path(path)
        if not self.path.exists():
            raise ConfigurationError(f"pilot corpus missing: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        version = data.get("version")
        if not isinstance(version, str) or not version:
            raise ConfigurationError("pilot corpus version is required")
        self.version = version
        self.cases: list[PilotCase] = []
        seen: set[str] = set()
        for raw in data.get("cases") or []:
            if not isinstance(raw, dict):
                raise ConfigurationError("pilot corpus case must be an object")
            case_id = raw.get("id")
            if not isinstance(case_id, str) or not case_id:
                raise ConfigurationError("pilot corpus case id is required")
            if case_id in seen:
                raise ConfigurationError(f"duplicate pilot corpus case: {case_id}")
            seen.add(case_id)
            category = raw.get("category")
            if category not in ALLOWED_CATEGORIES:
                raise ConfigurationError(f"case {case_id}: unknown category {category!r}")
            task_type = raw.get("task_type")
            output_contract = raw.get("output_contract")
            risk_level = raw.get("risk_level")
            authority = raw.get("authority_requirement")
            prompt = raw.get("prompt")
            expected = raw.get("expected")
            if not all(isinstance(value, str) and value for value in (
                    task_type, output_contract, risk_level, authority, prompt, expected)):
                raise ConfigurationError(f"case {case_id}: all fields must be non-empty strings")
            # Exploration corpus invariant: no strict-schema artifact generation
            # as a Harness task. Negative controls carry strict_schema and must
            # expect LEGACY_ONLY.
            if output_contract == "strict_schema" and expected != "LEGACY_ONLY":
                raise ConfigurationError(
                    f"case {case_id}: strict_schema task must expect LEGACY_ONLY")
            self.cases.append(PilotCase(
                id=case_id, category=category, task_type=task_type,
                output_contract=output_contract, risk_level=risk_level,
                authority_requirement=authority, prompt=prompt, expected=expected,
            ))
        if not self.cases:
            raise ConfigurationError("pilot corpus is empty")
        self._by_id = {case.id: case for case in self.cases}

    def get(self, case_id: str) -> PilotCase:
        try:
            return self._by_id[case_id]
        except KeyError as exc:
            raise ConfigurationError(f"unknown pilot corpus case: {case_id}") from exc

    def exploration_cases(self) -> list[PilotCase]:
        return [case for case in self.cases if case.category != "control"]

    def control_cases(self) -> list[PilotCase]:
        return [case for case in self.cases if case.category == "control"]

    def all(self) -> list[PilotCase]:
        return list(self.cases)


__all__ = ["PilotCase", "PilotCorpus", "DEFAULT_CORPUS_PATH"]
