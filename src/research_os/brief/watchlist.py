"""Brief Watchlist 只读 Loader（P7-D0）。

只负责：读取名单、验证格式、过滤 active、按 group 返回、保证稳定排序。
不得采集网页、不得访问网络。watchlist 描述用户要求长期检查谁，
不是 Source Registry（不产生平台级 Source）。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from pydantic import BaseModel, Field

_ALLOWED_FIELDS = {
    "watch_id", "group", "name", "platform", "source_reference",
    "focus_tags", "active", "priority", "access_mode", "last_verified_at", "notes",
}


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
    last_verified_at: str = ""
    notes: str = ""

    model_config = {"extra": "forbid"}


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
