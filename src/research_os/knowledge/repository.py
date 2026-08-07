"""GraphRepository：版本化追加图谱对象到 SQLite（Phase 5 M2 任务书 29 节）。

核心约束：
- graph_nodes / graph_edges 纯追加（INSERT ONLY），绝不 UPDATE。
- 写入前 model_dump → Schema validate → canonical JSON → insert。
- 版本单调：首个版本必须是 1，后续递增 N+1，gap 拒绝。
- 幂等：相同 (id, version) + 相同 payload → IDEMPOTENT_NOOP。
- 不可变：相同 (id, version) + 不同 payload → IMMUTABLE_VERSION_CONFLICT。
- graph_reviews 为 audit trail，同样版本化且记录决策。
- 所有写操作使用事务保证原子性。可传入 conn 复用外部事务。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, Optional

from research_os.models import GraphNode, GraphEdge, GraphReview
from research_os.validators.schema_validator import validate_model


class GraphRepository:
    """图谱对象版本化持久层（确定性代码，零 LLM）。"""

    def __init__(self, db: Any):
        """db 为 Database 实例。"""
        self._db = db

    # ---- node ----

    def append_node(self, node: GraphNode, conn: Optional[sqlite3.Connection] = None) -> str:
        """追加节点（版本化只增不覆盖）。

        Args:
            node: GraphNode 实例。
            conn: 可选外部连接（用于批量事务）。若为 None，方法自行管理事务。

        Returns:
            操作描述字符串："inserted" / "idempotent_noop"。
        Raises:
            ValueError: Schema 校验失败 / 版本规则违反 / 不可变版本冲突。
        """
        self._validate(node, "graph_node")
        payload = self._dump_canonical_json(node)

        def _do(conn):
            existing = conn.execute(
                "SELECT payload FROM graph_nodes WHERE node_id = ? AND version = ?",
                (node.node_id, node.version),
            ).fetchone()

            if existing is not None:
                existing_str = existing["payload"]
                if existing_str == payload:
                    return "idempotent_noop"
                raise ValueError(
                    f"IMMUTABLE_VERSION_CONFLICT: node_id={node.node_id} "
                    f"version={node.version} already exists with different payload"
                )

            # Version rules: first must be 1, next must be N+1
            if node.version > 1:
                max_row = conn.execute(
                    "SELECT MAX(version) AS mv FROM graph_nodes WHERE node_id = ?",
                    (node.node_id,),
                ).fetchone()
                max_version = max_row["mv"] if max_row and max_row["mv"] is not None else 0
                if node.version != max_version + 1:
                    raise ValueError(
                        f"VERSION_GAP: node_id={node.node_id} "
                        f"existing max version={max_version}, "
                        f"trying to insert version={node.version} (expected {max_version + 1})"
                    )
            elif node.version == 1:
                exists = conn.execute(
                    "SELECT 1 FROM graph_nodes WHERE node_id = ?", (node.node_id,)
                ).fetchone()
                if exists:
                    raise ValueError(
                        f"VERSION_VIOLATION: node_id={node.node_id} "
                        f"first version must be 1 but a record already exists"
                    )

            conn.execute(
                """INSERT INTO graph_nodes (
                    node_id, version, payload, node_type, name, status,
                    review_status, origin_kind, created_at,
                    valid_from, valid_to, last_reviewed_at, originating_graph_change_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    node.node_id, node.version, payload,
                    node.node_type, node.name, node.status,
                    node.review_status, node.origin_kind, node.created_at,
                    node.valid_from, node.valid_to,
                    node.last_reviewed_at, node.originating_graph_change_id,
                ),
            )
            return "inserted"

        if conn is not None:
            return _do(conn)
        with self._db.transaction() as tx_conn:
            return _do(tx_conn)

    def get_node_version(self, node_id: str, version: int) -> Optional[Dict]:
        """按 node_id + version 读取节点。"""
        row = self._db._conn.execute(
            "SELECT payload FROM graph_nodes WHERE node_id = ? AND version = ?",
            (node_id, version),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def count_nodes(self) -> int:
        """返回 graph_nodes 总行数（所有版本）。"""
        return self._db.count("graph_nodes")

    # ---- edge ----

    def append_edge(self, edge: GraphEdge, conn: Optional[sqlite3.Connection] = None) -> str:
        """追加关系（版本化只增不覆盖）。

        Args:
            edge: GraphEdge 实例。
            conn: 可选外部连接（用于批量事务）。若为 None，方法自行管理事务。

        Returns:
            操作描述字符串："inserted" / "idempotent_noop"。
        Raises:
            ValueError: Schema 校验失败 / 版本规则违反 / 不可变版本冲突。
        """
        self._validate(edge, "graph_edge")
        payload = self._dump_canonical_json(edge)

        def _do(conn):
            existing = conn.execute(
                "SELECT payload FROM graph_edges WHERE edge_id = ? AND version = ?",
                (edge.edge_id, edge.version),
            ).fetchone()

            if existing is not None:
                existing_str = existing["payload"]
                if existing_str == payload:
                    return "idempotent_noop"
                raise ValueError(
                    f"IMMUTABLE_VERSION_CONFLICT: edge_id={edge.edge_id} "
                    f"version={edge.version} already exists with different payload"
                )

            # Version rules
            if edge.version > 1:
                max_row = conn.execute(
                    "SELECT MAX(version) AS mv FROM graph_edges WHERE edge_id = ?",
                    (edge.edge_id,),
                ).fetchone()
                max_version = max_row["mv"] if max_row and max_row["mv"] is not None else 0
                if edge.version != max_version + 1:
                    raise ValueError(
                        f"VERSION_GAP: edge_id={edge.edge_id} "
                        f"existing max version={max_version}, "
                        f"trying to insert version={edge.version} (expected {max_version + 1})"
                    )
            elif edge.version == 1:
                exists = conn.execute(
                    "SELECT 1 FROM graph_edges WHERE edge_id = ?", (edge.edge_id,)
                ).fetchone()
                if exists:
                    raise ValueError(
                        f"VERSION_VIOLATION: edge_id={edge.edge_id} "
                        f"first version must be 1 but a record already exists"
                    )

            conn.execute(
                """INSERT INTO graph_edges (
                    edge_id, version, payload,
                    source_node_id, relation, target_node_id,
                    assertion_type, review_status, created_at,
                    valid_from, valid_to, confidence,
                    last_reviewed_at, originating_graph_change_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    edge.edge_id, edge.version, payload,
                    edge.source_node_id, edge.relation, edge.target_node_id,
                    edge.assertion_type, edge.review_status, edge.created_at,
                    edge.valid_from, edge.valid_to, edge.confidence,
                    edge.last_reviewed_at, edge.originating_graph_change_id,
                ),
            )
            return "inserted"

        if conn is not None:
            return _do(conn)
        with self._db.transaction() as tx_conn:
            return _do(tx_conn)

    def get_edge_version(self, edge_id: str, version: int) -> Optional[Dict]:
        """按 edge_id + version 读取关系。"""
        row = self._db._conn.execute(
            "SELECT payload FROM graph_edges WHERE edge_id = ? AND version = ?",
            (edge_id, version),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def count_edges(self) -> int:
        """返回 graph_edges 总行数（所有版本）。"""
        return self._db.count("graph_edges")

    # ---- review ----

    def append_review(self, review: GraphReview, conn: Optional[sqlite3.Connection] = None) -> str:
        """追加审核记录。

        Args:
            review: GraphReview 实例。
            conn: 可选外部连接（用于批量事务）。若为 None，方法自行管理事务。

        Returns:
            操作描述字符串："inserted" / "idempotent_noop"。
        Raises:
            ValueError: Schema 校验失败 / 不可变冲突。
        """
        self._validate(review, "graph_review")
        payload = self._dump_canonical_json(review)

        def _do(conn):
            existing = conn.execute(
                "SELECT payload FROM graph_reviews WHERE review_id = ?",
                (review.review_id,),
            ).fetchone()

            if existing is not None:
                existing_str = existing["payload"]
                if existing_str == payload:
                    return "idempotent_noop"
                raise ValueError(
                    f"IMMUTABLE_REVIEW_CONFLICT: review_id={review.review_id} "
                    f"already exists with different payload"
                )

            conn.execute(
                """INSERT INTO graph_reviews (
                    review_id, payload, graph_change_id, decision,
                    reviewer_id, reviewed_at, candidate_hash, resulting_graph_change_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    review.review_id, payload,
                    review.graph_change_id, review.decision,
                    review.reviewer.reviewer_id, review.reviewed_at,
                    review.candidate_hash, review.resulting_graph_change_id,
                ),
            )
            return "inserted"

        if conn is not None:
            return _do(conn)
        with self._db.transaction() as tx_conn:
            return _do(tx_conn)

    def get_review(self, review_id: str) -> Optional[Dict]:
        """按 review_id 读取审核记录。"""
        row = self._db._conn.execute(
            "SELECT payload FROM graph_reviews WHERE review_id = ?",
            (review_id,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    # ---- helpers ----

    @staticmethod
    def _validate(obj: Any, schema_name: str) -> None:
        """Schema 校验对象；失败抛出 ValueError。"""
        errors = validate_model(obj)
        if errors:
            raise ValueError(
                f"Schema validation failed for {type(obj).__name__}: {'; '.join(errors)}"
            )

    @staticmethod
    def _dump_canonical_json(obj: Any) -> str:
        """model_dump → 排序键 → 紧凑 JSON（确保幂等比较）。"""
        return json.dumps(obj.model_dump(), ensure_ascii=False, sort_keys=True)
