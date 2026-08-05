"""CLI 集成测试：research run / validate / probe-sources。"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli

# 真实 schemas 目录（复制进隔离项目根，使 CLI 的 schema 定位与真实一致）
REAL_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    """隔离的项目根：复制真实 schemas/，含 reports/data。"""
    root = tmp_path / "project"
    shutil.copytree(REAL_SCHEMAS, root / "schemas")
    (root / "reports").mkdir(parents=True)
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(root))
    return root


def test_run_creates_run_directory(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--scenario", "morning_brief",
                                 "--entity", "company:600519.SH"])
    assert result.exit_code == 0, result.output
    assert "[OK] 任务" in result.output
    assert "运行目录" in result.output

    runs = list((project_root / "reports" / "runs").iterdir())
    assert len(runs) == 1
    run_dir = runs[0]
    for f in ["task.json", "plan.json", "retrieval_log.jsonl",
              "evidence_index.json", "validation.json", "final.md", "errors.log"]:
        assert (run_dir / f).exists(), f"缺少 {f}"
    assert (run_dir / "module_results").is_dir()


def test_run_same_task_id_idempotent(project_root):
    runner = CliRunner()
    tid = "99999999-9999-9999-9999-999999999999"
    first = runner.invoke(cli, ["run", "--task-id", tid])
    assert first.exit_code == 0
    second = runner.invoke(cli, ["run", "--task-id", tid])
    assert second.exit_code == 0
    assert "[IDEMPOTENT]" in second.output
    runs = list((project_root / "reports" / "runs").iterdir())
    assert len(runs) == 1


def test_run_force_rebuilds(project_root):
    runner = CliRunner()
    tid = "88888888-8888-8888-8888-888888888888"
    assert runner.invoke(cli, ["run", "--task-id", tid]).exit_code == 0
    second = runner.invoke(cli, ["run", "--task-id", tid, "--force"])
    assert second.exit_code == 0
    assert "[OK] 任务" in second.output


def test_run_invalid_uuid_fails_cleanly(project_root):
    """非法 --task-id：无 traceback、清晰错误、非零退出码、不创建任务目录/DB 记录。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--task-id", "not-a-uuid"])
    assert result.exit_code != 0
    assert "Traceback" not in result.output, "不得输出 Pydantic traceback"
    assert "UUID" in result.output, "应提示 task-id 必须是合法 UUID"
    # 不创建任务目录
    assert not (project_root / "reports" / "runs").exists() or \
        not any((project_root / "reports" / "runs").iterdir()), "不得创建任务目录"
    # 不创建数据库记录
    import sqlite3

    db_path = project_root / "data" / "sqlite" / "research.db"
    if db_path.exists():
        conn = sqlite3.connect(db_path)
        n = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        conn.close()
        assert n == 0, "不得写入数据库记录"


def test_run_invalid_scenario_fails(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--scenario", "buy_stocks"])
    assert result.exit_code != 0


def test_run_valid_uuid_still_works(project_root):
    """合法 UUID 不受校验影响。"""
    runner = CliRunner()
    tid = "99999999-9999-4999-8999-999999999999"
    result = runner.invoke(cli, ["run", "--task-id", tid])
    assert result.exit_code == 0, result.output
    assert (project_root / "reports" / "runs" / tid).exists()


def test_morning_brief_invalid_params_clean_errors():
    """非法日期/非法 as-of：清晰错误、无 traceback、不创建部分任务（19.2 节）。"""
    runner = CliRunner()
    r1 = runner.invoke(cli, ["run", "morning-brief", "--date", "not-a-date", "--dry-run"])
    assert r1.exit_code != 0
    assert "--date 非法" in r1.output
    assert "Traceback" not in r1.output
    r2 = runner.invoke(cli, ["run", "morning-brief", "--as-of", "yesterday", "--dry-run"])
    assert r2.exit_code != 0
    assert "--as-of 非法" in r2.output
    assert "Traceback" not in r2.output


def test_morning_brief_dry_run_no_side_effects(project_root):
    """dry-run：只输出计划，不写任何产物。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "morning-brief",
                                 "--date", "2026-08-06", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "[DRY-RUN]" in result.output
    assert "信息窗口" in result.output
    # 未生成报告与运行目录
    assert not (project_root / "reports" / "morning").exists()
    assert not (project_root / "reports" / "runs").exists()


def test_validate_schemas_ok(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["validate"])
    assert result.exit_code == 0, result.output
    assert "19 个 Schema 通过" in result.output


def test_validate_report_missing_frontmatter_fails(project_root):
    runner = CliRunner()
    p = project_root / "bad_report.md"
    p.write_text("# 无 Front Matter\n", encoding="utf-8")
    result = runner.invoke(cli, ["validate", "--report", str(p)])
    assert result.exit_code == 1
    assert "缺少 Front Matter" in result.output


def test_validate_report_ok(project_root):
    runner = CliRunner()
    p = project_root / "good_report.md"
    fm = (
        "---\n"
        "report_id: rep-1\nscenario: stock_research_report\ntitle: 测试\n"
        "created_at: 2026-08-05T08:00:00\nas_of: 2026-08-05T08:00:00\n"
        "timezone: Asia/Shanghai\nentities: []\n"
        "time_window: {start: null, end: null}\ndata_status: ok\n"
        "source_coverage: {}\nmodel_route: flash_default\n"
        "runtime_seconds: 1\nvalidator_status: pending\nknowledge_coordinates: []\n"
        "---\n正文\n"
    )
    p.write_text(fm, encoding="utf-8")
    result = runner.invoke(cli, ["validate", "--report", str(p)])
    assert result.exit_code == 0, result.output


def test_validate_report_missing_project_root_fails(monkeypatch, tmp_path):
    """未设置 RESEARCH_PROJECT_PATH 且 cwd 无 schemas/ 时明确报错。"""
    monkeypatch.delenv("RESEARCH_PROJECT_PATH", raising=False)
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["validate"])
        assert result.exit_code != 0
        assert "未找到项目根" in result.output


def test_probe_sources_ok(project_root):
    """无参数 probe-sources：列出已登记探测规格，不发起网络请求（离线）。"""
    runner = CliRunner()
    result = runner.invoke(cli, ["probe-sources"])
    assert result.exit_code == 0
    assert "已登记探测规格" in result.output
    assert "cninfo" in result.output
    assert "nbs" in result.output


def test_probe_sources_unknown_source_fails(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["probe-sources", "--source", "no_such_source"])
    assert result.exit_code != 0
    assert "未登记来源" in result.output


def test_probe_sources_unknown_group_fails(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["probe-sources", "--group", "aliens"])
    assert result.exit_code != 0
    assert "未登记分组" in result.output


def test_run_plan_contains_scenario(project_root):
    runner = CliRunner()
    result = runner.invoke(cli, ["run", "--scenario", "abnormal_move_analysis"])
    assert result.exit_code == 0
    runs = list((project_root / "reports" / "runs").iterdir())
    plan = json.loads((runs[0] / "plan.json").read_text(encoding="utf-8"))
    assert plan["scenario"] == "abnormal_move_analysis"
