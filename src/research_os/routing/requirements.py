"""数据需求注册表（Phase 1 任务 8.1 节）。

加载 registry/data_requirements.yaml；主源失败后才使用备源；
最低字段不满足时返回 insufficient_data；禁止估算缺失值；
禁止把空响应解释为"没有事件"。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml

from pydantic import BaseModel, Field


class DataRequirement(BaseModel):
    """单个数据类型的数据需求。"""

    data_type: str
    primary: List[str] = Field(default_factory=list)
    secondary: List[str] = Field(default_factory=list)
    fallback: List[str] = Field(default_factory=list)
    minimum_fields: List[str] = Field(default_factory=list)
    failure_policy: str = "degraded"   # degraded / insufficient_data


class DataRequirementRegistry:
    """数据需求注册表。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._requirements: Dict[str, DataRequirement] = {}
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            self._requirements = {}
            return
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        for dtype, raw in (data.get("requirements") or {}).items():
            raw = dict(raw or {})
            min_acc = raw.pop("minimum_acceptable", {}) or {}
            self._requirements[dtype] = DataRequirement(
                data_type=dtype,
                primary=raw.get("primary", []),
                secondary=raw.get("secondary", []),
                fallback=raw.get("fallback", []),
                minimum_fields=min_acc.get("fields", []),
                failure_policy=raw.get("failure_policy", "degraded"),
            )

    def get(self, data_type: str) -> Optional[DataRequirement]:
        return self._requirements.get(data_type)

    def all(self) -> List[DataRequirement]:
        return list(self._requirements.values())

    def source_priority(self, data_type: str) -> List[str]:
        """主源 -> 备源 -> 兜底的完整尝试顺序。"""
        req = self._requirements.get(data_type)
        if req is None:
            return []
        return list(dict.fromkeys(req.primary + req.secondary + req.fallback))
