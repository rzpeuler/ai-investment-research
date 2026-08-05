"""Stub 采集适配器（Phase 0 占位）。

工程指南执行规则第 9 条：未验证数据源时建立 stub，并明确 TODO。
Phase 0 禁止实现任何网页抓取。所有方法显式返回"未探测"状态，禁止静默失败。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from research_os.collectors.base import (
    CollectorAdapter,
    HealthStatus,
    ItemRef,
    RateLimitPolicy,
    RawPayload,
)
from research_os.models import RawItem
from research_os.utils.time import now_iso


class NotProbedError(RuntimeError):
    """来源尚未探测（Phase 1 probe_sources 之后才能启用）。"""


class StubCollector(CollectorAdapter):
    """未探测来源的占位适配器。

    source_id 可指定（如 "sse"），但任何真实访问行为均为 TODO Phase 1。
    """

    def __init__(self, source_id: str = "stub", version: str = "0.0.0"):
        self.source_id = source_id
        self.version = version

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(
            source_id=self.source_id,
            ok=False,
            access="unavailable",
            message="Phase 0 stub：来源尚未探测（TODO Phase 1: probe_sources.py）",
            checked_at=now_iso(),
        )

    def discover(self, query: Dict[str, Any], time_window: Dict[str, Optional[str]]) -> List[ItemRef]:
        raise NotProbedError(
            f"来源 {self.source_id} 尚未探测，禁止 discover（TODO Phase 1）"
        )

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        raise NotProbedError(
            f"来源 {self.source_id} 尚未探测，禁止 fetch（TODO Phase 1）"
        )

    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        raise NotProbedError(
            f"来源 {self.source_id} 尚未探测，禁止 normalize（TODO Phase 1）"
        )

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=0, max_retries=0)
