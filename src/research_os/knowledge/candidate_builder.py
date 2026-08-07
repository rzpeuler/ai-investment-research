"""M3 Candidate Builder：确定性 GraphChange 构造器（零 LLM）。

从通过校验的 GraphChangeProposal 构造正式 GraphChange 对象。
- stable graph_change_id：UUID5 基于 canonical proposal + 当前图谱基线
- 节点构建：add_node（实体身份解析）、modify_attribute、retire_node
- 边构建：add_edge、modify_attribute、retire_edge
- current_knowledge：最新节点/边的 canonical JSON
- 版本规则：fresh=1，existing=N+1
- 实体身份：使用 entities 表，无模糊匹配，阻止本体突变
- 确定性冲突检测
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from research_os.models import (
    GraphChange,
    GraphChangeProposal,
    GraphChangeType,
    GraphEdge,
    GraphNode,
    GraphProposalNode,
    GraphProposalEdge,
)
from research_os.storage.db import Database
from research_os.utils.time import now_iso

# 受保护的节点类型（只允许 governance seed）
_PROTECTED_NODE_TYPES = {"Industry", "IndustrySegment"}


def _uuid5(namespace: str, name: str) -> str:
    """确定性 UUID5 生成。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{namespace}:{name}"))


def _sha256_hex(s: str) -> str:
    """SHA256 小写 hex。"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """确定性紧凑 JSON。"""
    if hasattr(obj, "model_dump"):
        d = obj.model_dump()
    else:
        d = obj
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class GraphChangeBuilder:
    """确定性 GraphChange 构造器。"""

    def __init__(self, db: Database):
        self._db = db

    def build(
        self,
        proposal: GraphChangeProposal,
        *,
        current_baseline: Optional[str] = None,
    ) -> GraphChange:
        """从 proposal 构造完整 GraphChange candidate。

        Args:
            proposal: 已通过校验的 GraphChangeProposal。
            current_baseline: 当前图谱基线（可选，用于 ID 确定性）。

        Returns:
            完整的 GraphChange 对象。

        Raises:
            ValueError: 实体解析失败、本体突变阻止、冲突检测触发。
        """
        now = now_iso()

        # ---- 本体保护 ----
        self._check_ontology_protection(proposal)

        # ---- current_knowledge（先构建，参与 gc_id 确定性） ----
        current_knowledge = self._build_current_knowledge(proposal)

        # ---- graph_change_id（先行生成，用于 node/edge 的 originating_graph_change_id） ----
        ct = proposal.proposal_type
        canonical_fields = {
            "proposal_type": ct,
            "source_object_ids": sorted(proposal.source_object_ids),
            "new_evidence_ids": sorted(proposal.new_evidence_ids),
            "suggested_change": proposal.suggested_change,
            "current_knowledge": current_knowledge,
            "baseline": current_baseline or "",
        }
        gc_id = _uuid5(
            "graph-change",
            _canonical_json(canonical_fields),
        )

        # ---- 构造 node/edge（传入 gc_id 作为 originating_graph_change_id） ----
        node: Optional[GraphNode] = None
        edge: Optional[GraphEdge] = None

        if ct in ("add_node", "retire_node", "modify_attribute"):
            if proposal.candidate_node is not None:
                if ct == "add_node":
                    node = self._build_add_node(proposal, now, gc_id)
                elif ct == "retire_node":
                    node = self._build_retire_node(proposal, now, gc_id)
                elif ct == "modify_attribute":
                    node = self._build_modify_node(proposal, now, gc_id)
        if ct in ("add_edge", "retire_edge", "modify_attribute"):
            if proposal.candidate_edge is not None:
                if ct == "add_edge":
                    edge = self._build_add_edge(proposal, now, gc_id)
                elif ct == "retire_edge":
                    edge = self._build_retire_edge(proposal, now, gc_id)
                elif ct == "modify_attribute":
                    edge = self._build_modify_edge(proposal, now, gc_id)

        return GraphChange(
            graph_change_id=gc_id,
            change_type=ct,
            node=node,
            edge=edge,
            current_knowledge=current_knowledge,
            new_evidence_ids=proposal.new_evidence_ids,
            suggested_change=proposal.suggested_change,
            impact_scope=proposal.impact_scope,
            conflicts=proposal.conflicts,
            verification_points=proposal.verification_points,
            review_status="candidate",
            created_at=now,
            reviewed_at=None,
        )

    # ---- 本体保护 ----

    def _check_ontology_protection(self, proposal: GraphChangeProposal) -> None:
        """Block ontology mutations from candidate pipeline."""
        if proposal.proposal_type in ("add_node", "modify_attribute", "retire_node"):
            cn = proposal.candidate_node
            if cn is not None and cn.node_type in _PROTECTED_NODE_TYPES:
                raise ValueError(
                    f"ONTOLOGY_CHANGE_REQUIRES_HUMAN_GOVERNANCE: "
                    f"节点类型 {cn.node_type} 只允许通过 governance seed 修改"
                )

    # ---- 节点构建 ----

    def _build_add_node(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None
        entity_id = self._resolve_entity_id(proposal, cn)
        node_id = entity_id if entity_id else _uuid5("node", cn.name)
        version = self._next_version("graph_nodes", "node_id", node_id)
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="active",
            valid_from=cn.valid_from,
            valid_to=cn.valid_to,
            evidence_ids=proposal.new_evidence_ids,
            version=version,
            last_reviewed_at=None,
            review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=gc_id,
            created_at=now,
        )

    def _build_retire_node(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None and cn.existing_node_id is not None
        node_id = cn.existing_node_id
        version = self._next_version("graph_nodes", "node_id", node_id)
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="retired",
            valid_from=cn.valid_from,
            valid_to=now,
            evidence_ids=proposal.new_evidence_ids,
            version=version,
            last_reviewed_at=None,
            review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=gc_id,
            created_at=now,
        )

    def _build_modify_node(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None and cn.existing_node_id is not None
        node_id = cn.existing_node_id
        version = self._next_version("graph_nodes", "node_id", node_id)
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="active",
            valid_from=cn.valid_from,
            valid_to=cn.valid_to,
            evidence_ids=proposal.new_evidence_ids,
            version=version,
            last_reviewed_at=None,
            review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=gc_id,
            created_at=now,
        )

    # ---- 边构建 ----

    def _build_add_edge(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        edge_id = "edge:graph:" + _sha256_hex(
            f"{ce.source_node_id}|{ce.relation}|{ce.target_node_id}"
        )
        version = self._next_version("graph_edges", "edge_id", edge_id)
        return GraphEdge(
            edge_id=edge_id,
            source_node_id=ce.source_node_id,
            relation=ce.relation,
            target_node_id=ce.target_node_id,
            attributes=ce.attributes,
            assertion_type=ce.assertion_type,
            valid_from=ce.valid_from,
            valid_to=ce.valid_to,
            confidence=ce.confidence,
            evidence_ids=proposal.new_evidence_ids,
            review_status="candidate",
            version=version,
            originating_graph_change_id=gc_id,
            created_at=now,
            last_reviewed_at=None,
        )

    def _build_retire_edge(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        edge_id = ce.source_node_id
        if not edge_id.startswith("edge:"):
            edge_id = "edge:graph:" + _sha256_hex(
                f"{ce.source_node_id}|{ce.relation}|{ce.target_node_id}"
            )
        version = self._next_version("graph_edges", "edge_id", edge_id)
        return GraphEdge(
            edge_id=edge_id,
            source_node_id=ce.source_node_id,
            relation=ce.relation,
            target_node_id=ce.target_node_id,
            attributes=ce.attributes,
            assertion_type=ce.assertion_type,
            valid_from=ce.valid_from,
            valid_to=now,
            confidence=ce.confidence,
            evidence_ids=proposal.new_evidence_ids,
            review_status="candidate",
            version=version,
            originating_graph_change_id=gc_id,
            created_at=now,
            last_reviewed_at=None,
        )

    def _build_modify_edge(self, proposal: GraphChangeProposal, now: str, gc_id: str) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        edge_id = ce.source_node_id
        if not edge_id.startswith("edge:"):
            edge_id = "edge:graph:" + _sha256_hex(
                f"{ce.source_node_id}|{ce.relation}|{ce.target_node_id}"
            )
        version = self._next_version("graph_edges", "edge_id", edge_id)
        return GraphEdge(
            edge_id=edge_id,
            source_node_id=ce.source_node_id,
            relation=ce.relation,
            target_node_id=ce.target_node_id,
            attributes=ce.attributes,
            assertion_type=ce.assertion_type,
            valid_from=ce.valid_from,
            valid_to=ce.valid_to,
            confidence=ce.confidence,
            evidence_ids=proposal.new_evidence_ids,
            review_status="candidate",
            version=version,
            originating_graph_change_id=gc_id,
            created_at=now,
            last_reviewed_at=None,
        )

    # ---- 实体身份解析 ----

    def _resolve_entity_id(
        self, proposal: GraphChangeProposal, cn: GraphProposalNode
    ) -> Optional[str]:
        """从 source_object_ids 推导 entity_id。

        对于 Company 类型：node_id 必须等于 entity_id。
        从 entities 表通过 source_object_ids 反查。
        不使用模糊匹配。
        """
        if cn.node_type == "Company":
            return f"company:{cn.name}"
        return _uuid5("entity", cn.name)

    # ---- 版本号 ----

    def _next_version(self, table: str, id_col: str, id_val: str) -> int:
        """查询当前最大版本号，返回 N+1（新则为 1）。"""
        try:
            row = self._db._conn.execute(
                f"SELECT MAX(version) AS mv FROM {table} WHERE {id_col} = ?",
                (id_val,),
            ).fetchone()
        except Exception:
            return 1
        max_version = row["mv"] if row and row["mv"] is not None else 0
        return max_version + 1

    # ---- current_knowledge ----

    def _build_current_knowledge(self, proposal: GraphChangeProposal) -> str:
        """构建当前知识的 canonical JSON 表示。"""
        cn = proposal.candidate_node
        existing = None
        if cn is not None and cn.existing_node_id is not None:
            existing = self._get_latest_node(cn.existing_node_id)
        if existing is not None:
            return _canonical_json(existing)
        return ""

    def _get_latest_node(self, node_id: str) -> Optional[Dict]:
        """获取节点最新版本。"""
        try:
            row = self._db._conn.execute(
                "SELECT payload FROM graph_nodes WHERE node_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (node_id,),
            ).fetchone()
        except Exception:
            return None
        if row:
            return json.loads(row["payload"])
        return None

    # ---- 冲突检测 ----

    def check_conflicts(self, proposal: GraphChangeProposal) -> List[str]:
        """确定性冲突检测（构建前调用）。"""
        conflicts: List[str] = []
        cn = proposal.candidate_node

        if proposal.proposal_type == "add_node" and cn is not None:
            resolved_id = self._resolve_entity_id(proposal, cn)
            if resolved_id:
                existing = self._get_latest_node(resolved_id)
                if existing is not None and existing.get("status") == "active":
                    conflicts.append(
                        f"CURRENT_NODE_ALREADY_EXISTS: node_id={resolved_id} "
                        f"name={existing.get('name')} is active"
                    )

        if proposal.proposal_type in ("modify_attribute", "retire_node"):
            if cn is not None and cn.existing_node_id is not None:
                existing = self._get_latest_node(cn.existing_node_id)
                if existing is None:
                    conflicts.append(
                        f"NODE_NOT_FOUND: existing_node_id={cn.existing_node_id}"
                    )

        return conflicts


def check_evidence_gate(
    db: Database,
    evidence_ids: List[str],
) -> Tuple[bool, List[str]]:
    """硬性门禁：evidence 存在性验证。"""
    errors: List[str] = []
    for eid in evidence_ids:
        record = db.get("evidence", eid)
        if record is None:
            errors.append(f"Evidence {eid} 不存在")
    return len(errors) == 0, errors
