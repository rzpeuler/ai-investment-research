"""采集器层：适配器与 stub。"""
from research_os.collectors.base import (
    CollectorAdapter,
    HealthStatus,
    ItemRef,
    RateLimitPolicy,
    RawPayload,
)

__all__ = [
    "CollectorAdapter",
    "HealthStatus",
    "ItemRef",
    "RateLimitPolicy",
    "RawPayload",
]
