"""场景数据需求注册表 Loader（P7-D0）。

职责仅限：加载 YAML、严格验证、按 Scenario 返回 requirement specs、
保证顺序确定性、禁止重复 requirement_id、拒绝未知 Scenario、拒绝未知字段、
拒绝 Source ID 写入 Scenario requirement。不得联网。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from research_os.models import ScenarioDataRequirement
from research_os.validators.schema_validator import validate_instance

_FORBIDDEN_KEYS = {"source_id", "selected_source", "provider_id", "url", "api_endpoint"}

# 现有 10 个 Scenario（与 Task Schema enum / DEFAULT_SCENARIOS 一致）
SCENARIO_IDS = [
    "morning_brief", "evening_brief", "daily_review",
    "abnormal_move_analysis", "stock_research_report", "first_coverage",
    "stock_review", "industry_research", "theme_discovery",
    "earnings_expectation",
]


class ScenarioDataRequirementRegistry:
    """场景数据需求注册表：加载并严格验证 registry/scenario_data_requirements.yaml。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._by_scenario: Dict[str, List[ScenarioDataRequirement]] = {}
        self._by_requirement_id: Dict[str, ScenarioDataRequirement] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Scenario requirement registry 不存在: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        scenarios = data.get("scenarios") or {}
        if not isinstance(scenarios, dict):
            raise ValueError("scenario_data_requirements.yaml 顶层必须是 scenarios 映射")

        by_scenario: Dict[str, List[ScenarioDataRequirement]] = {}
        by_req_id: Dict[str, ScenarioDataRequirement] = {}
        for scenario in SCENARIO_IDS:
            raw_reqs = scenarios.get(scenario)
            if raw_reqs is None:
                raise ValueError(f"缺少 Scenario {scenario} 的数据需求")
            reqs = raw_reqs.get("requirements") if isinstance(raw_reqs, dict) else None
            if not isinstance(reqs, list) or not reqs:
                raise ValueError(f"Scenario {scenario} 的 requirements 必须是非空列表")
            items: List[ScenarioDataRequirement] = []
            for raw in reqs:
                self._validate_raw(raw)
                req = ScenarioDataRequirement.model_validate(raw)
                # 机械锁定：requirement 中禁止 source 声明
                if req.data_type in _FORBIDDEN_KEYS:
                    raise ValueError(f"Scenario {scenario} 禁止使用 {req.data_type}")
                if req.requirement_id in by_req_id:
                    raise ValueError(f"重复 requirement_id: {req.requirement_id}")
                if req.scenario != scenario:
                    raise ValueError(
                        f"requirement {req.requirement_id} 的 scenario {req.scenario} "
                        f"与所属键 {scenario} 不一致"
                    )
                errs = validate_instance(req.model_dump(), "scenario_data_requirement")
                if errs:
                    raise ValueError(f"ScenarioDataRequirement 未通过 Schema 校验: {errs}")
                by_req_id[req.requirement_id] = req
                items.append(req)
            by_scenario[scenario] = items
        self._by_scenario = by_scenario
        self._by_requirement_id = by_req_id

    @staticmethod
    def _validate_raw(raw: object) -> None:
        if not isinstance(raw, dict):
            raise ValueError("每个 requirement 必须是对象")
        unknown = set(raw.keys()) - {
            "requirement_id", "scenario", "purpose", "data_type", "scope",
            "time_policy", "required", "minimum_fields", "minimum_coverage",
            "minimum_source_tier", "freshness_seconds", "point_in_time_policy",
            "acceptable_fallback_modes", "degradation_policy", "notes",
        }
        if unknown:
            raise ValueError(f"未知字段: {sorted(unknown)}")
        # 机械禁止 source 声明进入 Scenario requirement
        leaked = [k for k in _FORBIDDEN_KEYS if k in raw]
        if leaked:
            raise ValueError(f"Scenario requirement 禁止声明来源字段: {leaked}")

    def get(self, requirement_id: str) -> ScenarioDataRequirement | None:
        return self._by_requirement_id.get(requirement_id)

    def for_scenario(self, scenario: str) -> List[ScenarioDataRequirement]:
        if scenario not in self._by_scenario:
            raise ValueError(f"未知 Scenario: {scenario}")
        return list(self._by_scenario[scenario])

    def all(self) -> List[ScenarioDataRequirement]:
        ordered: List[ScenarioDataRequirement] = []
        for scenario in SCENARIO_IDS:
            ordered.extend(self._by_scenario[scenario])
        return ordered

    def requirement_ids(self) -> List[str]:
        return [req.requirement_id for req in self.all()]
