"""ResearchModule 抽象接口（工程指南 13 节模块通用接口）。

每个模块必须实现：validate_input / plan / run / validate_output。
模块目录必须包含 spec.md、prompt.md、module.py、rules.yaml、examples/、tests/。
prompt.md 只负责 LLM 推理说明；业务规则在 spec.md 与 rules.yaml，禁止塞进 Prompt。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List

from pydantic import BaseModel, Field

from research_os.models import ModuleResult


class ValidationResult(BaseModel):
    """输入/输出校验结果。失败必须显式返回，禁止静默失败。"""

    ok: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def failure(cls, errors: List[str]) -> "ValidationResult":
        return cls(ok=False, errors=errors)


class ModulePlan(BaseModel):
    """模块执行计划：数据需求、步骤、预算。"""

    module: str
    steps: List[str] = Field(default_factory=list)
    data_requirements: List[str] = Field(default_factory=list)
    estimated_runtime_seconds: int = 0
    needs_model: bool = False
    model_tier: str = "flash_default"


class ResearchModule(ABC):
    """功能模块基类。职责单一、可被多个场景复用（指南 6.1）。"""

    name: str = ""
    version: str = "0.0.0"

    @abstractmethod
    def validate_input(self, payload: Dict[str, Any]) -> ValidationResult:
        """校验模块输入（确定性校验，代码实现）。"""

    @abstractmethod
    def plan(self, payload: Dict[str, Any], context: Dict[str, Any]) -> ModulePlan:
        """生成模块执行计划。"""

    @abstractmethod
    def run(self, payload: Dict[str, Any], context: Dict[str, Any]) -> ModuleResult:
        """执行模块。任何失败必须返回 status=failed 的 ModuleResult，禁止抛异常吞掉。"""

    @abstractmethod
    def validate_output(self, result: ModuleResult) -> ValidationResult:
        """校验模块输出（必须通过 ModuleResult Schema 校验）。"""
