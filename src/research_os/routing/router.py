"""主备路由（Phase 1 任务 8.2-8.3 节）。

- 主源失败后才使用备源
- 备源结果不得伪装成主源（attempted_sources / selected_source 如实记录）
- 使用缓存时标明（warnings）
- 最低字段不满足时返回 insufficient_data
- 禁止估算缺失值
- 禁止把空响应解释为"没有事件"（空结果+字段齐全 = success，非"无事件"）

每次数据获取产生 DataRoute（通过 Schema 校验）。
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import AbstractSet, Any, Callable, Dict, FrozenSet, List, Optional, Tuple

from research_os.models import DataRoute
from research_os.routing.requirements import DataRequirementRegistry
from research_os.validators.schema_validator import validate_instance

# fetcher: (data_type, query, time_window) -> (items: list, fields_present: set[str])
FetchCallable = Callable[[str, Dict[str, Any], Dict[str, Optional[str]]],
                         Tuple[List[Any], AbstractSet[str]]]


@dataclass
class RoutedDataBatch:
    """一次既有路由决策及其选中来源数据（非持久化权威对象）。"""

    route: DataRoute
    items: Tuple[Any, ...]
    fields_present: FrozenSet[str]


class Router:
    """数据获取路由：按主备顺序尝试，返回 DataRoute。"""

    def __init__(self, requirements: DataRequirementRegistry,
                 fetchers: Dict[str, FetchCallable],
                 fallback_fetchers: Optional[Dict[str, FetchCallable]] = None):
        self.requirements = requirements
        self.fetchers = fetchers
        self.fallback_fetchers = fallback_fetchers or {}

    def resolve(self, data_type: str, query: Optional[Dict[str, Any]] = None,
                time_window: Optional[Dict[str, Optional[str]]] = None) -> DataRoute:
        """兼容接口：返回既有 DataRoute，语义保持不变。"""
        return self._resolve(
            data_type, query, time_window, snapshot_items=False
        ).route

    def resolve_with_items(
        self,
        data_type: str,
        query: Optional[Dict[str, Any]] = None,
        time_window: Optional[Dict[str, Optional[str]]] = None,
    ) -> RoutedDataBatch:
        """返回路由审计及被选中来源的规范化数据。"""
        return self._resolve(data_type, query, time_window, snapshot_items=True)

    def _resolve(
        self,
        data_type: str,
        query: Optional[Dict[str, Any]],
        time_window: Optional[Dict[str, Optional[str]]],
        *,
        snapshot_items: bool,
    ) -> RoutedDataBatch:
        """唯一主备/兜底路由算法，供两个公开接口共同使用。"""
        req = self.requirements.get(data_type)
        if req is None:
            raise KeyError(f"未登记数据类型: {data_type}")
        query = query or {}
        time_window = time_window or {}

        requested = list(req.primary) + list(req.secondary)
        attempted: List[str] = []
        warnings: List[str] = []
        selected: Optional[str] = None
        fallback_used = False
        items: List[Any] = []
        fields_present: AbstractSet[str] = set()
        last_error: Optional[str] = None

        # 1. 主源 + 备源
        for source_id in list(dict.fromkeys(req.primary + req.secondary)):
            attempted.append(source_id)
            fetcher = self.fetchers.get(source_id)
            if fetcher is None:
                warnings.append(f"{source_id} 无可用获取器")
                continue
            try:
                items, fields_present = fetcher(data_type, query, time_window)
            except Exception as exc:  # noqa: BLE001 —— 失败显式记录并尝试下一个
                last_error = str(exc)
                warnings.append(f"{source_id} 获取失败: {exc}")
                continue
            missing = [f for f in req.minimum_fields if f not in fields_present]
            if missing:
                warnings.append(f"{source_id} 缺最低字段 {missing}")
                continue
            selected = source_id
            break

        # 2. 主备均未成功 -> fallback（人工/导入）
        if selected is None:
            for fb_id in req.fallback:
                attempted.append(fb_id)
                fetcher = self.fallback_fetchers.get(fb_id)
                if fetcher is None:
                    warnings.append(f"{fb_id} 无可用兜底获取器")
                    continue
                try:
                    items, fields_present = fetcher(data_type, query, time_window)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"{fb_id} 兜底失败: {exc}")
                    continue
                missing = [f for f in req.minimum_fields if f not in fields_present]
                if missing:
                    warnings.append(f"{fb_id} 兜底缺最低字段 {missing}")
                    continue
                selected = fb_id
                fallback_used = True
                break

        # 3. 判定状态
        if selected is not None:
            if not items:
                # 空响应 ≠ 无事件：字段齐全但无条目，如实标记
                warnings.append("返回为空结果（不等于无事件，调用方不得据此推断业务无变化）")
            status = "degraded" if fallback_used else "success"
            missing = [f for f in req.minimum_fields if f not in fields_present]
        else:
            missing = [f for f in req.minimum_fields if f not in fields_present]
            status = "insufficient_data" if missing else (
                "failed" if last_error else "insufficient_data"
            )

        route = DataRoute(
            data_type=data_type,
            requested_sources=requested,
            attempted_sources=attempted,
            selected_source=selected,
            fallback_used=fallback_used,
            status=status,
            missing_fields=missing,
            warnings=warnings,
        )
        errs = validate_instance(route.model_dump(), "data_route")
        if errs:
            raise ValueError(f"DataRoute 未通过 Schema 校验: {errs}")
        include_selected_data = selected is not None and snapshot_items
        return RoutedDataBatch(
            route=route.model_copy(deep=True),
            items=tuple(deepcopy(items)) if include_selected_data else (),
            fields_present=(
                frozenset(deepcopy(fields_present))
                if include_selected_data else frozenset()
            ),
        )
