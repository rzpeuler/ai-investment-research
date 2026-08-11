"""Brief Watchlist 只读 Loader（P7-D0 / R1）。

只负责：读取名单、验证格式、过滤 active、按 group 返回、保证稳定排序。
不得采集网页、不得访问网络。watchlist 描述用户要求长期检查谁，
不是 Source Registry（不产生平台级 Source）。
R1-04：content_scope 机器可读内容边界（财联社 = non_fast_news_only）。
R1-05：last_verified_at 未真实验证时必须为 null，不得伪造联网验证时间。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Literal, Optional

import yaml

from pydantic import BaseModel, Field, field_validator

from research_os.utils.time import validate_iso

_ALLOWED_FIELDS = {
    "watch_id", "group", "name", "platform", "source_reference",
    "focus_tags", "active", "priority", "access_mode", "last_verified_at",
    "content_scope", "notes",
}

ContentScope = Literal["all_public_content", "non_fast_news_only", "public_institution_material"]


class WatchlistEntry(BaseModel):
    watch_id: str
    group: str
    name: str
    platform: str
    source_reference: str = ""
    focus_tags: List[str] = Field(default_factory=list)
    active: bool = True
    priority: int = Field(3, ge=1, le=5)
    access_mode: str = "manual_only"
    last_verified_at: Optional[str] = None
    content_scope: ContentScope = "all_public_content"
    notes: str = ""

    model_config = {"extra": "forbid"}

    @field_validator("last_verified_at")
    @classmethod
    def _iso_or_null(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            if not validate_iso(value):
                raise ValueError(f"last_verified_at 必须是合法 ISO-8601 或 null: {value!r}")
        return value


class BriefWatchlistRegistry:
    """Brief Watchlist 注册表：读取并验证 registry/brief_watchlist.yaml。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._entries: List[WatchlistEntry] = []
        self.reload()

    def reload(self) -> None:
        if not self.path.exists():
            raise FileNotFoundError(f"Watchlist 不存在: {self.path}")
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        raw_list = data.get("watchlist") or []
        if not isinstance(raw_list, list):
            raise ValueError("brief_watchlist.yaml 顶层 watchlist 必须是列表")
        entries: List[WatchlistEntry] = []
        seen: set[str] = set()
        for raw in raw_list:
            if not isinstance(raw, dict):
                raise ValueError("每个 watchlist 条目必须是对象")
            unknown = set(raw.keys()) - _ALLOWED_FIELDS
            if unknown:
                raise ValueError(f"watchlist 条目未知字段: {sorted(unknown)}")
            entry = WatchlistEntry.model_validate(raw)
            if entry.watch_id in seen:
                raise ValueError(f"重复 watch_id: {entry.watch_id}")
            seen.add(entry.watch_id)
            entries.append(entry)
        # 稳定排序：group → priority → watch_id
        entries.sort(key=lambda e: (e.group, e.priority, e.watch_id))
        self._entries = entries

    def all(self, active_only: bool = True) -> List[WatchlistEntry]:
        if active_only:
            return [e for e in self._entries if e.active]
        return list(self._entries)

    def by_group(self, group: str, active_only: bool = True) -> List[WatchlistEntry]:
        return [e for e in self.all(active_only=active_only) if e.group == group]

    def groups(self, active_only: bool = True) -> List[str]:
        seen: List[str] = []
        for e in self.all(active_only=active_only):
            if e.group not in seen:
                seen.append(e.group)
        return seen
