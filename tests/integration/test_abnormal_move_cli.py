"""异动分析 CLI 集成测试（Phase 3 任务书 17 节：参数/退出码/幂等/force/dry-run）。"""
from __future__ import annotations

import csv
import shutil
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli

REAL_SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"
REAL_REGISTRY = Path(__file__).resolve().parents[2] / "registry"


@pytest.fixture()
def project_root(tmp_path, monkeypatch):
    root = tmp_path / "project"
    shutil.copytree(REAL_SCHEMAS, root / "schemas")
    shutil.copytree(REAL_REGISTRY, root / "registry")
    (root / "reports").mkdir(parents=True)
    (root / "data" / "sqlite").mkdir(parents=True)
    monkeypatch.setenv("RESEARCH_PROJECT_PATH", str(root))
    return root


def _write_daily_csv(path: Path, symbol: str, days: int = 60,
                     final_move: float = 0.0) -> None:
    """生成日线 CSV（含最后一天可选异动）。"""
    rows = []
    d = date(2026, 5, 1)
    price = 10.0
    for i in range(days):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        is_last = i == days - 1
        close = price * (1 + final_move) if is_last else price
        rows.append({"symbol": symbol, "trade_date": d.isoformat(),
                     "open": close, "high": close * 1.01, "low": close * 0.99,
                     "close": close, "volume": 3000 if is_last else 1000})
        price *= 1.001
        d += timedelta(days=1)
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["symbol", "trade_date", "open",
                                                "high", "low", "close", "volume"])
        writer.writeheader()
        writer.writerows(rows)


@pytest.fixture()
def import_daily(project_root):
    """预置 600519.SH 日线（80 天覆盖到 8 月中旬，最后一天 +9.5%）。"""
    csv_path = project_root / "daily.csv"
    _write_daily_csv(csv_path, "600519.SH", days=80, final_move=0.095)
    runner = CliRunner()
    result = runner.invoke(cli, ["market-data", "import-daily", "--file", str(csv_path),
                                 "--adjustment", "qfq"])
    assert result.exit_code == 0, result.output
    return project_root


class TestCliParams:
    def test_requires_exactly_one_target(self, project_root):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move"])
        assert result.exit_code == 2
        assert "必须且只能指定一个" in result.output

    def test_invalid_entity_code(self, project_root):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519"])
        assert result.exit_code == 2
        assert "股票代码非法" in result.output

    def test_minute_granularity_rejected(self, project_root):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--granularity", "minute"])
        assert result.exit_code == 2
        assert "minute" in result.output

    def test_non_trading_day(self, project_root):
        runner = CliRunner()
        # 2026-08-08 周六
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--date", "2026-08-08"])
        assert result.exit_code == 2
        assert "不是交易日" in result.output


class TestCliPipeline:
    def test_no_daily_data_exit_3(self, project_root):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "000001.SZ"])
        assert result.exit_code == 3
        assert "数据不足" in result.output

    def test_full_flow_exit_0(self, import_daily):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--date", "2026-08-05", "--name", "贵州茅台"])
        assert result.exit_code == 0, result.output
        assert "[OK]" in result.output
        assert "报告" in result.output
        # 报告文件
        report = import_daily / "reports" / "abnormal_moves" / "2026" / "2026-08" / \
                 "2026-08-05_600519_SH_abnormal_move.md"
        assert report.exists()
        text = report.read_text(encoding="utf-8")
        assert "scenario: abnormal_move_analysis" in text
        assert "## 一、执行说明" in text
        # 运行产物
        runs = list((import_daily / "reports" / "runs").iterdir())
        assert runs
        run_dir = runs[0]
        for f in ["task.json", "plan.json", "scenario_execution_result.json",
                  "abnormal_move_request.json", "abnormal_move_run.json",
                  "abnormal_move_observation.json",
                  "anomaly_metrics.json", "benchmark_selection.json",
                  "cause_candidates.json", "attribution_result.json",
                  "validation.json", "model_route.json"]:
            assert (run_dir / f).exists(), f"缺少 {f}"
        import json
        task = json.loads((run_dir / "task.json").read_text(encoding="utf-8"))
        plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
        request = json.loads((run_dir / "abnormal_move_request.json").read_text(encoding="utf-8"))
        business_run = json.loads((run_dir / "abnormal_move_run.json").read_text(encoding="utf-8"))
        execution = json.loads((run_dir / "scenario_execution_result.json").read_text(encoding="utf-8"))
        assert {task["task_id"], plan["task_id"], request["task_id"],
                business_run["task_id"], execution["task_id"], run_dir.name} == {run_dir.name}

    def test_dry_run_zero_side_effect(self, import_daily):
        before = set((import_daily / "reports").rglob("*"))
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "[DRY-RUN]" in result.output
        after = set((import_daily / "reports").rglob("*"))
        assert before == after, "dry-run 不得产生任何报告副作用"

    def test_idempotent_skip(self, import_daily):
        runner = CliRunner()
        first = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH"])
        assert first.exit_code == 0
        second = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH"])
        assert second.exit_code == 0
        assert "[IDEMPOTENT]" in second.output
        runs = list((import_daily / "reports" / "runs").iterdir())
        assert len(runs) == 2  # 第二次请求仍保留统一控制面审计记录

    def test_force_new_version_no_overwrite(self, import_daily):
        runner = CliRunner()
        first = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH"])
        assert first.exit_code == 0
        second = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--force"])
        assert second.exit_code == 0
        assert "[IDEMPOTENT]" not in second.output
        runs = list((import_daily / "reports" / "runs").iterdir())
        assert len(runs) == 2, "force 产生新运行目录，不覆盖旧产物"

    def test_unexplained_move_is_exit_0(self, project_root):
        """无事件来源时 UNEXPLAINED_MOVE 是合法报告（exit 0）。"""
        csv_path = project_root / "daily.csv"
        _write_daily_csv(csv_path, "600519.SH", days=60, final_move=0.095)
        runner = CliRunner()
        imp = runner.invoke(cli, ["market-data", "import-daily", "--file", str(csv_path)])
        assert imp.exit_code == 0
        result = runner.invoke(cli, ["run", "abnormal-move", "--entity", "600519.SH",
                                     "--date", "2026-08-05"])
        assert result.exit_code == 0, result.output
        # 归因状态合法（EXPLAINED/UNEXPLAINED_MOVE/INSUFFICIENT_EVIDENCE 任一）
        assert any(s in result.output for s in ("归因状态=", "[DRY-RUN]")), result.output


class TestIndustryAnalysis:
    def test_industry_requires_peers(self, project_root):
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--industry", "industry:白酒"])
        assert result.exit_code == 3
        assert "成分股" in result.output

    def test_industry_with_peers_exit_0(self, project_root):
        for i, sym in enumerate(("600519.SH", "000858.SZ")):
            csv_path = project_root / f"d{i}.csv"
            _write_daily_csv(csv_path, sym, days=60, final_move=0.03)
            runner = CliRunner()
            imp = runner.invoke(cli, ["market-data", "import-daily",
                                      "--file", str(csv_path)])
            assert imp.exit_code == 0
        runner = CliRunner()
        result = runner.invoke(cli, ["run", "abnormal-move", "--industry", "industry:白酒",
                                     "--peer", "600519.SH", "--peer", "000858.SZ",
                                     "--date", "2026-08-05"])
        assert result.exit_code == 0, result.output
        assert "归因状态=" in result.output
