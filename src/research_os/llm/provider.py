"""LLM Provider 抽象与 Fake 实现（Phase 3 任务书 12.1、19.4）。

业务模块不得直接调用 Provider SDK；所有调用经 LlmClient 统一接口。
FakeLlmProvider 用于离线测试（不访问真实 Provider）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class LlmProvider(Protocol):
    """Provider 最小接口：给定请求与输出 Schema，返回结构化结果 dict。"""

    def complete_json(self, request, output_schema: Dict[str, Any]) -> Dict[str, Any]:
        """返回 {ok: bool, output: dict|None, error: str|None, model_id: str|None}。"""
        ...


class FakeLlmProvider:
    """确定性 Fake Provider：按脚本返回或抛错（测试用）。"""

    def __init__(self,
                 outputs: Optional[Dict[str, Any]] = None,
                 behavior: Optional[Callable[[Any, Dict[str, Any]], Dict[str, Any]]] = None,
                 default_error: Optional[str] = None):
        self.outputs = dict(outputs or {})
        self.behavior = behavior
        self.default_error = default_error
        self.calls: list = []

    def complete_json(self, request, output_schema: Dict[str, Any]) -> Dict[str, Any]:
        self.calls.append(request)
        if self.behavior is not None:
            return self.behavior(request, output_schema)
        key = request.prompt_hash
        if key in self.outputs:
            out = self.outputs[key]
            if isinstance(out, Exception):
                return {"ok": False, "output": None, "error": str(out), "model_id": "fake"}
            return {"ok": True, "output": out, "error": None, "model_id": "fake-model"}
        if self.default_error:
            return {"ok": False, "output": None, "error": self.default_error, "model_id": None}
        return {"ok": True, "output": {}, "error": None, "model_id": "fake-model"}
