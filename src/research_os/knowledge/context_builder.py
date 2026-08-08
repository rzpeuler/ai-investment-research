"""M8 Deterministic Knowledge Context Builder：graph + Evidence 同一 read snapshot。

零 LLM / 零 Provider / 零 network。只读（READ ONLY）。

冻结语义（Decision #38.6）：
- 复用 GraphQueryService（禁止第二套 traversal）
- graph 与 Evidence 必须在同一 read snapshot 内 strict load（禁止混合状态）
- KnowledgeContext = frozen dataclass / deterministic dict，不持久化，不新增 Schema
- Evidence strict read：JSON → dict → Schema → Pydantic → dump → Schema +
  DB primary identity / denormalized columns 核对
- 历史 as_of 下 Evidence 不按 retrieved_at 重新过滤（immutable provenance snapshot）
- Governance evidence_ids=[] 合法，不误报 QUERY_EVIDENCE_MISSING
- 禁止生成投资结论（target price / rating / advice / recommendation）
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from research_os.models import Evidence
from research_os.validators.schema_validator import validate_instance

from research_os.knowledge.query import (
    MAX_EVIDENCE,
    GraphQueryService,
    QueryError,
)

# Evidence summary 字段（Decision #38.6.28）：不含 excerpt
EVIDENCE_SUMMARY_FIELDS = (
    "evidence_id", "source_id", "raw_item_id", "title", "publisher",
    "published_at", "retrieved_at", "url", "evidence_type",
    "independence_group", "source_tier", "access_status",
)

# evidence 表 denormalized columns（与 001_initial.sql / M7 fixture 一致）
_EVIDENCE_COLUMNS = (
    ("source_id", "source_id"),
    ("raw_item_id", "raw_item_id"),
    ("independence_group", "independence_group"),
    ("source_tier", "source_tier"),
)


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
            evidence_summaries = self._strict_load_evidence(
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

    # ── Evidence strict lineage（Decision #38.6.27）──────────

    def _strict_load_evidence(
            self, conn: sqlite3.Connection,
            evidence_ids: Sequence[str]) -> List[Dict[str, Any]]:
        """对全部唯一 evidence_ids 做 strict read（fail-closed）。"""
        summaries: List[Dict[str, Any]] = []
        seen: set[str] = set()
        for eid in sorted(set(evidence_ids)):
            if eid in seen:
                continue
            seen.add(eid)
            if len(summaries) >= MAX_EVIDENCE:
                raise QueryError(
                    "QUERY_RESULT_LIMIT_EXCEEDED",
                    f"evidence 超过硬上限 MAX_EVIDENCE={MAX_EVIDENCE}")
            row = self._select_evidence_row(conn, eid)
            if row is None:
                raise QueryError(
                    "QUERY_EVIDENCE_MISSING", f"Evidence {eid} 缺失")
            try:
                payload = json.loads(row["payload"])
            except Exception as e:
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} payload 非法 JSON: {e}") from e
            if not isinstance(payload, dict):
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} payload 顶层必须是 object")
            schema_errors = validate_instance(payload, "evidence")
            if schema_errors:
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} schema invalid: "
                    f"{'; '.join(schema_errors)}")
            try:
                obj = Evidence(**payload)
            except Exception as e:
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} Pydantic parse failed: {e}") from e
            try:
                dumped = obj.model_dump()
            except Exception as e:
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} model_dump failed: {e}") from e
            schema_errors2 = validate_instance(dumped, "evidence")
            if schema_errors2:
                raise QueryError(
                    "QUERY_EVIDENCE_INVALID",
                    f"Evidence {eid} dump schema re-validation failed: "
                    f"{'; '.join(schema_errors2)}")
            # DB primary identity + denormalized columns 核对（不得只信一边）
            if dumped["evidence_id"] != row["evidence_id"]:
                raise QueryError(
                    "QUERY_EVIDENCE_INTEGRITY_CONFLICT",
                    f"Evidence DB evidence_id={row['evidence_id']} 与 "
                    f"payload evidence_id={dumped['evidence_id']} 不一致")
            for col, key in _EVIDENCE_COLUMNS:
                if row[col] != dumped.get(key):
                    raise QueryError(
                        "QUERY_EVIDENCE_INTEGRITY_CONFLICT",
                        f"Evidence {eid} DB column {col}={row[col]!r} 与 "
                        f"payload {key}={dumped.get(key)!r} 不一致")
            summaries.append(
                {k: dumped[k] for k in EVIDENCE_SUMMARY_FIELDS})
        return summaries

    @staticmethod
    def _select_evidence_row(conn: sqlite3.Connection, eid: str):
        try:
            return conn.execute(
                "SELECT evidence_id, payload, source_id, raw_item_id, "
                "independence_group, source_tier "
                "FROM evidence WHERE evidence_id = ?",
                (eid,),
            ).fetchone()
        except sqlite3.Error as e:
            raise QueryError(
                "QUERY_READ_FAILED",
                f"Evidence {eid} strict read failed: {e}") from e

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
