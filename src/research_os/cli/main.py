"""research CLI（工程指南立即执行清单第 7 条）。

命令：
  research run [--task-id UUID] [--scenario SCENARIO] [--entity CODE ...]
               [--depth fast|standard|deep] [--as-of ISO] [--force]
  research validate [--report PATH | --schemas]
  research probe-sources [--source SOURCE_ID]

Phase 0 不实现任何网页抓取；probe-sources 仅输出 stub 健康状态。
所有命令失败必须显式返回非零退出码，禁止静默失败。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from research_os.orchestrator import Orchestrator
from research_os.reports import validate_report as validate_report_file
from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    validate_all_schemas,
)


def _project_root() -> Path:
    """项目根：优先环境变量 RESEARCH_PROJECT_PATH，否则当前工作目录
    （README 要求从项目根运行）。每次调用动态读取，便于测试隔离。
    找到根后写入环境变量，供 schema_validator 等模块定位 schemas/。"""
    root = Path(os.environ.get("RESEARCH_PROJECT_PATH") or Path.cwd())
    if not (root / "schemas").exists():
        raise click.ClickException(
            f"未找到项目根（缺少 schemas/ 目录）: {root}。"
            "请从项目根目录运行，或设置 RESEARCH_PROJECT_PATH。"
        )
    os.environ.setdefault("RESEARCH_PROJECT_PATH", str(root))
    return root


@click.group()
def cli() -> None:
    """AI＋A股投研 Skill 系统 CLI。"""


@cli.command()
@click.option("--task-id", default=None, help="任务 ID（UUID）。相同 ID 重复执行幂等。")
@click.option("--scenario", default="morning_brief",
              type=click.Choice([
                  "morning_brief", "evening_brief", "daily_review",
                  "abnormal_move_analysis", "stock_research_report",
                  "first_coverage", "stock_review", "industry_research",
                  "theme_discovery", "earnings_expectation",
              ], case_sensitive=False))
@click.option("--entity", "entities", multiple=True, help="实体 ID（可重复）。")
@click.option("--depth", default="standard", type=click.Choice(["fast", "standard", "deep"]))
@click.option("--as-of", default=None, help="数据截止时间 ISO-8601。")
@click.option("--force", is_flag=True, help="已存在时重建运行目录。")
def run(task_id, scenario, entities, depth, as_of, force) -> None:
    """运行空任务：生成 Task、Plan 和 Run 目录（Phase 0 不采集数据）。"""
    root = _project_root()
    orch = Orchestrator(root)
    outcome = orch.run(
        scenario=scenario,
        entities=list(entities),
        depth=depth,
        task_id=task_id,
        as_of=as_of,
        force=force,
    )
    if outcome.status == "failed":
        click.echo(f"[FAILED] {outcome.message}", err=True)
        raise SystemExit(1)
    if outcome.status == "idempotent_skipped":
        click.echo(f"[IDEMPOTENT] {outcome.message}")
        raise SystemExit(0)
    click.echo(f"[OK] 任务 {outcome.task.task_id} 完成")
    click.echo(f"[OK] 运行目录: {outcome.run_dir}")
    click.echo(f"[OK] Plan: {outcome.plan.plan_id}")


@cli.command()
@click.option("--report", "report_path", default=None, help="校验 Markdown 报告文件。")
@click.option("--schemas", "check_schemas", is_flag=True, default=False,
              help="校验全部 JSON Schema 文件本身。")
def validate(report_path, check_schemas) -> None:
    """校验报告 Front Matter 或 Schema 文件。

    默认（无参数）校验全部 JSON Schema 文件。
    """
    root = _project_root()

    if report_path:
        result = validate_report_file(root / report_path if not Path(report_path).is_absolute() else report_path)
        if result.ok:
            click.echo(f"[OK] 报告校验通过: {report_path}")
            return
        for err in result.errors:
            click.echo(f"[FAIL] {err}", err=True)
        raise SystemExit(1)

    if not check_schemas:
        check_schemas = True  # 默认行为

    results = validate_all_schemas()
    failed = False
    for name in SCHEMA_NAMES:
        errors = results.get(name, ["未校验"])
        if errors:
            failed = True
            for err in errors:
                click.echo(f"[FAIL] {name}.schema.json: {err}", err=True)
        else:
            click.echo(f"[OK] {name}.schema.json 合法")
    if failed:
        raise SystemExit(1)
    click.echo(f"[OK] 全部 {len(SCHEMA_NAMES)} 个 Schema 通过")


@cli.command()
@click.option("--source", default=None, help="指定来源 ID（默认全部 stub）。")
def probe_sources(source) -> None:
    """探测来源可访问性（Phase 0：仅输出 stub 状态，不发起任何网络请求）。"""
    from research_os.collectors.stub import StubCollector

    ids = [source] if source else ["sse", "szse", "cninfo", "cls", "xueqiu", "nbs"]
    all_ok = True
    for sid in ids:
        stub = StubCollector(source_id=sid)
        status = stub.healthcheck()
        flag = "OK " if status.ok else "STUB"
        if not status.ok:
            all_ok = False
        click.echo(f"[{flag}] {status.source_id:12s} access={status.access:12s} {status.message}")
    click.echo("")
    click.echo("Phase 0：全部来源为 stub，尚未探测。")
    click.echo("Phase 1 将运行 scripts/probe_sources.py 进行真实探测（TODO）。")
    if not all_ok:
        click.echo("[INFO] stub 状态 ok=False 属预期行为（未探测来源禁止标记为可用）")


if __name__ == "__main__":
    cli()
