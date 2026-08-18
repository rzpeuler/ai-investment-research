"""P7-D3 M2：SourceQueryProjector —— canonical 查询 → 精确来源查询投影层。

职责（任务书 §6-8、§46）：
- 只把 canonical RouteExecutionInput 投影为 source-specific query；
- 纯确定性、无 LLM、无模糊猜测、无联网搜索、无隐式 fallback；
- 未知 (source_id, data_type)、未知组合、映射失败一律 FAIL CLOSED；
- 不修改调用方输入（canonical_query / time_window 只读）；
- 不做来源选择（existing Router 仍是唯一路由权威）。

注册表：精确 key = (source_id, data_type)。
- ("nbs", "macro_data")：不投影任何过滤条件 → {}
- ("cninfo", "company_announcement")：entity_ids → 权威 security 映射 → {"stock": "600519"}

time_window 只做合法性验证与格式转换（不得改变 canonical 窗口权威）。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Mapping, Optional

from research_os.utils.time import validate_iso

_SYMBOL_RE = re.compile(r"^(\d{6})\.(SH|SZ|BJ)$")
# CNINFO 公告查询覆盖沪深交易所；北交所不在本阶段范围
_CNINFO_SUPPORTED_EXCHANGES = {"SH", "SZ"}


class SourceQueryProjectionError(Exception):
    """投影失败（fail closed）。调用方必须显式处理，禁止猜测 / 降级 / best-effort。"""


# entity_id -> symbol("600519.SH") 或 None（权威映射缺失）
SecurityResolver = Callable[[str], Optional[str]]


def _default_security_resolver(db: Any) -> SecurityResolver:
    """基于权威 security_profiles 表的确定性映射（只读）。

    entity_id（company: 前缀）→ SecurityProfile.symbol。匹配 company_entity_id；
    与 EntityMappingChecker._resolve_symbols 同一 authority（R3-02/§22）。
    """

    def resolve(entity_id: str) -> Optional[str]:
        rows = db.query(
            "SELECT payload FROM security_profiles WHERE status IN ('listed', 'suspended')"
        )
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (TypeError, ValueError):
                    continue
            if not isinstance(payload, dict):
                continue
            if str(payload.get("company_entity_id")) == entity_id:
                symbol = payload.get("symbol")
                if isinstance(symbol, str):
                    return symbol
        return None

    return resolve


def _cninfo_stock(symbol: str) -> str:
    """SecurityProfile.symbol（600519.SH）→ CNINFO stock 参数（600519）。

    malformed symbol / 不支持的交易所 → fail closed。
    """
    m = _SYMBOL_RE.fullmatch(symbol)
    if m is None:
        raise SourceQueryProjectionError(f"malformed security symbol: {symbol!r}")
    code, exchange = m.group(1), m.group(2)
    if exchange not in _CNINFO_SUPPORTED_EXCHANGES:
        raise SourceQueryProjectionError(
            f"CNINFO 不支持交易所 {exchange!r}（仅 SH/SZ）: {symbol!r}"
        )
    return code


def _validate_time_window(time_window: Mapping[str, Any]) -> None:
    """time_window 合法性验证（只读，不转换权威窗口）。

    - 必须是 Mapping；
    - start/end 若提供必须是合法 ISO 时间（与项目时间 authority 一致）；
    - end 不得早于 start。
    """
    if not isinstance(time_window, Mapping):
        raise SourceQueryProjectionError(
            f"time_window 必须是 Mapping，得到 {type(time_window).__name__}"
        )
    start = time_window.get("start")
    end = time_window.get("end")
    for name, value in (("start", start), ("end", end)):
        if value is not None and not isinstance(value, str):
            raise SourceQueryProjectionError(
                f"time_window.{name} 必须是字符串或 None，得到 {type(value).__name__}"
            )
        if value is not None and not validate_iso(value):
            raise SourceQueryProjectionError(f"time_window.{name} 非法 ISO 时间: {value!r}")
    if start is not None and end is not None and end < start:
        raise SourceQueryProjectionError(
            f"time_window.end({end!r}) 早于 start({start!r})"
        )


class SourceQueryProjector:
    """canonical RouteExecutionInput → source-specific query 的精确投影器。"""

    def __init__(self, security_resolver: Optional[SecurityResolver] = None):
        self._resolver = security_resolver
        self._registry: Mapping[tuple[str, str], Callable[
            [Mapping[str, Any], Mapping[str, Any]], Mapping[str, Any]
        ]] = {
            ("nbs", "macro_data"): self._project_nbs_macro_data,
            ("cninfo", "company_announcement"): self._project_cninfo_announcement,
        }

    @property
    def registered_pairs(self) -> tuple[tuple[str, str], ...]:
        return tuple(sorted(self._registry))

    def project(
        self,
        *,
        source_id: str,
        data_type: str,
        canonical_query: Mapping[str, Any],
        time_window: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """canonical query → source-specific query。未知组合 fail closed。"""
        impl = self._registry.get((source_id, data_type))
        if impl is None:
            raise SourceQueryProjectionError(
                f"unknown (source_id, data_type): {source_id!r}/{data_type!r}"
            )
        if not isinstance(canonical_query, Mapping):
            raise SourceQueryProjectionError(
                f"canonical_query 必须是 Mapping，得到 {type(canonical_query).__name__}"
            )
        # 只读：绝不修改调用方输入
        return dict(impl(canonical_query, time_window))

    # ---- 已登记投影 ----

    def _project_nbs_macro_data(
        self,
        canonical_query: Mapping[str, Any],
        time_window: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """NBS 宏观数据：不投影任何过滤条件（Collector 按官方列表页抓取）。"""
        _validate_time_window(time_window)
        return {}

    def _project_cninfo_announcement(
        self,
        canonical_query: Mapping[str, Any],
        time_window: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """CNINFO 公告：entity_ids → 权威 security 映射 → stock（6 位代码）。

        - entity_ids 为空 → 全局公告查询（不限定 stock）；
        - 恰好 1 个 entity → 必须唯一映射到受支持交易所的 security，否则 fail closed；
        - 多个 entity → 无法唯一确定 stock → fail closed。
        """
        _validate_time_window(time_window)
        entity_ids = canonical_query.get("entity_ids", [])
        if not isinstance(entity_ids, list) or any(
            not isinstance(v, str) for v in entity_ids
        ):
            raise SourceQueryProjectionError(
                f"canonical_query.entity_ids 必须是字符串列表，得到 {entity_ids!r}"
            )
        if not entity_ids:
            return {}
        if len(entity_ids) != 1:
            raise SourceQueryProjectionError(
                "CNINFO 查询要求恰好 0 或 1 个 entity_id "
                f"（多个无法唯一确定 stock）: {entity_ids!r}"
            )
        entity_id = entity_ids[0]
        if self._resolver is None:
            raise SourceQueryProjectionError(
                "CNINFO 投影需要 security resolver（未注入权威映射）"
            )
        symbol = self._resolver(entity_id)
        if symbol is None:
            raise SourceQueryProjectionError(
                f"entity {entity_id!r} 无权威 security 映射"
            )
        return {"stock": _cninfo_stock(symbol)}
