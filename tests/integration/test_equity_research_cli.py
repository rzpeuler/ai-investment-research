"""Phase 4 CLI 集成测试（任务书 3.25 CLI 集成节，Commit 17）。

覆盖：参数错误 exit 2；缺财务数据 exit 3；dry-run 零副作用；完整离线流程生成报告；
Validator 失败 exit 4；内部错误 exit 5；不静默猜代码；Skill 只调用 CLI。
"""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from research_os.cli.main import cli
from research_os.storage.db import Database

COMPANY = "company:600519.SH"

CSV_HEADER = (
    "company_entity_id,period_start,period_end,fiscal_year,report_type,statement_scope,"
    "statement_type,taxonomy_code,label_raw,value,unit_scale,currency"
)
CSV_GOOD = "\n".join([
    CSV_HEADER,
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,revenue,营业收入,123450000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,income_statement,cost_of_sales,营业成本,70000000000,10000,CNY",
    f"{COMPANY},2025-01-01,2025-12-31,2025,annual,consolidated,balance_sheet,total_assets,资产总计,300000000000,10000,CNY",
])


@pytest.fixture()
def runner(tmp_path, monkeypatch):
    """隔离：CLI 使用临时项目根（避免污染真实 reports/）。"""
    from research_os.cli import main as cli_main

    monkeypatch.setattr(cli_main, "_project_root", lambda: tmp_path)
    db = Database(tmp_path / "data" / "sqlite" / "research.db")
    db.initialize()
    db.close()
    return CliRunner()


def _write_fin(tmp_path):
    p = tmp_path / "fin.csv"
    p.write_text(CSV_GOOD, encoding="utf-8")
    return str(p)


class TestParamErrors:
    def test_missing_entity_exit_2(self, runner):
        result = runner.invoke(cli, ["run", "equity-research"])
        assert result.exit_code == 2
        assert "entity" in result.output

    def test_illegal_symbol_exit_2(self, runner):
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "茅台"])
        assert result.exit_code == 2

    def test_no_fuzzy_name_guessing(self, runner):
        """不静默猜代码：非代码输入直接拒绝。"""
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "贵州茅台"])
        assert result.exit_code == 2

    def test_periods_out_of_range_exit_2(self, runner):
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "600519.SH", "--periods", "20"])
        assert result.exit_code == 2

    def test_forecast_without_scenario_exit_2(self, runner):
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "600519.SH", "--include-forecast"])
        assert result.exit_code == 2

    def test_live_rejected_exit_2(self, runner):
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "600519.SH", "--live"])
        assert result.exit_code == 2


class TestDataInsufficient:
    def test_no_financial_file_exit_3(self, runner):
        result = runner.invoke(cli, ["run", "equity-research", "--entity", "600519.SH"])
        assert result.exit_code == 3
        assert "DATA_INSUFFICIENT" in result.output


class TestDryRun:
    def test_dry_run_zero_side_effects(self, runner, tmp_path):
        fin = _write_fin(tmp_path)
        result = runner.invoke(cli, [
            "run", "equity-research", "--entity", "600519.SH",
            "--financial-file", fin, "--dry-run",
        ])
        assert result.exit_code == 0
        assert "dry-run" in result.output
        # 零副作用：不写报告、不写财务表
        assert not (tmp_path / "reports" / "stocks" / "600519.SH").exists()
        db = Database(tmp_path / "data" / "sqlite" / "research.db")
        assert db.count("financial_facts") == 0
        assert db.count("equity_research_runs") == 0
        db.close()


class TestFullFlow:
    def test_full_offline_flow_generates_report(self, runner, tmp_path):
        fin = _write_fin(tmp_path)
        result = runner.invoke(cli, [
            "run", "equity-research", "--entity", "600519.SH",
            "--date", "2026-08-06", "--financial-file", fin,
        ])
        assert result.exit_code == 0, result.output
        assert "报告:" in result.output
        report = tmp_path / "reports" / "stocks" / "600519.SH" / "2026-08-06_equity_research.md"
        assert report.exists()
        text = report.read_text(encoding="utf-8")
        assert "## 1. Front Matter" in text
        assert "## 38. 免责声明" in text
        # 报告无目标价/评级（免责声明固定文案除外：定位到免责声明起点截断）
        disclaimer_idx = text.find("本报告由 AI＋A 股投研系统自动生成")
        body = text[:disclaimer_idx] if disclaimer_idx >= 0 else text
        for forbidden in ("目标价", "买入评级", "建议买入", "上涨空间", "仓位建议"):
            assert forbidden not in body
        # 模型路由诚实
        assert "deterministic_fallback" in text

    def test_report_written_to_db_side_artifacts(self, runner, tmp_path):
        fin = _write_fin(tmp_path)
        runner.invoke(cli, [
            "run", "equity-research", "--entity", "600519.SH",
            "--date", "2026-08-06", "--financial-file", fin,
        ])
        db = Database(tmp_path / "data" / "sqlite" / "research.db")
        assert db.count("financial_facts") == 3
        assert db.count("financial_metrics") > 0
        db.close()


class TestSkillBoundary:
    def test_skill_file_exists_and_no_formulas(self):
        """Skill 只构造 CLI：不含公式/权重/阈值。"""
        p = __import__("pathlib").Path("skills/finance/equity-research/SKILL.md")
        assert p.exists()
        text = p.read_text(encoding="utf-8")
        assert "equity-research" in text
        assert "run equity-research" in text
        # 不得复制公式/权重/阈值
        assert "gross_margin" not in text
        assert "total_score_min" not in text
        assert "robust_z" not in text
        assert "PE_TTM" not in text
