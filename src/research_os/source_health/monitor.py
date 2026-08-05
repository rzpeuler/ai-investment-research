"""来源健康检查（Phase 1 任务 7.4 节）。

状态枚举：healthy / degraded / blocked / auth_required / rate_limited /
schema_changed / unavailable / unknown。

对注册表中已登记的来源调用适配器 healthcheck，结果写入 source_health 表。
健康检查不抓取内容，只做可达性/结构探测。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from research_os.collectors import CollectorAdapter, HealthStatus
from research_os.source_registry import SourceRegistry
from research_os.storage import Database
from research_os.utils.time import now_iso

# 适配器健康状态 -> 项目健康状态映射
_HEALTH_MAP = {
    "public": "healthy",
    "public_but_unstable": "degraded",
    "login_required": "auth_required",
    "client_only": "auth_required",
    "paid": "blocked",
    "manual_only": "unknown",
    "unavailable": "unavailable",
    "unknown": "unknown",
}


@dataclass
class HealthRecord:
    """单条健康检查记录（入库前）。"""

    source_id: str
    status: str
    payload: dict
    checked_at: str


class SourceHealthMonitor:
    """来源健康检查器。"""

    def __init__(self, registry: SourceRegistry, adapters: Dict[str, CollectorAdapter],
                 db: Database):
        self.registry = registry
        self.adapters = adapters
        self.db = db

    def check(self, source_ids: Optional[List[str]] = None) -> List[HealthRecord]:
        """检查指定来源（默认：注册表中已登记且存在适配器的来源）。"""
        ids = source_ids or [s.source_id for s in self.registry.all()
                             if s.source_id in self.adapters]
        records: List[HealthRecord] = []
        for sid in ids:
            adapter = self.adapters.get(sid)
            if adapter is None:
                record = HealthRecord(
                    source_id=sid, status="unknown",
                    payload={"ok": False, "message": "无适配器"},
                    checked_at=now_iso(),
                )
            else:
                try:
                    status: HealthStatus = adapter.healthcheck()
                except Exception as exc:  # noqa: BLE001
                    record = HealthRecord(
                        source_id=sid, status="unavailable",
                        payload={"ok": False, "message": f"健康检查异常: {exc}"},
                        checked_at=now_iso(),
                    )
                    self._store(record)
                    records.append(record)
                    continue
                mapped = _HEALTH_MAP.get(status.access, "unknown")
                record = HealthRecord(
                    source_id=sid, status=mapped,
                    payload=status.model_dump(),
                    checked_at=status.checked_at or now_iso(),
                )
            self._store(record)
            records.append(record)
        return records

    def _store(self, record: HealthRecord) -> None:
        self.db._conn.execute(
            "INSERT INTO source_health (source_id, payload, status, checked_at) "
            "VALUES (?, ?, ?, ?)",
            (record.source_id, __import__("json").dumps(record.payload, ensure_ascii=False),
             record.status, record.checked_at),
        )
        self.db._conn.commit()
