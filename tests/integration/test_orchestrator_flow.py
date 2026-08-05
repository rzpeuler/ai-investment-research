"""Orchestrator 空任务测试：Task/Plan/Run 目录生成、幂等性、失败记录。"""
from __future__ import annotations

import pytest

from research_os.orchestrator import Orchestrator, RunDirectory
from research_os.orchestrator.orchestrator import RunOutcome
from research_os.storage import Database


@pytest.fixture()
def project(tmp_path):
    root = tmp_path / "project"
    (root / "reports").mkdir(parents=True)
    return root


def test_run_generates_task_plan_and_run_dir(project):
    orch = Orchestrator(project)
    outcome = orch.run(scenario="morning_brief", entities=["company:600519.SH"])
    assert outcome.status == "created"
    assert outcome.task is not None
    assert outcome.plan is not None

    run_dir = RunDirectory(project / "reports" / "runs", outcome.task.task_id)
    assert run_dir.exists()
    # 运行目录文件齐全（指南 50 节）
    assert run_dir.task_json.exists()
    assert run_dir.plan_json.exists()
    assert run_dir.retrieval_log.exists()
    assert run_dir.evidence_index.exists()
    assert run_dir.validation_json.exists()
    assert run_dir.final_md.exists()
    assert run_dir.errors_log.exists()
    assert run_dir.module_results_dir.exists()


def test_run_task_file_passes_schema(project):
    orch = Orchestrator(project)
    outcome = orch.run()
    stored = outcome.run_dir / "task.json"
    from research_os.validators.schema_validator import validate_instance
    import json

    data = json.loads(stored.read_text(encoding="utf-8"))
    assert validate_instance(data, "task") == []
    assert data["status"] == "completed"
    assert data["timezone"] == "Asia/Shanghai"


def test_plan_file_contents(project):
    orch = Orchestrator(project)
    outcome = orch.run(scenario="abnormal_move_analysis")
    import json

    plan = json.loads((outcome.run_dir / "plan.json").read_text(encoding="utf-8"))
    assert plan["task_id"] == outcome.task.task_id
    assert plan["scenario"] == "abnormal_move_analysis"
    assert plan["depth"] == "standard"


def test_same_task_id_idempotent(project):
    """相同 task_id 重复执行：第二次幂等跳过，不重建目录。"""
    orch = Orchestrator(project)
    first = orch.run(task_id="11111111-1111-1111-1111-111111111111")
    assert first.status == "created"

    second = orch.run(task_id="11111111-1111-1111-1111-111111111111")
    assert second.status == "idempotent_skipped"

    run_dir = RunDirectory(project / "reports" / "runs", first.task.task_id)
    assert run_dir.exists()
    # 目录不重复创建（retrieval_log 只有一次 task_created 记录）
    entries = run_dir.retrieval_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(entries) == 1


def test_force_rebuilds(project):
    orch = Orchestrator(project)
    first = orch.run(task_id="22222222-2222-2222-2222-222222222222")
    assert first.status == "created"
    second = orch.run(task_id="22222222-2222-2222-2222-222222222222", force=True)
    assert second.status == "created"


def test_different_task_ids_do_not_collide(project):
    orch = Orchestrator(project)
    a = orch.run(task_id="33333333-3333-3333-3333-333333333333")
    b = orch.run(task_id="44444444-4444-4444-4444-444444444444")
    assert a.run_dir != b.run_dir
    assert a.run_dir.exists() and b.run_dir.exists()


def test_task_persisted_to_db(project):
    orch = Orchestrator(project)
    outcome = orch.run(task_id="55555555-5555-5555-5555-555555555555")
    db = Database(project / "data" / "sqlite" / "research.db")
    stored = db.get("tasks", outcome.task.task_id)
    db.close()
    assert stored is not None
    assert stored["status"] == "completed"
    assert stored["scenario"] == "morning_brief"


def test_run_uses_defaults(project):
    orch = Orchestrator(project)
    outcome = orch.run()
    assert outcome.status == "created"
    assert outcome.task.depth == "standard"
    assert outcome.task.scenario == "morning_brief"
    assert outcome.task.source_policy == "public_first"
    assert outcome.task.output_formats == ["markdown"]


def test_invalid_scenario_rejected(project):
    """非法 scenario 在 Task 构造层即失败（显式错误，非静默）。"""
    orch = Orchestrator(project)
    with pytest.raises(Exception):
        orch.run(scenario="buy_stocks")


def test_run_failure_path_returns_failed_and_logs_error(project, monkeypatch):
    """失败场景：运行中异常必须返回显式 failed 状态并写入 errors.log。

    模拟存储层异常（db.upsert 抛错），验证：
    - outcome.status == "failed"（禁止静默失败）
    - errors.log 记录时间、组件、异常消息
    - 不产生成功产物
    """
    orch = Orchestrator(project)

    def boom(*args, **kwargs):
        raise RuntimeError("模拟数据库写入失败")

    monkeypatch.setattr(orch.db, "upsert", boom)
    outcome = orch.run(task_id="eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee")

    assert outcome.status == "failed"
    assert outcome.errors == ["模拟数据库写入失败"]
    assert "任务执行失败" in outcome.message

    from research_os.utils.logging import ErrorLog

    log = ErrorLog(outcome.run_dir / "errors.log")
    entries = log.read()
    assert entries, "errors.log 应有记录"
    entry = entries[0]
    assert entry["level"] == "ERROR"
    assert entry["component"] == "orchestrator"
    assert entry["ts"], "必须记录时间"
    assert "模拟数据库写入失败" in entry["message"]
