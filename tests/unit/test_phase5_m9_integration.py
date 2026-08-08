"""Phase 5 M9-R1 结构化研究 Candidate 集成测试。

R1 覆盖:
- Morning: task_id 绑定、evidence_index 闭包、full Claim canonical equality、validation gate
- Phase3: SQLite run/cause/link authority、full chain verification
- Phase4: SQLite run/request authority、no fallback、full Finding canonical
- 攻击测试: foreign claim/evidence tamper/forged IDs/cross-run/missing cause/failed validation
- CLI: provider error structured

基准: 9750dcf M9 initial implementation
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from research_os.knowledge.scenario_integration import (
    IntegrationError,
    IntegrationResult,
    MAX_INTEGRATION_SOURCES,
    ScenarioCandidateIntegrator,
)
from research_os.models import Claim, Evidence, Event, AbnormalMoveRun, CauseCandidate, CauseEvidenceLink
from research_os.models.equity_research import ResearchFinding, EquityResearchRun, EquityResearchRequest
from research_os.storage.db import Database
from research_os.utils.id import new_uuid

T0 = "2026-08-07T17:00:00+08:00"
T1 = "2026-08-07T18:00:00+08:00"


# ====================================================================
# Fixtures
# ====================================================================

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
def db_path(project_env):
    db_p = project_env / "data" / "sqlite" / "research.db"
    db = Database(db_p)
    db.migrate()
    db.close()
    return str(db_p)


def _open_db(db_p: str) -> Database:
    return Database(Path(db_p))


def _make_integrator(db, project_root, *, live=False, dry_run=False):
    return ScenarioCandidateIntegrator(
        db=db, project_root=project_root,
        knowledge_dir=project_root / "knowledge",
        live=live, dry_run=dry_run,
    )


# ====================================================================
# Helpers: produce real artifact JSON + DB records
# ====================================================================

def _make_evidence(db: Database, eid: str, title: str = "证据") -> Evidence:
    ev = Evidence(
        evidence_id=eid, source_id="source:test", raw_item_id=str(new_uuid()),
        title=title, publisher="test", published_at=T0, retrieved_at=T0,
        url="https://example.com/ev", excerpt="...",
        evidence_type="news_report", independence_group="g1",
        source_tier="B", access_status="ok",
    )
    db.upsert(ev)
    return ev


def _make_claim(db: Database, cid: str, ev_ids: list, statement: str = "声明") -> Claim:
    claim = Claim(
        claim_id=cid, claim_type="FACT", statement=statement,
        subject_entities=["company:test"], predicate="reports",
        as_of=T0, evidence_ids=ev_ids,
    )
    db.upsert(claim)
    return claim


def _make_morning_run(project_root: Path, db: Database) -> tuple[Path, list[str], list[str]]:
    """创建符合真实 Phase2 artifact contract 的晨报 run。

    返回 (run_dir, claim_ids, evidence_ids)。
    """
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    eid = str(new_uuid())
    ev = _make_evidence(db, eid)
    cid = str(new_uuid())
    claim = _make_claim(db, cid, [eid])

    # task.json（真实 contract）
    (run_dir / "task.json").write_text(json.dumps({
        "task_id": task_id, "scenario": "morning_brief",
    }), encoding="utf-8")

    # evidence_index.json（{eid: Evidence.model_dump()}）
    (run_dir / "evidence_index.json").write_text(json.dumps({
        eid: ev.model_dump(),
    }), encoding="utf-8")

    # claims.json
    (run_dir / "claims.json").write_text(json.dumps([
        claim.model_dump(),
    ]), encoding="utf-8")

    # validation.json（真实 contract: status="ok"）
    (run_dir / "validation.json").write_text(json.dumps({
        "status": "ok", "task_id": task_id, "checks": 0, "errors": [],
    }), encoding="utf-8")

    return run_dir, [cid], [eid]


def _make_abnormal_run(project_root: Path, db: Database) -> tuple[Path, str, str, str, str]:
    """创建符合真实 Phase3 artifact contract 的异动 run。

    返回 (run_dir, run_id, cause_id, link_id, evidence_id)。
    """
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    run_id = str(new_uuid())
    request_id = str(new_uuid())
    observation_id = str(new_uuid())
    cause_id = str(new_uuid())
    link_id = str(new_uuid())
    eid = str(new_uuid())

    # Evidence
    _make_evidence(db, eid)

    # DB AbnormalMoveRun
    db_run = AbnormalMoveRun(
        run_id=run_id, task_id=task_id, request_id=request_id,
        observation_id=observation_id,
        idempotency_key=f"key_{task_id}", run_version=1,
        started_at=T0, finished_at=T0,
    )
    db.upsert(db_run)

    # DB CauseCandidate
    db_cause = CauseCandidate(
        cause_candidate_id=cause_id, request_id=request_id,
        observation_id=observation_id,
        title="测试原因", cause_category="direct_trigger", retrieval_layer=1,
        evidence_ids=[eid],
    )
    db.upsert(db_cause)

    # DB CauseEvidenceLink
    db_link = CauseEvidenceLink(
        link_id=link_id, cause_candidate_id=cause_id, evidence_id=eid,
        relation="supports", independence_group="g1", created_at=T0,
    )
    db.upsert(db_link)

    # Artifacts
    (run_dir / "abnormal_move_run.json").write_text(json.dumps({
        "run_id": run_id, "task_id": task_id, "request_id": request_id,
    }), encoding="utf-8")
    (run_dir / "cause_candidates.json").write_text(json.dumps([
        db_cause.model_dump(),
    ]), encoding="utf-8")
    (run_dir / "cause_evidence_links.json").write_text(json.dumps([
        db_link.model_dump(),
    ]), encoding="utf-8")
    # 真实 Phase3 validation contract: {"ok": true/false, "errors": [...], "warnings": [...]}
    (run_dir / "validation.json").write_text(json.dumps({
        "ok": True, "errors": [], "warnings": [],
    }), encoding="utf-8")

    return run_dir, run_id, cause_id, link_id, eid


def _make_equity_run(project_root: Path, db: Database) -> tuple[Path, str, str]:
    """创建符合真实 Phase4 artifact contract 的个股研报 run。

    返回 (run_dir, finding_id, request_id)。
    """
    task_id = str(new_uuid())
    run_dir = project_root / "reports" / "runs" / task_id
    run_dir.mkdir(parents=True)

    run_id = str(new_uuid())
    request_id = str(new_uuid())
    finding_id = str(new_uuid())
    eid = str(new_uuid())

    _make_evidence(db, eid)

    # DB EquityResearchRun
    db_run = EquityResearchRun(
        run_id=run_id, request_id=request_id, task_id=task_id,
        idempotency_key=f"eq_{task_id}", run_version=1,
        started_at=T0, status="success",
    )
    db.upsert(db_run)

    # DB EquityResearchRequest
    db_req = EquityResearchRequest(
        request_id=request_id, task_id=task_id,
        company_entity_id="company:600519.SH", security_entity_id="security:600519.SH",
        as_of=T0, as_of_basis="user_provided", report_date="2026-08-07",
        timezone="Asia/Shanghai", requested_at=T0,
    )
    db.upsert(db_req)

    # DB ResearchFinding
    finding = ResearchFinding(
        finding_id=finding_id, request_id=request_id,
        company_entity_id="company:600519.SH", finding_type="business_analysis",
        title="发现", statement="发现", claim_type="FACT", predicate="reports",
        as_of=T0, evidence_ids=[eid], counter_evidence_ids=[],
        confidence=0.5, section_id="semantic", created_at=T0,
    )
    db.upsert(finding)

    # Artifacts
    (run_dir / "equity_research_run.json").write_text(json.dumps({
        "run_id": run_id, "request_id": request_id, "task_id": task_id,
    }), encoding="utf-8")
    (run_dir / "equity_research_request.json").write_text(json.dumps({
        "request_id": request_id, "task_id": task_id,
        "company_entity_id": "company:600519.SH", "security_entity_id": "security:600519.SH",
        "as_of": T0, "as_of_basis": "user_provided", "report_date": "2026-08-07",
        "timezone": "Asia/Shanghai", "requested_at": T0,
    }), encoding="utf-8")
    (run_dir / "research_findings.json").write_text(json.dumps([
        finding.model_dump(),
    ]), encoding="utf-8")
    # 真实 Phase4 validation contract: {"status": ..., "errors": [...], "warnings": [...]}
    (run_dir / "validation.json").write_text(json.dumps({
        "status": "pass", "errors": [], "warnings": [],
    }), encoding="utf-8")

    return run_dir, finding_id, request_id


# ====================================================================
# Morning Tests
# ====================================================================

class TestMorningIntegration:

    def test_valid_morning_claims(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, cids, eids = _make_morning_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("morning_brief", run_dir)

        assert result.status == "dry_run"
        assert f"Claim:{cids[0]}" in result.resolved_source_refs

    def test_task_id_mismatch(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, _, _ = _make_morning_run(project_env, db)
        # forge task_id
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": "wrong_id", "scenario": "morning_brief",
        }), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_foreign_claim_not_in_evidence_closure(self, project_env, db_path):
        """foreign Claim: evidence 不在 evidence_index.json 中"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        eid = str(new_uuid())
        ev = _make_evidence(db, eid)
        cid = str(new_uuid())
        claim = _make_claim(db, cid, [eid])

        (run_dir / "task.json").write_text(json.dumps({
            "task_id": task_id, "scenario": "morning_brief",
        }), encoding="utf-8")
        # evidence_index.json 不包含此 evidence
        (run_dir / "evidence_index.json").write_text(json.dumps({}), encoding="utf-8")
        (run_dir / "claims.json").write_text(json.dumps([claim.model_dump()]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_evidence_index_artifact_db_tamper(self, project_env, db_path):
        """evidence_index 中 Evidence 与 DB 不一致"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        eid = str(new_uuid())
        ev = _make_evidence(db, eid, "正确标题")
        cid = str(new_uuid())
        claim = _make_claim(db, cid, [eid])

        # 写入被篡改的 evidence（不同 title）
        tampered = ev.model_dump()
        tampered["title"] = "被篡改的标题"
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": task_id, "scenario": "morning_brief",
        }), encoding="utf-8")
        (run_dir / "evidence_index.json").write_text(json.dumps({eid: tampered}), encoding="utf-8")
        (run_dir / "claims.json").write_text(json.dumps([claim.model_dump()]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_full_claim_canonical_tamper(self, project_env, db_path):
        """Claim 非旧四字段被篡改 → reject（R1: full canonical equality）"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        eid = str(new_uuid())
        ev = _make_evidence(db, eid)
        cid = str(new_uuid())
        claim = _make_claim(db, cid, [eid])

        # 篡改 predicate（非旧四字段之一）
        tampered = claim.model_dump()
        tampered["predicate"] = "tampered_predicate"
        (run_dir / "task.json").write_text(json.dumps({
            "task_id": task_id, "scenario": "morning_brief",
        }), encoding="utf-8")
        (run_dir / "evidence_index.json").write_text(json.dumps({eid: ev.model_dump()}), encoding="utf-8")
        (run_dir / "claims.json").write_text(json.dumps([tampered]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_validation_failed(self, project_env, db_path):
        """validation.json status != ok → INTEGRATION_RUN_NOT_ELIGIBLE"""
        db = _open_db(db_path)
        run_dir, _, _ = _make_morning_run(project_env, db)
        (run_dir / "validation.json").write_text(json.dumps({"status": "failed"}), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_RUN_NOT_ELIGIBLE"

    def test_claim_id_not_in_db(self, project_env, db_path):
        """claim_id 不在 DB → reject"""
        db = _open_db(db_path)
        run_dir, _, _ = _make_morning_run(project_env, db)
        # 写入不存在的 claim_id
        (run_dir / "claims.json").write_text(json.dumps([{
            "claim_id": str(new_uuid()), "claim_type": "FACT", "statement": "x",
            "subject_entities": ["company:test"], "predicate": "reports",
            "as_of": T0, "evidence_ids": [],
            "object": {}, "support_level": "inferred", "confidence": 0.5,
            "valid_until": None, "review_status": "unreviewed",
        }]), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_invalid_json(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir = project_env / "reports" / "runs" / str(new_uuid())
        run_dir.mkdir(parents=True)
        (run_dir / "task.json").write_text("{}", encoding="utf-8")
        (run_dir / "claims.json").write_text("not json", encoding="utf-8")
        (run_dir / "evidence_index.json").write_text("{}", encoding="utf-8")
        (run_dir / "validation.json").write_text('{"status":"ok"}', encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INVALID"

    def test_run_dir_traversal(self, project_env, db_path):
        db = _open_db(db_path)
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", project_env / "reports" / "runs" / ".." / ".." / "etc")
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_RUN_DIR_INVALID"

    def test_missing_artifact(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir = project_env / "reports" / "runs" / str(new_uuid())
        run_dir.mkdir(parents=True)
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert "INTEGRATION_ARTIFACT_MISSING" in (result.error_code or "")


# ====================================================================
# Phase3 Tests
# ====================================================================

class TestAbnormalIntegration:

    def test_valid_abnormal_evidence(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, _, _, _, eid = _make_abnormal_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("abnormal_move_analysis", run_dir)

        assert result.status == "dry_run"
        assert f"Evidence:{eid}" in result.resolved_source_refs

    def test_forged_run_request_id(self, project_env, db_path):
        """artifact run.request_id 被伪造 → reject"""
        db = _open_db(db_path)
        run_dir, run_id, _, _, _ = _make_abnormal_run(project_env, db)
        # 篡改 artifact 中 request_id
        (run_dir / "abnormal_move_run.json").write_text(json.dumps({
            "run_id": run_id,
            "task_id": run_dir.name,
            "request_id": "forged_request_id",
        }), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_forged_cause_request_id(self, project_env, db_path):
        """forged CauseCandidate.request_id → foreign run → reject"""
        db = _open_db(db_path)
        run_dir, run_id, cause_id, link_id, eid = _make_abnormal_run(project_env, db)
        # DB CauseCandidate 已经有正确的 request_id。
        # 创建一个 foreign CauseCandidate 用来替换 artifact 中的引用
        foreign_cause_id = str(new_uuid())
        foreign_obs_id = str(new_uuid())
        db.upsert(CauseCandidate(
            cause_candidate_id=foreign_cause_id,
            request_id=str(new_uuid()),  # foreign request!
            observation_id=foreign_obs_id,
            title="foreign", cause_category="direct_trigger", retrieval_layer=1,
            evidence_ids=[eid],
        ))
        # 篡改 artifact link 引用 foreign cause
        (run_dir / "cause_candidates.json").write_text(json.dumps([
            {"cause_candidate_id": foreign_cause_id, "request_id": str(new_uuid())},
        ]), encoding="utf-8")
        (run_dir / "cause_evidence_links.json").write_text(json.dumps([{
            "link_id": link_id, "cause_candidate_id": foreign_cause_id, "evidence_id": eid,
        }]), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        assert result.error_code in (
            "INTEGRATION_SOURCE_RUN_MISMATCH",
            "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
        )

    def test_missing_cause_candidate(self, project_env, db_path):
        """cause candidate 不在 artifact → reject（R1: no longer warning）"""
        db = _open_db(db_path)
        run_dir, run_id, cause_id, link_id, eid = _make_abnormal_run(project_env, db)
        # 清空 cause_candidates.json
        (run_dir / "cause_candidates.json").write_text("[]", encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_cause_candidate_missing_db(self, project_env, db_path):
        """cause_candidate 不在 DB → reject"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        run_id = str(new_uuid())
        req_id = str(new_uuid())
        obs_id = str(new_uuid())
        fake_cause_id = str(new_uuid())
        eid = str(new_uuid())

        _make_evidence(db, eid)
        db.upsert(AbnormalMoveRun(
            run_id=run_id, task_id=task_id, request_id=req_id,
            observation_id=obs_id,
            idempotency_key=f"k_{task_id}", run_version=1,
            started_at=T0, finished_at=T0,
        ))
        link_id = str(new_uuid())
        db.upsert(CauseEvidenceLink(
            link_id=link_id, cause_candidate_id=fake_cause_id, evidence_id=eid,
            relation="supports", independence_group="g1", created_at=T0,
        ))

        (run_dir / "abnormal_move_run.json").write_text(json.dumps({
            "run_id": run_id, "task_id": task_id, "request_id": req_id,
        }), encoding="utf-8")
        (run_dir / "cause_candidates.json").write_text(json.dumps([
            {"cause_candidate_id": fake_cause_id, "request_id": req_id},
        ]), encoding="utf-8")
        (run_dir / "cause_evidence_links.json").write_text(json.dumps([{
            "link_id": link_id, "cause_candidate_id": fake_cause_id, "evidence_id": eid,
        }]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "ok": True, "errors": [], "warnings": [],
        }), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        # Should fail because CauseCandidate is not in DB
        assert result.error_code in (
            "INTEGRATION_SOURCE_RUN_MISMATCH",
            "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
            "INTEGRATION_READ_FAILED",
        )

    def test_artifact_cause_db_mismatch(self, project_env, db_path):
        """artifact CauseCandidate 与 DB 不一致 → reject"""
        db = _open_db(db_path)
        run_dir, run_id, cause_id, link_id, eid = _make_abnormal_run(project_env, db)
        # tamper artifact: change cause_candidate title
        (run_dir / "cause_candidates.json").write_text(json.dumps([{
            "cause_candidate_id": cause_id, "request_id": "forged_req",
            "title": "tampered",
        }]), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_validation_failed(self, project_env, db_path):
        """validation ok=false → INTEGRATION_RUN_NOT_ELIGIBLE"""
        db = _open_db(db_path)
        run_dir, _, _, _, _ = _make_abnormal_run(project_env, db)
        (run_dir / "validation.json").write_text(json.dumps({
            "ok": False, "errors": ["hard fail"], "warnings": [],
        }), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_RUN_NOT_ELIGIBLE"

    def test_db_task_id_mismatch(self, project_env, db_path):
        """DB run.task_id != run_dir.name → reject"""
        db = _open_db(db_path)
        run_dir, run_id, _, _, _ = _make_abnormal_run(project_env, db)
        # DB task_id already matches run_dir.name from fixture
        # Create a new run with mismatched task_id
        task_id2 = str(new_uuid())
        run_dir2 = project_env / "reports" / "runs" / task_id2
        run_dir2.mkdir(parents=True)
        run_id2 = str(new_uuid())
        req_id2 = str(new_uuid())
        obs_id2 = str(new_uuid())
        eid2 = str(new_uuid())
        _make_evidence(db, eid2)

        # DB run has task_id="different"
        db.upsert(AbnormalMoveRun(
            run_id=run_id2, task_id=str(new_uuid()), request_id=req_id2,
            observation_id=obs_id2,
            idempotency_key=f"k_{task_id2}", run_version=1,
            started_at=T0, finished_at=T0,
        ))
        cause_id2 = str(new_uuid())
        db.upsert(CauseCandidate(
            cause_candidate_id=cause_id2, request_id=req_id2,
            observation_id=obs_id2,
            title="x", cause_category="direct_trigger", retrieval_layer=1,
            evidence_ids=[eid2],
        ))
        link_id2 = str(new_uuid())
        db.upsert(CauseEvidenceLink(
            link_id=link_id2, cause_candidate_id=cause_id2, evidence_id=eid2,
            relation="supports", independence_group="g1", created_at=T0,
        ))

        (run_dir2 / "abnormal_move_run.json").write_text(json.dumps({
            "run_id": run_id2, "task_id": "different", "request_id": req_id2,
        }), encoding="utf-8")
        (run_dir2 / "cause_candidates.json").write_text(json.dumps([{
            "cause_candidate_id": cause_id2, "request_id": req_id2,
        }]), encoding="utf-8")
        (run_dir2 / "cause_evidence_links.json").write_text(json.dumps([{
            "link_id": link_id2, "cause_candidate_id": cause_id2, "evidence_id": eid2,
        }]), encoding="utf-8")
        (run_dir2 / "validation.json").write_text(json.dumps({
            "ok": True, "errors": [], "warnings": [],
        }), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("abnormal_move_analysis", run_dir2)
        assert result.status == "error"
        # task_id mismatch caught at canonical comparison stage
        assert result.error_code in (
            "INTEGRATION_SOURCE_RUN_MISMATCH",
            "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
        )

    def test_duplicate_evidence_dedup(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, _, _, _, eid = _make_abnormal_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("abnormal_move_analysis", run_dir)
        assert result.resolved_source_refs == [f"Evidence:{eid}"]


# ====================================================================
# Phase4 Tests
# ====================================================================

class TestEquityIntegration:

    def test_valid_equity_findings(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, fid, _ = _make_equity_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("stock_research_report", run_dir)

        assert result.status == "dry_run"
        assert f"ResearchFinding:{fid}" in result.resolved_source_refs

    def test_forged_run_request_id(self, project_env, db_path):
        """artifact run.request_id forged to match foreign finding"""
        db = _open_db(db_path)
        run_dir, fid, req_id = _make_equity_run(project_env, db)
        # forge artifact run request_id
        (run_dir / "equity_research_run.json").write_text(json.dumps({
            "run_id": json.loads((run_dir / "equity_research_run.json").read_text(encoding="utf-8"))["run_id"],
            "request_id": "forged",
            "task_id": run_dir.name,
        }), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_missing_run_json(self, project_env, db_path):
        """equity_research_run.json 缺失 → INTEGRATION_ARTIFACT_MISSING（R1: no fallback）"""
        db = _open_db(db_path)
        run_dir = project_env / "reports" / "runs" / str(new_uuid())
        run_dir.mkdir(parents=True)
        (run_dir / "equity_research_request.json").write_text('{"request_id":"x"}', encoding="utf-8")
        (run_dir / "research_findings.json").write_text("[]", encoding="utf-8")
        (run_dir / "validation.json").write_text('{"status":"pass"}', encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_MISSING"

    def test_db_run_missing(self, project_env, db_path):
        """run_id 在 DB 中不存在 → reject"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)
        fake_run_id = str(new_uuid())
        fake_req_id = str(new_uuid())

        _make_evidence(db, str(new_uuid()))
        (run_dir / "equity_research_run.json").write_text(json.dumps({
            "run_id": fake_run_id, "request_id": fake_req_id, "task_id": task_id,
        }), encoding="utf-8")
        (run_dir / "equity_research_request.json").write_text(json.dumps({
            "request_id": fake_req_id, "company_entity_id": "company:600519.SH",
            "security_entity_id": "security:600519.SH",
            "as_of": T0, "as_of_basis": "user_provided", "report_date": "2026-08-07",
            "timezone": "Asia/Shanghai", "requested_at": T0,
        }), encoding="utf-8")
        (run_dir / "research_findings.json").write_text("[]", encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": "pass", "errors": [], "warnings": [],
        }), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_cross_run_finding(self, project_env, db_path):
        """foreign finding 注入 → INTEGRATION_SOURCE_RUN_MISMATCH"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        run_id = str(new_uuid())
        run_req = str(new_uuid())
        foreign_req = str(new_uuid())
        eid = str(new_uuid())

        _make_evidence(db, eid)
        db.upsert(EquityResearchRun(
            run_id=run_id, request_id=run_req, task_id=task_id,
            idempotency_key=f"k_{task_id}", run_version=1,
            started_at=T0, status="success",
        ))
        db.upsert(EquityResearchRequest(
            request_id=run_req, task_id=task_id,
            company_entity_id="company:600519.SH", security_entity_id="security:600519.SH",
            as_of=T0, as_of_basis="user_provided", report_date="2026-08-07",
            timezone="Asia/Shanghai", requested_at=T0,
        ))
        fid = str(new_uuid())
        db.upsert(ResearchFinding(
            finding_id=fid, request_id=foreign_req,  # foreign!
            company_entity_id="company:600519.SH", finding_type="business_analysis",
            title="x", statement="x", claim_type="FACT", predicate="reports",
            as_of=T0, evidence_ids=[eid], counter_evidence_ids=[],
            confidence=0.5, section_id="semantic", created_at=T0,
        ))

        finding_model = ResearchFinding(
            finding_id=fid, request_id=foreign_req,
            company_entity_id="company:600519.SH", finding_type="business_analysis",
            title="x", statement="x", claim_type="FACT", predicate="reports",
            as_of=T0, evidence_ids=[eid], counter_evidence_ids=[],
            confidence=0.5, section_id="semantic", created_at=T0,
        )
        (run_dir / "equity_research_run.json").write_text(json.dumps({
            "run_id": run_id, "request_id": run_req, "task_id": task_id,
        }), encoding="utf-8")
        (run_dir / "equity_research_request.json").write_text(json.dumps({
            "request_id": run_req, "company_entity_id": "company:600519.SH",
            "security_entity_id": "security:600519.SH",
            "as_of": T0, "as_of_basis": "user_provided", "report_date": "2026-08-07",
            "timezone": "Asia/Shanghai", "requested_at": T0,
        }), encoding="utf-8")
        (run_dir / "research_findings.json").write_text(json.dumps([
            finding_model.model_dump(),
        ]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": "pass", "errors": [], "warnings": [],
        }), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_full_finding_tamper(self, project_env, db_path):
        """Finding 非基本字段被篡改 → reject"""
        db = _open_db(db_path)
        run_dir, fid, _ = _make_equity_run(project_env, db)
        # 读取发现，篡改 confidence
        findings = json.loads((run_dir / "research_findings.json").read_text(encoding="utf-8"))
        findings[0]["confidence"] = 0.99  # tampered
        (run_dir / "research_findings.json").write_text(json.dumps(findings), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT"

    def test_validation_failed(self, project_env, db_path):
        """validation status=fail → INTEGRATION_RUN_NOT_ELIGIBLE"""
        db = _open_db(db_path)
        run_dir, _, _ = _make_equity_run(project_env, db)
        (run_dir / "validation.json").write_text(json.dumps({
            "status": "fail", "errors": ["hard fail"], "warnings": [],
        }), encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_RUN_NOT_ELIGIBLE"

    def test_db_task_id_mismatch(self, project_env, db_path):
        """DB run.task_id != run_dir.name → reject"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)
        run_id = str(new_uuid())
        req_id = str(new_uuid())
        eid = str(new_uuid())

        _make_evidence(db, eid)
        # DB task_id != run_dir.name
        db.upsert(EquityResearchRun(
            run_id=run_id, request_id=req_id, task_id="different",
            idempotency_key=f"k_{task_id}", run_version=1,
            started_at=T0, status="success",
        ))
        db.upsert(EquityResearchRequest(
            request_id=req_id, task_id=task_id,
            company_entity_id="company:600519.SH", security_entity_id="security:600519.SH",
            as_of=T0, as_of_basis="user_provided", report_date="2026-08-07",
            timezone="Asia/Shanghai", requested_at=T0,
        ))
        fid = str(new_uuid())
        finding = ResearchFinding(
            finding_id=fid, request_id=req_id,
            company_entity_id="company:600519.SH", finding_type="business_analysis",
            title="x", statement="x", claim_type="FACT", predicate="reports",
            as_of=T0, evidence_ids=[eid], counter_evidence_ids=[],
            confidence=0.5, section_id="semantic", created_at=T0,
        )
        db.upsert(finding)

        (run_dir / "equity_research_run.json").write_text(json.dumps({
            "run_id": run_id, "request_id": req_id, "task_id": "different",
        }), encoding="utf-8")
        (run_dir / "equity_research_request.json").write_text(json.dumps({
            "request_id": req_id, "company_entity_id": "company:600519.SH",
            "security_entity_id": "security:600519.SH",
            "as_of": T0, "as_of_basis": "user_provided", "report_date": "2026-08-07",
            "timezone": "Asia/Shanghai", "requested_at": T0,
        }), encoding="utf-8")
        (run_dir / "research_findings.json").write_text(json.dumps([
            finding.model_dump(),
        ]), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({
            "status": "pass", "errors": [], "warnings": [],
        }), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_RUN_MISMATCH"

    def test_no_eligible_sources(self, project_env, db_path):
        """空 findings → no eligible sources"""
        db = _open_db(db_path)
        run_dir, _, _ = _make_equity_run(project_env, db)
        (run_dir / "research_findings.json").write_text("[]", encoding="utf-8")
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("stock_research_report", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_NO_ELIGIBLE_SOURCES"


# ====================================================================
# M9 Core Tests
# ====================================================================

class TestM9Core:

    def test_unsupported_scenario(self, project_env, db_path):
        db = _open_db(db_path)
        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("unknown", project_env / "reports" / "runs" / "x")
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SCENARIO_UNSUPPORTED"

    def test_source_limit_exceeded(self, project_env, db_path):
        """source > 20 → reject"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        eid = str(new_uuid())
        ev = _make_evidence(db, eid)
        claims_art = []
        for i in range(25):
            cid = str(new_uuid())
            claim = _make_claim(db, cid, [eid], f"声明{i}")
            claims_art.append(claim.model_dump())

        (run_dir / "task.json").write_text(json.dumps({
            "task_id": task_id, "scenario": "morning_brief",
        }), encoding="utf-8")
        (run_dir / "evidence_index.json").write_text(json.dumps({eid: ev.model_dump()}), encoding="utf-8")
        (run_dir / "claims.json").write_text(json.dumps(claims_art), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        integrator = _make_integrator(db, project_env)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "error"
        assert result.error_code == "INTEGRATION_SOURCE_LIMIT_EXCEEDED"

    def test_explicit_subset(self, project_env, db_path):
        """显式子集 filter → pass"""
        db = _open_db(db_path)
        task_id = str(new_uuid())
        run_dir = project_env / "reports" / "runs" / task_id
        run_dir.mkdir(parents=True)

        eid = str(new_uuid())
        ev = _make_evidence(db, eid)
        cids = []
        claims_art = []
        for i in range(25):
            cid = str(new_uuid())
            cids.append(cid)
            claim = _make_claim(db, cid, [eid], f"声明{i}")
            claims_art.append(claim.model_dump())

        (run_dir / "task.json").write_text(json.dumps({
            "task_id": task_id, "scenario": "morning_brief",
        }), encoding="utf-8")
        (run_dir / "evidence_index.json").write_text(json.dumps({eid: ev.model_dump()}), encoding="utf-8")
        (run_dir / "claims.json").write_text(json.dumps(claims_art), encoding="utf-8")
        (run_dir / "validation.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")

        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("morning_brief", run_dir,
                                      selected_sources=[f"Claim:{cids[0]}", f"Claim:{cids[1]}"])
        assert result.status == "dry_run"
        assert len(result.selected_source_refs) == 2

    def test_dry_run_zero_provider(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, _, _ = _make_morning_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=True)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "dry_run"
        assert result.pipeline_result is not None
        assert result.pipeline_result.get("status") == "dry_run"

    def test_non_live_preflight(self, project_env, db_path):
        db = _open_db(db_path)
        run_dir, _, _ = _make_morning_run(project_env, db)
        integrator = _make_integrator(db, project_env, dry_run=False, live=False)
        result = integrator.integrate("morning_brief", run_dir)
        assert result.status == "preflight_only"
