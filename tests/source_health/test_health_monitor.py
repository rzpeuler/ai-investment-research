"""来源健康检查测试（Phase 1 任务 11 节 / tests/source_health/）。

全部离线：适配器 healthcheck 使用 mock。
"""
from __future__ import annotations

import pytest

from research_os.collectors import HealthStatus
from research_os.source_health import SourceHealthMonitor
from research_os.source_registry import SourceRegistry
from research_os.storage import Database
from research_os.utils.time import now_iso


class FakeAdapter:
    source_id = "cninfo"
    version = "1.0.0"

    def __init__(self, status: HealthStatus):
        self._status = status

    def healthcheck(self) -> HealthStatus:
        return self._status


@pytest.fixture()
def registry(tmp_path):
    import yaml

    p = tmp_path / "sources.yaml"
    payload = {"sources": {
        "cninfo": {"name": "巨潮", "platform": "cninfo",
                   "base_domain": "http://www.cninfo.com.cn",
                   "source_type": "official_disclosure", "source_tier": "S",
                   "access_level": "public", "automation_level": "html",
                   "status": "candidate"},
        "nosuch": {"name": "无适配器", "platform": "x",
                   "base_domain": "https://x.example",
                   "source_type": "unknown", "source_tier": "D",
                   "access_level": "unknown", "automation_level": "unknown",
                   "status": "candidate"},
    }}
    p.write_text(yaml.safe_dump(payload, allow_unicode=True), encoding="utf-8")
    return SourceRegistry(p)


def _mkdb(tmp_path):
    db = Database(tmp_path / "health.db")
    db.initialize()
    return db


def test_health_check_healthy(registry, tmp_path):
    db = _mkdb(tmp_path)
    adapter = FakeAdapter(HealthStatus(source_id="cninfo", ok=True, access="public",
                                       checked_at=now_iso()))
    monitor = SourceHealthMonitor(registry, {"cninfo": adapter}, db)
    records = monitor.check(["cninfo"])
    assert records[0].status == "healthy"
    db.close()
    # 写入 source_health 表
    import sqlite3

    c2 = sqlite3.connect(tmp_path / "health.db")
    n = c2.execute("SELECT COUNT(*) FROM source_health").fetchone()[0]
    c2.close()
    assert n == 1


def test_health_check_maps_states(registry, tmp_path):
    cases = {
        "public": "healthy",
        "public_but_unstable": "degraded",
        "login_required": "auth_required",
        "unavailable": "unavailable",
        "client_only": "auth_required",
    }
    for access, expected in cases.items():
        db = _mkdb(tmp_path)
        adapter = FakeAdapter(HealthStatus(source_id="x", ok=access == "public",
                                           access=access, checked_at=now_iso()))
        monitor = SourceHealthMonitor(registry, {"cninfo": adapter}, db)
        records = monitor.check(["cninfo"])
        db.close()
        assert records[0].status == expected, f"{access} -> {expected}"


def test_health_check_missing_adapter_unknown(registry, tmp_path):
    db = _mkdb(tmp_path)
    monitor = SourceHealthMonitor(registry, {}, db)
    records = monitor.check(["nosuch"])
    db.close()
    assert records[0].status == "unknown"


def test_health_check_adapter_exception(registry, tmp_path):
    class Boom:
        source_id = "cninfo"

        def healthcheck(self):
            raise RuntimeError("boom")

    db = _mkdb(tmp_path)
    monitor = SourceHealthMonitor(registry, {"cninfo": Boom()}, db)
    records = monitor.check(["cninfo"])
    db.close()
    assert records[0].status == "unavailable"
