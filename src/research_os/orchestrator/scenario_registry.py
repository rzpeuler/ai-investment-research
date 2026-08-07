"""显式场景注册表。"""
from __future__ import annotations

from typing import Dict, Iterable

from research_os.orchestrator.scenario_runner import ScenarioRunner


class ScenarioRegistry:
    def __init__(self) -> None:
        self._runners: Dict[str, ScenarioRunner] = {}

    def register(self, runner: ScenarioRunner) -> None:
        if not runner.scenario:
            raise ValueError("场景名不能为空")
        self._runners[runner.scenario] = runner

    def get(self, scenario: str) -> ScenarioRunner:
        try:
            return self._runners[scenario]
        except KeyError as exc:
            raise ValueError(f"未注册场景: {scenario}") from exc

    def names(self) -> Iterable[str]:
        return tuple(sorted(self._runners))

    def __contains__(self, scenario: str) -> bool:
        return scenario in self._runners
