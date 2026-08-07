"""M3 Candidate Repository：GraphChange candidate 专用持久层（insert-only, 不可变）。

核心约束：
- INSERT ONLY，绝不 UPDATE
- 同 graph_change_id + 同 payload → IDEMPOTENT_NOOP
- 同 graph_change_id + 异 payload → IMMUTABLE_CANDIDATE_CONFLICT
- 拒绝 generic Database.upsert(GraphChange)
- GraphChange 从 generic TABLES/PK_COLUMNS 中移除
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, List, Optional

from research_os.models import GraphChange
from research_os.validators.schema_validator import validate_model


class GraphChangeCandidateRepository:
    """GraphChange candidate 不可变持久层。"""

    def __init__(self, db: Any):
        """db 为 Database 实例。"""
        self._db = db

    # ---- canonical JSON ----

    @staticmethod
    def _dump_canonical_json(obj: Any) -> str:
        """确定性紧凑 JSON。"""
        return json.dumps(
            obj.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _validate(graph_change: GraphChange) -> None:
        """Schema 校验。"""
        errors = validate_model(graph_change)
        if errors:
            raise ValueError(
                f"GraphChange Schema validation failed: {'; '.join(errors)}"
            )

    # ---- append_candidate ----

    def append_candidate(
        self,
        graph_change: GraphChange,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """追加 GraphChange candidate（幂等回放 + 不可变冲突）。

        Args:
            graph_change: 完整 GraphChange 实例。
            conn: 可选外部连接（批量事务）。

        Returns:
            "inserted" / "idempotent_noop"

        Raises:
            ValueError: Schema 校验失败 / 不可变冲突。
        """
        self._validate(graph_change)
        payload = self._dump_canonical_json(graph_change)

        def _do(conn: sqlite3.Connection) -> str:
            # 检查是否已存在
            existing = conn.execute(
                "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
                (graph_change.graph_change_id,),
            ).fetchone()

            if existing is not None:
                existing_str = existing["payload"]
                if existing_str == payload:
                    return "idempotent_noop"
                raise ValueError(
                    f"IMMUTABLE_CANDIDATE_CONFLICT: "
                    f"graph_change_id={graph_change.graph_change_id} "
                    f"already exists with different payload"
                )

            # INSERT
            conn.execute(
                """INSERT INTO graph_changes (
                    graph_change_id, payload,
                    change_type, review_status, created_at
                ) VALUES (?, ?, ?, ?, ?)""",
                (
                    graph_change.graph_change_id,
                    payload,
                    graph_change.change_type,
                    graph_change.review_status,
                    graph_change.created_at,
                ),
            )
            return "inserted"

        if conn is not None:
            return _do(conn)
        with self._db.transaction() as tx_conn:
            return _do(tx_conn)

    # ---- 查询 ----

    def get_candidate(self, graph_change_id: str) -> Optional[dict]:
        """按 graph_change_id 读取 candidate。"""
        row = self._db._conn.execute(
            "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
            (graph_change_id,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def count_candidates(self) -> int:
        """返回 graph_changes 总数。"""
        return self._db.count("graph_changes")

    def list_candidates(self) -> List[dict]:
        """列出全部 candidate payload。"""
        rows = self._db._conn.execute(
            "SELECT payload FROM graph_changes ORDER BY created_at DESC"
        ).fetchall()
        return [json.loads(r["payload"]) for r in rows]


# ---- 从 generic upsert 路径中移除 GraphChange ----

def remove_graph_change_from_generic():
    """从 db.py 的 TABLES 和 PK_COLUMNS 中移除 GraphChange 条目。

    此函数通过 patch 修改 db.py，确保 generic Database.upsert(GraphChange) 被机械阻断。
    （实际删除在 db.py patch 中完成）
    """
    pass  # 副作用由 patch db.py 实现
