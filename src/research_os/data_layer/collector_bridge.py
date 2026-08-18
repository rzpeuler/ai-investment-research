"""将注入式 CollectorAdapter 映射适配为既有 Router fetcher。

本模块不注册真实适配器，不执行限速、重试或任何来源专用网络策略。
"""
from __future__ import annotations

from types import MappingProxyType
from typing import Any, Dict, FrozenSet, List, Mapping, Optional, Tuple

from research_os.collectors.base import CollectorAdapter, ItemRef, RawPayload
from research_os.models import RawItem
from research_os.routing.router import FetchCallable
from research_os.validators.schema_validator import validate_instance


class CollectorBridgeError(RuntimeError):
    """单一来源 bridge attempt 失败；不保留 adapter 异常详情。"""


class CollectorFetcherBridge:
    """把显式注入的 ``source_id -> CollectorAdapter`` 变为 fetcher map。

    ``projector``（可选）为 SourceQueryProjector：fetcher 收到 canonical query 后，
    按 (source_id, data_type) 精确投影为 source-specific query 再交给 adapter。
    未注入 projector 时保持既有行为（canonical query 原样传递）。
    """

    def __init__(self, adapters: Mapping[str, CollectorAdapter],
                 projector: Optional[Any] = None):
        self._adapters = MappingProxyType(dict(adapters))
        self._projector = projector
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

    def _make_fetcher(self, source_id: str,
                      adapter: CollectorAdapter) -> FetchCallable:
        def fetcher(
            data_type: str,
            query: Dict[str, Any],
            time_window: Dict[str, Optional[str]],
        ) -> Tuple[List[RawItem], FrozenSet[str]]:
            try:
                projected = query
                if self._projector is not None:
                    projected = self._projector.project(
                        source_id=source_id,
                        data_type=data_type,
                        canonical_query=query,
                        time_window=time_window,
                    )
                return CollectorFetcherBridge._run_attempt(
                    source_id, adapter, projected, time_window
                )
            except Exception:  # noqa: BLE001 -- Router 必须接收显式来源失败
                raise CollectorBridgeError(
                    f"collector {source_id} attempt failed"
                ) from None

        return fetcher

    @staticmethod
    def _run_attempt(
        source_id: str,
        adapter: CollectorAdapter,
        query: Dict[str, Any],
        time_window: Dict[str, Optional[str]],
    ) -> Tuple[List[RawItem], FrozenSet[str]]:
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
            return [], frozenset()

        # Foundation 只证明权威 RawItem 契约字段：不读取 ItemRef.extra，不做 data_type
        # alias/source-specific projection。一个字段必须在每条返回记录中都有非空值。
        per_item_fields = []
        for item in normalized_items:
            present = {
                key for key, value in item.model_dump().items()
                if CollectorFetcherBridge._has_authoritative_value(value)
            }
            per_item_fields.append(present)
        fields_present = set.intersection(*per_item_fields)
        return normalized_items, frozenset(fields_present)

    @staticmethod
    def _has_authoritative_value(value: object) -> bool:
        if value is None:
            return False
        if isinstance(value, str):
            return bool(value.strip())
        if isinstance(value, (list, tuple, set, frozenset, dict)):
            return bool(value)
        return True

    @staticmethod
    def _require_source(source_id: str, value: object, boundary: str) -> None:
        actual = getattr(value, "source_id", None)
        if actual != source_id:
            raise CollectorBridgeError(
                f"{boundary} source_id mismatch: expected {source_id!r}, got {actual!r}"
            )


__all__ = ["CollectorBridgeError", "CollectorFetcherBridge"]
