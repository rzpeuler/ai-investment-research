"""来源注册表（Phase 1 任务 4 节）。

加载 registry/sources.yaml，所有条目必须通过 Source Schema；
提供按 ID/分组/状态查询与更新写回。
"""
from __future__ import annotations

import yaml
from pathlib import Path
from typing import Dict, List, Optional

from research_os.models import Source
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance


class SourceRegistry:
    """来源注册表读写。"""

    def __init__(self, registry_file: str | Path):
        self.path = Path(registry_file)
        self._sources: Dict[str, Source] = {}
        self.reload()

    # ---------- 加载 ----------

    def reload(self) -> None:
        """重新加载注册表（不存在的文件视为空注册表）。"""
        if not self.path.exists():
            self._sources = {}
            return
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        entries = data.get("sources", {})
        loaded: Dict[str, Source] = {}
        for sid, raw in entries.items():
            raw = dict(raw or {})
            raw.pop("source_id", None)  # 以 YAML 键为准
            source = Source(**raw, source_id=sid)
            errors = validate_instance(source.model_dump(), "source")
            if errors:
                raise ValueError(f"来源 {sid} 未通过 Source Schema: {errors}")
            loaded[sid] = source
        self._sources = loaded

    # ---------- 查询 ----------

    def all(self) -> List[Source]:
        return list(self._sources.values())

    def get(self, source_id: str) -> Optional[Source]:
        return self._sources.get(source_id)

    def by_status(self, status: str) -> List[Source]:
        return [s for s in self._sources.values() if s.status == status]

    def by_group(self, source_type: str) -> List[Source]:
        return [s for s in self._sources.values() if s.source_type == source_type]

    def ids(self) -> List[str]:
        return sorted(self._sources.keys())

    # ---------- 更新 ----------

    def update(self, source: Source) -> None:
        """更新单个来源并写回注册表（保持其余条目）。"""
        errors = validate_instance(source.model_dump(), "source")
        if errors:
            raise ValueError(f"来源 {source.source_id} 未通过 Source Schema: {errors}")
        self._sources[source.source_id] = source
        self._write()

    def mark_verified(self, source_id: str, **changes) -> Source:
        """探测后更新来源状态/证据/分数，并写回。"""
        src = self._sources.get(source_id)
        if src is None:
            raise KeyError(f"未登记来源: {source_id}")
        data = src.model_dump()
        data.update(changes)
        data["last_verified_at"] = now_iso()
        updated = Source(**data)
        self.update(updated)
        return updated

    def _write(self) -> None:
        payload = {"sources": {s.source_id: s.model_dump()
                               for s in sorted(self._sources.values(),
                                               key=lambda x: x.source_id)}}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
