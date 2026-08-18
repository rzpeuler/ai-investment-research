"""P7-D3 M3：Canonical Field Projection —— RawItem → DataRequirement minimum-field evidence。

职责（任务书 §9-10、§21）：
- 精确注册表 key = (source_id, data_type, raw_category)；
- 只把 RawItem 的 canonical 字段投影为 data_type 的 minimum-field evidence
  （如 NBS: published_at → publish_date；CNINFO: publisher(=secName) → company）；
- 确定性、无 LLM、无模糊别名、无任意 source metadata 提升；
- 不修改 RawItem（输入只读）；
- 来源身份保留（source_id 不变）；
- 投影血缘可审计（记录 source/data_type/raw_category/来源字段）；
- 未知组合：FAIL CLOSED，禁止字段名猜测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Tuple

# 精确注册表 key 类型：(source_id, data_type, raw_category)
_Projector = Callable[[Mapping[str, Any]], Mapping[str, Any]]


class FieldProjectionError(Exception):
    """字段投影失败（fail closed）。调用方必须显式处理，禁止猜测 / 降级。"""


@dataclass(frozen=True)
class FieldProjection:
    """一次可审计的字段投影结果。"""

    source_id: str
    data_type: str
    raw_category: str
    evidence: Mapping[str, Any]          # {"publish_date": ...} 或 {"company": ...}
    source_fields: Tuple[str, ...]       # 投影输入字段（RawItem canonical 字段名）

    @property
    def evidence_fields(self) -> Tuple[str, ...]:
        return tuple(self.evidence)


class FieldProjector:
    """exact canonical field projection registry。"""

    def __init__(self) -> None:
        self._registry: Mapping[Tuple[str, str, str], _Projector] = {
            ("nbs", "macro_data", "statistics_release"): _project_nbs_macro_data,
            ("cninfo", "company_announcement", "announcement"): _project_cninfo_announcement,
        }

    @property
    def registered_keys(self) -> Tuple[Tuple[str, str, str], ...]:
        return tuple(sorted(self._registry))

    def project(
        self,
        *,
        source_id: str,
        data_type: str,
        raw_category: str,
        fields: Mapping[str, Any],
    ) -> FieldProjection:
        """RawItem 字段 → canonical evidence。

        - 未知 (source_id, data_type, raw_category) → FAIL CLOSED；
        - 输入只读，绝不修改调用方 RawItem 字段。
        """
        key = (source_id, data_type, raw_category)
        impl = self._registry.get(key)
        if impl is None:
            raise FieldProjectionError(
                f"unknown projection key: {source_id!r}/{data_type!r}/{raw_category!r}"
            )
        if not isinstance(fields, Mapping):
            raise FieldProjectionError(
                f"fields 必须是 Mapping，得到 {type(fields).__name__}"
            )
        evidence = dict(impl(fields))
        source_fields = _source_fields(impl, fields)
        return FieldProjection(
            source_id=source_id,
            data_type=data_type,
            raw_category=raw_category,
            evidence=evidence,
            source_fields=source_fields,
        )


def _source_fields(impl: _Projector, fields: Mapping[str, Any]) -> Tuple[str, ...]:
    """记录投影输入字段（可审计血缘）。"""
    if impl is _project_nbs_macro_data:
        return ("published_at",) if fields.get("published_at") else ()
    if impl is _project_cninfo_announcement:
        return ("publisher",) if fields.get("publisher") else ()
    return ()


def _project_nbs_macro_data(fields: Mapping[str, Any]) -> Mapping[str, Any]:
    """NBS 宏观数据：published_at → publish_date（严格同值投影，不做格式改写）。"""
    published_at = fields.get("published_at")
    if not published_at or not isinstance(published_at, str) or not published_at.strip():
        raise FieldProjectionError(
            "NBS macro_data 投影需要非空 published_at（禁止伪造值）"
        )
    return {"publish_date": published_at}


def _project_cninfo_announcement(fields: Mapping[str, Any]) -> Mapping[str, Any]:
    """CNINFO 公告：publisher（=已验证的 secName 公司主体）→ company。"""
    publisher = fields.get("publisher")
    if not publisher or not isinstance(publisher, str) or not publisher.strip():
        raise FieldProjectionError(
            "CNINFO company_announcement 投影需要非空 publisher（禁止伪造值）"
        )
    return {"company": publisher}


__all__ = [
    "FieldProjection",
    "FieldProjectionError",
    "FieldProjector",
]
