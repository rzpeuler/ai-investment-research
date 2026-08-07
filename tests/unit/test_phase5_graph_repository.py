"""Phase 5 M2 GraphRepository 测试（架构评审修正版）。

覆盖：
- 节点 v1 插入 / 回放 / 冲突
- 节点 1→2 pass, 首个 v2 fail, 1→3 fail
- 边等价操作
- GraphReview 插入 / 回放 / 冲突
- 不可变版本冲突滚回
- 事务滚回
- canonical JSON 幂等比较（separators）
- seed_ontology 全量预检查 + 摘要字段
- generic upsert 不可用于 graph 表
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from research_os.models import (
    GraphNode, GraphEdge, GraphReview, GraphReviewer,
)
from research_os.knowledge.repository import GraphRepository
from research_os.storage.db import Database, TABLES, PK_COLUMNS

T0 = "2026-08-07T17:00:00+08:00"
T1 = "2026-08-07T18:00:00+08:00"
_GC_ID = "11111111-1111-1111-1111-111111111111"
_HASH = "a" * 64


@pytest.fixture()
def repo(tmp_path):
    db = Database(tmp_path / "test.db")
    db.migrate()
    r = GraphRepository(db)
    yield r
    db.close()


def _make_node(node_id="industry:test", version=1, name="测试行业", **kw):
    defaults = {
        "node_id": node_id, "node_type": "Industry", "name": name,
        "aliases": [], "description": "", "status": "active",
        "valid_from": None, "valid_to": None, "evidence_ids": [],
        "version": version, "last_reviewed_at": None,
        "review_status": "approved", "origin_kind": "governance_seed",
        "originating_graph_change_id": None, "created_at": T0,
    }
    defaults.update(kw)
    return GraphNode(**defaults)


def _make_edge(edge_id="edge:governance:abc", source="n1", relation="BELONGS_TO", target="n2", version=1, **kw):
    defaults = {
        "edge_id": edge_id, "source_node_id": source,
        "relation": relation, "target_node_id": target,
        "attributes": {}, "assertion_type": "GOVERNANCE",
        "valid_from": None, "valid_to": None, "confidence": 1.0,
        "evidence_ids": [], "review_status": "approved",
        "version": version, "originating_graph_change_id": None,
        "created_at": T0, "last_reviewed_at": None,
    }
    defaults.update(kw)
    return GraphEdge(**defaults)


def _make_review(review_id="33333333-3333-3333-3333-333333333333", **kw):
    reviewer = GraphReviewer(reviewer_id="human:tester")
    defaults = {
        "review_id": review_id, "graph_change_id": _GC_ID,
        "decision": "approved", "reviewer": reviewer,
        "reviewed_at": T1, "candidate_hash": _HASH,
        "resulting_graph_change_id": None, "review_patch": [], "notes": "",
    }
    defaults.update(kw)
    return GraphReview(**defaults)


# ===== node v1 =====

def test_node_v1_insert(repo):
    node = _make_node()
    result = repo.append_node(node)
    assert result == "inserted"
    fetched = repo.get_node_version("industry:test", 1)
    assert fetched is not None
    assert fetched["node_id"] == "industry:test"
    assert fetched["version"] == 1


def test_node_v1_replay_idempotent(repo):
    node = _make_node()
    assert repo.append_node(node) == "inserted"
    assert repo.append_node(node) == "idempotent_noop"


def test_node_v1_replay_different_payload_conflict(repo):
    n1 = _make_node()
    assert repo.append_node(n1) == "inserted"
    n2 = _make_node(name="不同的名称")
    with pytest.raises(ValueError, match="IMMUTABLE_VERSION_CONFLICT"):
        repo.append_node(n2)


# ===== node version chain =====

def test_node_v1_to_v2_pass(repo):
    node_v1 = _make_node()
    repo.append_node(node_v1)
    node_v2 = _make_node(node_id="industry:test", version=2, name="更新名称")
    result = repo.append_node(node_v2)
    assert result == "inserted"
    fetched = repo.get_node_version("industry:test", 2)
    assert fetched["name"] == "更新名称"


def test_node_first_v2_fail(repo):
    node_v2 = _make_node(node_id="industry:new", version=2)
    with pytest.raises(ValueError, match="VERSION_VIOLATION"):
        repo.append_node(node_v2)


def test_node_v1_to_v3_skip_fail(repo):
    node_v1 = _make_node()
    repo.append_node(node_v1)
    node_v3 = _make_node(node_id="industry:test", version=3)
    with pytest.raises(ValueError, match="VERSION_GAP"):
        repo.append_node(node_v3)


# ===== edge =====

def test_edge_v1_insert(repo):
    edge = _make_edge()
    result = repo.append_edge(edge)
    assert result == "inserted"
    fetched = repo.get_edge_version("edge:governance:abc", 1)
    assert fetched is not None


def test_edge_v1_replay_idempotent(repo):
    edge = _make_edge()
    assert repo.append_edge(edge) == "inserted"
    assert repo.append_edge(edge) == "idempotent_noop"


def test_edge_v1_replay_different_payload_conflict(repo):
    e1 = _make_edge()
    assert repo.append_edge(e1) == "inserted"
    e2 = _make_edge(confidence=0.5)
    with pytest.raises(ValueError, match="IMMUTABLE_VERSION_CONFLICT"):
        repo.append_edge(e2)


def test_edge_v1_to_v2_pass(repo):
    e1 = _make_edge()
    repo.append_edge(e1)
    e2 = _make_edge(version=2, confidence=0.9)
    result = repo.append_edge(e2)
    assert result == "inserted"


def test_edge_first_v2_fail(repo):
    e2 = _make_edge(edge_id="edge:governance:xyz", version=2)
    with pytest.raises(ValueError, match="VERSION_VIOLATION"):
        repo.append_edge(e2)


# ===== review =====

def test_review_insert(repo):
    # 先插入一条 graph_change 以满足 FK
    repo._db._conn.execute(
        "INSERT INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("11111111-1111-1111-1111-111111111111", "{}", "add_node", "candidate", T0),
    )
    review = _make_review()
    result = repo.append_review(review)
    assert result == "inserted"
    fetched = repo.get_review("33333333-3333-3333-3333-333333333333")
    assert fetched is not None


def test_review_replay_idempotent(repo):
    repo._db._conn.execute(
        "INSERT INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("11111111-1111-1111-1111-111111111111", "{}", "add_node", "candidate", T0),
    )
    review = _make_review()
    assert repo.append_review(review) == "inserted"
    assert repo.append_review(review) == "idempotent_noop"


def test_review_replay_different_payload_conflict(repo):
    repo._db._conn.execute(
        "INSERT INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("11111111-1111-1111-1111-111111111111", "{}", "add_node", "candidate", T0),
    )
    r1 = _make_review()
    assert repo.append_review(r1) == "inserted"
    r2 = _make_review(notes="changed")
    with pytest.raises(ValueError, match="IMMUTABLE_REVIEW_CONFLICT"):
        repo.append_review(r2)


# ===== canonical JSON =====

def test_canonical_json_compact(repo):
    """验证 canonical JSON 使用 separators(',', ':')。"""
    node = _make_node()
    payload = repo._dump_canonical_json(node)
    # compact JSON 不应包含空格
    assert "  " not in payload
    assert '": ' not in payload  # 紧密格式


def test_canonical_json_deterministic(repo):
    """两次 dump 同一对象得到完全相同的 JSON。"""
    node = _make_node()
    p1 = repo._dump_canonical_json(node)
    p2 = repo._dump_canonical_json(node)
    assert p1 == p2


# ===== transaction rollback =====

def test_transaction_rollback_on_node_conflict(repo):
    """节点冲突时事务回滚，已插入的节点不应保留。"""
    node = _make_node()
    repo.append_node(node)
    node2 = _make_node(node_id="industry:test2")

    with pytest.raises(ValueError):
        with repo._db.transaction() as conn:
            repo.append_node(node2, conn=conn)
            # 也插入一条边
            edge = _make_edge()
            repo.append_edge(edge, conn=conn)
            # 然后故意触发节点冲突
            repo.append_node(_make_node(name="冲突名称"), conn=conn)  # 相同 id/v1

    # 节点2和边都应回滚
    assert repo.get_node_version("industry:test2", 1) is None
    assert repo.get_edge_version("edge:governance:abc", 1) is None


# ===== seed_ontology =====

def test_seed_ontology_fresh(repo):
    nodes = [_make_node(node_id="industry:s1"), _make_node(node_id="industry:s2")]
    edges = [_make_edge(edge_id="e1", source="industry:s1", target="industry:s2")]
    summary = repo.seed_ontology(
        nodes=nodes, edges=edges,
        ontology_id="test_graph", ontology_version=1,
        ontology_sha256="a" * 64, dry_run=False,
    )
    assert summary["nodes_inserted"] == 2
    assert summary["edges_inserted"] == 1
    assert summary["nodes_idempotent"] == 0
    assert summary["edges_idempotent"] == 0
    assert summary["status"] == "ok"
    assert summary["ontology_id"] == "test_graph"
    assert "ontology_sha256" in summary


def test_seed_ontology_idempotent_second_run(repo):
    nodes = [_make_node(node_id="industry:s1")]
    edges = []
    repo.seed_ontology(nodes=nodes, edges=edges, ontology_id="t", ontology_version=1,
                        ontology_sha256="a" * 64, dry_run=False)
    # Second run
    summary = repo.seed_ontology(nodes=nodes, edges=edges, ontology_id="t", ontology_version=1,
                                  ontology_sha256="a" * 64, dry_run=False)
    assert summary["nodes_inserted"] == 0
    assert summary["nodes_idempotent"] == 1
    assert summary["edges_inserted"] == 0


def test_seed_ontology_conflict_rollback(repo):
    """Preflight 检测到冲突时应在写入前抛出，不允许部分写入。"""
    nodes = [_make_node(node_id="industry:s1")]
    repo.seed_ontology(nodes=nodes, edges=[], ontology_id="t", ontology_version=1,
                        ontology_sha256="a" * 64, dry_run=False)
    # 不同 payload 的相同 ID 应触发冲突
    nodes2 = [_make_node(node_id="industry:s1", name="改名")]
    with pytest.raises(ValueError, match="IMMUTABLE_VERSION_CONFLICT"):
        repo.seed_ontology(nodes=nodes2, edges=[], ontology_id="t", ontology_version=1,
                           ontology_sha256="a" * 64, dry_run=False)
    # 验证计数器未变
    assert repo.count_nodes() == 1


def test_seed_ontology_dry_run(repo):
    nodes = [_make_node(node_id="industry:s1"), _make_node(node_id="industry:s2")]
    edges = [_make_edge(edge_id="e1", source="industry:s1", target="industry:s2")]
    summary = repo.seed_ontology(
        nodes=nodes, edges=edges,
        ontology_id="test", ontology_version=1,
        ontology_sha256="a" * 64, dry_run=True,
    )
    assert summary["dry_run"] is True
    assert summary["nodes_would_insert"] == 2
    assert summary["edges_would_insert"] == 1
    assert summary["nodes_inserted"] == 0
    assert repo.count_nodes() == 0


def test_seed_ontology_summary_fields(repo):
    """验证 summary 包含所有必需字段。"""
    summary = repo.seed_ontology(
        nodes=[], edges=[],
        ontology_id="t", ontology_version=1,
        ontology_sha256="a" * 64, dry_run=False,
    )
    required = {
        "status", "dry_run", "ontology_id", "ontology_version",
        "ontology_sha256", "nodes_total", "edges_total",
        "nodes_inserted", "edges_inserted",
        "nodes_idempotent", "edges_idempotent",
        "nodes_would_insert", "edges_would_insert",
        "migration_required", "conflicts", "db_path",
    }
    assert required <= set(summary.keys())
    assert summary["ontology_id"] == "t"
    assert summary["nodes_total"] == 0


# ===== generic upsert not available for graph tables =====

def test_generic_upsert_raises_for_graph_tables(repo):
    """graph_* 表不在 generic TABLES/PK_COLUMNS 中，无法走 generic upsert。"""
    assert "GraphNode" not in TABLES
    assert "GraphEdge" not in TABLES
    assert "GraphReview" not in TABLES
    assert "graph_nodes" not in PK_COLUMNS
    assert "graph_edges" not in PK_COLUMNS
    assert "graph_reviews" not in PK_COLUMNS
    assert "graph_applications" not in PK_COLUMNS
