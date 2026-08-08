"""M3 Candidate Builder：确定性 GraphChange 构造器（零 LLM）。

从通过校验的 GraphChangeProposal 构造正式 GraphChange 对象。
- stable graph_change_id：SHA256(proposal.model_dump() + current_knowledge + deterministic_conflicts) → UUID5
- Replay first：compute ID → check persisted → return canonical with persisted created_at
- 节点构建：add_node（实体身份解析 → 现有节点检查 → 版本递增）、modify_attribute、retire_node
- 边构建：add_edge（triple lookup, reuse existing edge_id; fresh → edge:graph:sha256）、modify_attribute、retire_edge
- current_knowledge：最新节点/边的 canonical JSON
- 版本规则：fresh=1，existing=N+1
- 实体身份：从源对象 entity_id/company_entity_id/*_entity_id/*_entity_ids/subject_entities/object_entities/target_entities 读取，entities 表验证 ALL types
- 0→IDENTITY_RESOLUTION_REQUIRED，>1→AMBIGUOUS_ENTITY_IDENTITY，无 name/alias/slug/hash fallback
- Retire: valid_to 仅从 Proposal，never auto-now
- 认知门禁：SOURCE_OPINION/HYPOTHESIS-only + FACT edge → EPISTEMIC_ESCALATION_REJECTED
- 确定性冲突：proposal.conflicts + builder conflicts，stable dedup+order
- 证据闭包：仅允许 source-derived evidence（source.evidence_ids + counter_evidence_ids + Evidence self）；外部证据 → PROPOSAL_REJECTED
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
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
    Entity,
)
from research_os.storage.db import Database
from research_os.validators.schema_validator import validate_instance
from research_os.utils.time import now_iso, parse_iso


def validate_proposal_lifecycle_times(
    proposal: GraphChangeProposal,
) -> Optional[str]:
    """M7-R1：proposal 生命周期时间确定性校验（单一 authority）。

    CandidatePipeline 与 GraphChangeBuilder 共用，禁止复制两套规则。

    - modify_attribute：candidate_node/candidate_edge.valid_from 必须非 null
      且合法 ISO → 缺失 `TRANSITION_TIME_MISSING` / 非法 `TRANSITION_TIME_INVALID`
    - retire_node / retire_edge：candidate_*.valid_from / valid_to 必须非 null、
      valid_from == valid_to（= retire_at）、均合法 ISO
      → 否则 `RETIRE_TIME_INVALID`
    - add_node / add_edge：不要求生命周期时间

    Returns:
        None（通过）或 error code 字符串。
    """
    pt = proposal.proposal_type
    if pt == "modify_attribute":
        target = proposal.candidate_node or proposal.candidate_edge
        if target is None or target.valid_from is None:
            return "TRANSITION_TIME_MISSING"
        try:
            parse_iso(target.valid_from)
        except ValueError:
            return "TRANSITION_TIME_INVALID"
        return None
    if pt in ("retire_node", "retire_edge"):
        target = (
            proposal.candidate_node
            if pt == "retire_node"
            else proposal.candidate_edge
        )
        if target is None or target.valid_from is None or target.valid_to is None:
            return "RETIRE_TIME_INVALID"
        if target.valid_from != target.valid_to:
            return "RETIRE_TIME_INVALID"
        try:
            parse_iso(target.valid_from)
            parse_iso(target.valid_to)
        except ValueError:
            return "RETIRE_TIME_INVALID"
        return None
    return None  # add_node / add_edge 不要求

# ---- 受保护的节点类型（只允许 governance seed）----
_PROTECTED_NODE_TYPES = {"Industry", "IndustrySegment"}

# ---- 认知受限的 Claim 类型：不允许独立支撑 FACT edge ----
_EPISTEMIC_RESTRICTED_CLAIM_TYPES = {"SOURCE_OPINION", "HYPOTHESIS", "MODEL_INFERENCE"}

# ---- GraphNodeType → Entity.entity_type 映射 ----
_NODE_TYPE_TO_ENTITY_TYPE: Dict[str, str] = {
    "Company": "company",
    "Product": "product",
    "Technology": "technology",
    "Material": "material",
    "Equipment": "equipment",
    "Application": "application",
    "Policy": "policy",
    "Event": "event",
    "Metric": "metric",
    "PersonOrInstitution": "person_or_institution",
    "Report": "report",
    "InvestmentTheme": "investment_theme",
    "Industry": "industry",
    "IndustrySegment": "industry_segment",
}


def _uuid5(namespace: str, name: str) -> str:
    """确定性 UUID5 生成。"""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{namespace}:{name}"))


def _sha256_hex(s: str) -> str:
    """SHA256 小写 hex。"""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def stable_evidence_merge(
    old_ids: List[str],
    new_ids: List[str],
) -> List[str]:
    """稳定证据合并：保留旧顺序，仅追加未出现的新 ID。

    保证：old_ids 的顺序原封不动，new_ids 中不在 old_ids 中的元素
    按 new_ids 顺序追加到末尾。去重但不排序。
    """
    seen = set(old_ids)
    result = list(old_ids)
    for eid in new_ids:
        if eid not in seen:
            seen.add(eid)
            result.append(eid)
    return result


@dataclass
class BuildResult:
    """GraphChangeBuilder.build() 的确定性和可审计返回类型。

    分离 graph_change 和 deterministic_conflicts，让 pipeline
    在构建后直接访问冲突列表进行 Pro escalation，而无需解析
    已合并到 gc.conflicts 中的最终列表。
    """
    graph_change: "GraphChange"
    deterministic_conflicts: List[str]


def _canonical_json(obj: Any) -> str:
    """确定性紧凑 JSON。"""
    if hasattr(obj, "model_dump"):
        d = obj.model_dump()
    else:
        d = obj
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _canonical_json_no_volatile(obj: Any) -> str:
    """确定性紧凑 JSON（排除 volatile 字段如 created_at）。"""
    if hasattr(obj, "model_dump"):
        d = obj.model_dump()
    else:
        d = obj
    # 排除 volatile 字段确保确定性
    for volatile_key in ("created_at", "last_reviewed_at", "reviewed_at", "call_id"):
        d.pop(volatile_key, None)
    return json.dumps(d, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_graph_change_id(
    proposal: GraphChangeProposal,
    current_knowledge: str,
    deterministic_conflicts: List[str],
    current_baseline: str,
) -> str:
    """确定性 GraphChange ID：
    SHA256(proposal.model_dump() + current_knowledge + deterministic_conflicts + evidence + baseline) → UUID5

    不含 created_at / call_id / random。同一 proposal+baseline → 同一 ID。
    """
    proposal_json = _canonical_json_no_volatile(proposal)
    conflicts_json = _canonical_json(sorted(deterministic_conflicts))
    combined = (
        proposal_json
        + current_knowledge
        + conflicts_json
        + (current_baseline or "")
    )
    sha = _sha256_hex(combined)
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
    ) -> BuildResult:
        """从 proposal 构造完整 GraphChange candidate。

        Args:
            proposal: 已通过校验的 GraphChangeProposal。
            source_objects: 源对象 dict {(Type, id): model}，用于实体身份解析和认知门禁。
            current_baseline: 当前图谱基线（可选，用于 ID 确定性）。
            supporting_evidence_ids: 允许使用的证据 ID 列表（source-derived only，闭包）。

        Returns:
            完整的 GraphChange 对象。

        Raises:
            ValueError: 实体解析失败、本体突变阻止、认知门禁拒绝、
                       证据闭包违规、冲突检测触发、生命周期时间不完整。
        """
        # ---- 0. M7-R1 lifecycle time gate（defense-in-depth：绕过 pipeline
        #      直接调用 builder 也必须拒绝不完整生命周期时间）----
        lifecycle_err = validate_proposal_lifecycle_times(proposal)
        if lifecycle_err is not None:
            raise ValueError(f"PROPOSAL_REJECTED: {lifecycle_err}")

        # ---- 1. 实体身份解析（先于 gc_id 计算，影响 current_knowledge）----
        self._check_ontology_protection(proposal)
        self._check_epistemic_gate(proposal, source_objects)

        ct = proposal.proposal_type
        resolved_entity_id: Optional[str] = None
        existing_node_info: Optional[Dict] = None
        builder_conflicts: List[str] = []
        if ct in ("add_node", "retire_node", "modify_attribute"):
            if proposal.candidate_node is not None:
                if ct == "add_node":
                    # 解析实体身份（先于所有其他计算）
                    resolved_entity_id = self._resolve_entity_id(
                        proposal, proposal.candidate_node, source_objects
                    )
                    # 检查是否已有同 entity 的节点（baseline lookup）
                    existing_node_info = self._get_latest_node(resolved_entity_id)

        # ---- 2. 证据闭包 ---- 必须从 source-derived set，拒绝外部证据
        sup_ids = supporting_evidence_ids or proposal.new_evidence_ids
        self._check_evidence_closure(proposal, sup_ids)

        # ---- 3. 确定性冲突（proposal.conflicts + builder conflicts，stable dedup+order）----
        builder_conflicts.extend(self.check_conflicts(proposal))
        # add add_node existing conflict if detected
        if ct == "add_node" and existing_node_info is not None:
            add_conflict = f"CURRENT_NODE_ALREADY_EXISTS: node_id={resolved_entity_id}"
            builder_conflicts.append(add_conflict)
        deterministic_conflicts = self._merge_conflicts(
            proposal.conflicts or [], builder_conflicts
        )

        # ---- 4. current_knowledge（先构建，参与 gc_id 确定性）----
        current_knowledge = self._build_current_knowledge(
            proposal, existing_node_info=existing_node_info
        )

        # ---- 5. graph_change_id（确定性）----
        gc_id = _stable_graph_change_id(
            proposal=proposal,
            current_knowledge=current_knowledge,
            deterministic_conflicts=deterministic_conflicts,
            current_baseline=current_baseline or "",
        )

        # ---- 6. Replay first ----
        replayed = self._replay(gc_id)
        if replayed is not None:
            return BuildResult(
                graph_change=replayed,
                deterministic_conflicts=builder_conflicts,
            )

        # ---- 7. 新 candidate：用 now_iso() ----
        now = now_iso()

        # ---- 8. 构造 node/edge（传入 gc_id 作为 originating_graph_change_id）----
        node: Optional[GraphNode] = None
        edge: Optional[GraphEdge] = None

        if ct in ("add_node", "retire_node", "modify_attribute"):
            if proposal.candidate_node is not None:
                if ct == "add_node":
                    node = self._build_add_node(
                        proposal, source_objects, now, gc_id,
                        entity_id=resolved_entity_id,
                        existing_node_info=existing_node_info,
                    )
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

        return BuildResult(
            graph_change=GraphChange(
                graph_change_id=gc_id,
                change_type=ct,
                node=node,
                edge=edge,
                current_knowledge=current_knowledge,
                new_evidence_ids=proposal.new_evidence_ids,  # 与 proposal 精确一致
                suggested_change=proposal.suggested_change,
                impact_scope=proposal.impact_scope,
                conflicts=deterministic_conflicts,
                verification_points=proposal.verification_points,
                review_status="candidate",
                created_at=now,
                reviewed_at=None,
            ),
            deterministic_conflicts=builder_conflicts,
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

    # ---- 证据闭包 ----

    @staticmethod
    def _check_evidence_closure(
        proposal: GraphChangeProposal,
        source_derived_evidence_ids: List[str],
    ) -> None:
        """验证 new_evidence_ids ⊆ source-derived evidence IDs（闭包）。

        拒绝任意外部扩展证据。Out-of-context Evidence → PROPOSAL_REJECTED。
        """
        allowed = set(source_derived_evidence_ids)
        for eid in proposal.new_evidence_ids:
            if eid not in allowed:
                raise ValueError(
                    f"PROPOSAL_REJECTED: evidence closure violation: "
                    f"evidence_id={eid} 不在 source-derived evidence 集合中"
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
        if proposal.proposal_type not in ("add_edge", "modify_attribute"):
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
    ) -> str:
        """从源对象和 entities 表推导 entity_id（ALL node types）。

        优先读取源对象的显式字段：
        - entity_id
        - company_entity_id
        - *_entity_id (singular)
        - *_entity_ids (plural, 提取每个元素)
        - subject_entities
        - object_entities
        - target_entities

        验证 entities 表：entity_id 必须存在且 entity_type 匹配 node_type 映射。
        0 → IDENTITY_RESOLUTION_REQUIRED（绝不使用 name/alias/slug/hash fallback）
        >1 → AMBIGUOUS_ENTITY_IDENTITY
        """
        candidate_entity_ids: List[str] = []

        # 从源对象提取
        if source_objects:
            for (st, sid), obj in source_objects.items():
                d = obj.model_dump() if hasattr(obj, "model_dump") else vars(obj)
                # entity_id (explicit)
                if "entity_id" in d and d["entity_id"]:
                    candidate_entity_ids.append(str(d["entity_id"]))
                # company_entity_id
                if "company_entity_id" in d and d["company_entity_id"]:
                    candidate_entity_ids.append(str(d["company_entity_id"]))
                # *_entity_id pattern (singular, not already handled)
                for key, val in d.items():
                    if key.endswith("_entity_id") and key not in ("entity_id", "company_entity_id"):
                        if isinstance(val, str) and val:
                            candidate_entity_ids.append(val)
                # *_entity_ids pattern (plural — extract each element)
                for key, val in d.items():
                    if key.endswith("_entity_ids") and isinstance(val, list):
                        for v in val:
                            if isinstance(v, str) and v:
                                candidate_entity_ids.append(v)
                # subject_entities
                if "subject_entities" in d and isinstance(d["subject_entities"], list):
                    for se in d["subject_entities"]:
                        if isinstance(se, str) and se:
                            candidate_entity_ids.append(se)
                # object_entities
                if "object_entities" in d and isinstance(d["object_entities"], list):
                    for oe in d["object_entities"]:
                        if isinstance(oe, str) and oe:
                            candidate_entity_ids.append(oe)
                # target_entities
                if "target_entities" in d and isinstance(d["target_entities"], list):
                    for te in d["target_entities"]:
                        if isinstance(te, str) and te:
                            candidate_entity_ids.append(te)

        # 去重（保持插入顺序）
        candidate_entity_ids = list(dict.fromkeys(candidate_entity_ids))

        # ── Schema-first 实体验证 + 实体类型过滤（先于歧义检查）──
        # 三步验证：validate_instance(raw) → Entity(**entity) → validate_instance(dump)
        # 任何一步失败都跳过该 entity
        # 然后按 entity_type 过滤
        expected_type = _NODE_TYPE_TO_ENTITY_TYPE.get(cn.node_type)
        if expected_type:
            filtered = []
            for eid in candidate_entity_ids:
                ent = self._db.get("entities", eid)
                if ent is None:
                    continue
                # Step 1: Schema-first validation on raw dict
                errors = validate_instance(ent, "entity")
                if errors:
                    continue
                # Step 2: Pydantic Entity construction
                try:
                    entity_obj = Entity(**ent)
                except Exception:
                    continue
                # Step 3: Schema validation on model_dump
                dumped = entity_obj.model_dump()
                errors2 = validate_instance(dumped, "entity")
                if errors2:
                    continue
                # Step 4: entity_type filtering
                if ent.get("entity_type") == expected_type:
                    filtered.append(eid)
            # UNCONDITIONAL: zero matches → IDENTITY_RESOLUTION_REQUIRED below
            candidate_entity_ids = filtered

        if len(candidate_entity_ids) == 0:
            # 绝不使用 name/alias/slug/hash fallback
            raise ValueError(
                "IDENTITY_RESOLUTION_REQUIRED: "
                f"无法从源对象解析 entity_id，节点类型={cn.node_type}，名称={cn.name}。"
                f"请确保源对象包含 explicit entity_id / company_entity_id / *_entity_id / *_entity_ids / subject_entities / object_entities / target_entities 字段。"
            )

        if len(candidate_entity_ids) > 1:
            raise ValueError(
                f"AMBIGUOUS_ENTITY_IDENTITY: "
                f"多个候选 entity_id: {candidate_entity_ids}"
            )

        resolved = candidate_entity_ids[0]

        # 验证 entities 表（ALL node types，不只是 Company）
        expected_entity_type = _NODE_TYPE_TO_ENTITY_TYPE.get(cn.node_type)
        if expected_entity_type is None:
            raise ValueError(
                f"IDENTITY_RESOLUTION_REQUIRED: "
                f"不支持的节点类型 {cn.node_type}，缺少 entity_type 映射"
            )
        entity = self._db.get("entities", resolved)
        if entity is None:
            raise ValueError(
                f"IDENTITY_RESOLUTION_REQUIRED: "
                f"entity_id={resolved} 不在 entities 表中"
            )
        # 验证 entity_type 匹配
        actual_entity_type = entity.get("entity_type")
        if actual_entity_type != expected_entity_type:
            raise ValueError(
                f"IDENTITY_RESOLUTION_REQUIRED: "
                f"entity_id={resolved} 的 entity_type={actual_entity_type}，"
                f"与节点类型 {cn.node_type} 要求的 entity_type={expected_entity_type} 不匹配"
            )
        # 确保该 entity 通过 Pydantic 构造 + model_dump → Schema
        try:
            obj = Entity(**entity)
            obj.model_dump()
        except Exception as exc:
            raise ValueError(
                f"IDENTITY_RESOLUTION_REQUIRED: "
                f"entity_id={resolved} 在 entities 表中但 Pydantic+Schema 校验失败: {exc}"
            )

        return resolved

    # ---- 节点构建 ----

    def _build_add_node(
        self, proposal: GraphChangeProposal,
        source_objects: Optional[Dict[Any, Any]], now: str, gc_id: str,
        entity_id: Optional[str] = None,
        existing_node_info: Optional[Dict] = None,
    ) -> GraphNode:
        cn = proposal.candidate_node
        assert cn is not None
        # entity_id 已由先前的 _resolve_entity_id 解析（如果未传入则在此处解析）
        if entity_id is None:
            entity_id = self._resolve_entity_id(proposal, cn, source_objects)
            existing_node_info = self._get_latest_node(entity_id)
        # Company: node_id == entity_id；其他类型同样使用 entity_id 作为 node_id
        node_id = entity_id
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
        # 证据闭包合并：读取最新持久化 evidence_ids，追加 proposal 新证据
        latest_ev: List[str] = []
        latest_node = self._get_latest_node(node_id)
        if latest_node:
            latest_ev = latest_node.get("evidence_ids") or []
        merged_evidence = stable_evidence_merge(latest_ev, proposal.new_evidence_ids)
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="retired",
            valid_from=cn.valid_from,
            valid_to=cn.valid_to,
            evidence_ids=merged_evidence,
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
        # 证据闭包合并：读取最新持久化 evidence_ids，追加 proposal 新证据
        latest_ev: List[str] = []
        latest_node = self._get_latest_node(node_id)
        if latest_node:
            latest_ev = latest_node.get("evidence_ids") or []
        merged_evidence = stable_evidence_merge(latest_ev, proposal.new_evidence_ids)
        return GraphNode(
            node_id=node_id,
            node_type=cn.node_type,
            name=cn.name,
            aliases=cn.aliases,
            description=cn.description,
            status="active",
            valid_from=cn.valid_from,
            valid_to=cn.valid_to,
            evidence_ids=merged_evidence,
            version=version,
            last_reviewed_at=None,
            review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=gc_id,
            created_at=now,
        )

    # ---- 边构建（triple identity via repository helper）----

    def _lookup_edge_by_triple(
        self, source_node_id: str, relation: str, target_node_id: str
    ) -> Tuple[int, Optional[str], Optional[str]]:
        """通过三元组 (source_node_id, relation, target_node_id) 查找边。

        直接在 graph_edges 表中按列查询（非猜测 hash）。

        Returns:
            (count, latest_edge_id, latest_payload_json):
            - count=0 → fresh（无现有边）
            - count=1 → reuse existing edge_id
            - count>1 → AMBIGUOUS_EDGE_IDENTITY

        注意：version 行（v1, v2 同 edge_id）不算歧义，因为我们查 DISTINCT edge_id。
        """
        try:
            rows = self._db._conn.execute(
                """SELECT DISTINCT edge_id, payload FROM graph_edges
                   WHERE source_node_id = ? AND relation = ? AND target_node_id = ?
                   ORDER BY edge_id, version DESC""",
                (source_node_id, relation, target_node_id),
            ).fetchall()
        except Exception:
            return (0, None, None)

        distinct_edge_ids = list(dict.fromkeys(r["edge_id"] for r in rows))

        if len(distinct_edge_ids) == 0:
            return (0, None, None)

        if len(distinct_edge_ids) > 1:
            return (len(distinct_edge_ids), None, None)

        # 恰好 1 个 edge_id
        edge_id = distinct_edge_ids[0]
        # 找最新版本 payload
        latest_payload = rows[0]["payload"] if rows else None
        return (1, edge_id, latest_payload)

    def _build_add_edge(
        self, proposal: GraphChangeProposal,
        source_objects: Optional[Dict[Any, Any]], now: str, gc_id: str
    ) -> GraphEdge:
        ce = proposal.candidate_edge
        assert ce is not None

        cnt, existing_edge_id, _ = self._lookup_edge_by_triple(
            ce.source_node_id, ce.relation, ce.target_node_id
        )

        if cnt > 1:
            raise ValueError(
                f"AMBIGUOUS_EDGE_IDENTITY: "
                f"三元组 (source={ce.source_node_id}, relation={ce.relation}, "
                f"target={ce.target_node_id}) 对应 {cnt} 个不同的 edge_id"
            )

        if cnt == 1 and existing_edge_id is not None:
            edge_id = existing_edge_id  # reuse existing（含 governance edges）
        else:
            # 0 → fresh edge_id: "edge:graph:" + sha256(source|relation|target) lowercase hex
            edge_id = "edge:graph:" + _sha256_hex(
                f"{ce.source_node_id}|{ce.relation}|{ce.target_node_id}"
            )[:64]

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

    def _check_edge_operational_conflicts(
        self, ce: GraphProposalEdge, existing_count: int
    ) -> List[str]:
        """边操作冲突检测。

        - add_edge 时 existing_count>0 → CURRENT_EDGE_ALREADY_EXISTS
        """
        conflicts: List[str] = []
        if existing_count == 1:
            conflicts.append(
                f"CURRENT_EDGE_ALREADY_EXISTS: "
                f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
            )
        return conflicts

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
        cnt, existing_edge_id, latest_payload_json = self._lookup_edge_by_triple(
            ce.source_node_id, ce.relation, ce.target_node_id
        )
        if cnt == 0:
            raise ValueError(
                f"CURRENT_EDGE_NOT_FOUND: "
                f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
            )
        if cnt > 1:
            raise ValueError(
                f"AMBIGUOUS_EDGE_IDENTITY: "
                f"三元组对应 {cnt} 个不同的 edge_id，无法确定 retire 目标"
            )
        edge_id = existing_edge_id
        version = self._next_version("graph_edges", "edge_id", edge_id)
        # 证据闭包合并：读取最新持久化 evidence_ids，追加 proposal 新证据
        latest_ev: List[str] = []
        if latest_payload_json:
            try:
                payload = json.loads(latest_payload_json)
                latest_ev = payload.get("evidence_ids") or []
            except (json.JSONDecodeError, TypeError):
                pass
        merged_evidence = stable_evidence_merge(latest_ev, proposal.new_evidence_ids)
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
            evidence_ids=merged_evidence,
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
        cnt, existing_edge_id, latest_payload_json = self._lookup_edge_by_triple(
            ce.source_node_id, ce.relation, ce.target_node_id
        )
        if cnt > 1:
            raise ValueError(
                f"AMBIGUOUS_EDGE_IDENTITY: "
                f"三元组对应 {cnt} 个不同的 edge_id"
            )
        if cnt == 0:
            # modify_edge missing → CURRENT_EDGE_NOT_FOUND，绝不 mint fresh
            raise ValueError(
                f"CURRENT_EDGE_NOT_FOUND: "
                f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
            )
        if existing_edge_id is None:
            raise ValueError(
                f"CURRENT_EDGE_NOT_FOUND: "
                f"三元组存在但无法解析 edge_id"
            )
        edge_id = existing_edge_id
        version = self._next_version("graph_edges", "edge_id", edge_id)
        # 证据闭包合并：读取最新持久化 evidence_ids，追加 proposal 新证据
        latest_ev: List[str] = []
        if latest_payload_json:
            try:
                payload = json.loads(latest_payload_json)
                latest_ev = payload.get("evidence_ids") or []
            except (json.JSONDecodeError, TypeError):
                pass
        merged_evidence = stable_evidence_merge(latest_ev, proposal.new_evidence_ids)
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
            evidence_ids=merged_evidence,
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

    def _build_current_knowledge(
        self, proposal: GraphChangeProposal,
        existing_node_info: Optional[Dict] = None,
    ) -> str:
        """构建当前知识的 canonical JSON 表示。

        add_node: 使用已解析的 existing_node_info（resolve identity 后查找）
        modify/retire_node: 查询最新 canonical
        """
        cn = proposal.candidate_node
        if cn is not None:
            if cn.existing_node_id is not None:
                existing = self._get_latest_node(cn.existing_node_id)
                if existing is not None:
                    return _canonical_json(existing)
            elif existing_node_info is not None:
                # add_node with resolved existing node info
                return _canonical_json(existing_node_info)
            # else: 新节点无需 current_knowledge

        # edge current_knowledge
        ce = proposal.candidate_edge
        if ce is not None:
            cnt, _, existing_payload = self._lookup_edge_by_triple(
                ce.source_node_id, ce.relation, ce.target_node_id
            )
            if cnt == 1 and existing_payload:
                return _canonical_json(json.loads(existing_payload))

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
        """确定性冲突检测（构建前调用）。

        使用显式 entity_id 检查（不使用 name-based 回退）。
        """
        conflicts: List[str] = []
        cn = proposal.candidate_node

        if proposal.proposal_type in ("modify_attribute", "retire_node"):
            if cn is not None and cn.existing_node_id is not None:
                existing = self._get_latest_node(cn.existing_node_id)
                if existing is None:
                    conflicts.append(
                        f"CURRENT_NODE_NOT_FOUND: existing_node_id={cn.existing_node_id}"
                    )

        # 边冲突检测
        ce = proposal.candidate_edge
        if ce is not None:
            cnt, _, _ = self._lookup_edge_by_triple(
                ce.source_node_id, ce.relation, ce.target_node_id
            )
            if proposal.proposal_type == "add_edge":
                # add_edge fresh: 无冲突；add_edge existing: CURRENT_EDGE_ALREADY_EXISTS
                if cnt == 0:
                    pass  # fresh add_edge → no conflict
                elif cnt == 1:
                    conflicts.append(
                        f"CURRENT_EDGE_ALREADY_EXISTS: "
                        f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
                    )
            elif proposal.proposal_type in ("modify_edge", "modify_attribute"):
                if cnt == 0:
                    conflicts.append(
                        f"CURRENT_EDGE_NOT_FOUND: "
                        f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
                    )
            elif proposal.proposal_type == "retire_edge":
                if cnt == 0:
                    conflicts.append(
                        f"CURRENT_EDGE_NOT_FOUND: "
                        f"source={ce.source_node_id} relation={ce.relation} target={ce.target_node_id}"
                    )
                elif cnt > 1:
                    conflicts.append(
                        f"AMBIGUOUS_EDGE_IDENTITY: "
                        f"三元组对应 {cnt} 个不同的 edge_id"
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
    """硬性门禁：evidence 存在性验证（含 Pydantic+Schema 校验）。"""
    errors: List[str] = []
    for eid in evidence_ids:
        record = db.get("evidence", eid)
        if record is None:
            errors.append(f"Evidence {eid} 不存在")
            continue
        # 验证可通过 Pydantic 构造
        try:
            from research_os.models import Evidence
            Evidence(**record)
        except Exception as exc:
            errors.append(f"Evidence {eid} Pydantic 校验失败: {exc}")
    return len(errors) == 0, errors
