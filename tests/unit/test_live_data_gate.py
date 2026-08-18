"""P7-D3 M4b：--live-data 信任边界与 gate 分离测试。

覆盖任务书 §14-15、§42-43：
- 默认（无 --live-data）不联网：disabled path，Router/Repository 永不触达；
- --live-data 只注入真实 wiring，不打开 LLM provider；
- --live-data + dry_run → 仍 NO NETWORK / NO PERSISTENCE（DRY_RUN_PROHIBITS_EXECUTION）；
- 环境变量不得成为隐式 live-data 授权（代码中不存在 DATA_LIVE 等读取）；
- 真实 wiring 下 enabled=false + capability 未 BUSINESS_SUFFICIENT → 正常执行 fail closed。
全部离线。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from research_os.data_layer.coordinator import AcquisitionCoordinator
from research_os.data_layer.execution import AcquisitionExecutionService
from research_os.orchestrator.orchestrator import Orchestrator
from research_os.storage.db import Database

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def project(tmp_path) -> Path:
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    return project


class TestDefaultGateOff:
    def test_default_orchestrator_uses_disabled_path(self, project):
        orch = Orchestrator(project)
        coordinator = orch.acquisition_coordinator
        assert isinstance(coordinator, AcquisitionCoordinator)
        # disabled path：live gate 永久关闭
        assert coordinator._live_authorized is False
        orch.close()

    def test_default_execution_never_reaches_router(self, project):
        orch = Orchestrator(project)
        coordinator = orch.acquisition_coordinator
        execution: AcquisitionExecutionService = coordinator._execution
        # disabled path 的 Router 是哨兵：任何触达都会 AssertionError
        with pytest.raises(AssertionError, match="disabled production acquisition"):
            execution._router.resolve_with_items("macro_data", {}, {})
        orch.close()

    def test_normal_scenario_run_no_network_no_persistence(self, project, monkeypatch):
        # 普通执行（无 --live-data）：acquisition 保持 disabled，不产生网络/DB 副作用
        import research_os.orchestrator.orchestrator as mod
        created = []
        monkeypatch.setattr(
            mod, "Database", lambda *a, **k: _RecordingDatabase(created))
        orch = Orchestrator(project)
        orch.close()
        # disabled path 不构造真实 Repository（不写 acquisition DB）
        assert created == []


class _RecordingDatabase(Database):
    def __init__(self, created, *args, **kwargs):
        created.append(True)
        super().__init__(*args, **kwargs)


class TestLiveDataWiring:
    def test_live_data_injects_real_router_not_sentinel(self, project):
        db = Database(project / "data" / "sqlite" / "research.db")
        orch = Orchestrator(project, db=db, live_data=True)
        coordinator = orch.acquisition_coordinator
        assert coordinator._live_authorized is True
        execution: AcquisitionExecutionService = coordinator._execution
        from research_os.routing.router import Router
        assert isinstance(execution._router, Router)
        orch.close()

    def test_live_data_still_fails_closed_on_capability_gate(self, project, tmp_path):
        # 即使 --live-data：enabled=false 且 capability 未 BUSINESS_SUFFICIENT，
        # 正常 execution 仍 fail closed，不联网（真实验收走独立 acceptance harness）。
        db = Database(project / "data" / "sqlite" / "research.db")
        orch = Orchestrator(project, db=db, live_data=True)
        coordinator = orch.acquisition_coordinator
        execution: AcquisitionExecutionService = coordinator._execution
        from research_os.data_layer.execution import RouteExecutionInput

        plan = {
            "task_id": "11111111-1111-4111-8111-111111111111",
            "scenario": "morning_brief",
            "as_of": "2026-08-16T00:00:00+08:00",
            "steps": [
                {
                    "step_id": "22222222-2222-4222-8222-222222222222",
                    "requirement_id": "macro_data",
                    "data_type": "macro_data",
                    "action": "route_existing_sources",
                    "dependencies": [],
                    "status": "pending",
                    "warnings": [],
                }
            ],
            "warnings": [],
        }
        result = execution.execute(
            plan=plan, task_id="11111111-1111-4111-8111-111111111111",
            scenario="morning_brief",
            as_of="2026-08-16T00:00:00+08:00", dry_run=False, live_authorized=True,
            route_inputs={"macro_data": RouteExecutionInput(
                query={}, time_window={"start": None, "end": "2026-08-16T00:00:00+08:00"})},
        )
        assert result.status == "not_executable"
        assert result.steps[0].reason_codes[0] in (
            "EXECUTION_DISABLED", "CAPABILITY_NOT_BUSINESS_SUFFICIENT",
        )
        orch.close()

    def test_dry_run_with_live_data_no_network(self, project, monkeypatch):
        import research_os.collectors.government.nbs as nbs_mod
        calls = []
        monkeypatch.setattr(nbs_mod.subprocess, "run", lambda *a, **k: calls.append(1))
        db = Database(project / "data" / "sqlite" / "research.db")
        orch = Orchestrator(project, db=db, live_data=True)
        # dry_run 时 coordinate 返回 DRY_RUN_PROHIBITS_EXECUTION，不触达任何 collector
        result = orch.execute("morning_brief", {
            "task_id": "33333333-3333-4333-8333-333333333333",
            "report_date": "2026-08-16",
            "as_of": "2026-08-16T00:00:00+08:00",
            "dry_run": True,
        })
        assert result.status == "planned"  # dry-run 返回 planned / exit_code=0
        assert result.exit_code == 0
        assert result.validation_status == "not_run"
        assert calls == []
        orch.close()


class TestNoEnvVarAutoAuthorization:
    def test_no_env_var_gate_in_orchestrator(self):
        # 环境变量不得成为隐式 live-data 授权：orchestrator 源码不应读取 DATA_LIVE 等
        src = (ROOT / "src" / "research_os" / "orchestrator" / "orchestrator.py").read_text(
            encoding="utf-8")
        for forbidden in ("DATA_LIVE", "AUTO_DATA", "CI_LIVE", "os.environ"):
            assert forbidden not in src, f"orchestrator 不得读取环境变量 {forbidden}"

    def test_no_env_var_gate_in_cli(self):
        src = (ROOT / "src" / "research_os" / "cli" / "main.py").read_text(encoding="utf-8")
        for forbidden in ("DATA_LIVE", "AUTO_DATA", "CI_LIVE"):
            assert forbidden not in src, f"CLI 不得读取环境变量 {forbidden}"


class TestCliLiveDataFlag:
    """CLI --live-data 端到端：不崩溃、dry-run 零副作用、与 --live 分离。"""

    def test_cli_execute_live_data_dry_run_no_network(self, tmp_path):
        import json

        from click.testing import CliRunner

        from research_os.cli.main import cli
        from research_os.utils.time import now_iso

        req = tmp_path / "req.json"
        req.write_text(json.dumps({
            "task_id": "55555555-5555-4555-8555-555555555555",
            "report_date": "2026-08-18",
            "as_of": "2026-08-18T00:00:00+08:00",
            "dry_run": True,
        }, ensure_ascii=False), encoding="utf-8")
        runner = CliRunner()
        result = runner.invoke(cli, [
            "execute", "--scenario", "morning_brief",
            "--request-file", str(req), "--live-data",
        ])
        assert result.exit_code == 0, result.output
        assert "dry-run" in result.output or "dry_run" in result.output

    def test_cli_help_separates_live_data_from_live(self):
        from click.testing import CliRunner

        from research_os.cli.main import cli

        runner = CliRunner()
        result = runner.invoke(cli, ["execute", "--help"])
        assert "--live-data" in result.output
        assert "真实数据采集" in result.output


class TestDryRunNoPersistence:
    """D3 独立验收修复：dry-run + --live-data 不得创建/初始化 SQLite（NO PERSISTENCE）。"""

    def test_orchestrator_lazy_db_not_created_on_dry_run(self, project, monkeypatch):
        # live_data=True 但不显式传 db：惰性路径。dry-run 执行后不得落盘。
        import research_os.collectors.government.nbs as nbs_mod
        calls = []
        monkeypatch.setattr(nbs_mod.subprocess, "run", lambda *a, **k: calls.append(1))
        orch = Orchestrator(project, live_data=True)
        # 惰性赋值阶段：db 对象存在但未初始化（不得落盘）
        assert orch._db is not None
        db_path = project / "data" / "sqlite" / "research.db"
        assert not db_path.exists(), "构造 Orchestrator 不得初始化 SQLite（dry-run 语义）"
        result = orch.execute("morning_brief", {
            "task_id": "44444444-4444-4444-8444-444444444444",
            "report_date": "2026-08-16",
            "as_of": "2026-08-16T00:00:00+08:00",
            "dry_run": True,
        })
        assert result.status == "planned"
        assert result.exit_code == 0
        assert calls == []
        assert not db_path.exists(), "dry-run 结束不得创建 SQLite 文件"
        orch.close()

    def test_non_dry_run_initializes_db_when_needed(self, project):
        # 非 dry-run + live_data：execute 需要 DB 时才初始化（幂等）
        orch = Orchestrator(project, live_data=True)
        db = orch.db  # execute 路径的同一 ensure 逻辑
        assert (project / "data" / "sqlite" / "research.db").exists()
        assert db is orch._db
        orch.close()
