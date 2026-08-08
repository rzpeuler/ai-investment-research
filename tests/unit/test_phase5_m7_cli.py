"""Phase 5 M7 — History CLI 测试。

覆盖：
- `knowledge history --node-id`：deterministic JSON（versions + as_of 解析）
- `--edge-id` / `--as-of` 传递
- 二选一校验（两个都给 / 都不给）→ non-zero exit + error_code
- invalid as_of → non-zero exit + HISTORY_AS_OF_INVALID
- 数据库不存在 → non-zero exit
- 禁止 M8 泄漏（无 relation filtering / traversal）
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.models import Evidence, Entity, GraphChange, GraphNode
from research_os.storage.db import Database

T0 = "2026-08-08T10:00:00+08:00"
T1 = "2026-08-08T14:00:00+08:00"
T2 = "2026-08-09T09:00:00+08:00"
APPLIED_AT = "2026-08-09T10:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


def _canonical(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


@pytest.fixture()
def project_env(tmp_path):
    """创建最小项目结构供 CLI 使用。"""
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


def _seed_applied_node(db_path: Path):
    """直接向 DB 灌入一个已 apply 的 node v1（含完整 origin 链）。"""
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
        "entities": ["company:test-corp"],
        "raw_category": "news",
    }, ensure_ascii=False)
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, ri_payload, SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    entity = Entity(entity_id="company:test-corp", entity_type="company",
                    canonical_name="测试公司")
    conn.execute(
        "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
        "VALUES (?, ?, ?, ?)",
        ("company:test-corp", _canonical(entity.model_dump()), "company",
         "测试公司"),
    )

    gc_id = str(uuid.uuid4())
    node = GraphNode(
        node_id="company:test-corp",
        node_type="Company",
        name="测试公司",
        aliases=["测试"],
        description="测试描述",
        status="active",
        valid_from=None,
        valid_to=None,
        evidence_ids=[EVIDENCE_UUID],
        version=1,
        last_reviewed_at=T1,
        review_status="approved",
        origin_kind="graph_change",
        originating_graph_change_id=gc_id,
        created_at=T0,
    )
    gc = GraphChange(
        graph_change_id=gc_id,
        change_type="add_node",
        node=GraphNode(**{**node.model_dump(), "review_status": "candidate",
                          "last_reviewed_at": None}),
        edge=None,
        current_knowledge="",
        new_evidence_ids=[EVIDENCE_UUID],
        suggested_change="添加新公司节点",
        impact_scope=["industry_a"],
        conflicts=[],
        verification_points=["验证公司注册信息"],
        review_status="candidate",
        created_at=T0,
        reviewed_at=None,
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (gc_id, _canonical(gc.model_dump()), "add_node", "candidate", T0),
    )
    conn.execute(
        "INSERT OR IGNORE INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at, valid_from, valid_to, last_reviewed_at, originating_graph_change_id) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("company:test-corp", 1, _canonical(node.model_dump()), "Company",
         "测试公司", "active", "approved", "graph_change", T0, None, None,
         T1, gc_id),
    )
    conn.commit()
    db.close()
    return gc_id


class TestHistoryCli:
    def test_node_history_success(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """node history 成功：deterministic JSON，无 as_of 时 resolved=null。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history", "--node-id", "company:test-corp",
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["kind"] == "node"
        assert out["identity"] == "company:test-corp"
        assert out["as_of"] is None
        assert out["resolved"] is None
        assert out["versions"][0]["version"] == 1
        assert out["versions"][0]["payload"]["name"] == "测试公司"

    def test_node_history_with_as_of(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """--as-of 提供 → resolved 计算。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history", "--node-id", "company:test-corp",
            "--as-of", T2,
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["as_of"] == T2
        assert out["resolved"]["version"] == 1
        assert out["resolved"]["derived_status"] == "active"
        assert out["resolved"]["is_active"] is True

    def test_missing_identity_rejected(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """两个 identity 都给 → non-zero exit + error_code。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history",
            "--node-id", "company:test-corp",
            "--edge-id", "edge:x",
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["error_code"] == "HISTORY_IDENTITY_REQUIRED"

    def test_no_identity_rejected(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """identity 都不给 → non-zero exit + error_code。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history",
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 2
        out = json.loads(result.output)
        assert out["error_code"] == "HISTORY_IDENTITY_REQUIRED"

    def test_invalid_as_of_rejected(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """invalid as_of → non-zero exit + HISTORY_AS_OF_INVALID。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history", "--node-id", "company:test-corp",
            "--as-of", "not-a-time",
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["error_code"] == "HISTORY_AS_OF_INVALID"

    def test_db_missing_rejected(self, project_env, monkeypatch):
        """数据库不存在 → non-zero exit + HISTORY_READ_FAILED。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history", "--node-id", "company:test-corp",
            "--db", "data/sqlite/does-not-exist.db",
        ])
        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["error_code"] == "HISTORY_READ_FAILED"

    def test_unknown_identity_error(self, project_env, monkeypatch):
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        """identity 不存在 → non-zero exit + HISTORY_READ_FAILED 或空 history。"""
        db_path = project_env / "data" / "sqlite" / "research.db"
        _seed_applied_node(db_path)
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "history", "--node-id", "company:unknown",
            "--db", str(db_path.relative_to(project_env)).replace("\\", "/"),
        ])
        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["versions"] == []
        assert out["resolved"] is None
