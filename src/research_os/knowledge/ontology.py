"""Ontology loader：解析 YAML 本体文件 → 构造 GraphNode/GraphEdge 列表（Phase 5 M2 架构评审修正版）。

确定性代码；零 LLM。所有对象在返回前必须通过 Schema 校验。

M2 修正要点：
- 严格顶层键：ontology_id / ontology_version / seed_created_at / nodes / edges
- seed_created_at 必须来自 YAML（不允许代码默认值）
- edge_id 格式：edge:governance:<sha256>
- Loader 始终设置 aliases=[], description=""（YAML 不再包含这些字段）
- 硬性门禁包括 ontology_id 和 ontology_version 校验
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

import yaml

from research_os.models import GraphNode, GraphEdge
from research_os.validators.schema_validator import validate_model

# 允许的节点类型（governance seed 范围）
_ALLOWED_NODE_TYPES = {"Industry", "IndustrySegment"}

# 允许的关系类型（首版骨架只支持分类关系）
_ALLOWED_RELATIONS = {"BELONGS_TO"}

# 禁止的节点类型（Company 不得借 governance seed 绕过 Evidence）
_FORBIDDEN_NODE_TYPES = {"Company"}

# 顶层键白名单 + 必需键
_REQUIRED_TOP_KEYS = {"ontology_id", "ontology_version", "seed_created_at", "nodes", "edges"}
_TOP_KEY_WHITELIST = _REQUIRED_TOP_KEYS


class OntologyLoadError(ValueError):
    """本体加载硬性错误（不可恢复）。"""


def _deterministic_edge_id(source_node_id: str, relation: str, target_node_id: str) -> str:
    """确定性 edge_id：edge:governance:<sha256(source|relation|target) lowercase hex>."""
    raw = f"{source_node_id}|{relation}|{target_node_id}"
    return "edge:governance:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
    - 顶层键缺失或多余 → 拒绝
    - ontology_id 不为 "industry_graph" → 拒绝
    - ontology_version 不为 1 → 拒绝
    - seed_created_at 缺失 → 拒绝
    - Company 节点类型 → 拒绝
    - 未知 node_type → 拒绝
    - 未知 relation → 拒绝
    - 重复 node_id → 拒绝
    - 重复 edge 定义 → 拒绝
    - 边引用缺失端点 → 拒绝
    - version != 1 → 拒绝
    - Schema 校验失败 → 拒绝

    Returns:
        (nodes: List[GraphNode], edges: List[GraphEdge], meta: dict)
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"本体文件不存在: {path}")

    raw_bytes = path.read_bytes()
    raw = yaml.safe_load(raw_bytes.decode("utf-8"))
    if not isinstance(raw, dict):
        raise OntologyLoadError("本体文件顶层必须是 dict/mapping")

    # ---- 严格顶层键校验 ----
    top_keys = set(raw.keys())
    missing = _REQUIRED_TOP_KEYS - top_keys
    extra = top_keys - _TOP_KEY_WHITELIST
    if missing:
        raise OntologyLoadError(f"缺失顶层键: {sorted(missing)}")
    if extra:
        raise OntologyLoadError(f"未知顶层键: {sorted(extra)}")

    ontology_id = raw["ontology_id"]
    ontology_version = raw["ontology_version"]
    seed_created_at = raw["seed_created_at"]

    # 硬性门禁：ontology_id
    if not isinstance(ontology_id, str) or ontology_id != "industry_graph":
        raise OntologyLoadError(
            f"ontology_id 必须为 'industry_graph'，当前为 {ontology_id!r}"
        )

    # 硬性门禁：ontology_version
    if not isinstance(ontology_version, int) or ontology_version != 1:
        raise OntologyLoadError(
            f"ontology_version 必须为 1，当前为 {ontology_version!r}"
        )

    # 硬性门禁：seed_created_at
    if not isinstance(seed_created_at, str) or not seed_created_at.strip():
        raise OntologyLoadError("seed_created_at 必须为非空字符串")

    # 计算 YAML 原始字节的 SHA256（供 CLI/测试使用）
    ontology_sha256 = hashlib.sha256(raw_bytes).hexdigest()

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
                aliases=[],  # 严格始终为空
                description="",  # 严格始终为空
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

        # 硬性门禁：BELONGS_TO 方向 = IndustrySegment → Industry
        if rel == "BELONGS_TO":
            src_type = node_map[src].get("node_type", "")
            tgt_type = node_map[tgt].get("node_type", "")
            if src_type != "IndustrySegment" or tgt_type != "Industry":
                raise OntologyLoadError(
                    f"edges[{i}] BELONGS_TO 方向错误："
                    f"source={src}({src_type}) → target={tgt}({tgt_type})；"
                    f"必须为 IndustrySegment → Industry"
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

    meta = {
        "ontology_id": ontology_id,
        "ontology_version": ontology_version,
        "seed_created_at": seed_created_at,
        "ontology_sha256": ontology_sha256,
    }
    return nodes, edges, meta
