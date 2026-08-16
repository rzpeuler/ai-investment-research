"""将注入式 CollectorAdapter 映射适配为既有 Router fetcher。

本模块不注册真实适配器，不执行限速、重试或任何来源专用网络策略。
"""
from __future__ import annotations

import re
from types import MappingProxyType
from typing import Any, Dict, List, Mapping, Optional, Tuple

from research_os.collectors.base import CollectorAdapter, ItemRef, RawPayload
from research_os.models import RawItem
from research_os.routing.router import FetchCallable
from research_os.validators.schema_validator import validate_instance


class CollectorBridgeError(RuntimeError):
    """单一来源 bridge attempt 失败；消息已做最小凭证脱敏。"""


_SECRET_PATTERNS = (
    re.compile(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"
    ),
    re.compile(
        r"(?i)((?:cookie|set-cookie|token|api[_-]?key|password|secret)\s*[:=]\s*)"
        r"[^\s,;]+"
    ),
)


def _sanitize_message(message: str) -> str:
    """遮蔽明显凭证值；完整结构化错误治理属于后续执行服务。"""
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub(r"\1[REDACTED]", sanitized)
    return sanitized


class CollectorFetcherBridge:
    """把显式注入的 ``source_id -> CollectorAdapter`` 变为 fetcher map。"""

    def __init__(self, adapters: Mapping[str, CollectorAdapter]):
        self._adapters = MappingProxyType(dict(adapters))
        self._fetchers = MappingProxyType({
            source_id: self._make_fetcher(source_id, adapter)
            for source_id, adapter in self._adapters.items()
        })

    @property
    def fetchers(self) -> Mapping[str, FetchCallable]:
        """供现有 Router 注入；构造或读取不会调用任何 adapter 方法。"""
        return self._fetchers

    def as_fetchers(self) -> Dict[str, FetchCallable]:
        """返回普通 dict，便于需要可变字典类型的旧调用方注入。"""
        return dict(self._fetchers)

    @staticmethod
    def _make_fetcher(source_id: str, adapter: CollectorAdapter) -> FetchCallable:
        def fetcher(
            query: Dict[str, Any],
            time_window: Dict[str, Optional[str]],
        ) -> Tuple[List[RawItem], set[str]]:
            try:
                return CollectorFetcherBridge._run_attempt(
                    source_id, adapter, query, time_window
                )
            except Exception as exc:  # noqa: BLE001 -- Router 必须接收显式来源失败
                detail = _sanitize_message(str(exc))
                raise CollectorBridgeError(
                    f"collector {source_id} attempt failed: {detail}"
                ) from None

        return fetcher

    @staticmethod
    def _run_attempt(
        source_id: str,
        adapter: CollectorAdapter,
        query: Dict[str, Any],
        time_window: Dict[str, Optional[str]],
    ) -> Tuple[List[RawItem], set[str]]:
        adapter_source_id = getattr(adapter, "source_id", None)
        if adapter_source_id != source_id:
            raise CollectorBridgeError(
                f"adapter source_id mismatch: expected {source_id!r}, got {adapter_source_id!r}"
            )

        refs = adapter.discover(query, time_window)
        normalized_items: List[RawItem] = []
        for ref in refs:
            CollectorFetcherBridge._require_source(source_id, ref, "ItemRef")
            payload = adapter.fetch(ref)
            CollectorFetcherBridge._require_source(source_id, payload, "RawPayload")
            items = adapter.normalize(payload)
            for item in items:
                CollectorFetcherBridge._require_source(source_id, item, "RawItem")
                if not isinstance(item, RawItem):
                    raise CollectorBridgeError(
                        "RawItem Schema validation failed: normalize returned non-RawItem"
                    )
                errors = validate_instance(item.model_dump(), "raw_item")
                if errors:
                    raise CollectorBridgeError(
                        "RawItem Schema validation failed: " + "; ".join(errors)
                    )
                normalized_items.append(item)

        if not normalized_items:
            return [], set()
        fields_present: set[str] = set()
        for item in normalized_items:
            # nullable 值不能证明内容字段存在；这里只报告本次规范化结果的严格字段并集。
            fields_present.update(item.model_dump(exclude_none=True).keys())
        return normalized_items, fields_present

    @staticmethod
    def _require_source(source_id: str, value: object, boundary: str) -> None:
        actual = getattr(value, "source_id", None)
        if actual != source_id:
            raise CollectorBridgeError(
                f"{boundary} source_id mismatch: expected {source_id!r}, got {actual!r}"
            )


__all__ = ["CollectorBridgeError", "CollectorFetcherBridge"]
