"""统一 LLM 客户端与模型路由（Phase 3 任务书 12 节）。

- LlmClient 统一接口：业务模块不得直接调用 Provider SDK
- Flash 职责：语义关联/候选生成/机制摘要/叙事归纳/结构草案（不决定权重、
  阈值、基准资格或证据门槛）
- Pro 升级：业务复杂度路由（12.3），与 provider 故障回退分离（12.6）
- 失败降级：deterministic_fallback 如实记录（llm_called 区分是否实际调用）
- LLM 输出必须经过 JSON 解析 -> Schema 校验 -> Pydantic -> dump -> 再校验
  -> 确定性业务规则，不得直接进入报告（12.4）
"""
from research_os.llm.client import LlmClient
from research_os.llm.models import LlmRequest, LlmResponse
from research_os.llm.provider import FakeLlmProvider, LlmProvider
from research_os.llm.routing import ModelRouter

__all__ = [
    "FakeLlmProvider",
    "LlmClient",
    "LlmProvider",
    "LlmRequest",
    "LlmResponse",
    "ModelRouter",
]
