"""Phase 5 M3 Candidate CLI 测试。

覆盖：
- dry-run 预检输出
- 不支持的源类型参数错误
- source 格式错误
- 数据库不存在错误
- JSON 摘要输出
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.models import Event, Evidence
from research_os.storage.db import Database
from research_os.utils.id import new_uuid

T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def project_env(tmp_path):
    """创建最小项目结构供 CLI 使用。"""
    root = tmp_path / "project"
    schemas_dir = root / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    # 复制 schema 文件
    real_root = Path(__file__).resolve().parents[2]
    real_schemas = real_root / "schemas"
    if real_schemas.exists():
        for f in real_schemas.iterdir():
            shutil.copy(f, schemas_dir / f.name)
    data_dir = root / "data" / "sqlite"
    data_dir.mkdir(parents=True)

    # 复制迁移文件
    migrations_dir = root / "src" / "research_os" / "storage" / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)
    real_migrations = real_root / "src" / "research_os" / "storage" / "migrations"
    for f in real_migrations.iterdir():
        shutil.copy(f, migrations_dir / f.name)

    # 复制 knowledge
    knowledge_dir = root / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)

    # 复制 src/ 包
    src_dir = root / "src" / "research_os"
    src_dir.mkdir(parents=True, exist_ok=True)
    real_src = real_root / "src" / "research_os"
    shutil.copytree(real_src, src_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def db_with_event(project_env):
    """创建已迁移的 DB 并插入一个 Event。"""
    db_path = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.migrate()

    ev_id = new_uuid()
    event = Event(
        event_id=ev_id, event_type="test", subject_entities=["company:test"],
        object_entities=[], event_time=T0, announced_at=T0, effective_at=None,
        status="announced", summary="事件摘要", quantitative_fields={},
        industry_coordinates=[], novelty=0.5, impact_direction="neutral",
        impact_horizon="short", evidence_ids=[], confidence=0.5, conflicts=[],
    )
    db.upsert(event)
    db.close()
    return str(db_path), ev_id


# ---- dry-run ----

def test_candidates_dry_run(project_env, db_with_event, runner):
    """dry-run 返回正确的 JSON 摘要。"""
    db_path, ev_id = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", f"Event:{ev_id}",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code == 0, f"stderr: {result.output}"
    output = result.output.strip()
    summary = json.loads(output)
    assert summary["dry_run"] is True
    assert summary["status"] == "dry_run"


def test_candidates_preflight_only(project_env, db_with_event, runner):
    """无 --live 时返回 preflight_only。"""
    db_path, ev_id = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", f"Event:{ev_id}",
        "--db", db_path,
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code == 0, f"stderr: {result.output}"
    output = result.output.strip()
    summary = json.loads(output)
    assert summary["status"] == "preflight_only"


# ---- 参数错误 ----

def test_candidates_unsupported_source_type(project_env, db_with_event, runner):
    """不支持的源类型返回参数错误。"""
    db_path, _ = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", "Opinion:any-id",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code != 0


def test_candidates_bad_source_format(project_env, db_with_event, runner):
    """格式错误的 source 返回参数错误。"""
    db_path, _ = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", "BadFormatNoColon",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code != 0


def test_candidates_missing_source(project_env, db_with_event, runner):
    """缺少 --source 返回参数错误。"""
    db_path, _ = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code == 2


# ---- 数据库不存在 ----

def test_candidates_db_not_found(project_env, runner):
    """数据库不存在时返回错误。"""
    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", "Event:test-id",
        "--db", "nonexistent/path/research.db",
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code != 0


# ---- 多个 source ----

def test_candidates_multiple_sources(project_env, db_with_event, runner):
    """多个 --source 参数正确解析。"""
    db_path, ev_id = db_with_event

    # 再插入一个 Claim
    db = Database(db_path)
    cl_id = new_uuid()
    from research_os.models import Claim
    claim = Claim(
        claim_id=cl_id, claim_type="FACT", statement="测试声明",
        subject_entities=["company:test"], predicate="pred", object={"v": 1},
        as_of=T0, evidence_ids=[], support_level="inferred",
        confidence=0.5, valid_until=None, review_status="unreviewed",
    )
    db.upsert(claim)
    db.close()

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", f"Event:{ev_id}",
        "--source", f"Claim:{cl_id}",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    assert result.exit_code == 0, f"stderr: {result.output}"
    summary = json.loads(result.output.strip())
    assert summary["sources_processed"] == 2  # dry-run 仍加载源做 preflight
    assert summary["dry_run"] is True


# ---- JSON 摘要 ----

def test_candidates_json_summary(project_env, db_with_event, runner):
    """输出为合法 JSON 且包含必要字段。"""
    db_path, ev_id = db_with_event

    result = runner.invoke(cli, [
        "knowledge", "candidates",
        "--source", f"Event:{ev_id}",
        "--db", db_path,
        "--dry-run",
    ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

    output = result.output.strip()
    summary = json.loads(output)
    assert "status" in summary
    assert "dry_run" in summary
    assert "live" in summary
    assert "sources_processed" in summary
    assert "candidates" in summary
    assert "errors" in summary
