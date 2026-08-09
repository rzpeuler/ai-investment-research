"""Phase 5 M9-R1 CLI 集成测试。

R1 覆盖:
- dry-run / preflight 输出
- provider error (--live without --provider / invalid provider)
- 场景验证
- run_dir 安全
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.models import AbnormalMoveRun, CauseCandidate, CauseEvidenceLink, Claim, Evidence
from research_os.models.equity_research import EquityResearchRun, EquityResearchRequest, ResearchFinding
from research_os.storage.db import Database
from research_os.utils.id import new_uuid

T0 = "2026-08-07T17:00:00+08:00"


@pytest.fixture()
def project_env(tmp_path):
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
    db_p = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_p)
    db.migrate()
    db.close()
    return str(db_p)


def _make_evidence(db: Database, eid: str) -> Evidence:
    ev = Evidence(
        evidence_id=eid, source_id="source:test", raw_item_id=str(new_uuid()),
        title="证据", publisher="test", published_at=T0, retrieved_at=T0,
        url="https://ex.com", excerpt="...", evidence_type="news_report",
        independence_group="g1", source_tier="B", access_status="ok",
    )
    db.upsert(ev)
    return ev


def _make_morning_run(project_root: Path, db_path: str) -> Path:
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    eid = str(new_uuid())
    ev = _make_evidence(db, eid)
    cid = str(new_uuid())
    claim = Claim(
        claim_id=cid, claim_type="FACT", statement="测试",
        subject_entities=["company:test"], predicate="reports",
        as_of=T0, evidence_ids=[eid],
    )
    db.upsert(claim)
    db.close()

    (run_dir / "task.json").write_text(json.dumps({
        "task_id": task_id, "scenario": "morning_brief",
    }), encoding="utf-8")
    (run_dir / "evidence_index.json").write_text(json.dumps({
        eid: ev.model_dump(),
    }), encoding="utf-8")
    (run_dir / "claims.json").write_text(json.dumps([claim.model_dump()]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({
        "status": "ok", "task_id": task_id, "checks": 0, "errors": [],
    }), encoding="utf-8")
    return run_dir


def _make_abnormal_run(project_root: Path, db_path: str) -> Path:
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    run_id = str(new_uuid())
    req_id = str(new_uuid())
    obs_id = str(new_uuid())
    cause_id = str(new_uuid())
    link_id = str(new_uuid())
    eid = str(new_uuid())

    _make_evidence(db, eid)
    db_run = AbnormalMoveRun(
        run_id=run_id, task_id=task_id, request_id=req_id,
        observation_id=obs_id, idempotency_key=f"k_{task_id}",
        run_version=1, started_at=T0, finished_at=T0, validation_status="passed",
    )
    db.upsert(db_run)
    db_cause = CauseCandidate(
        cause_candidate_id=cause_id, request_id=req_id,
        observation_id=obs_id, title="x", cause_category="direct_trigger",
        retrieval_layer=1, evidence_ids=[eid],
    )
    db.upsert(db_cause)
    db_link = CauseEvidenceLink(
        link_id=link_id, cause_candidate_id=cause_id, evidence_id=eid,
        relation="supports", independence_group="g1", created_at=T0,
    )
    db.upsert(db_link)
    db.close()

    (run_dir / "abnormal_move_run.json").write_text(json.dumps(
        db_run.model_dump(),
    ), encoding="utf-8")
    (run_dir / "cause_candidates.json").write_text(json.dumps([
        db_cause.model_dump(),
    ]), encoding="utf-8")
    (run_dir / "cause_evidence_links.json").write_text(json.dumps([
        db_link.model_dump(),
    ]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({
        "ok": True, "errors": [], "warnings": [],
    }), encoding="utf-8")
    return run_dir


def _make_equity_run(project_root: Path, db_path: str) -> Path:
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    db = Database(Path(db_path))
    run_id = str(new_uuid())
    req_id = str(new_uuid())
    fid = str(new_uuid())
    eid = str(new_uuid())

    _make_evidence(db, eid)
    db_run = EquityResearchRun(
        run_id=run_id, request_id=req_id, task_id=task_id,
        idempotency_key=f"k_{task_id}", run_version=1,
        started_at=T0, status="success", validation_status="pass",
    )
    db.upsert(db_run)
    db_req = EquityResearchRequest(
        request_id=req_id, task_id=task_id,
        company_entity_id="company:600519.SH",
        security_entity_id="security:600519.SH",
        as_of=T0, as_of_basis="user_provided", report_date="2026-08-07",
        timezone="Asia/Shanghai", requested_at=T0,
    )
    db.upsert(db_req)
    finding = ResearchFinding(
        finding_id=fid, request_id=req_id,
        company_entity_id="company:600519.SH", finding_type="business_analysis",
        title="发现", statement="发现", claim_type="FACT", predicate="reports",
        as_of=T0, evidence_ids=[eid], counter_evidence_ids=[],
        confidence=0.5, section_id="semantic", created_at=T0,
    )
    db.upsert(finding)
    db.close()

    (run_dir / "equity_research_run.json").write_text(json.dumps(
        db_run.model_dump(),
    ), encoding="utf-8")
    (run_dir / "equity_research_request.json").write_text(json.dumps(
        db_req.model_dump(),
    ), encoding="utf-8")
    (run_dir / "research_findings.json").write_text(json.dumps([
        finding.model_dump(),
    ]), encoding="utf-8")
    (run_dir / "validation.json").write_text(json.dumps({
        "status": "pass", "errors": [], "warnings": [],
    }), encoding="utf-8")
    return run_dir


# ====================================================================
# CLI Tests
# ====================================================================

class TestCliMorning:
    def test_dry_run(self, project_env, init_db, runner):
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

    def test_source_filter(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result1 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        refs = json.loads(result1.output.strip())["resolved_source_refs"]
        assert len(refs) >= 1

        result2 = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
            "--source", refs[0],
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result2.exit_code == 0

    def test_invalid_source_filter(self, project_env, init_db, runner):
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

    def test_invalid_scenario(self, project_env, init_db, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "bad",
            "--run-dir", str(project_env / "reports" / "runs"),
            "--db", init_db, "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1

    def test_missing_run_dir(self, project_env, init_db, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", "reports/runs/nonexistent",
            "--db", init_db, "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1


class TestCliAbnormal:
    def test_dry_run(self, project_env, init_db, runner):
        run_dir = _make_abnormal_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "abnormal_move_analysis",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 0


class TestCliEquity:
    def test_dry_run(self, project_env, init_db, runner):
        run_dir = _make_equity_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "stock_research_report",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 0


class TestCliProvider:
    def test_live_without_provider(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--live",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_PROVIDER_ERROR"
        assert "Traceback" not in result.output

    def test_invalid_provider(self, project_env, init_db, runner):
        run_dir = _make_morning_run(project_env, init_db)
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", str(run_dir),
            "--db", init_db,
            "--live", "--provider", "nonexistent_provider",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 1
        out = json.loads(result.output.strip())
        assert out["error_code"] == "INTEGRATION_PROVIDER_ERROR"
        assert "Traceback" not in result.output


class TestCliCore:
    def test_db_not_found(self, project_env, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate",
            "--scenario", "morning_brief",
            "--run-dir", "reports/runs/x",
            "--db", "nonexistent.db", "--dry-run",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 2

    def test_help(self, project_env, runner):
        result = runner.invoke(cli, [
            "knowledge", "integrate", "--help",
        ], env={"RESEARCH_PROJECT_PATH": str(project_env)})
        assert result.exit_code == 0
        assert "--scenario" in result.output
        assert "--run-dir" in result.output
