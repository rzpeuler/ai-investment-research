"""统一场景执行协议。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, Field


class ScenarioExecutionResult(BaseModel):
    """三个核心场景共享的执行结果。"""

    status: str
    exit_code: int
    task_id: str
    run_id: Optional[str] = None
    run_dir: Optional[str] = None
    report_path: Optional[str] = None
    validation_status: str = "pending"
    warnings: List[str] = Field(default_factory=list)
    missing_data: List[str] = Field(default_factory=list)
    model_route: Dict[str, Any] = Field(default_factory=dict)
    runtime_seconds: float = 0.0
    message: str = ""


@runtime_checkable
class ScenarioRunner(Protocol):
    """场景适配器只编排既有 Pipeline，不承载具体研究算法。"""

    scenario: str
    version: str

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]: ...

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]: ...

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult: ...
