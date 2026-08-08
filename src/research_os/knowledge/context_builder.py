"""M8 Deterministic Knowledge Context Builder：graph + Evidence 同一 read snapshot。

零 LLM / 零 Provider / 零 network。只读（READ ONLY）。

冻结语义（Decision #38.6 / #38.11）：
- 复用 GraphQueryService（禁止第二套 traversal）
- graph 与 Evidence 必须在同一 read snapshot 内 strict load（禁止混合状态）
- Evidence strict read 单一权威在 GraphQueryService（本模块委托，禁止第二套 loader）
- KnowledgeContext = frozen dataclass / deterministic dict，不持久化，不新增 Schema
- 历史 as_of 下 Evidence 不按 retrieved_at 重新过滤（immutable provenance snapshot）
- Governance evidence_ids=[] 合法，不误报 QUERY_EVIDENCE_MISSING
- 禁止生成投资结论（target price / rating / advice / recommendation）
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from research_os.knowledge.query import (
    EVIDENCE_SUMMARY_FIELDS,  # re-export（测试与 CLI 兼容引用）
    GraphQueryService,
    QueryError,
)

__all__ = ["EVIDENCE_SUMMARY_FIELDS", "KnowledgeContext", "KnowledgeContextBuilder"]


@dataclass(frozen=True)
class KnowledgeContext:
    """知识上下文（结构化知识输入，不是研究报告）。"""

    root: Dict[str, Any]
    as_of: str
    max_depth: int
    query_parameters: Dict[str, Any]
    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    epistemic: Dict[str, List[str]] = field(default_factory=dict)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    limitations: List[Dict[str, str]] = field(default_factory=list)
    conflicts: List[Any] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root": self.root,
            "as_of": self.as_of,
            "max_depth": self.max_depth,
            "query_parameters": self.query_parameters,
            "nodes": self.nodes,
            "edges": self.edges,
            "epistemic": self.epistemic,
            "evidence": self.evidence,
            "evidence_ids": self.evidence_ids,
            "limitations": self.limitations,
            "conflicts": self.conflicts,
        }


class KnowledgeContextBuilder:
    """M8 确定性知识上下文构建器（复用 GraphQueryService）。"""

    def __init__(self, query_service: GraphQueryService):
        self._query = query_service

    # ── public API ──────────────────────────────────────────

    def build(
        self,
        root_node_id: str,
        as_of: str,
        *,
        max_depth: int = 1,
        relation_filters: Optional[Sequence[str]] = None,
        direction: str = "both",
        assertion_types: Optional[Sequence[str]] = None,
    ) -> KnowledgeContext:
        """构建 KnowledgeContext（graph + Evidence 同一 read snapshot）。"""
        as_of = self._query._validate_as_of(as_of)
        max_depth = self._query._validate_depth(max_depth)
        relation_filters = self._query._validate_relations(relation_filters)
        direction = self._query._validate_direction(direction)
        assertion_types = self._query._validate_assertion_types(assertion_types)

        conn = self._query._db._conn
        if conn.in_transaction:
            raise QueryError(
                "QUERY_ACTIVE_TRANSACTION_CONFLICT",
                "M8 context 不得 commit/rollback 调用者已有事务")
        try:
            conn.execute("BEGIN")
        except Exception as e:
            raise QueryError(
                "QUERY_READ_FAILED",
                f"read snapshot BEGIN failed: {e}") from e
        try:
            qr = self._query._query_graph_locked(
                conn, root_node_id, as_of, max_depth=max_depth,
                relation_filters=relation_filters, direction=direction,
                assertion_types=assertion_types)
            # Evidence strict read 单一权威（GraphQueryService），同一 snapshot
            evidence_summaries = self._query._strict_read_evidence(
                conn, qr.evidence_ids)
            evidence_ids = [s["evidence_id"] for s in evidence_summaries]
            ctx = KnowledgeContext(
                root=qr.root,
                as_of=qr.as_of,
                max_depth=qr.max_depth,
                query_parameters=qr.query_parameters,
                nodes=qr.nodes,
                edges=qr.edges,
                epistemic=qr.epistemic,
                evidence=evidence_summaries,
                evidence_ids=evidence_ids,
                limitations=qr.limitations,
                conflicts=qr.conflicts,
            )
            self._close_snapshot(conn)
            return ctx
        except QueryError:
            self._close_snapshot(conn)
            raise
        except Exception as e:
            self._close_snapshot(conn)
            raise QueryError(
                "QUERY_READ_FAILED", f"context build failed: {e}") from e

    # ── snapshot helper（与 GraphQueryService 同一契约）──────

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
