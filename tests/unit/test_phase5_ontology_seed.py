"""Phase 5 M2 Ontology Seed 测试（架构评审修正版）。

覆盖：
- 34/31 计数正确
- BELONGS_TO 方向 child→parent（IndustrySegment → Industry）
- edge ID 前缀 "edge:governance:"
- edge ID 稳定（相同输入得到相同结果）
- 节点仅含 node_id/node_type/name（无 aliases/description）
- 未知 node_type 失败
- Company 节点失败
- 重复 node 失败
- 重复 edge 失败
- 缺失端点失败
- ontology_version != 1 失败
- ontology_id 不为 "industry_graph" 失败
- ontology_id 为比较正确的字符串
- 顶层键缺漏/多余失败
- seed_created_at 必须来自 YAML
- 元信息含 ontology_sha256
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
import yaml

from research_os.knowledge.ontology import (
    load_ontology,
    _deterministic_edge_id,
    _ALLOWED_NODE_TYPES,
    _ALLOWED_RELATIONS,
    _FORBIDDEN_NODE_TYPES,
    OntologyLoadError,
)
from research_os.models import GraphNode, GraphEdge


# ---- YAML fixture helpers ----

def _build_yaml(*, ontology_id="industry_graph", ontology_version=1,
                seed_created_at="2026-08-07T17:34:00+08:00",
                nodes=None, edges=None):
    return {
        "ontology_id": ontology_id,
        "ontology_version": ontology_version,
        "seed_created_at": seed_created_at,
        "nodes": nodes or [],
        "edges": edges or [],
    }


def _write_yaml(data: dict, path: Path):
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _basic_nodes():
    return [
        {"node_id": "industry:ai_hardware", "node_type": "Industry", "name": "AI硬件"},
        {"node_id": "industry_segment:ai_hardware:compute_chip", "node_type": "IndustrySegment", "name": "算力芯片"},
        {"node_id": "industry:semiconductor", "node_type": "Industry", "name": "半导体"},
        {"node_id": "industry_segment:semiconductor:eda_ip", "node_type": "IndustrySegment", "name": "EDA与IP"},
    ]


def _basic_edges():
    return [
        {"source_node_id": "industry_segment:ai_hardware:compute_chip",
         "relation": "BELONGS_TO",
         "target_node_id": "industry:ai_hardware"},
        {"source_node_id": "industry_segment:semiconductor:eda_ip",
         "relation": "BELONGS_TO",
         "target_node_id": "industry:semiconductor"},
    ]


# ---- 实际 YAML 加载 ----

def test_load_actual_ontology():
    """加载真实 industry_graph_v1.yaml 并验证计数。"""
    project_root = Path(__file__).resolve().parents[2]
    ont_path = project_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    assert ont_path.exists(), f"本体文件不存在: {ont_path}"
    nodes, edges, meta = load_ontology(ont_path)
    assert len(nodes) == 34, f"预期 34 节点，实际 {len(nodes)}"
    assert len(edges) == 31, f"预期 31 边，实际 {len(edges)}"


def test_actual_ontology_edge_id_prefix():
    """所有边 ID 以 'edge:governance:' 开头。"""
    project_root = Path(__file__).resolve().parents[2]
    ont_path = project_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    nodes, edges, meta = load_ontology(ont_path)
    for edge in edges:
        assert edge.edge_id.startswith("edge:governance:"), f"边 {edge.edge_id} 不以 edge:governance: 开头"


def test_actual_ontology_belongs_to_direction():
    """BELONGS_TO 方向为 child(IndustrySegment) → parent(Industry)。"""
    project_root = Path(__file__).resolve().parents[2]
    ont_path = project_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    nodes, edges, meta = load_ontology(ont_path)
    for edge in edges:
        assert edge.relation == "BELONGS_TO"
        assert edge.source_node_id.startswith("industry_segment:"), \
            f"期望 source 为 industry_segment，实际 {edge.source_node_id}"
        assert edge.target_node_id.startswith("industry:"), \
            f"期望 target 为 industry，实际 {edge.target_node_id}"


def test_actual_ontology_nodes_no_aliases_description():
    """节点仅含 node_id/node_type/name。"""
    project_root = Path(__file__).resolve().parents[2]
    ont_path = project_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    nodes, edges, meta = load_ontology(ont_path)
    for node in nodes:
        assert node.aliases == [], f"节点 {node.node_id} aliases 应为空列表"
        assert node.description == "", f"节点 {node.node_id} description 应为空字符串"


def test_actual_ontology_meta():
    """元信息含 ontology_id/ontology_version/ontology_sha256。"""
    project_root = Path(__file__).resolve().parents[2]
    ont_path = project_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    nodes, edges, meta = load_ontology(ont_path)
    assert meta["ontology_id"] == "industry_graph"
    assert meta["ontology_version"] == 1
    assert len(meta["ontology_sha256"]) == 64


# ---- 合成 YAML 测试 ----

def test_ontology_id_valid(tmp_path):
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    _write_yaml(data, tmp_path / "test.yaml")
    nodes, edges, meta = load_ontology(tmp_path / "test.yaml")
    assert meta["ontology_id"] == "industry_graph"


def test_ontology_id_wrong_fails(tmp_path):
    data = _build_yaml(ontology_id="wrong_id", nodes=_basic_nodes(), edges=_basic_edges())
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="ontology_id"):
        load_ontology(tmp_path / "test.yaml")


def test_ontology_version_wrong_fails(tmp_path):
    data = _build_yaml(ontology_version=2, nodes=_basic_nodes(), edges=_basic_edges())
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="ontology_version"):
        load_ontology(tmp_path / "test.yaml")


def test_missing_seed_created_at_fails(tmp_path):
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    del data["seed_created_at"]
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="缺失"):
        load_ontology(tmp_path / "test.yaml")


def test_extra_top_key_fails(tmp_path):
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    data["extra_key"] = "intruder"
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="未知顶层键"):
        load_ontology(tmp_path / "test.yaml")


def test_missing_top_key_fails(tmp_path):
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    del data["nodes"]
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="缺失顶层键"):
        load_ontology(tmp_path / "test.yaml")


# ---- 节点门禁 ----

def test_unknown_node_type_fails(tmp_path):
    nodes = [{"node_id": "unknown:t", "node_type": "UnknownType", "name": "x"}]
    data = _build_yaml(nodes=nodes, edges=[])
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="仅允许"):
        load_ontology(tmp_path / "test.yaml")


def test_company_node_fails(tmp_path):
    nodes = [{"node_id": "company:600519.SH", "node_type": "Company", "name": "茅台"}]
    data = _build_yaml(nodes=nodes, edges=[])
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="禁止 Company"):
        load_ontology(tmp_path / "test.yaml")


def test_duplicate_node_fails(tmp_path):
    nodes = [
        {"node_id": "industry:t", "node_type": "Industry", "name": "x"},
        {"node_id": "industry:t", "node_type": "Industry", "name": "y"},
    ]
    data = _build_yaml(nodes=nodes, edges=[])
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="重复 node_id"):
        load_ontology(tmp_path / "test.yaml")


# ---- 边门禁 ----

def test_duplicate_edge_fails(tmp_path):
    nodes = _basic_nodes()
    edges = [
        {"source_node_id": "industry_segment:ai_hardware:compute_chip",
         "relation": "BELONGS_TO",
         "target_node_id": "industry:ai_hardware"},
        {"source_node_id": "industry_segment:ai_hardware:compute_chip",
         "relation": "BELONGS_TO",
         "target_node_id": "industry:ai_hardware"},
    ]
    data = _build_yaml(nodes=nodes, edges=edges)
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="重复边"):
        load_ontology(tmp_path / "test.yaml")


def test_edge_missing_endpoint_fails(tmp_path):
    nodes = _basic_nodes()
    edges = [
        {"source_node_id": "industry_segment:nonexistent",
         "relation": "BELONGS_TO",
         "target_node_id": "industry:ai_hardware"},
    ]
    data = _build_yaml(nodes=nodes, edges=edges)
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="不在节点集中"):
        load_ontology(tmp_path / "test.yaml")


def test_edge_unknown_relation_fails(tmp_path):
    nodes = _basic_nodes()
    edges = [
        {"source_node_id": "industry_segment:ai_hardware:compute_chip",
         "relation": "SUPPLIES",
         "target_node_id": "industry:ai_hardware"},
    ]
    data = _build_yaml(nodes=nodes, edges=edges)
    _write_yaml(data, tmp_path / "test.yaml")
    with pytest.raises(OntologyLoadError, match="仅允许"):
        load_ontology(tmp_path / "test.yaml")


# ---- edge ID ----

def test_deterministic_edge_id():
    """验证 edge ID 格式和行为。"""
    eid = _deterministic_edge_id("src", "BELONGS_TO", "tgt")
    assert eid.startswith("edge:governance:"), f"实际: {eid}"
    # 确定性
    eid2 = _deterministic_edge_id("src", "BELONGS_TO", "tgt")
    assert eid == eid2
    # 不同输入产生不同输出
    eid3 = _deterministic_edge_id("src2", "BELONGS_TO", "tgt")
    assert eid != eid3


def test_edge_id_stable_across_loads(tmp_path):
    """同一 YAML 多次加载产生相同 edge_id。"""
    _write_yaml(_build_yaml(nodes=_basic_nodes(), edges=_basic_edges()), tmp_path / "t.yaml")
    _, edges1, _ = load_ontology(tmp_path / "t.yaml")
    _, edges2, _ = load_ontology(tmp_path / "t.yaml")
    for e1, e2 in zip(edges1, edges2):
        assert e1.edge_id == e2.edge_id


# ---- ontology_sha256 ----

def test_ontology_sha256_stable(tmp_path):
    """同一 YAML 文件两次加载得到相同的 SHA256。"""
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    path = tmp_path / "test.yaml"
    _write_yaml(data, path)
    _, _, meta1 = load_ontology(path)
    _, _, meta2 = load_ontology(path)
    assert meta1["ontology_sha256"] == meta2["ontology_sha256"]


def test_ontology_sha256_changes_with_content(tmp_path):
    """修改 YAML 内容后 SHA256 变化。"""
    data = _build_yaml(nodes=_basic_nodes(), edges=_basic_edges())
    path1 = tmp_path / "a.yaml"
    _write_yaml(data, path1)
    _, _, meta1 = load_ontology(path1)

    # 缩减为仅第一个子图（2 节点 1 边），边仍然有效
    data["nodes"] = [_basic_nodes()[0], _basic_nodes()[1]]
    data["edges"] = [_basic_edges()[0]]
    path2 = tmp_path / "b.yaml"
    _write_yaml(data, path2)
    _, _, meta2 = load_ontology(path2)
    assert meta1["ontology_sha256"] != meta2["ontology_sha256"]


# ---- M2-R2 BELONGS_TO 方向硬门禁攻击 ----

def test_belongs_to_reverse_direction_fails(tmp_path):
    """Industry BELONGS_TO IndustrySegment -> FAIL."""
    data = _build_yaml(
        nodes=[
            {"node_id": "industry:test", "node_type": "Industry", "name": "Test"},
            {"node_id": "industry_segment:test:child", "node_type": "IndustrySegment", "name": "Child"},
        ],
        edges=[
            {"source_node_id": "industry:test", "relation": "BELONGS_TO", "target_node_id": "industry_segment:test:child"},
        ],
    )
    _write_yaml(data, tmp_path / "bad.yaml")
    with pytest.raises(OntologyLoadError, match="方向错误"):
        load_ontology(tmp_path / "bad.yaml")

def test_belongs_to_segment_to_segment_fails(tmp_path):
    """IndustrySegment BELONGS_TO IndustrySegment -> FAIL."""
    data = _build_yaml(
        nodes=[
            {"node_id": "industry_segment:test:a", "node_type": "IndustrySegment", "name": "A"},
            {"node_id": "industry_segment:test:b", "node_type": "IndustrySegment", "name": "B"},
        ],
        edges=[
            {"source_node_id": "industry_segment:test:a", "relation": "BELONGS_TO", "target_node_id": "industry_segment:test:b"},
        ],
    )
    _write_yaml(data, tmp_path / "bad.yaml")
    with pytest.raises(OntologyLoadError, match="方向错误"):
        load_ontology(tmp_path / "bad.yaml")

def test_belongs_to_industry_to_industry_fails(tmp_path):
    """Industry BELONGS_TO Industry -> FAIL."""
    data = _build_yaml(
        nodes=[
            {"node_id": "industry:test:a", "node_type": "Industry", "name": "A"},
            {"node_id": "industry:test:b", "node_type": "Industry", "name": "B"},
        ],
        edges=[
            {"source_node_id": "industry:test:a", "relation": "BELONGS_TO", "target_node_id": "industry:test:b"},
        ],
    )
    _write_yaml(data, tmp_path / "bad.yaml")
    with pytest.raises(OntologyLoadError, match="方向错误"):
        load_ontology(tmp_path / "bad.yaml")
