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
    assert plan["steps"]
    assert plan["data_requirements"]
    assert plan["runtime_budget"]["max_runtime_seconds"] > 0
    assert plan["model_policy"]
    assert plan["fallback_policy"]


def test_default_registry_contains_all_core_scenarios(project):
    orch = Orchestrator(project)
    assert set(orch.registry.names()) == {
        "morning_brief", "abnormal_move_analysis", "stock_research_report",
    }
    orch.close()


def test_execute_rejects_unregistered_scenario(project):
    orch = Orchestrator(project)
    outcome = orch.execute("unregistered", {"dry_run": True})
    orch.close()
    assert outcome.status == "failed"
    assert outcome.exit_code == 2
    assert "未注册场景" in outcome.message


def test_execute_rejects_empty_plan(project):
    from research_os.orchestrator.scenario_registry import ScenarioRegistry
    from research_os.orchestrator.scenario_runner import ScenarioExecutionResult

    class EmptyPlanRunner:
        scenario = "morning_brief"
        version = "1.0.0"

        def validate_request(self, request):
            return request

        def build_plan(self, request, context):
            return {"steps": [], "data_requirements": []}

        def execute(self, request, context):
            return ScenarioExecutionResult(status="success", exit_code=0, task_id=context["task"].task_id)

    registry = ScenarioRegistry()
    registry.register(EmptyPlanRunner())
    orch = Orchestrator(project, registry=registry)
    outcome = orch.execute("morning_brief", {"dry_run": True})
    orch.close()
    assert outcome.exit_code == 2
    assert "空 Plan" in outcome.message


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
    - errors.log 记录时间、组件、异常类型、消息
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
    main = next(e for e in entries if "模拟数据库写入失败" in e["message"])
    assert main["level"] == "ERROR"
    assert main["component"] == "orchestrator"
    assert main["timestamp"], "必须记录时间"
    assert main["exception_type"] == "RuntimeError", "必须记录异常类型"
    assert main["task_id"] == "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
    # 二次失败（upsert 再次抛错）必须记录
    assert any("二次失败" in e["message"] for e in entries), "二次失败必须记录"


def test_run_failure_persists_failed_state(project, monkeypatch):
    """失败状态持久化（Phase 0.1 / 2.3）：

    - task.json.status == failed
    - task.json.finished_at 已写入
    - 数据库任务状态为 failed
    - validation.json 标明未完成
    - 无成功 final.md（保持占位）
    - 重复读取该任务时仍识别失败状态
    """
    from research_os.orchestrator import RunDirectory

    orch = Orchestrator(project)

    def module_boom(self, *args, **kwargs):
        raise RuntimeError("模拟模块执行异常")

    # 模拟任务执行中途（写 plan 阶段）模块异常；_mark_failed 中的
    # write_task/write_validation/db.upsert 均正常，从而验证状态同步。
    monkeypatch.setattr(RunDirectory, "write_plan", module_boom)
    tid = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    outcome = orch.run(task_id=tid)
    assert outcome.status == "failed"

    # task.json 状态
    task_json = outcome.run_dir / "task.json"
    import json

    task_data = json.loads(task_json.read_text(encoding="utf-8"))
    assert task_data["status"] == "failed"
    assert task_data["finished_at"], "finished_at 必须写入"
    assert task_data["task_id"] == tid

    # validation.json 标明未完成
    validation = json.loads((outcome.run_dir / "validation.json").read_text(encoding="utf-8"))
    assert validation["status"] == "failed"

    # final.md 不得为成功报告（保持占位）
    final = (outcome.run_dir / "final.md").read_text(encoding="utf-8")
    assert "待生成报告" in final

    # 数据库同步为 failed
    from research_os.storage import Database

    db = Database(project / "data" / "sqlite" / "research.db")
    stored = db.get("tasks", tid)
    db.close()
    assert stored is not None
    assert stored["status"] == "failed"
    assert stored["finished_at"], "数据库 finished_at 必须写入"

    # 重复读取该任务：仍识别失败状态（不重跑、不覆盖证据）
    retry = orch.run(task_id=tid)
    assert retry.status == "failed"
    assert "此前已失败" in retry.message
    task_data2 = json.loads(task_json.read_text(encoding="utf-8"))
    assert task_data2["status"] == "failed"

    # --force 可重跑（但 write_plan 仍抛错，仍为 failed）
    forced = orch.run(task_id=tid, force=True)
    assert forced.status == "failed"
