"""CollectorAdapter 抽象接口（工程指南 21 节采集器统一接口）。

平台采集器属于数据采集层，不是功能模块（指南 6.2）。
禁止在功能模块 Prompt 中写死网页结构、CSS 选择器、Cookie 或平台登录流程。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from research_os.models import RawItem


class HealthStatus(BaseModel):
    """来源健康状态。access 对应指南 23.2 访问状态。"""

    source_id: str
    ok: bool
    access: str = "unknown"          # public / public_but_unstable / login_required / client_only / paid / manual_only / unavailable
    latency_seconds: Optional[float] = None
    message: str = ""
    checked_at: str = ""


class ItemRef(BaseModel):
    """采集发现的条目引用（未抓取）。"""

    source_id: str
    external_id: str
    url: str
    title: str = ""
    published_at: Optional[str] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class RawPayload(BaseModel):
    """采集原始负载：适配器 normalize 的输入（临时，不落库）。"""

    source_id: str
    external_id: str
    url: str
    title: str
    publisher: str
    author: Optional[str] = None
    published_at: Optional[str] = None
    content: str = ""
    retrieved_at: str = ""
    fetch_status: str = "ok"          # ok / partial / failed / unauthorized
    error_message: str = ""


class RateLimitPolicy(BaseModel):
    """限速策略。"""

    requests_per_minute: int = 0       # 0 = 无限制
    backoff_seconds: float = 1.0
    max_retries: int = 0
    timeout_seconds: float = 10.0


class CollectorAdapter(ABC):
    """采集器适配器基类。

    每个适配器必须支持：健康检查、超时、重试、限速、缓存、分页、日期范围、
    来源字段、失败原因、解析版本、测试样例（指南 21 节）。
    """

    source_id: str = ""
    version: str = "0.0.0"

    @abstractmethod
    def healthcheck(self) -> HealthStatus:
        """健康检查。未探测来源必须返回 ok=False，并明确访问状态。"""

    @abstractmethod
    def discover(self, query: Dict[str, Any], time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        """按查询与时间窗口发现条目。"""

    @abstractmethod
    def fetch(self, item_ref: ItemRef) -> RawPayload:
        """抓取条目原始内容。"""

    @abstractmethod
    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        """原始负载 -> 标准 RawItem 列表（必须通过 RawItem Schema 校验）。"""

    @abstractmethod
    def rate_limit_policy(self) -> RateLimitPolicy:
        """限速与重试策略。"""
