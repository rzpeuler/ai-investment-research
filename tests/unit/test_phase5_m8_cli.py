"""Phase 5 M8 — Query / Context CLI 测试。

覆盖（Decision #38.8.39 + 任务书 §42/43/48）：
- `knowledge query`：--node-id inspection / --depth traversal / --edge-id direct
- as_of 必填；node/edge exactly one；--edge-id 禁止 --depth > 0；--depth 3 拒绝
- `knowledge context`：node root + Evidence summaries
- 错误：non-zero exit + structured JSON（status=error / error_code / errors）
- 无 traceback；deterministic JSON
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.models import Entity, Evidence, GraphChange, GraphEdge, GraphNode
from research_os.storage.db import Database

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture()
def project_env(tmp_path):
    """创建最小项目结构供 CLI 使用（对齐 M7 CLI 测试）。"""
    root = tmp_path / "project"
    schemas_dir = root / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    real_root = Path(__file__).resolve().parents[2]
    real_schemas = real_root / "schemas"
    if real_schemas.exists():
        for f in real_schemas.iterdir():
            shutil.copy(f, schemas_dir / f.name)
    data_dir = root / "data" / "sqlite"
    data_dir.mkdir(parents=True)

    migrations_dir = root / "src" / "research_os" / "storage" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    real_migrations = real_root / "src" / "research_os" / "storage" / "migrations"
    for f in real_migrations.iterdir():
        shutil.copy(f, migrations_dir / f.name)

    knowledge_dir = root / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    src_dir = root / "src" / "research_os"
    src_dir.mkdir(parents=True, exist_ok=True)
    real_src = real_root / "src" / "research_os"
    shutil.copytree(real_src, src_dir, dirs_exist_ok=True)

    return root


def _seed_graph(db_path: Path):
    """构造 2 nodes + 1 FACT edge + 1 Evidence（含完整 origin 链）。"""
    db = Database(db_path)
    db.initialize()
    conn = db._conn

    ev = Evidence(
        evidence_id=EVIDENCE_UUID,
        source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID,
        title="测试证据",
        publisher="测试发布者",
        published_at="2026-08-01T10:00:00+08:00",
        retrieved_at="2026-08-02T10:00:00+08:00",
        url="https://example.com",
        excerpt="测试摘录",
        evidence_type="news_report",
        independence_group="group-1",
        source_tier="B",
        access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID, _canonical(ev.model_dump()), SOURCE_UUID,
         RAW_ITEM_UUID, "group-1", "B"),
    )
    ri_payload = json.dumps({
        "raw_item_id": RAW_ITEM_UUID,
        "source_id": SOURCE_UUID,
        "external_id": "ext-001",
        "url": "https://example.com",
        "title": "测试",
        "publisher": "测试",
        "author": "测试作者",
        "published_at": "2026-08-01T10:00:00+08:00",
        "retrieved_at": "2026-08-02T10:00:00+08:00",
        "content_hash": SHA256_ZEROS,
        "content_excerpt": "测试摘录",
        "content_storage": "metadata_and_excerpt",
        "language": "zh-CN",
        "access_status": "ok",
        "entities": ["company:a"],
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    for eid, etype, name in (("company:a", "company", "公司A"),
                             ("company:b", "company", "公司B")):
        entity = Entity(entity_id=eid, entity_type=etype, canonical_name=name)
        conn.execute(
            "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
            "VALUES (?, ?, ?, ?)",
            (eid, _canonical(entity.model_dump()), etype, name),
        )

    gc_node_a = str(uuid.uuid4())
    node_a = GraphNode(
        node_id="company:a", node_type="Company", name="公司A", aliases=[],
        description="测试", status="active", valid_from=None, valid_to=None,
        evidence_ids=[EVIDENCE_UUID], version=1, last_reviewed_at=T1,
        review_status="approved", origin_kind="graph_change",
        originating_graph_change_id=gc_node_a, created_at=T0,
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gc_node_a, _canonical(GraphChange(
            graph_change_id=gc_node_a, change_type="add_node",
            node=GraphNode(**{**node_a.model_dump(), "review_status": "candidate",
                              "last_reviewed_at": None}),
            edge=None, current_knowledge="", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="添加节点A", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate", created_at=T0,
            reviewed_at=None).model_dump()), "add_node", "candidate", T0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("company:a", 1, _canonical(node_a.model_dump()), "Company", "公司A",
         "active", "approved", "graph_change", T0, None, None, T1, gc_node_a),
    )

    gc_node_b = str(uuid.uuid4())
    node_b = GraphNode(
        node_id="company:b", node_type="Company", name="公司B", aliases=[],
        description="测试", status="active", valid_from=None, valid_to=None,
        evidence_ids=[EVIDENCE_UUID], version=1, last_reviewed_at=T1,
        review_status="approved", origin_kind="graph_change",
        originating_graph_change_id=gc_node_b, created_at=T0,
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gc_node_b, _canonical(GraphChange(
            graph_change_id=gc_node_b, change_type="add_node",
            node=GraphNode(**{**node_b.model_dump(), "review_status": "candidate",
                              "last_reviewed_at": None}),
            edge=None, current_knowledge="", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="添加节点B", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate", created_at=T0,
            reviewed_at=None).model_dump()), "add_node", "candidate", T0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("company:b", 1, _canonical(node_b.model_dump()), "Company", "公司B",
         "active", "approved", "graph_change", T0, None, None, T1, gc_node_b),
    )

    gc_edge = str(uuid.uuid4())
    edge = GraphEdge(
        edge_id="edge:ab", source_node_id="company:a", relation="SUPPLIES",
        target_node_id="company:b", attributes={}, assertion_type="FACT",
        valid_from=None, valid_to=None, confidence=0.9,
        evidence_ids=[EVIDENCE_UUID], review_status="approved", version=1,
        originating_graph_change_id=gc_edge, created_at=T0, last_reviewed_at=T1,
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gc_edge, _canonical(GraphChange(
            graph_change_id=gc_edge, change_type="add_edge", node=None,
            edge=GraphEdge(**{**edge.model_dump(), "review_status": "candidate",
                              "last_reviewed_at": None}),
            current_knowledge="", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="添加边", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate", created_at=T0,
            reviewed_at=None).model_dump()), "add_edge", "candidate", T0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, valid_from, valid_to, confidence, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("edge:ab", 1, _canonical(edge.model_dump()), "company:a", "SUPPLIES",
         "company:b", "FACT", "approved", T0, None, None, 0.9, T1, gc_edge),
    )
    conn.commit()
    db.close()


def _rel(project_env, db_path):
    return str(db_path.relative_to(project_env)).replace("\\", "/")


class TestQueryCli:
    def test_query_node_inspection(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:a",
            "--as-of", T2, "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["kind"] == "node"
        assert out["identity"] == "company:a"
        assert out["derived_status"] == "active"
        assert out["is_active"] is True

    def test_query_node_depth1_traversal(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:a",
            "--as-of", T2, "--depth", "1",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert {w["node_id"] for w in out["nodes"]} == {"company:a", "company:b"}
        assert [w["edge_id"] for w in out["edges"]] == ["edge:ab"]
        assert out["epistemic"]["facts"] == ["edge:ab"]

    def test_query_edge_direct(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--edge-id", "edge:ab",
            "--as-of", T2, "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["kind"] == "edge"
        assert out["payload"]["relation"] == "SUPPLIES"

    def test_query_missing_as_of(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:a",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["status"] == "error"
        assert out["error_code"] == "QUERY_AS_OF_REQUIRED"

    def test_query_identity_required(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--as-of", T2,
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_IDENTITY_REQUIRED"

    def test_query_edge_with_depth_rejected(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--edge-id", "edge:ab",
            "--as-of", T2, "--depth", "1",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_DEPTH_EXCEEDED"

    def test_query_depth_3_rejected(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:a",
            "--as-of", T2, "--depth", "3",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_DEPTH_EXCEEDED"

    def test_query_node_not_found(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:missing",
            "--as-of", T2, "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_NODE_NOT_FOUND"

    def test_query_db_missing(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "missing.db"
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:a",
            "--as-of", T2, "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_READ_FAILED"

    def test_query_no_traceback(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "query", "--node-id", "company:missing",
            "--as-of", T2, "--db", _rel(project_env, db_path),
        ])
        assert "Traceback" not in result.output
        assert "traceback" not in result.output.lower()


class TestContextCli:
    def test_context_success(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "context", "--node-id", "company:a",
            "--as-of", T2, "--depth", "1",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["root"]["node_id"] == "company:a"
        assert out["evidence_ids"] == [EVIDENCE_UUID]
        assert out["evidence"][0]["evidence_id"] == EVIDENCE_UUID
        assert "excerpt" not in out["evidence"][0]
        assert out["conflicts"] == []

    def test_context_missing_as_of(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        result = CliRunner().invoke(cli, [
            "knowledge", "context", "--node-id", "company:a",
            "--db", _rel(project_env, db_path),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["error_code"] == "QUERY_AS_OF_REQUIRED"

    def test_context_deterministic_json(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_graph(db_path)
        runner = CliRunner()
        args = ["knowledge", "context", "--node-id", "company:a",
                "--as-of", T2, "--depth", "1",
                "--db", _rel(project_env, db_path)]
        r1 = runner.invoke(cli, args)
        r2 = runner.invoke(cli, args)
        assert r1.exit_code == 0 and r2.exit_code == 0
        assert json.loads(r1.output) == json.loads(r2.output)
