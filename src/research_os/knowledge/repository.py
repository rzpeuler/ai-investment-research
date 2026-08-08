"""GraphRepository：版本化追加图谱对象到 SQLite（Phase 5 M2 架构评审修正版）。

核心约束：
- graph_nodes / graph_edges 纯追加（INSERT ONLY），绝不 UPDATE。
- 写入前 model_dump → Schema validate → canonical JSON → insert。
- 版本单调：首个版本必须是 1，后续递增 N+1，gap 拒绝。
- 幂等：相同 (id, version) + 相同 payload → IDEMPOTENT_NOOP。
- 不可变：相同 (id, version) + 不同 payload → IMMUTABLE_VERSION_CONFLICT。
- graph_reviews 为 audit trail，同样版本化且记录决策。
- 所有写操作使用事务保证原子性。可传入 conn 复用外部事务。
- canonical JSON 使用 separators(",", ":") 确保紧凑确定性。
- seed 操作全量预检查再事务写入（0 writes 保证）。
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional, Tuple

from research_os.models import GraphNode, GraphEdge, GraphReview
from research_os.validators.schema_validator import validate_model


class GraphRepository:
    """图谱对象版本化持久层（确定性代码，零 LLM）。"""

    def __init__(self, db: Any):
        """db 为 Database 实例。"""
        self._db = db

    # ---- canonical JSON ----

    @staticmethod
    def _dump_canonical_json(obj: Any) -> str:
        """model_dump → 排序键 → 紧凑 JSON（确保幂等比较）。"""
        return json.dumps(
            obj.model_dump(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @staticmethod
    def _validate(obj: Any, schema_name: str) -> None:
        """Schema 校验对象；失败抛出 ValueError。"""
        errors = validate_model(obj)
        if errors:
            raise ValueError(
                f"Schema validation failed for {type(obj).__name__}: {'; '.join(errors)}"
            )

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
            max_row = conn.execute(
                "SELECT MAX(version) AS mv FROM graph_nodes WHERE node_id = ?",
                (node.node_id,),
            ).fetchone()
            max_version = max_row["mv"] if max_row and max_row["mv"] is not None else 0
            if node.version > 1 and max_version == 0:
                raise ValueError(
                    f"VERSION_VIOLATION: node_id={node.node_id} "
                    f"first version must be 1, got version={node.version}"
                )
            if max_version > 0 and node.version != max_version + 1:
                    raise ValueError(
                        f"VERSION_GAP: node_id={node.node_id} "
                        f"existing max version={max_version}, "
                        f"trying to insert version={node.version} (expected {max_version + 1})"
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

            # Version rules: first must be 1, next must be N+1
            max_row = conn.execute(
                "SELECT MAX(version) AS mv FROM graph_edges WHERE edge_id = ?",
                (edge.edge_id,),
            ).fetchone()
            max_version = max_row["mv"] if max_row and max_row["mv"] is not None else 0
            if edge.version > 1 and max_version == 0:
                raise ValueError(
                    f"VERSION_VIOLATION: edge_id={edge.edge_id} "
                    f"first version must be 1, got version={edge.version}"
                )
            if max_version > 0 and edge.version != max_version + 1:
                raise ValueError(
                    f"VERSION_GAP: edge_id={edge.edge_id} "
                    f"existing max version={max_version}, "
                    f"trying to insert version={edge.version} (expected {max_version + 1})"
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

    # ---- edge triple lookup helper (for M3 candidate builder) ----

    def find_edge_by_triple(
        self, source_node_id: str, relation: str, target_node_id: str
    ) -> List[Dict[str, Any]]:
        """按三元组 (source_node_id, relation, target_node_id) 查找边。

        直接在 graph_edges 表中按列查询（非猜测 hash）。
        用于 M3 candidate builder 的 edge identity resolution。

        Returns:
            匹配的边列表（按 version DESC 排序），
            每个元素为 dict 包含 edge_id, version, payload。
            0 条 → fresh edge_id
            >1 条且有多个不同 edge_id → AMBIGUOUS_EDGE_IDENTITY
            version 行（v1, v2 同 edge_id）不算歧义。
        """
        try:
            rows = self._db._conn.execute(
                """SELECT edge_id, version, payload FROM graph_edges
                   WHERE source_node_id = ? AND relation = ? AND target_node_id = ?
                   ORDER BY edge_id, version DESC""",
                (source_node_id, relation, target_node_id),
            ).fetchall()
        except Exception:
            return []

        result: List[Dict[str, Any]] = []
        for row in rows:
            result.append({
                "edge_id": row["edge_id"],
                "version": row["version"],
                "payload": row["payload"],
            })
        return result

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

    # ---- application (M6) ----

    def get_application_by_idempotency_key(self, idempotency_key: str) -> Optional[Dict]:
        """按 idempotency_key 读取 GraphApplication 全部列（strict read）。

        JSON parse failure 直接上抛（M6 strict read path 禁止 fail-open，
        由 engine 转 APPLICATION_INTEGRITY_CONFLICT / APPLICATION_READ_FAILED）。

        Returns:
            {
                "application_id": ...,
                "graph_change_id": ...,
                "review_id": ...,
                "idempotency_key": ...,
                "payload": {...},
                "applied_at": ...,
            }
            或 None（不存在）。
        """
        row = self._db._conn.execute(
            "SELECT application_id, graph_change_id, review_id, "
            "idempotency_key, payload, applied_at "
            "FROM graph_applications WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if row is None:
            return None
        return {
            "application_id": row["application_id"],
            "graph_change_id": row["graph_change_id"],
            "review_id": row["review_id"],
            "idempotency_key": row["idempotency_key"],
            "payload": json.loads(row["payload"]),
            "applied_at": row["applied_at"],
        }

    def get_application_by_identity(self, application_id: str,
                                    idempotency_key: str) -> Optional[Dict]:
        """按双 deterministic identity 查找 GraphApplication（M6 安全路径）。

        语义：
        - 0 rows → None（无 previous application）
        - 1 row → 返回全列 + parsed payload
        - >1 logically conflicting rows（application_id 命中 row A、
          idempotency_key 命中 row B）→ raise ValueError
          （APPLICATION_DUAL_IDENTITY_CONFLICT，audit corruption，
           不得任选其一；由 engine 转 APPLICATION_INTEGRITY_CONFLICT）

        正常 DB 中 application_id 为 PRIMARY KEY、idempotency_key 为 UNIQUE，
        双命中不同行只能来自 SQL 篡改。JSON parse failure 直接上抛。

        Returns:
            全列 dict 或 None。
        Raises:
            ValueError: 双 identity 命中不同行 / JSON parse failure。
        """
        rows = self._db._conn.execute(
            "SELECT application_id, graph_change_id, review_id, "
            "idempotency_key, payload, applied_at "
            "FROM graph_applications "
            "WHERE application_id = ? OR idempotency_key = ?",
            (application_id, idempotency_key),
        ).fetchall()
        if not rows:
            return None
        if len(rows) > 1:
            raise ValueError(
                f"APPLICATION_DUAL_IDENTITY_CONFLICT: application_id={application_id} "
                f"与 idempotency_key={idempotency_key} 命中不同行（audit corruption）"
            )
        row = rows[0]
        return {
            "application_id": row["application_id"],
            "graph_change_id": row["graph_change_id"],
            "review_id": row["review_id"],
            "idempotency_key": row["idempotency_key"],
            "payload": json.loads(row["payload"]),
            "applied_at": row["applied_at"],
        }

    def get_application(self, application_id: str) -> Optional[Dict]:
        """按 application_id 读取 GraphApplication payload。"""
        row = self._db._conn.execute(
            "SELECT payload FROM graph_applications WHERE application_id = ?",
            (application_id,),
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def get_graph_change_type(
        self,
        graph_change_id: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> Optional[str]:
        """strict read：GraphChange.change_type（M7 origin integrity / retire 判定共享）。

        - missing → None
        - DB error / invalid JSON / 顶层非 dict / 无 change_type 字段
          → raise ValueError（strict read 语义，调用方转
          HISTORY_ORIGIN_INTEGRITY_CONFLICT / INCIDENT_EDGE_CHECK_FAILED 等）

        仅读取 change_type 一个字段；完整 schema-first 校验由
        HistoryService._check_origin 负责（本 helper 供 apply 侧判定
        latest edge 是否 retire tombstone 等轻量用途）。
        """
        dbc = conn or self._db._conn
        try:
            row = dbc.execute(
                "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
                (graph_change_id,),
            ).fetchone()
        except Exception as e:
            raise ValueError(
                f"GRAPH_CHANGE_READ_FAILED: DB error reading {graph_change_id}: {e}"
            ) from e
        if row is None:
            return None
        try:
            gc_dict = json.loads(row["payload"])
        except Exception as e:
            raise ValueError(
                f"GRAPH_CHANGE_PAYLOAD_INVALID: {graph_change_id} invalid JSON: {e}"
            ) from e
        if not isinstance(gc_dict, dict):
            raise ValueError(
                f"GRAPH_CHANGE_PAYLOAD_INVALID: {graph_change_id} payload 顶层非 object"
            )
        ct = gc_dict.get("change_type")
        if not isinstance(ct, str) or not ct:
            raise ValueError(
                f"GRAPH_CHANGE_PAYLOAD_INVALID: {graph_change_id} 缺少 change_type"
            )
        return ct

    def append_application(
        self,
        application_id: str,
        graph_change_id: str,
        review_id: str,
        idempotency_key: str,
        payload: Dict[str, Any],
        applied_at: str,
        conn: Optional[sqlite3.Connection] = None,
    ) -> str:
        """追加 GraphApplication（INSERT ONLY，完整 immutable contract）。

        - 已有同 application_id 或同 idempotency_key：
          只有 all columns same（application_id / graph_change_id / review_id /
          idempotency_key / applied_at）AND canonical payload same
          才返回 idempotent_noop；
          否则 IMMUTABLE_APPLICATION_CONFLICT（不得覆盖）。
        - 不得仅比较 payload。

        Args:
            application_id: UUID5 确定性 application ID。
            graph_change_id: effective GraphChange ID（实际被 applied 的）。
            review_id: 关联 GraphReview ID。
            idempotency_key: sha256(canonical intent)。
            payload: GraphApplication internal audit payload dict。
            applied_at: ISO 时间。
            conn: 可选外部连接（用于批量事务）。

        Returns:
            "inserted" / "idempotent_noop"

        Raises:
            ValueError: 不可变冲突。
        """
        canonical_payload = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

        def _row_matches(row) -> bool:
            """all columns + canonical payload 全部一致才算幂等。"""
            return (
                row["application_id"] == application_id
                and row["graph_change_id"] == graph_change_id
                and row["review_id"] == review_id
                and row["idempotency_key"] == idempotency_key
                and row["applied_at"] == applied_at
                and row["payload"] == canonical_payload
            )

        def _do(conn):
            existing = conn.execute(
                "SELECT application_id, graph_change_id, review_id, "
                "idempotency_key, payload, applied_at "
                "FROM graph_applications WHERE application_id = ? OR idempotency_key = ?",
                (application_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                if _row_matches(existing):
                    return "idempotent_noop"
                raise ValueError(
                    f"IMMUTABLE_APPLICATION_CONFLICT: application_id={application_id} "
                    f"/ idempotency_key={idempotency_key} 已存在但 columns/payload 不同"
                )
            conn.execute(
                """INSERT INTO graph_applications (
                    application_id, graph_change_id, review_id,
                    idempotency_key, payload, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    application_id,
                    graph_change_id,
                    review_id,
                    idempotency_key,
                    canonical_payload,
                    applied_at,
                ),
            )
            return "inserted"

        if conn is not None:
            return _do(conn)
        with self._db.transaction() as tx_conn:
            return _do(tx_conn)

    def get_latest_node_version(self, node_id: str) -> Optional[int]:
        """返回 node_id 的最新版本号（无则 None）。"""
        row = self._db._conn.execute(
            "SELECT MAX(version) AS mv FROM graph_nodes WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        if row is None or row["mv"] is None:
            return None
        return int(row["mv"])

    def get_latest_edge_version(self, edge_id: str) -> Optional[int]:
        """返回 edge_id 的最新版本号（无则 None）。"""
        row = self._db._conn.execute(
            "SELECT MAX(version) AS mv FROM graph_edges WHERE edge_id = ?",
            (edge_id,),
        ).fetchone()
        if row is None or row["mv"] is None:
            return None
        return int(row["mv"])

    # ========== seed ==========

    def seed_ontology(
        self,
        nodes: List[GraphNode],
        edges: List[GraphEdge],
        *,
        ontology_id: str,
        ontology_version: int,
        ontology_sha256: str,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """种子入图：全量预检查 → 事务写入（保证 0 写入即滚回）。

        Preflight（在事务之外执行）：
        1. 对每个 node 做 read-only 检查：是否存在、payload 是否一致
        2. 对每个 edge 做 read-only 检查：是否存在、payload 是否一致
        3. 如果任何冲突（相同版本不同 payload），收集所有冲突后抛出（0 writes）

        事务写入（仅非 dry-run）：
        1. 逐 node 执行 append_node
        2. 逐 edge 执行 append_edge
        3. 任何错误滚回全部

        Returns:
            seed summary dict with fields:
            status, dry_run, ontology_id, ontology_version, ontology_sha256,
            nodes_total, edges_total,
            nodes_inserted, edges_inserted,
            nodes_idempotent, edges_idempotent,
            nodes_would_insert, edges_would_insert,
            migration_required, conflicts, db_path
        """
        nodes_total = len(nodes)
        edges_total = len(edges)
        db_path = str(self._db.path)
        conflicts: List[str] = []

        # ---- Check for migration readiness FIRST ----
        migration_required = False
        tables_exist = False
        try:
            conn = self._db._conn
            ver_row = conn.execute("PRAGMA user_version").fetchone()
            db_version = int(ver_row[0]) if ver_row else 0
            if db_version < 6:
                migration_required = True
            else:
                # Confirm the graph tables exist
                check = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_nodes'"
                ).fetchone()
                if check is None:
                    migration_required = True
                else:
                    tables_exist = True
        except Exception:
            migration_required = True

        # ---- Preflight: check all nodes ----
        preflight_nodes_inserted = 0
        preflight_nodes_idempotent = 0

        if tables_exist:
            for node in nodes:
                payload = self._dump_canonical_json(node)
                existing = self.get_node_version(node.node_id, node.version)
                if existing is None:
                    preflight_nodes_inserted += 1
                else:
                    existing_payload = json.dumps(
                        existing,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if existing_payload == payload:
                        preflight_nodes_idempotent += 1
                    else:
                        conflicts.append(
                            f"node {node.node_id} v{node.version}: "
                            f"IMMUTABLE_VERSION_CONFLICT (existing payload differs)"
                        )
        else:
            preflight_nodes_inserted = nodes_total

        # ---- Preflight: check all edges ----
        preflight_edges_inserted = 0
        preflight_edges_idempotent = 0

        if tables_exist:
            for edge in edges:
                payload = self._dump_canonical_json(edge)
                existing = self.get_edge_version(edge.edge_id, edge.version)
                if existing is None:
                    preflight_edges_inserted += 1
                else:
                    existing_payload = json.dumps(
                        existing,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    if existing_payload == payload:
                        preflight_edges_idempotent += 1
                    else:
                        conflicts.append(
                            f"edge {edge.edge_id} v{edge.version}: "
                            f"IMMUTABLE_VERSION_CONFLICT (existing payload differs)"
                        )
        else:
            preflight_edges_inserted = edges_total

        # ---- Build summary ----
        summary = {
            "status": "dry_run" if dry_run else "ok",
            "dry_run": dry_run,
            "ontology_id": ontology_id,
            "ontology_version": ontology_version,
            "ontology_sha256": ontology_sha256,
            "nodes_total": nodes_total,
            "edges_total": edges_total,
            "nodes_inserted": 0,
            "edges_inserted": 0,
            "nodes_idempotent": 0,
            "edges_idempotent": 0,
            "nodes_would_insert": preflight_nodes_inserted,
            "edges_would_insert": preflight_edges_inserted,
            "migration_required": migration_required,
            "conflicts": conflicts,
            "db_path": db_path,
        }

        # ---- If conflicts exist, fail before any writes ----
        if conflicts:
            summary["status"] = "conflict"
            raise ValueError(
                "Seed preflight found immutable conflicts:\n" + "\n".join(conflicts)
            )

        # ---- Dry-run: return summary without writes ----
        if dry_run:
            return summary

        # ---- Transaction: write everything ----
        nodes_inserted = 0
        nodes_idempotent = 0
        edges_inserted = 0
        edges_idempotent = 0
        write_errors: List[str] = []

        with self._db.transaction() as conn:
            for i, node in enumerate(nodes):
                try:
                    result = self.append_node(node, conn=conn)
                    if result == "inserted":
                        nodes_inserted += 1
                    else:
                        nodes_idempotent += 1
                except ValueError as exc:
                    write_errors.append(f"nodes[{i}] {node.node_id}: {exc}")

            if write_errors:
                raise ValueError(
                    "写入失败，事务已回滚。错误:\n" + "\n".join(write_errors)
                )

            for i, edge in enumerate(edges):
                try:
                    result = self.append_edge(edge, conn=conn)
                    if result == "inserted":
                        edges_inserted += 1
                    else:
                        edges_idempotent += 1
                except ValueError as exc:
                    write_errors.append(f"edges[{i}] {edge.edge_id}: {exc}")

            if write_errors:
                raise ValueError(
                    "写入失败，事务已回滚。错误:\n" + "\n".join(write_errors)
                )

        summary["nodes_inserted"] = nodes_inserted
        summary["edges_inserted"] = edges_inserted
        summary["nodes_idempotent"] = nodes_idempotent
        summary["edges_idempotent"] = edges_idempotent
        summary["nodes_would_insert"] = 0  # already written
        summary["edges_would_insert"] = 0
        return summary
