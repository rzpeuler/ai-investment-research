"""Phase 5 M6 Apply CLI 测试。

覆盖：
- apply 成功：deterministic JSON（status/applied_at/application_id/idempotency_key/target）
- APPLY_REJECTED：non-zero exit + status=APPLY_REJECTED + errors
- --dry-run：status=dry_run，零写入
- --applied-at 传递
- 数据库不存在错误
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
APPLIED_AT = "2026-08-09T10:00:00+08:00"

EVIDENCE_UUID = "11111111-1111-1111-1111-111111111111"
RAW_ITEM_UUID = "22222222-2222-2222-2222-222222222222"
SOURCE_UUID = "33333333-3333-3333-3333-333333333333"
SHA256_ZEROS = "0000000000000000000000000000000000000000000000000000000000000000"


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
    shutil.copytree(real_src, src_dir, dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return root


def _setup_apply_state(db_path: Path) -> dict:
    """在 db_path 建立可 apply 状态，返回 (graph_change_id, review_id)。"""
    from research_os.knowledge.candidate_repository import (
        GraphChangeCandidateRepository,
    )
    from research_os.knowledge.repository import GraphRepository
    from research_os.knowledge.knowledge_validator import KnowledgeValidator
    from research_os.knowledge.review_workflow import ReviewWorkflow

    db = Database(db_path)
    db.initialize()
    conn = db._conn

    ev = Evidence(
        evidence_id=EVIDENCE_UUID, source_id=SOURCE_UUID,
        raw_item_id=RAW_ITEM_UUID, title="测试证据",
        publisher="测试发布者",
        published_at="2026-08-01T10:00:00+08:00",
        retrieved_at="2026-08-02T10:00:00+08:00",
        url="https://example.com", excerpt="测试摘录",
        evidence_type="news_report", independence_group="group-1",
        source_tier="B", access_status="ok",
    )
    conn.execute(
        "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (EVIDENCE_UUID,
         json.dumps(ev.model_dump(), ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")),
         SOURCE_UUID, RAW_ITEM_UUID, "group-1", "B"),
    )
    ri = {
        "raw_item_id": RAW_ITEM_UUID, "source_id": SOURCE_UUID,
        "external_id": "ext-001", "url": "https://example.com",
        "title": "测试", "publisher": "测试", "author": "测试作者",
        "published_at": "2026-08-01T10:00:00+08:00",
        "retrieved_at": "2026-08-02T10:00:00+08:00",
        "content_hash": SHA256_ZEROS, "content_excerpt": "测试摘录",
        "content_storage": "metadata_and_excerpt", "language": "zh-CN",
        "access_status": "ok", "entities": ["company:test-corp"],
        "raw_category": "news",
    }
    conn.execute(
        "INSERT OR IGNORE INTO raw_items "
        "(raw_item_id, payload, source_id, content_hash, access_status) "
        "VALUES (?, ?, ?, ?, ?)",
        (RAW_ITEM_UUID, json.dumps(ri, ensure_ascii=False),
         SOURCE_UUID, SHA256_ZEROS, "ok"),
    )
    ent = Entity(entity_id="company:test-corp", entity_type="company",
                 canonical_name="测试公司")
    conn.execute(
        "INSERT OR IGNORE INTO entities (entity_id, payload, entity_type, canonical_name) "
        "VALUES (?, ?, ?, ?)",
        ("company:test-corp",
         json.dumps(ent.model_dump(), ensure_ascii=False,
                    sort_keys=True, separators=(",", ":")),
         "company", "测试公司"),
    )
    conn.commit()

    # candidate
    gc = GraphChange(
        graph_change_id=str(uuid.uuid4()),
        change_type="add_node",
        node=GraphNode(
            node_id="company:test-corp", node_type="Company",
            name="测试公司", aliases=["测试"], description="测试描述",
            status="active", valid_from=None, valid_to=None,
            evidence_ids=[EVIDENCE_UUID], version=1,
            last_reviewed_at=None, review_status="candidate",
            origin_kind="graph_change",
            originating_graph_change_id=str(uuid.uuid4()),
            created_at=T0,
        ),
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
    candidate_repo = GraphChangeCandidateRepository(db)
    graph_repo = GraphRepository(db)
    validator = KnowledgeValidator(db, graph_repo)
    workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)
    candidate_repo.append_candidate(gc)

    # import review
    from research_os.knowledge.knowledge_validator import KnowledgeValidator as KV
    candidate_hash = KV.compute_candidate_hash(gc)
    md = _review_markdown(gc, candidate_hash)
    result = workflow.review_import(md)
    assert result.status == "ok", f"review_import failed: {result.errors}"
    review_id = result.review_id
    db.close()
    return {"graph_change_id": gc.graph_change_id, "review_id": review_id}


def _review_markdown(gc, candidate_hash):
    gc_dump = gc.model_dump()
    return "\n".join([
        "# 图谱变更候选", "",
        "## GraphChange ID", "",
        f"- **graph_change_id**: `{gc_dump['graph_change_id']}`",
        f"- **candidate_hash**: `{candidate_hash}`", "",
        "## 变更类型", "",
        f"- **change_type**: `{gc_dump['change_type']}`",
        f"- **review_status**: `{gc_dump['review_status']}`",
        f"- **created_at**: {gc_dump['created_at']}", "",
        "## 当前知识", "",
        "_（无当前知识——此为新节点/边）_", "",
        "## 新证据", "",
        f"- **{EVIDENCE_UUID}**: 测试证据", "",
        "### 节点", "",
        f"- **node_id**: `{gc_dump['node']['node_id']}`", "",
        "## 建议变更", "",
        gc_dump["suggested_change"], "",
        "## 影响范围", "",
        "- industry_a", "",
        "## 冲突信息", "",
        "_（无冲突）_", "",
        "## 验证节点", "",
        "- [ ] 验证公司注册信息", "",
        "## 审核选项", "",
        "- [x] 批准", "- [ ] 修改后批准", "- [ ] 暂缓", "- [ ] 拒绝", "",
        "## Reviewer", "",
        "```yaml",
        "# 请填写以下字段：",
        "reviewer_type: human",
        'reviewer_id: "reviewer-001"      # 必填，非空',
        'display_name: ""     # 可选',
        f'reviewed_at: "{T1}"      # ISO 8601 datetime，必填',
        "```", "",
        "## Review Notes", "",
        "_（请在此填写审核意见）_", "",
        "## Approved Patch", "",
        "_（仅\"修改后批准\"时填写 JSON Patch 数组）_", "",
        "---",
        "*本文件为审阅模板，请填写后通过 review-import 导入。*",
    ])


class TestApplyCli:
    """research knowledge apply CLI 测试。"""

    def test_apply_success_json(self, project_env, monkeypatch):
        """apply 成功：deterministic JSON + exit 0。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        state = _setup_apply_state(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", state["graph_change_id"],
            "--applied-at", APPLIED_AT,
        ])

        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["status"] == "applied"
        assert out["original_graph_change_id"] == state["graph_change_id"]
        assert out["effective_graph_change_id"] == state["graph_change_id"]
        assert out["review_id"] == state["review_id"]
        assert out["application_id"] is not None
        assert out["idempotency_key"] is not None
        assert out["target_kind"] == "node"
        assert out["target_id"] == "company:test-corp"
        assert out["target_version"] == 1
        assert out["applied_at"] == APPLIED_AT
        assert out["dry_run"] is False
        assert out["warnings"] == []

    def test_apply_applied_at_default_captured_once(self, project_env, monkeypatch):
        """未提供 --applied-at：capture now_iso() once（JSON 含 applied_at）。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        state = _setup_apply_state(db_path)

        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", state["graph_change_id"],
        ])

        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["status"] == "applied"
        assert out["applied_at"] is not None
        # 同一 change 再次 apply → idempotent_noop（幂等不依赖 applied_at）
        result2 = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", state["graph_change_id"],
        ])
        out2 = json.loads(result2.output)
        assert out2["status"] == "idempotent_noop"

    def test_apply_rejected_nonzero_exit(self, project_env, monkeypatch):
        """无 review → non-zero exit + status=APPLY_REJECTED + errors。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        # 只建 candidate（不 import review）——通过直接构造
        from research_os.knowledge.candidate_repository import (
            GraphChangeCandidateRepository,
        )
        db = Database(db_path)
        db.initialize()
        conn = db._conn
        ev = Evidence(
            evidence_id=EVIDENCE_UUID, source_id=SOURCE_UUID,
            raw_item_id=RAW_ITEM_UUID, title="t",
            publisher="p", published_at="2026-08-01T10:00:00+08:00",
            retrieved_at="2026-08-02T10:00:00+08:00",
            url="https://example.com", excerpt="e",
            evidence_type="news_report", independence_group="g",
            source_tier="B", access_status="ok",
        )
        conn.execute(
            "INSERT OR IGNORE INTO evidence (evidence_id, payload, source_id, raw_item_id, independence_group, source_tier) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (EVIDENCE_UUID,
             json.dumps(ev.model_dump(), ensure_ascii=False, sort_keys=True,
                        separators=(",", ":")),
             SOURCE_UUID, RAW_ITEM_UUID, "g", "B"),
        )
        conn.commit()
        gc = GraphChange(
            graph_change_id=str(uuid.uuid4()), change_type="add_node",
            node=GraphNode(
                node_id="company:test-corp", node_type="Company",
                name="测试公司", status="active", version=1,
                evidence_ids=[EVIDENCE_UUID], review_status="candidate",
                origin_kind="graph_change",
                originating_graph_change_id=str(uuid.uuid4()),
                created_at=T0,
            ),
            edge=None, current_knowledge="", new_evidence_ids=[EVIDENCE_UUID],
            suggested_change="x", impact_scope=[], conflicts=[],
            verification_points=[], review_status="candidate",
            created_at=T0, reviewed_at=None,
        )
        GraphChangeCandidateRepository(db).append_candidate(gc)
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", gc.graph_change_id,
            "--applied-at", APPLIED_AT,
        ])

        assert result.exit_code == 1
        out = json.loads(result.output)
        assert out["status"] == "APPLY_REJECTED"
        assert any("REVIEW_REQUIRED" in e for e in out["errors"])

    def test_apply_dry_run_zero_writes(self, project_env, monkeypatch):
        """--dry-run：status=dry_run，DB 零写入。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        db_path = project_env / "data" / "sqlite" / "research.db"
        state = _setup_apply_state(db_path)

        db = Database(db_path)
        nodes_before = db._conn.execute(
            "SELECT COUNT(*) AS c FROM graph_nodes").fetchone()["c"]
        apps_before = db._conn.execute(
            "SELECT COUNT(*) AS c FROM graph_applications").fetchone()["c"]
        db.close()

        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", state["graph_change_id"],
            "--applied-at", APPLIED_AT,
            "--dry-run",
        ])

        assert result.exit_code == 0, result.output
        out = json.loads(result.output)
        assert out["status"] == "dry_run"
        assert out["dry_run"] is True
        assert out["application_id"] is not None

        db = Database(db_path)
        assert db._conn.execute(
            "SELECT COUNT(*) AS c FROM graph_nodes").fetchone()["c"] == nodes_before
        assert db._conn.execute(
            "SELECT COUNT(*) AS c FROM graph_applications").fetchone()["c"] == apps_before
        db.close()

    def test_apply_db_not_found(self, project_env, monkeypatch):
        """数据库不存在 → non-zero exit。"""
        monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(project_env))
        runner = CliRunner()
        result = runner.invoke(cli, [
            "knowledge", "apply",
            "--change-id", str(uuid.uuid4()),
            "--db", "data/sqlite/nonexistent.db",
        ])
        assert result.exit_code != 0
        assert "数据库不存在" in result.output
