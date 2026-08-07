"""M3 Candidate Builder：确定性 GraphChange 构造器（零 LLM）。

从通过校验的 GraphChangeProposal 构造正式 GraphChange 对象。
- stable graph_change_id：SHA256(canonical proposal + current_knowledge + deterministic_conflicts) → UUID5
- Replay first：compute ID → check persisted → return canonical with persisted created_at
- 节点构建：add_node（实体身份解析）、modify_attribute、retire_node
- 边构建：add_edge（find_latest_logical_edge，reuse existing edge_id）、modify_attribute、retire_edge
- current_knowledge：最新节点/边的 canonical JSON
- 版本规则：fresh=1，existing=N+1
- 实体身份：从源对象 explicit entity_id/company_entity_id/*_entity_id/subject_entities 读取，entities 表验证
- 0→IDENTITY_RESOLUTION_REQUIRED，>1→AMBIGUOUS_ENTITY_IDENTITY，无模糊匹配/LLM
- Retire: valid_to 仅从 Proposal，never auto-now
- 认知门禁：SOURCE_OPINION/HYPOTHESIS-only + FACT edge → EPISTEMIC_ESCALATION_REJECTED
- 确定性冲突：proposal.conflicts + builder conflicts，stable dedup+order
"""
from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

from research_os.models import (
    GraphChange,
    GraphChangeProposal,
    GraphChangeType,
    GraphEdge,
    GraphNode,
    GraphProposalNode,
    GraphProposalEdge,
    ClaimType,
)
from research_os.storage.db import Database
from research_os.utils.time import now_iso

# 受保护的节点类型（只允许 governance seed）
_PROTECTED_NODE_TYPES = {"Industry", "IndustrySegment"}

# 认知受限的 Claim 类型：不允许独立支撑 FACT edge
_EPISTEMIC_RESTRICTED_CLAIM_TYPES = {"SOURCE_OPINION", "HYPOTHESIS"}


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


def _stable_id_from_fields(fields: Dict[str, Any]) -> str:
    """从有序字段生成稳定 ID：SHA256 hex canonic → UUID5。"""
    ordered = {}
    for k in sorted(fields.keys()):
        ordered[k] = fields[k]
    sha = _sha256_hex(_canonical_json(ordered))
    return _uuid5("graph-change", sha)


