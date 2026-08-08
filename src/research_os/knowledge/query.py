"""M8 Deterministic Graph Query Service：single identity query + depth-limited traversal。

零 LLM / 零 Provider / 零 network。只读（READ ONLY）。

冻结语义（Decision #38，2026-08-08）：
- as_of 必填（BUSINESS VALIDITY TIME，完全继承 M7 半开区间 / derived lifecycle）
- HistoryService 是 lifecycle 唯一 authority（resolve_* 委托，禁止第二套算法）
- read snapshot：一次 public call = 一个连接 + 显式 BEGIN + 全部 SELECT + ROLLBACK
- resolve-then-traverse 是唯一合法查询模型
- depth ∈ {0,1,2}（edge-hop；root depth=0；一条 edge 增加一跳）
- incident-edge identity discovery 双源（denormalized columns UNION payload，json_valid guard）
- fail-closed：任何 strict read 失败 → 整查询失败（QUERY_*），禁止 silent skip / partial result
- 合法生命周期状态（expired / retired / not_yet_valid / knowledge gap）不是 corruption
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from research_os.knowledge.history import HistoryError, HistoryService
from research_os.knowledge.repository import GraphRepository
from research_os.utils.time import parse_iso

# 硬上限（Decision #38.5.25）：达到上限 → QUERY_RESULT_LIMIT_EXCEEDED 整查询失败
MAX_NODES = 200
MAX_EDGES = 500
MAX_EVIDENCE = 1000

_VALID_DIRECTIONS = ("outgoing", "incoming", "both")
_VALID_ASSERTION_TYPES = ("GOVERNANCE", "FACT", "MODEL_INFERENCE")
_VALID_RELATIONS = (
    "BELONGS_TO", "UPSTREAM_OF", "DOWNSTREAM_OF", "SUPPLIES", "PURCHASES_FROM",
    "PRODUCES", "USES_TECHNOLOGY", "APPLIED_IN", "COMPETES_WITH", "SUBSTITUTES",
    "BENEFITS_FROM", "HARMED_BY", "AFFECTS", "MENTIONED_IN", "SUPPORTED_BY",
    "CONTRADICTED_BY", "HAS_METRIC", "HAS_CATALYST",
)

# HistoryError → QUERY namespace（Decision #38.7.34）
_HISTORY_PAYLOAD_CODES = ("HISTORY_PAYLOAD_INVALID", "HISTORY_SCHEMA_INVALID")
_HISTORY_ERROR_MAP = {
    "HISTORY_READ_FAILED": "QUERY_READ_FAILED",
    "HISTORY_INTEGRITY_CONFLICT": "QUERY_INTEGRITY_CONFLICT",
    "HISTORY_VERSION_GAP": "QUERY_VERSION_GAP",
    "HISTORY_INTERVAL_INVALID": "QUERY_INTERVAL_INVALID",
    "HISTORY_ORIGIN_INTEGRITY_CONFLICT": "QUERY_ORIGIN_INTEGRITY_CONFLICT",
    "HISTORY_AS_OF_REQUIRED": "QUERY_AS_OF_REQUIRED",
    "HISTORY_AS_OF_INVALID": "QUERY_AS_OF_INVALID",
}


class QueryError(Exception):
    """M8 query/context 统一 public failure（error_code 精确机械 code）。"""

    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


@dataclass(frozen=True)
class QueryObjectResult:
    """direct identity query 结果（inspection API，返回 M7 resolved result）。"""

    kind: str  # "node" | "edge"
    identity: str
    as_of: str
    version: int
    derived_status: str
    is_active: bool
    payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "identity": self.identity,
            "as_of": self.as_of,
            "version": self.version,
            "derived_status": self.derived_status,
            "is_active": self.is_active,
            "payload": self.payload,
        }


class QueryNodeResult(QueryObjectResult):
    """single node query 结果（kind="node"）。"""

    def __init__(self, identity: str, as_of: str, version: int,
                 derived_status: str, is_active: bool, payload: Dict[str, Any]):
        super().__init__("node", identity, as_of, version, derived_status,
                         is_active, payload)


class QueryEdgeResult(QueryObjectResult):
    """single edge query 结果（kind="edge"）。"""

    def __init__(self, identity: str, as_of: str, version: int,
                 derived_status: str, is_active: bool, payload: Dict[str, Any]):
        super().__init__("edge", identity, as_of, version, derived_status,
                         is_active, payload)


@dataclass(frozen=True)
class QueryGraphResult:
    """depth-limited traversal 输出（deterministic dataclass，不持久化）。"""

    as_of: str
    root: Dict[str, Any]
    max_depth: int
    query_parameters: Dict[str, Any]
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    epistemic: Dict[str, List[str]] = field(default_factory=dict)
    evidence_ids: List[str] = field(default_factory=list)
    limitations: List[Dict[str, str]] = field(default_factory=list)
    conflicts: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "root": self.root,
            "max_depth": self.max_depth,
            "query_parameters": self.query_parameters,
            "nodes": self.nodes,
            "edges": self.edges,
            "epistemic": self.epistemic,
            "evidence_ids": self.evidence_ids,
            "limitations": self.limitations,
            "conflicts": self.conflicts,
        }


def _node_wrapper(depth: int, resolved: Dict[str, Any]) -> Dict[str, Any]:
    payload = resolved["payload"]
    return {
        "depth": depth,
        "node_id": payload["node_id"],
        "version": resolved["version"],
        "derived_status": resolved["derived_status"],
        "is_active": resolved["is_active"],
        "payload": payload,
    }


def _edge_wrapper(depth: int, resolved: Dict[str, Any]) -> Dict[str, Any]:
    payload = resolved["payload"]
    return {
        "depth": depth,
        "edge_id": payload["edge_id"],
        "version": resolved["version"],
        "derived_status": resolved["derived_status"],
        "is_active": resolved["is_active"],
        "payload": payload,
    }


class GraphQueryService:
    """M8 确定性图谱查询服务（零 LLM，READ ONLY）。

    与 HistoryService 共享同一 Database 实例（同一连接），保证 read snapshot
    覆盖 graph/history/origin 全部读取。
    """

    def __init__(self, db: Any, graph_repo: Optional[GraphRepository] = None,
                 history: Optional[HistoryService] = None):
        self._db = db
        self._graph_repo = graph_repo or GraphRepository(db)
        self._history = history or HistoryService(db, self._graph_repo)

    # ── public API ──────────────────────────────────────────

    def get_node(self, node_id: str, as_of: str) -> QueryNodeResult:
        """direct node inspection（as_of 必填；inactive 不伪装 NOT_FOUND）。"""
        as_of = self._validate_as_of(as_of)
        with self._snapshot() as conn:
            resolved = self._resolve_node(node_id, as_of, conn)
            if resolved is None:
                raise QueryError(
                    "QUERY_NODE_NOT_FOUND", f"node {node_id} 不存在")
            return QueryNodeResult(
                identity=node_id, as_of=as_of, version=resolved["version"],
                derived_status=resolved["derived_status"],
                is_active=resolved["is_active"], payload=resolved["payload"])

    def get_edge(self, edge_id: str, as_of: str) -> QueryEdgeResult:
        """direct edge inspection（as_of 必填；inactive 不伪装 NOT_FOUND）。"""
        as_of = self._validate_as_of(as_of)
        with self._snapshot() as conn:
            resolved = self._resolve_edge(edge_id, as_of, conn)
            if resolved is None:
                raise QueryError(
                    "QUERY_EDGE_NOT_FOUND", f"edge {edge_id} 不存在")
            return QueryEdgeResult(
                identity=edge_id, as_of=as_of, version=resolved["version"],
                derived_status=resolved["derived_status"],
                is_active=resolved["is_active"], payload=resolved["payload"])

    def query_graph(
        self,
        root_node_id: str,
        as_of: str,
        *,
        max_depth: int = 1,
        relation_filters: Optional[Sequence[str]] = None,
        direction: str = "both",
        assertion_types: Optional[Sequence[str]] = None,
    ) -> QueryGraphResult:
        """depth-limited traversal（resolve-then-traverse，唯一合法模型）。"""
        as_of = self._validate_as_of(as_of)
        max_depth = self._validate_depth(max_depth)
        relation_filters = self._validate_relations(relation_filters)
        direction = self._validate_direction(direction)
        assertion_types = self._validate_assertion_types(assertion_types)
        with self._snapshot() as conn:
            return self._query_graph_locked(
                conn, root_node_id, as_of, max_depth=max_depth,
                relation_filters=relation_filters, direction=direction,
                assertion_types=assertion_types)

    # ── read snapshot（Decision #38.3.10/38.3.11）───────────

    @contextmanager
    def _snapshot(self) -> Iterator[sqlite3.Connection]:
        """一个 public call = 一个连接 + 显式 BEGIN + 全部 SELECT + ROLLBACK。

        只读事务成功读完也用 ROLLBACK 关闭（零写）。
        """
        conn = self._db._conn
        if conn.in_transaction:
            raise QueryError(
                "QUERY_ACTIVE_TRANSACTION_CONFLICT",
                "M8 query 不得 commit/rollback 调用者已有事务")
        try:
            conn.execute("BEGIN")
        except Exception as e:
            raise QueryError(
                "QUERY_READ_FAILED", f"read snapshot BEGIN failed: {e}") from e
        try:
            yield conn
            self._close_snapshot(conn)
        except QueryError:
            self._close_snapshot(conn)
            raise
        except Exception as e:
            self._close_snapshot(conn)
            raise QueryError(
                "QUERY_READ_FAILED", f"query failed: {e}") from e

    @staticmethod
    def _close_snapshot(conn: sqlite3.Connection) -> None:
        """关闭只读事务；cleanup 失败必须传播结构化 query failure。"""
        try:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
        except Exception as e:
            raise QueryError(
                "QUERY_READ_FAILED",
                f"read snapshot cleanup failed: {e}") from e

    # ── parameter validation（fail fast，snapshot 外）───────

    @staticmethod
    def _validate_as_of(as_of: Optional[str]) -> str:
        if as_of is None:
            raise QueryError(
                "QUERY_AS_OF_REQUIRED",
                "as_of 必须显式提供（禁止默认 now()）")
        try:
            parse_iso(as_of)
        except ValueError as e:
            raise QueryError(
                "QUERY_AS_OF_INVALID", f"as_of 非法 ISO: {e}") from e
        return as_of

    @staticmethod
    def _validate_depth(max_depth: int) -> int:
        if isinstance(max_depth, bool) or not isinstance(max_depth, int):
            raise QueryError(
                "QUERY_DEPTH_INVALID", f"max_depth 必须是整数: {max_depth!r}")
        if max_depth < 0:
            raise QueryError(
                "QUERY_DEPTH_INVALID", f"max_depth 不能为负: {max_depth}")
        if max_depth > 2:
            raise QueryError(
                "QUERY_DEPTH_EXCEEDED",
                f"Phase5 第一版 max_depth 硬上限为 2，got {max_depth}")
        return max_depth

    @staticmethod
    def _validate_direction(direction: str) -> str:
        if direction not in _VALID_DIRECTIONS:
            raise QueryError(
                "QUERY_FILTER_INVALID",
                f"direction 必须是 {_VALID_DIRECTIONS} 之一，got {direction!r}")
        return direction

    @staticmethod
    def _validate_relations(
            relation_filters: Optional[Sequence[str]]) -> Optional[Tuple[str, ...]]:
        if relation_filters is None:
            return None
        seen: List[str] = []
        for rel in relation_filters:
            if rel not in _VALID_RELATIONS:
                raise QueryError(
                    "QUERY_FILTER_INVALID",
                    f"relation {rel!r} 不在正式 18 relations 内")
            if rel not in seen:
                seen.append(rel)
        return tuple(seen) or None

    @staticmethod
    def _validate_assertion_types(
            assertion_types: Optional[Sequence[str]]) -> Optional[Tuple[str, ...]]:
        if assertion_types is None:
            return None
        seen: List[str] = []
        for at in assertion_types:
            if at not in _VALID_ASSERTION_TYPES:
                raise QueryError(
                    "QUERY_FILTER_INVALID",
                    f"assertion_type {at!r} 不在 "
                    f"{_VALID_ASSERTION_TYPES} 内")
            if at not in seen:
                seen.append(at)
        return tuple(seen) or None

    # ── HistoryService delegation（lifecycle 唯一 authority）─

    @staticmethod
    def _map_history_error(exc: HistoryError, kind: str) -> QueryError:
        if exc.error_code in _HISTORY_PAYLOAD_CODES:
            code = ("QUERY_NODE_PAYLOAD_INVALID" if kind == "node"
                    else "QUERY_EDGE_PAYLOAD_INVALID")
        else:
            code = _HISTORY_ERROR_MAP.get(
                exc.error_code, "QUERY_READ_FAILED")
        return QueryError(code, str(exc))

    def _resolve_node(self, node_id: str, as_of: str,
                      conn) -> Optional[Dict[str, Any]]:
        try:
            return self._history.resolve_node_as_of(
                node_id, as_of, conn=conn)
        except HistoryError as e:
            raise self._map_history_error(e, "node") from e

    def _resolve_edge(self, edge_id: str, as_of: str,
                      conn) -> Optional[Dict[str, Any]]:
        try:
            return self._history.resolve_edge_as_of(
                edge_id, as_of, conn=conn)
        except HistoryError as e:
            raise self._map_history_error(e, "edge") from e

    # ── traversal（resolve-then-traverse）───────────────────

    def _query_graph_locked(
        self,
        conn: sqlite3.Connection,
        root_node_id: str,
        as_of: str,
        *,
        max_depth: int,
        relation_filters: Optional[Tuple[str, ...]],
        direction: str,
        assertion_types: Optional[Tuple[str, ...]],
    ) -> QueryGraphResult:
        """在调用方 read snapshot 内执行 traversal（context builder 复用）。"""
        root_resolved = self._resolve_node(root_node_id, as_of, conn)
        if root_resolved is None:
            raise QueryError(
                "QUERY_ROOT_NOT_FOUND", f"root node {root_node_id} 不存在")

        root_wrapper = _node_wrapper(0, root_resolved)
        limitations: List[Dict[str, str]] = [
            {"code": "BUSINESS_VALIDITY_TIME_ONLY",
             "message": "as_of resolves business validity, not historical "
                        "system-knowledge availability."},
            {"code": "PATHS_NOT_CAUSAL",
             "message": "知识图路径不是自动因果证明；不输出 path 作为知识结论。"},
        ]

        nodes: Dict[str, Dict[str, Any]] = {root_node_id: root_wrapper}
        edges: Dict[str, Dict[str, Any]] = {}
        triple_owner: Dict[Tuple[str, str, str], str] = {}

        if not root_resolved["is_active"]:
            # inactive root 不是 corruption：返回 root，不扩展（Decision #38.4.14）
            limitations.append({
                "code": "ROOT_INACTIVE_NO_TRAVERSAL",
                "message": f"root derived_status="
                           f"{root_resolved['derived_status']}，不扩展 traversal"})
            return self._build_result(
                as_of, root_wrapper, max_depth, relation_filters,
                direction, assertion_types, nodes, edges, limitations)

        if max_depth > 0:
            limitations.append({
                "code": "DEPTH_BOUNDED",
                "message": f"traversal bounded to max_depth={max_depth}"})

        visited: set[str] = {root_node_id}
        frontier: List[str] = [root_node_id]
        current_depth = 0

        while frontier and current_depth < max_depth:
            next_frontier: List[str] = []
            for node_id in frontier:
                for edge_id in self._discover_incident_edge_ids(
                        conn, node_id):
                    if edge_id in edges:
                        continue  # 已入集合（同 edge_id 只算一个 active logical edge）
                    resolved = self._resolve_edge(edge_id, as_of, conn)
                    if resolved is None:
                        raise QueryError(
                            "QUERY_READ_FAILED",
                            f"edge {edge_id} discovery 命中但 resolve 为空")
                    if not resolved["is_active"]:
                        continue  # 合法生命周期（expired/retired/not_yet_valid）不参与遍历
                    payload = resolved["payload"]
                    src = payload["source_node_id"]
                    tgt = payload["target_node_id"]
                    # direction 只影响 traversal expansion（Decision #38.4.19）
                    if direction == "outgoing" and src != node_id:
                        continue
                    if direction == "incoming" and tgt != node_id:
                        continue
                    # relation / assertion 过滤
                    if relation_filters is not None \
                            and payload["relation"] not in relation_filters:
                        continue
                    if assertion_types is not None \
                            and payload["assertion_type"] not in assertion_types:
                        continue
                    # duplicate active triple（Decision #38.4.17）
                    triple = (src, payload["relation"], tgt)
                    owner = triple_owner.get(triple)
                    if owner is not None and owner != edge_id:
                        raise QueryError(
                            "QUERY_AMBIGUOUS_EDGE_IDENTITY",
                            f"同一 as_of 下 logical triple {triple} 存在多个 "
                            f"active edge_id：{owner} 与 {edge_id}")
                    triple_owner[triple] = edge_id
                    # active edge endpoint contract（Decision #38.4.15）
                    ep_src = self._resolve_node(src, as_of, conn)
                    ep_tgt = self._resolve_node(tgt, as_of, conn)
                    if ep_src is None or ep_tgt is None:
                        raise QueryError(
                            "QUERY_ENDPOINT_MISSING",
                            f"edge {edge_id} endpoint 缺失："
                            f"source={src!r} target={tgt!r}")
                    if not ep_src["is_active"] or not ep_tgt["is_active"]:
                        raise QueryError(
                            "QUERY_ENDPOINT_INACTIVE",
                            f"edge {edge_id} endpoint 非 active："
                            f"source={ep_src['derived_status']} "
                            f"target={ep_tgt['derived_status']}")
                    # 加入 edge（depth = 扩展源 depth + 1）
                    edge_depth = nodes[node_id]["depth"] + 1
                    edges[edge_id] = _edge_wrapper(edge_depth, resolved)
                    # 扩展对端节点（dedup；已访问节点不再次扩展）
                    neighbor = tgt if src == node_id else src
                    if neighbor not in visited:
                        visited.add(neighbor)
                        ep_resolved = ep_src if neighbor == src else ep_tgt
                        nodes[neighbor] = _node_wrapper(edge_depth, ep_resolved)
                        next_frontier.append(neighbor)
                # 硬上限检查（Decision #38.5.25）：达到上限 → 整查询失败
                if len(nodes) > MAX_NODES:
                    raise QueryError(
                        "QUERY_RESULT_LIMIT_EXCEEDED",
                        f"nodes 超过硬上限 MAX_NODES={MAX_NODES}")
                if len(edges) > MAX_EDGES:
                    raise QueryError(
                        "QUERY_RESULT_LIMIT_EXCEEDED",
                        f"edges 超过硬上限 MAX_EDGES={MAX_EDGES}")
            frontier = next_frontier
            current_depth += 1

        # MODEL_INFERENCE 存在 → deterministic limitation（Decision #38.6.32）
        if any(e["payload"]["assertion_type"] == "MODEL_INFERENCE"
               for e in edges.values()):
            limitations.append({
                "code": "MODEL_INFERENCE_PRESENT",
                "message": "结果包含 MODEL_INFERENCE 边（独立分区，非事实，"
                           "未经独立确认）。"})

        return self._build_result(
            as_of, root_wrapper, max_depth, relation_filters,
            direction, assertion_types, nodes, edges, limitations)

    def _build_result(
        self,
        as_of: str,
        root_wrapper: Dict[str, Any],
        max_depth: int,
        relation_filters: Optional[Tuple[str, ...]],
        direction: str,
        assertion_types: Optional[Tuple[str, ...]],
        nodes: Dict[str, Dict[str, Any]],
        edges: Dict[str, Dict[str, Any]],
        limitations: List[Dict[str, str]],
    ) -> QueryGraphResult:
        # deterministic ordering（Decision #38.7.33）
        node_list = sorted(nodes.values(), key=lambda w: (w["depth"], w["node_id"]))
        edge_list = sorted(
            edges.values(),
            key=lambda w: (w["depth"], w["payload"]["source_node_id"],
                           w["payload"]["relation"],
                           w["payload"]["target_node_id"], w["edge_id"]))
        edge_id_order = [w["edge_id"] for w in edge_list]

        epistemic: Dict[str, List[str]] = {
            "governance": [
                eid for eid in edge_id_order
                if edges[eid]["payload"]["assertion_type"] == "GOVERNANCE"],
            "facts": [
                eid for eid in edge_id_order
                if edges[eid]["payload"]["assertion_type"] == "FACT"],
            "model_inferences": [
                eid for eid in edge_id_order
                if edges[eid]["payload"]["assertion_type"] == "MODEL_INFERENCE"],
        }

        evidence_ids: List[str] = []
        for w in node_list + edge_list:
            for eid in w["payload"].get("evidence_ids") or []:
                if eid not in evidence_ids:
                    evidence_ids.append(eid)
        evidence_ids.sort()

        return QueryGraphResult(
            as_of=as_of,
            root=root_wrapper,
            max_depth=max_depth,
            query_parameters={
                "max_depth": max_depth,
                "relation_filters": list(relation_filters)
                if relation_filters is not None else None,
                "direction": direction,
                "assertion_types": list(assertion_types)
                if assertion_types is not None else None,
            },
            nodes=node_list,
            edges=edge_list,
            epistemic=epistemic,
            evidence_ids=evidence_ids,
            limitations=sorted(limitations, key=lambda x: (x["code"], x["message"])),
            conflicts=[],
        )

    # ── incident-edge identity discovery（dual-source，Decision #38.4.16）─

    @staticmethod
    def _discover_incident_edge_ids(conn: sqlite3.Connection,
                                    node_id: str) -> List[str]:
        """denormalized columns UNION valid payload 双源发现候选 edge_id。

        - source 1：graph_edges.source_node_id / target_node_id 列
        - source 2：json_valid(payload) guard 后的 payload.source_node_id /
          target_node_id（防 column 单边篡改藏边）
        malformed JSON 由 json_valid guard 排除，不产生未捕获异常。
        """
        candidates: set[str] = set()
        try:
            col_rows = conn.execute(
                "SELECT edge_id FROM graph_edges "
                "WHERE source_node_id = ? "
                "UNION SELECT edge_id FROM graph_edges "
                "WHERE target_node_id = ?",
                (node_id, node_id),
            ).fetchall()
        except sqlite3.Error as e:
            raise QueryError(
                "QUERY_READ_FAILED",
                f"incident edge discovery (columns) failed: {e}") from e
        for r in col_rows:
            candidates.add(r["edge_id"])

        try:
            payload_rows = conn.execute(
                "SELECT edge_id FROM graph_edges "
                "WHERE json_valid(payload) = 1 "
                "AND (json_extract(payload, '$.source_node_id') = ? "
                "     OR json_extract(payload, '$.target_node_id') = ?)",
                (node_id, node_id),
            ).fetchall()
        except sqlite3.Error as e:
            raise QueryError(
                "QUERY_READ_FAILED",
                f"incident edge discovery (payload) failed: {e}") from e
        for r in payload_rows:
            candidates.add(r["edge_id"])

        return sorted(candidates)
