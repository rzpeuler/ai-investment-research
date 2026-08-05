"""SQLite 存储层：初始化、版本化迁移、核心对象存取。

迁移机制：PRAGMA user_version 记录已应用版本，storage/migrations/ 下按序号
排列的 *.sql 逐个在事务中应用。确定性逻辑（数据库写入）必须使用代码（指南 6.3）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.utils.time import now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# 核心对象 -> 表名 映射
TABLES = {
    "Task": "tasks",
    "Entity": "entities",
    "RawItem": "raw_items",
    "Event": "events",
    "Opinion": "opinions",
    "Claim": "claims",
    "Evidence": "evidence",
    "ModuleResult": "module_results",
    "GraphChange": "graph_changes",
    # Phase 1：来源层
    "Source": "sources",
    "SourceProbe": "source_probes",
    "DataRoute": "data_routes",
    "ManualInbox": "manual_inbox",
}

# 各表主键列名（与 001_initial.sql 保持一致）
PK_COLUMNS = {
    "tasks": "task_id",
    "entities": "entity_id",
    "raw_items": "raw_item_id",
    "events": "event_id",
    "opinions": "opinion_id",
    "claims": "claim_id",
    "evidence": "evidence_id",
    "graph_changes": "graph_change_id",
    "sources": "source_id",
    "source_probes": "probe_id",
    "manual_inbox": "inbox_id",
}


class Database:
    """轻量 SQLite 封装：连接管理 + 迁移 + 对象级 upsert/query。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    # ---------- 迁移 ----------

    def migrations_available(self) -> List[str]:
        """按文件名排序返回全部迁移脚本名（不含扩展名）。"""
        if not MIGRATIONS_DIR.exists():
            return []
        return sorted(
            p.stem for p in MIGRATIONS_DIR.glob("*.sql")
        )

    def current_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def applied_migrations(self) -> List[str]:
        version = self.current_version()
        return self.migrations_available()[:version]

    def migrate(self) -> List[str]:
        """应用全部未应用迁移。返回本次应用的迁移名列表。"""
        available = self.migrations_available()
        applied = self.current_version()
        applied_now: List[str] = []
        for name in available[applied:]:
            script = (MIGRATIONS_DIR / f"{name}.sql").read_text(encoding="utf-8")
            with self._conn:
                self._conn.executescript(script)
                self._conn.execute(f"PRAGMA user_version = {applied + 1}")
            applied_now.append(name)
            applied += 1
        return applied_now

    def initialize(self) -> List[str]:
        """初始化：确保迁移全部应用。返回应用的迁移名列表。"""
        return self.migrate()

    # ---------- 对象存取 ----------

    @staticmethod
    def _extra_columns(obj: Any, now: str) -> Dict[str, Any]:
        """从模型对象提取索引列。"""
        name = type(obj).__name__
        d = obj.model_dump()
        if name == "Task":
            return {"status": d["status"], "scenario": d["scenario"],
                    "created_at": d["requested_at"], "updated_at": now}
        if name == "Entity":
            return {"entity_type": d["entity_type"], "canonical_name": d["canonical_name"],
                    "valid_from": d["valid_from"], "valid_to": d["valid_to"]}
        if name == "RawItem":
            return {"source_id": d["source_id"], "content_hash": d["content_hash"],
                    "published_at": d["published_at"], "retrieved_at": d["retrieved_at"],
                    "access_status": d["access_status"]}
        if name == "Event":
            return {"event_type": d["event_type"], "event_time": d["event_time"], "status": d["status"]}
        if name == "Opinion":
            return {"speaker_entity_id": d["speaker_entity_id"], "stance": d["stance"],
                    "published_at": d["published_at"]}
        if name == "Claim":
            return {"claim_type": d["claim_type"], "review_status": d["review_status"], "as_of": d["as_of"]}
        if name == "Evidence":
            return {"source_id": d["source_id"], "raw_item_id": d["raw_item_id"],
                    "independence_group": d["independence_group"], "source_tier": d["source_tier"]}
        if name == "ModuleResult":
            return {"status": d["status"], "as_of": d["as_of"]}
        if name == "GraphChange":
            return {"change_type": d["change_type"], "review_status": d["review_status"],
                    "created_at": d["created_at"]}
        if name == "Source":
            return {"name": d["name"], "status": d["status"],
                    "last_verified_at": d["last_verified_at"]}
        if name == "SourceProbe":
            return {"source_id": d["source_id"], "status": d["status"],
                    "started_at": d["started_at"], "finished_at": d["finished_at"]}
        if name == "ManualInbox":
            return {"source_name": d["source_name"], "status": d["status"],
                    "submitted_at": d["submitted_at"]}
        raise ValueError(f"未知对象类型: {name}")

    def upsert(self, obj: Any, task_id: Optional[str] = None) -> None:
        """插入或更新核心对象（幂等：相同主键不产生重复行）。

        调用方必须保证 obj 已通过对应 Schema 校验。
        task_id 仅对 ModuleResult 有意义（归属任务）。
        """
        name = type(obj).__name__
        table = TABLES[name]
        d = obj.model_dump()
        payload = json.dumps(d, ensure_ascii=False)
        now = now_iso()
        extra = self._extra_columns(obj, now)

        with self._conn:
            if name in ("ModuleResult", "DataRoute"):
                if name == "ModuleResult":
                    self._conn.execute(
                        "INSERT INTO module_results (task_id, module, payload, status, as_of, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (task_id or "", d["module"], payload, d["status"], d["as_of"], now),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO data_routes (data_type, payload, status, selected_source, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (d["data_type"], payload, d["status"], d.get("selected_source"), now),
                    )
                return

            pk_col = PK_COLUMNS[table]
            pk_value = d[pk_col]
            cols = [c for c in ("payload", *extra.keys())]
            placeholders = ", ".join(f":{c}" for c in cols)
            update_cols = ", ".join(f"{c}=excluded.{c}" for c in cols)
            params = {"payload": payload, **extra}
            sql = (
                f"INSERT INTO {table} ({pk_col}, {', '.join(cols)}) "
                f"VALUES (:{pk_col}, {placeholders}) "
                f"ON CONFLICT({pk_col}) DO UPDATE SET {update_cols}"
            )
            self._conn.execute(sql, {pk_col: pk_value, **params})

    def get(self, table: str, pk_value: str) -> Optional[dict]:
        """按主键读取对象（返回 JSON payload dict）。"""
        pk_col = {"tasks": "task_id", "entities": "entity_id", "raw_items": "raw_item_id",
                  "events": "event_id", "opinions": "opinion_id", "claims": "claim_id",
                  "evidence": "evidence_id", "graph_changes": "graph_change_id",
                  "sources": "source_id", "source_probes": "probe_id",
                  "manual_inbox": "inbox_id"}.get(table)
        if pk_col is None:
            raise ValueError(f"不支持的主键表: {table}")
        row = self._conn.execute(
            f"SELECT payload FROM {table} WHERE {pk_col} = ?", (pk_value,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def query(self, sql: str, params: tuple = ()) -> List[dict]:
        """通用查询，返回 dict 列表。"""
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"])

    def close(self) -> None:
        self._conn.close()
