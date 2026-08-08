"""Phase 5 M9 Scenario Integration CLI 测试。

覆盖:
- dry-run 预检输出
- 场景名称验证
- run-dir 安全/验证
- source filter 参数
- JSON 输出格式
- 非零退出码
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.models import Claim, Evidence
from research_os.models.abnormal_move import CauseEvidenceLink
from research_os.models.equity_research import ResearchFinding
from research_os.storage.db import Database
from research_os.utils.id import new_uuid

T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def project_env(tmp_path):
    """创建最小项目结构。"""
    root = tmp_path / "project"
    real_root = Path(__file__).resolve().parents[2]
    (root / "schemas").mkdir(parents=True, exist_ok=True)
    for f in (real_root / "schemas").iterdir():
        shutil.copy(f, root / "schemas" / f.name)
    (root / "data" / "sqlite").mkdir(parents=True)
    mig_dst = root / "src" / "research_os" / "storage" / "migrations"
    mig_dst.mkdir(parents=True, exist_ok=True)
    mig_src = real_root / "src" / "research_os" / "storage" / "migrations"
    for f in mig_src.iterdir():
        shutil.copy(f, mig_dst / f.name)
    (root / "knowledge").mkdir(parents=True, exist_ok=True)
    src_dst = root / "src" / "research_os"
    src_dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        real_root / "src" / "research_os", src_dst,
        dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (root / "reports" / "runs").mkdir(parents=True)
    return root


@pytest.fixture()
def runner():
    return CliRunner()


@pytest.fixture()
def init_db(project_env):
    """已迁移 DB 路径。"""
    db_p = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_p)
    db.migrate()
    db.close()
    return str(db_p)


def _make_morning_run(project_root: Path, db_path: str) -> Path:
    """创建最小晨报 run 目录。"""
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    cid = str(new_uuid())

    ev_id = str(new_uuid())
    db.upsert(Evidence(
        evidence_id=ev_id, source_id="source:test", raw_item_id=str(new_uuid()),
        title="证据", publisher="test", published_at=T0, retrieved_at=T0,
        url="https://ex.com", excerpt="...", evidence_type="news_report",
        independence_group="g1", source_tier="B", access_status="ok",
    ))
    claim = Claim(
        claim_id=cid, claim_type="FACT", statement="测试",
        subject_entities=["company:test"], predicate="reports",
        as_of=T0, evidence_ids=[ev_id],
    )
    db.upsert(claim)
    db.close()

    (run_dir / "task.json").write_text(json.dumps({
        "task_id": task_id, "scenario": "morning_brief",
    }), encoding="utf-8")
    (run_dir / "evidence_index.json").write_text("[]", encoding="utf-8")
    (run_dir / "claims.json").write_text(json.dumps([{
        "claim_id": cid, "claim_type": "FACT", "statement": "测试",
        "evidence_ids": [ev_id],
    }]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    return run_dir


def _make_abnormal_run(project_root: Path, db_path: str) -> Path:
    """创建最小异动 run 目录。"""
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    eid = str(new_uuid())
    req_id = str(new_uuid())
    cause_id = str(new_uuid())

    ev = Evidence(
        evidence_id=eid, source_id="source:test", raw_item_id=str(new_uuid()),
        title="证据", publisher="test", published_at=T0, retrieved_at=T0,
        url="https://ex.com", excerpt="...", evidence_type="news_report",
        independence_group="g1", source_tier="B", access_status="ok",
    )
    db.upsert(ev)
    link_id = str(new_uuid())
    db.upsert(CauseEvidenceLink(
        link_id=link_id, cause_candidate_id=cause_id, evidence_id=eid,
        relation="supports", independence_group="g1", created_at=T0,
    ))
    db.close()

    (run_dir / "abnormal_move_run.json").write_text(json.dumps({
        "request_id": req_id,
    }), encoding="utf-8")
    (run_dir / "cause_candidates.json").write_text(json.dumps([{
        "cause_candidate_id": cause_id, "request_id": req_id,
    }]), encoding="utf-8")
    (run_dir / "cause_evidence_links.json").write_text(json.dumps([{
        "link_id": link_id, "cause_candidate_id": cause_id, "evidence_id": eid,
    }]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    return run_dir


def _make_equity_run(project_root: Path, db_path: str) -> Path:
    """创建最小个股研报 run 目录。"""
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    fid = str(new_uuid())
    req_id = str(new_uuid())

    ev_id = str(new_uuid())
    db.upsert(Evidence(
        evidence_id=ev_id, source_id="source:test", raw_item_id=str(new_uuid()),
        title="证据", publisher="test", published_at=T0, retrieved_at=T0,
        url="https://ex.com", excerpt="...", evidence_type="news_report",
        independence_group="g1", source_tier="B", access_status="ok",
    ))
    finding = ResearchFinding(
        finding_id=fid, request_id=req_id,
        company_entity_id="company:600519.SH", finding_type="business_analysis",
        title="发现", statement="发现", claim_type="FACT", predicate="reports",
        as_of=T0, evidence_ids=[ev_id], counter_evidence_ids=[],
        confidence=0.5, section_id="semantic", created_at=T0,
    )
    db.upsert(finding)
    db.close()

    (run_dir / "equity_research_run.json").write_text(json.dumps({
        "request_id": req_id,
    }), encoding="utf-8")
    (run_dir / "equity_research_request.json").write_text(json.dumps({
        "request_id": req_id,
    }), encoding="utf-8")
    (run_dir / "research_findings.json").write_text(json.dumps([{
        "finding_id": fid, "request_id": req_id, "statement": "发现",
        "evidence_ids": [ev_id],
    }]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({"status": "pass"}), encoding="utf-8")

    return run_dir


# ====================================================================
# CLI Tests
# ====================================================================

class TestCliMorning:
    """knowledge integrate --scenario morning_brief"""

    def test_dry_run_morning(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

        assert result.exit_code == 0
        out = json.loads(result.output.strip())
        assert out["status"] == "dry_run"
        assert len(out["resolved_source_refs"]) >= 1

    def test_non_live_preflight(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

        assert result.exit_code == 0
        out = json.loads(result.output.strip())
        assert out["status"] == "preflight_only"

    def test_invalid_scenario(self, project_env, init_db, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "bad_scenario",
            "--run-dir", str(project_env / "reports" / "runs"),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_SCENARIO_UNSUPPORTED"

    def test_missing_run_dir(self, project_env, init_db, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", "reports/runs/nonexistent",
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_RUN_DIR_INVALID"

    def test_source_filter_valid(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        # 解析到的 source
        # 先 dry-run 获取 resolved
        result1 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        refs = json.loads(result1.output.strip())["resolved_source_refs"]

        # 用 resolved 的第一个作为 filter
        result2 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
            "--source", refs[0],
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result2.exit_code == 0
        out = json.loads(result2.output.strip())
        assert out["selected_source_refs"] == [refs[0]]

    def test_source_filter_invalid(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
            "--source", "Claim:bad-id",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_SOURCE_FILTER_INVALID"

    def test_json_output_format(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 0
        out = json.loads(result.output.strip())
        assert isinstance(out, dict)
        assert "status" in out
        assert "error_code" in out
        assert "resolved_source_refs" in out
        assert "selected_source_refs" in out
        assert "warnings" in out
        assert "pipeline_result" in out


class TestCliAbnormal:
    """knowledge integrate --scenario abnormal_move_analysis"""

    def test_dry_run_abnormal(self, project_env, init_db, runner):
        run_dir = _make_abnormal_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "abnormal_move_analysis",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

        assert result.exit_code == 0
        out = json.loads(result.output.strip())
        assert out["status"] == "dry_run"
        # 应该有 Evidence refs
        assert len(out["resolved_source_refs"]) >= 1
        assert all(r.startswith("Evidence:") for r in out["resolved_source_refs"])

    def test_abnormal_source_filter_subset(self, project_env, init_db, runner):
        run_dir = _make_abnormal_run(project_env, init_db)
        result1 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "abnormal_move_analysis",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        refs = json.loads(result1.output.strip())["resolved_source_refs"]

        result2 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "abnormal_move_analysis",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
            "--source", refs[0],
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result2.exit_code == 0

    def test_missing_run_json(self, project_env, init_db, runner):
        """缺少 abnormal_move_run.json → error"""
        run_dir = project_env / "reports" / "runs" / str(new_uuid())
        run_dir.mkdir(parents=True)
        (run_dir / "cause_evidence_links.json").write_text("[]", encoding="utf-8")

        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "abnormal_move_analysis",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert "ARTIFACT_MISSING" in (out.get("error_code", ""))


class TestCliEquity:
    """knowledge integrate --scenario stock_research_report"""

    def test_dry_run_equity(self, project_env, init_db, runner):
        run_dir = _make_equity_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "stock_research_report",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})

        assert result.exit_code == 0
        out = json.loads(result.output.strip())
        assert out["status"] == "dry_run"
        assert any("ResearchFinding:" in r for r in out["resolved_source_refs"])

    def test_no_findings(self, project_env, init_db, runner):
        """空 findings → no eligible sources"""
        run_dir = project_env / "reports" / "runs" / str(new_uuid())
        run_dir.mkdir(parents=True)
        (run_dir / "equity_research_run.json").write_text(
            '{"request_id":"x"}', encoding="utf-8",
        )
        (run_dir / "research_findings.json").write_text("[]", encoding="utf-8")

        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "stock_research_report",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_NO_ELIGIBLE_SOURCES"


class TestCliCore:
    """M9 CLI 核心安全性/边界"""

    def test_db_not_found(self, project_env, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", "reports/runs/test",
            "--db", "nonexistent.db",
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 2

    def test_help_shows_options(self, project_env, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate", "--help",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 0
        assert "--scenario" in result.output
        assert "--run-dir" in result.output
        assert "--source" in result.output
        assert "--live" in result.output
        assert "--dry-run" in result.output

    def test_no_traceback_on_error(self, project_env, runner):
        """错误输出不应包含 Python traceback。"""
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", "reports/runs/nonexistent",
            "--db", "data/sqlite/research.db",
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert "Traceback" not in result.output
        assert "INTEGRATION" in result.output
