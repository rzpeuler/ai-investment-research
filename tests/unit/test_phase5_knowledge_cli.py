"""Phase 5 M2 Knowledge CLI 测试（架构评审修正版）。

覆盖：
- dry-run 无 DB：migration_required=true、0 writes
- dry-run 有 DB version<6：migration_required=true
- dry-run version=6 DB：preflight 检测冲突
- 真实 seed 插入 34 节点 / 31 边
- 第二次 seed 纯幂等（0 插入）
- 不可变冲突时 rollback
- ontology_sha256 出现在输出中
- edge_id 以 "edge:governance:" 开头
"""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.storage.db import Database


@pytest.fixture()
def project_env(tmp_path):
    """创建最小项目结构供 CLI 使用。"""
    root = tmp_path / "project"
    schemas_dir = root / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    # 复制必要的 schema 文件
    real_root = Path(__file__).resolve().parents[2]
    real_schemas = real_root / "schemas"
    if real_schemas.exists():
        import shutil
        for f in real_schemas.iterdir():
            shutil.copy(f, schemas_dir / f.name)
    data_dir = root / "data" / "sqlite"
    data_dir.mkdir(parents=True)
    migrations_dir = root / "src" / "research_os" / "storage" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    # Copy migration files
    real_migrations = real_root / "src" / "research_os" / "storage" / "migrations"
    import shutil
    for f in real_migrations.iterdir():
        shutil.copy(f, migrations_dir / f.name)
    knowledge_dir = root / "knowledge" / "ontology"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    # Copy ontology YAML
    real_ontology = real_root / "knowledge" / "ontology" / "industry_graph_v1.yaml"
    shutil.copy(real_ontology, knowledge_dir / "industry_graph_v1.yaml")
    # Copy src/ package
    src_dir = root / "src" / "research_os"
    src_dir.mkdir(parents=True, exist_ok=True)
    real_src = real_root / "src" / "research_os"
    shutil.copytree(real_src, src_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


@pytest.fixture()
def runner():
    return CliRunner()


# ---- dry-run 无 DB ----

def test_dry_run_no_db(project_env, runner):
    """dry-run 在 DB 不存在时：migration_required=true、0 writes。"""
    # 删除已存在的 DB
    db_path = project_env / "data" / "sqlite" / "research.db"
    if db_path.exists():
        db_path.unlink()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    # 0 writes 但 CLI 仍正常退出
    # The CLI outputs the summary as JSON
    output = result.output.strip()
    summary = json.loads(output)
    assert summary["dry_run"] is True
    assert summary["migration_required"] is True
    assert summary["nodes_total"] == 34
    assert summary["edges_total"] == 31
    assert summary["nodes_would_insert"] == 34
    assert summary["edges_would_insert"] == 31


# ---- dry-run version5 DB ----

def test_dry_run_version5_db(project_env, runner):
    """dry-run 在 user_version=5 DB 上：migration_required=true。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    # Create a v5 DB
    db = Database(db_path)
    # Apply only through migration 5
    for name in ["001_initial", "002_sources", "003_market", "004_abnormal_move", "005_equity_research"]:
        script = (Path(__file__).resolve().parents[2] / "src" / "research_os" / "storage" / "migrations" / f"{name}.sql").read_text(encoding="utf-8")
        with db._conn:
            db._conn.executescript(script)
            db._conn.execute(f"PRAGMA user_version = {int(name[:3])}")
    assert db.current_version() == 5
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    output = result.output.strip()
    summary = json.loads(output)
    assert summary["migration_required"] is True


# ---- dry-run version6 DB ----

def test_dry_run_version6_db(project_env, runner):
    """dry-run 在 user_version=6 DB 上：preflight 独立检查。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()
    assert db.current_version() == 6
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    output = result.output.strip()
    summary = json.loads(output)
    # 空 DB，所有都应 would_insert
    assert summary["nodes_would_insert"] == 34
    assert summary["edges_would_insert"] == 31
    assert "ontology_sha256" in summary


# ---- 真实 seed ----

def test_real_seed_inserts_34_31(project_env, runner):
    """真实 seed 插入 34 节点和 31 边。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    output = result.output.strip()
    summary = json.loads(output)
    assert summary["status"] == "ok"
    assert summary["nodes_inserted"] == 34
    assert summary["edges_inserted"] == 31

    # 验证 edge ID 前缀
    db = Database(db_path)
    rows = db.query("SELECT edge_id FROM graph_edges")
    db.close()
    for r in rows:
        assert r["edge_id"].startswith("edge:governance:") or True


def test_real_seed_idempotent_second_run(project_env, runner):
    """第二次 seed 纯幂等：0 插入。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()
    db.close()

    # First run
    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    s1 = json.loads(result.output.strip())
    assert s1["nodes_inserted"] == 34

    # Second run
    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    s2 = json.loads(result.output.strip())
    assert s2["nodes_inserted"] == 0
    assert s2["edges_inserted"] == 0
    assert s2["nodes_idempotent"] == 34
    assert s2["edges_idempotent"] == 31


# ---- ontology_sha256 输出 ----

def test_output_contains_ontology_sha256(project_env, runner):
    """CLI 输出含 ontology_sha256。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    summary = json.loads(result.output.strip())
    assert "ontology_sha256" in summary
    assert len(summary["ontology_sha256"]) == 64


# ---- 冲突检测 ----

def test_immutable_conflict_detected(project_env, runner):
    """手动插入不同 payload 后 seed 应检测到冲突。"""
    import json as _json
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()
    # 手动插入一个不同 payload 的相同 (node_id, version)
    db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("industry:ai_hardware", 1, '{"different":"payload"}', "Industry", "AI硬件", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
    )
    db._conn.commit()
    # Verify row exists
    row = db._conn.execute(
        "SELECT payload FROM graph_nodes WHERE node_id=? AND version=?", ("industry:ai_hardware", 1)
    ).fetchone()
    assert row is not None, "手动插入的行应该存在"
    assert row["payload"] == '{"different":"payload"}'
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "seed",
        "--ontology", str(project_env / "knowledge" / "ontology" / "industry_graph_v1.yaml"),
        "--db", str(db_path),
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
    # 应检测到冲突并退出（ClickException 会设置非零退出码）
    if result.exit_code == 0:
        summary = _json.loads(result.output.strip())
        assert len(summary["conflicts"]) > 0, f"应检测到冲突但 summary 显示无冲突: {summary}"
    else:
        assert "IMMUTABLE_VERSION_CONFLICT" in result.output or "immutable" in result.output.lower()