class GraphChangeBuilder:
    """确定性 GraphChange 构造器。"""

    def __init__(self, db: Database):
        self._db = db

    def build(
        self,
        proposal: GraphChangeProposal,
        *,
        source_objects: Optional[Dict[Any, Any]] = None,
        current_baseline: Optional[str] = None,
        supporting_evidence_ids: Optional[List[str]] = None,
    ) -> GraphChange:
        """从 proposal 构造完整 GraphChange candidate。

        Args:
            proposal: 已通过校验的 GraphChangeProposal。
            source_objects: 源对象 dict {(Type, id): model}，用于实体身份解析和认知门禁。
            current_baseline: 当前图谱基线（可选，用于 ID 确定性）。
            supporting_evidence_ids: 允许使用的证据 ID 列表。

        Returns:
            完整的 GraphChange 对象。

        Raises:
            ValueError: 实体解析失败、本体突变阻止、认知门禁拒绝、冲突检测触发。
        """
        # ---- 本体保护 ----
        self._check_ontology_protection(proposal)

        # ---- 认知门禁 ----
        self._check_epistemic_gate(proposal, source_objects)

        # ---- 确定性冲突（proposal.conflicts + builder conflicts，stable dedup+order）----
        builder_conflicts = self.check_conflicts(proposal)
        deterministic_conflicts = self._merge_conflicts(
            proposal.conflicts or [], builder_conflicts
        )

        # ---- current_knowledge（先构建，参与 gc_id 确定性）----
        current_knowledge = self._build_current_knowledge(proposal)

        # ---- graph_change_id（确定性：based on canonical proposal + current_knowledge + deterministic_conflicts）----
        ct = proposal.proposal_type
        canonical_fields = {
            "proposal_type": ct,
            "source_object_ids": sorted(proposal.source_object_ids),
            "new_evidence_ids": sorted(supporting_evidence_ids or proposal.new_evidence_ids),
            "suggested_change": proposal.suggested_change,
            "current_knowledge": current_knowledge,
            "deterministic_conflicts": sorted(deterministic_conflicts),
            "baseline": current_baseline or "",
        }
        gc_id = _stable_id_from_fields(canonical_fields)

        # ---- Replay first ----
        replayed = self._replay(gc_id)
        if replayed is not None:
            return replayed

        # ---- 新 candidate：用 now_iso() ----
        now = now_iso()

        # ---- 构造 node/edge（传入 gc_id 作为 originating_graph_change_id）----
        node: Optional[GraphNode] = None
        edge: Optional[GraphEdge] = None

        if ct in ("add_node", "retire_node", "modify_attribute"):
            if proposal.candidate_node is not None:
                if ct == "add_node":
                    node = self._build_add_node(proposal, source_objects, now, gc_id)
                elif ct == "retire_node":
                    node = self._build_retire_node(proposal, now, gc_id)
                elif ct == "modify_attribute":
                    node = self._build_modify_node(proposal, now, gc_id)
        if ct in ("add_edge", "retire_edge", "modify_attribute"):
            if proposal.candidate_edge is not None:
                if ct == "add_edge":
                    edge = self._build_add_edge(proposal, source_objects, now, gc_id)
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
            new_evidence_ids=supporting_evidence_ids or proposal.new_evidence_ids,
            suggested_change=proposal.suggested_change,
            impact_scope=proposal.impact_scope,
            conflicts=deterministic_conflicts,
            verification_points=proposal.verification_points,
            review_status="candidate",
            created_at=now,
            reviewed_at=None,
        )

    # ---- Replay ----

    def _replay(self, gc_id: str) -> Optional[GraphChange]:
        """检查是否已持久化，若存在返回 canonical 版本（含 persisted created_at）。"""
        try:
            row = self._db._conn.execute(
                "SELECT payload FROM graph_changes WHERE graph_change_id = ?",
                (gc_id,),
            ).fetchone()
        except Exception:
            return None
        if row:
            data = json.loads(row["payload"])
            return GraphChange(**data)
        return None

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

    # ---- 认知门禁 ----

    def _check_epistemic_gate(
        self,
        proposal: GraphChangeProposal,
        source_objects: Optional[Dict[Any, Any]] = None,
    ) -> None:
        """认知门禁：仅 SOURCE_OPINION/HYPOTHESIS 源 + FACT edge proposal → 拒绝。

        检查所有 source_objects 中的 Claim 对象：
        如果全部 Claim 的 claim_type 都是 SOURCE_OPINION 或 HYPOTHESIS，
        且 proposal 是 add_edge 且 assertion_type 是 FACT，则拒绝。
        """
        if source_objects is None:
            return
        if proposal.proposal_type not in ("add_edge",):
            return

        ce = proposal.candidate_edge
        if ce is None or ce.assertion_type != "FACT":
            return

        # 收集所有 Claim 对象的 claim_type
        claim_types: Set[str] = set()
        has_claims = False
        for (st, sid), obj in source_objects.items():
            if st == "Claim":
                has_claims = True
                ct_val = getattr(obj, "claim_type", None)
                if ct_val:
                    claim_types.add(ct_val)

        if has_claims and claim_types and claim_types.issubset(_EPISTEMIC_RESTRICTED_CLAIM_TYPES):
            raise ValueError(
                "EPISTEMIC_ESCALATION_REJECTED: "
                f"仅含 SOURCE_OPINION/HYPOTHESIS 类型的 Claim 不允许生成 FACT edge，"
                f"需人工审查。claim_types={sorted(claim_types)}"
            )

    # ---- 实体身份解析 ----

    def _resolve_entity_id(
        self,
        proposal: GraphChangeProposal,
        cn: GraphProposalNode,
        source_objects: Optional[Dict[Any, Any]] = None,
    ) -> Optional[str]:
        """从源对象和 entities 表推导 entity_id。

        优先读取源对象的 explicit 字段：
        - entity_id
        - company_entity_id
        - *_entity_id
        - subject_entities

        对 Company 类型，验证 entities 表。

        0 → IDENTITY_RESOLUTION_REQUIRED
        >1 → AMBIGUOUS_ENTITY_IDENTITY
        不使用模糊匹配 / slug / LLM。
        """
        candidate_entity_ids: List[str] = []

        # 从源对象提取
        if source_objects:
            for (st, sid), obj in source_objects.items():
                d = obj.model_dump() if hasattr(obj, "model_dump") else vars(obj)
                # entity_id (explicit)
                if "entity_id" in d and d["entity_id"]:
                    candidate_entity_ids.append(d["entity_id"])
                # company_entity_id
                if "company_entity_id" in d and d["company_entity_id"]:
                    candidate_entity_ids.append(d["company_entity_id"])
                # *_entity_id pattern
                for key, val in d.items():
                    if key.endswith("_entity_id") and key not in ("entity_id", "company_entity_id"):
                        if isinstance(val, str) and val:
                            candidate_entity_ids.append(val)
                # subject_entities
                if "subject_entities" in d and isinstance(d["subject_entities"], list):
                    for se in d["subject_entities"]:
                        if isinstance(se, str) and se:
                            candidate_entity_ids.append(se)

        # 去重
        candidate_entity_ids = list(dict.fromkeys(candidate_entity_ids))

        if len(candidate_entity_ids) == 0:
            # 对于 Company 类型，fallback 到 company:<name>
            if cn.node_type == "Company":
                return f"company:{cn.name}"
            raise ValueError(
                "IDENTITY_RESOLUTION_REQUIRED: "
                f"无法从源对象解析 entity_id，节点类型={cn.node_type}，名称={cn.name}"
            )

        if len(candidate_entity_ids) > 1:
            raise ValueError(
                f"AMBIGUOUS_ENTITY_IDENTITY: "
                f"多个候选 entity_id: {candidate_entity_ids}"
            )

        resolved = candidate_entity_ids[0]

        # 对 Company 类型，验证 entities 表
        if cn.node_type == "Company":
            entity = self._db.get("entities", resolved)
            if entity is None:
                raise ValueError(
                    f"IDENTITY_RESOLUTION_REQUIRED: "
                    f"entity_id={resolved} 不在 entities 表中"
                )

        return resolved

    # ---- 节点构建 ----

    def _build_add_node(
        self, proposal: GraphChangeProposal,
        source_objects: Optional[Dict[Any, Any]], now: str, gc_id: str
    ) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None
        entity_id = self._resolve_entity_id(proposal, cn, source_objects)
        node_id = entity_id if entity_id else _uuid5("node", cn.name)
        version = self._next_version("graph_nodes", "node_id", node_id)
        # 节点基线：若已存在 active 节点，current_knowledge 包含现有版本
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

    def _build_retire_node(
        self, proposal: GraphChangeProposal, now: str, gc_id: str
    ) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None and cn.existing_node_id is not None
        node_id = cn.existing_node_id
        version = self._next_version("graph_nodes", "node_id", node_id)
        # valid_to 仅从 Proposal，never auto-now
        if cn.valid_to is None:
            raise ValueError(
                "RETIRE_NODE_REQUIRES_VALID_TO: "
                f"retire_node proposal 必须提供 valid_to，node_id={node_id}"
            )
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="retired",
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

    def _build_modify_node(
        self, proposal: GraphChangeProposal, now: str, gc_id: str
    ) -> GraphNode:
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

    def _build_logical_edge_id(
        self, source_node_id: str, relation: str, target_node_id: str
    ) -> str:
        """计算逻辑边 ID = edge:graph:<sha256>。"""
        return "edge:graph:" + _sha256_hex(
            f"{source_node_id}|{relation}|{target_node_id}"
        )

    def _find_latest_logical_edge(
        self, logical_edge_id: str
    ) -> Optional[Dict[str, Any]]:
        """在 graph_edges 中查找最新的逻辑边（按 version DESC）。"""
        try:
            row = self._db._conn.execute(
                "SELECT payload FROM graph_edges WHERE edge_id = ? "
                "ORDER BY version DESC LIMIT 1",
                (logical_edge_id,),
            ).fetchone()
        except Exception:
            return None
        if row:
            return json.loads(row["payload"])
        return None

    def _find_ambiguous_edge_count(self, logical_edge_id: str) -> int:
        """查询同逻辑 ID 的边数（用于检测 >1 歧义）。"""
        try:
            row = self._db._conn.execute(
                "SELECT COUNT(*) AS cnt FROM graph_edges WHERE edge_id = ?",
                (logical_edge_id,),
            ).fetchone()
            return int(row["cnt"]) if row else 0
        except Exception:
            return 0

    def _build_add_edge(
        self, proposal: GraphChangeProposal,
        source_objects: Optional[Dict[Any, Any]], now: str, gc_id: str
    ) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        logical_edge_id = self._build_logical_edge_id(
            ce.source_node_id, ce.relation, ce.target_node_id
        )
        # 检查是否存在 >1（歧义）
        cnt = self._find_ambiguous_edge_count(logical_edge_id)
        if cnt > 1:
            raise ValueError(
                f"AMBIGUOUS_EDGE_IDENTITY: "
                f"逻辑边 {logical_edge_id} 有 {cnt} 条记录"
            )

        # 查找最新逻辑边
        existing = self._find_latest_logical_edge(logical_edge_id)
        if existing is not None:
            # 复用现有 edge_id
            edge_id = existing.get("edge_id", logical_edge_id)
        else:
            edge_id = logical_edge_id

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

    def _build_retire_edge(
        self, proposal: GraphChangeProposal, now: str, gc_id: str
    ) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        # valid_to 仅从 Proposal，never auto-now
        if ce.valid_to is None:
            raise ValueError(
                "RETIRE_EDGE_REQUIRES_VALID_TO: "
                f"retire_edge proposal 必须提供 valid_to，"
                f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
            )
        logical_edge_id = self._build_logical_edge_id(
            ce.source_node_id, ce.relation, ce.target_node_id
        )
        existing = self._find_latest_logical_edge(logical_edge_id)
        if existing is not None:
            edge_id = existing.get("edge_id", logical_edge_id)
        else:
            edge_id = logical_edge_id
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

    def _build_modify_edge(
        self, proposal: GraphChangeProposal, now: str, gc_id: str
    ) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None
        logical_edge_id = self._build_logical_edge_id(
            ce.source_node_id, ce.relation, ce.target_node_id
        )
        existing = self._find_latest_logical_edge(logical_edge_id)
        if existing is not None:
            edge_id = existing.get("edge_id", logical_edge_id)
        else:
            edge_id = logical_edge_id
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
        """构建当前知识的 canonical JSON 表示。

        add_node: 检查是否已存在则包含现有版本
        modify/retire_node: 查询最新 canonical
        """
        cn = proposal.candidate_node
        if cn is not None:
            if cn.existing_node_id is not None:
                existing = self._get_latest_node(cn.existing_node_id)
                if existing is not None:
                    return _canonical_json(existing)
            else:
                # add_node: 尝试用 node_id 查找
                resolved = self._try_resolve_node_id(proposal)
                if resolved:
                    existing = self._get_latest_node(resolved)
                    if existing is not None:
                        return _canonical_json(existing)
        return ""

    def _try_resolve_node_id(self, proposal: GraphChangeProposal) -> Optional[str]:
        """尝试解析 add_node 的 node_id（与 _resolve_entity_id 回退逻辑一致）。"""
        cn = proposal.candidate_node
        if cn is None:
            return None
        if cn.node_type == "Company":
            return f"company:{cn.name}"
        return None

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
            # 检查节点是否已存在
            resolved_id = self._try_resolve_node_id(proposal)
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

    @staticmethod
    def _merge_conflicts(
        proposal_conflicts: List[str],
        builder_conflicts: List[str],
    ) -> List[str]:
        """合并冲突列表，stable dedup + sorted order。"""
        merged: Set[str] = set()
        for c in proposal_conflicts:
            if c.strip():
                merged.add(c.strip())
        for c in builder_conflicts:
            if c.strip():
                merged.add(c.strip())
        return sorted(merged)


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
