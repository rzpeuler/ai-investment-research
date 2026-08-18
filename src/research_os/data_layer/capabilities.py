"""获取能力注册表 Loader（P7-D1）。

严格加载 registry/data_acquisition_capabilities.yaml：
- unknown field / unknown lifecycle / duplicate data_type → reject
- 与 Scenario Requirement 的 data_type 集合必须完全一致（missing / extra → reject）
- source-like forbidden field → reject
- implementation_refs 必须是仓库内存在的路径 → reject

这是内部控制 Registry，不新增公共 JSON Schema。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from pydantic import BaseModel, Field, field_validator

from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry

LIFECYCLE_VALUES = [
    "NONE", "REGISTERED", "PROBED", "ADAPTER_IMPLEMENTED",
    "WORKFLOW_WIRED", "BUSINESS_SUFFICIENT",
]

_FORBIDDEN_KEYS = {
    "source_id", "selected_source", "provider_id", "url", "api_url",
    "endpoint", "source_priority",
}

_ALLOWED_FIELDS = {
    "data_type", "automatic_acquisition_lifecycle", "deterministic_derivation",
    "manual_modes", "requires_human_review", "requires_governed_workflow",
    "source_tier_applicable", "implementation_refs", "notes",
}


class AcquisitionCapability(BaseModel):
    data_type: str
    automatic_acquisition_lifecycle: str
    deterministic_derivation: bool = False
    manual_modes: List[str] = Field(default_factory=list)
    requires_human_review: bool = False
    requires_governed_workflow: bool = False
    source_tier_applicable: bool = True
    implementation_refs: List[str] = Field(default_factory=list)
    notes: str = ""

    model_config = {"extra": "forbid"}

    @field_validator("automatic_acquisition_lifecycle")
    @classmethod
    def _lifecycle(cls, value: str) -> str:
        if value not in LIFECYCLE_VALUES:
            raise ValueError(f"未知 lifecycle: {value!r}（允许 {LIFECYCLE_VALUES}）")
        return value


class AcquisitionCapabilityRegistry:
    """获取能力注册表：严格加载并校验 registry/data_acquisition_capabilities.yaml。"""

    def __init__(self, path: str | Path,
                 scenario_requirements: ScenarioDataRequirementRegistry | None = None,
                 repo_root: str | Path | None = None):
        self.path = Path(path)
        self._repo_root = Path(repo_root) if repo_root is not None else \
            Path(__file__).resolve().parents[3]
        self._scenario_requirements = scenario_requirements
        self._by_data_type: Dict[str, AcquisitionCapability] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Capability registry 不存在: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        raw_map = data.get("capabilities") or {}
        if not isinstance(raw_map, dict):
            raise ValueError("data_acquisition_capabilities.yaml 顶层必须是 capabilities 映射")

        by_type: Dict[str, AcquisitionCapability] = {}
        for dtype, raw in raw_map.items():
            if not isinstance(raw, dict):
                raise ValueError(f"capability {dtype} 必须是对象")
            unknown = set(raw.keys()) - _ALLOWED_FIELDS
            if unknown:
                raise ValueError(f"capability {dtype} 未知字段: {sorted(unknown)}")
            leaked = [k for k in _FORBIDDEN_KEYS if k in raw]
            if leaked:
                raise ValueError(f"capability {dtype} 禁止来源字段: {leaked}")
            if dtype in by_type:
                raise ValueError(f"重复 data_type: {dtype}")
            cap = AcquisitionCapability.model_validate({"data_type": dtype, **raw})
            for ref in cap.implementation_refs:
                if not (self._repo_root / ref).exists():
                    raise ValueError(
                        f"capability {dtype} implementation_ref 不存在: {ref}")
            by_type[dtype] = cap

        # fail-closed 覆盖率：必须与 Scenario Requirement data_type 完全一致
        if self._scenario_requirements is not None:
            required = {r.data_type for r in self._scenario_requirements.all()}
            actual = set(by_type.keys())
            missing = required - actual
            extra = actual - required
            if missing:
                raise ValueError(f"capability registry 缺少 data_type: {sorted(missing)}")
            if extra:
                raise ValueError(f"capability registry 多余 data_type: {sorted(extra)}")

        self._by_data_type = by_type

    def get(self, data_type: str) -> AcquisitionCapability:
        try:
            return self._by_data_type[data_type]
        except KeyError as exc:
            raise KeyError(f"未知 data_type capability: {data_type}") from exc

    def has(self, data_type: str) -> bool:
        return data_type in self._by_data_type

    def all(self) -> List[AcquisitionCapability]:
        return [self._by_data_type[t] for t in sorted(self._by_data_type)]

    def data_types(self) -> List[str]:
        return sorted(self._by_data_type)
