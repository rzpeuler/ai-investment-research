"""Ontology loader：解析 YAML 本体文件 → 构造 GraphNode/GraphEdge 列表（Phase 5 M2）。

确定性代码；零 LLM。所有对象在返回前必须通过 Schema 校验。
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from research_os.models import GraphNode, GraphEdge
from research_os.validators.schema_validator import validate_model

# 允许的节点类型（governance seed 范围）
_ALLOWED_NODE_TYPES = {"Industry", "IndustrySegment"}

# 允许的关系类型（首版骨架只支持分类关系）
_ALLOWED_RELATIONS = {"BELONGS_TO"}

# 禁止的节点类型（Company 不得借 governance seed 绕过 Evidence）
_FORBIDDEN_NODE_TYPES = {"Company"}

# 种子固定 created_at
DEFAULT_SEED_CREATED_AT = "2026-08-07T17:34:00+08:00"


class OntologyLoadError(ValueError):
    """本体加载硬性错误（不可恢复）。"""


def _deterministic_edge_id(source_node_id: str, relation: str, target_node_id: str) -> str:
    """确定性 edge_id：sha256(source + "|" + relation + "|" + target) lowercase hex。"""
    raw = f"{source_node_id}|{relation}|{target_node_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_model_or_raise(obj, label: str) -> None:
    """Schema 校验，失败抛出 OntologyLoadError。"""
    errors = validate_model(obj)
    if errors:
        raise OntologyLoadError(
            f"Schema validation failed for {label}: {'; '.join(errors)}"
        )


def load_ontology(path: str | Path) -> Tuple[List[GraphNode], List[GraphEdge], dict]:
    """解析 YAML 本体文件 → (nodes, edges, 元信息)。

    硬性门禁（失败即抛 OntologyLoadError）：
    - Company 节点类型  → 拒绝
    - 未知 node_type    → 拒绝
    - 未知 relation     → 拒绝
    - 重复 node_id      → 拒绝
    - 重复 edge 定义    → 拒绝
    - 边引用缺失端点   → 拒绝
    - version != 1      → 拒绝
    - Schema 校验失败   → 拒绝

    Returns:
        (nodes: List[GraphNode], edges: List[GraphEdge], meta: dict)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"本体文件不存在: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise OntologyLoadError("本体文件顶层必须是 dict/mapping")

    meta = raw.get("meta", {})
    seed_created_at = meta.get("seed_created_at", DEFAULT_SEED_CREATED_AT)

    # ---- 收集 node IDs（去重检查） ----
    node_id_set: set = set()
    raw_nodes = raw.get("nodes", [])
    if not isinstance(raw_nodes, list):
        raise OntologyLoadError("'nodes' 必须是 list")

    node_map: Dict[str, dict] = {}
    for i, nd in enumerate(raw_nodes):
        if not isinstance(nd, dict):
            raise OntologyLoadError(f"nodes[{i}] 必须是 dict/mapping")
        nid = nd.get("node_id")
        if not nid:
            raise OntologyLoadError(f"nodes[{i}] 缺少 node_id")
        if nid in node_id_set:
            raise OntologyLoadError(f"重复 node_id: {nid}")
        node_id_set.add(nid)
        node_map[nid] = nd

    # ---- 硬性门禁：节点类型 ----
    for nid, nd in node_map.items():
        nt = nd.get("node_type", "")
        if nt in _FORBIDDEN_NODE_TYPES:
            raise OntologyLoadError(
                f"节点 {nid} 类型为 {nt}：governance seed 禁止 Company 类型"
            )
        if nt not in _ALLOWED_NODE_TYPES:
            raise OntologyLoadError(
                f"节点 {nid} 类型为 {nt!r}：governance seed 仅允许 "
                f"{sorted(_ALLOWED_NODE_TYPES)}"
            )

    # ---- 构造节点 ----
    nodes: List[GraphNode] = []
    for nid, nd in node_map.items():
        try:
            node = GraphNode(
                node_id=nid,
                node_type=nd["node_type"],
                name=nd["name"],
                aliases=list(nd.get("aliases", [])),
                description=str(nd.get("description", "")),
                status="active",
                valid_from=None,
                valid_to=None,
                evidence_ids=[],
                version=1,
                last_reviewed_at=None,
                review_status="approved",
                origin_kind="governance_seed",
                originating_graph_change_id=None,
                created_at=seed_created_at,
            )
        except Exception as e:
            raise OntologyLoadError(f"节点 {nid} 构造失败: {e}") from e
        _validate_model_or_raise(node, f"node {nid}")
        nodes.append(node)

    # ---- 构造边 ----
    raw_edges = raw.get("edges", [])
    if not isinstance(raw_edges, list):
        raise OntologyLoadError("'edges' 必须是 list")

    # 去重（按 edge_id 去重）
    edge_set: set = set()
    edges: List[GraphEdge] = []
    for i, ed in enumerate(raw_edges):
        if not isinstance(ed, dict):
            raise OntologyLoadError(f"edges[{i}] 必须是 dict/mapping")
        src = ed.get("source_node_id", "")
        rel = ed.get("relation", "")
        tgt = ed.get("target_node_id", "")

        if not src or not rel or not tgt:
            raise OntologyLoadError(
                f"edges[{i}] 缺少 source_node_id/relation/target_node_id"
            )

        # 硬性门禁：关系类型
        if rel not in _ALLOWED_RELATIONS:
            raise OntologyLoadError(
                f"edges[{i}] relation={rel!r}：governance seed 仅允许 "
                f"{sorted(_ALLOWED_RELATIONS)}"
            )

        # 硬性门禁：端点存在
        if src not in node_id_set:
            raise OntologyLoadError(
                f"edges[{i}] source_node_id={src} 不在节点集中"
            )
        if tgt not in node_id_set:
            raise OntologyLoadError(
                f"edges[{i}] target_node_id={tgt} 不在节点集中"
            )

        edge_id = _deterministic_edge_id(src, rel, tgt)

        # 去重
        edge_key = (src, rel, tgt)
        if edge_key in edge_set:
            raise OntologyLoadError(
                f"重复边: {src} --[{rel}]--> {tgt}"
            )
        edge_set.add(edge_key)

        try:
            edge = GraphEdge(
                edge_id=edge_id,
                source_node_id=src,
                relation=rel,
                target_node_id=tgt,
                attributes={},
                assertion_type="GOVERNANCE",
                valid_from=None,
                valid_to=None,
                confidence=1.0,
                evidence_ids=[],
                review_status="approved",
                version=1,
                originating_graph_change_id=None,
                created_at=seed_created_at,
                last_reviewed_at=None,
            )
        except Exception as e:
            raise OntologyLoadError(f"edges[{i}] 构造失败: {e}") from e
        _validate_model_or_raise(edge, f"edge {edge_id}")
        edges.append(edge)

    return nodes, edges, meta
