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
import uuid
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


def _validate_uuid(ctx: click.Context, param: click.Parameter, value: Optional[str]) -> Optional[str]:
    """校验 task-id 为合法 UUID；非法时返回清晰参数错误（不创建任何东西）。"""
    if value is None:
        return None
    try:
        uuid.UUID(value)
    except ValueError:
        raise click.BadParameter(
            f"'{value}' 不是合法 UUID。task-id 必须是 36 字符 UUID，"
            "例如 12345678-1234-1234-1234-123456789abc。"
        ) from None
    return value


@cli.command()
@click.option("--task-id", default=None, callback=_validate_uuid,
              help="任务 ID（UUID）。相同 ID 重复执行幂等。")
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
@click.option("--all", "probe_all", is_flag=True, default=False, help="探测注册表全部来源。")
@click.option("--source", "source_id", default=None, help="探测指定来源 ID。")
@click.option("--group", "group", default=None,
              help="按分组探测（official / government / market / news / company）。")
@click.option("--output", "output_dir", default=None, help="探测证据输出目录（默认 data/source_probes/）。")
@click.option("--no-write", is_flag=True, default=False, help="只输出结果，不写文件/数据库。")
def probe_sources(probe_all, source_id, group, output_dir, no_write) -> None:
    """探测来源可访问性。

    Phase 1：真实 HTTP 探测（curl），只验证可达性/字段/登录/JS 依赖，
    不抓取内容、不保存全文。未指定参数时列出全部已登记来源（不探测）。
    """
    from research_os.source_probe import PROBE_SPECS, probe_source, save_probe
    from research_os.storage import Database

    root = _project_root()

    # 选择探测目标
    specs = []
    if source_id:
        specs = [s for s in PROBE_SPECS if s.source_id == source_id]
        if not specs:
            raise click.ClickException(f"未登记来源: {source_id}")
    elif group:
        specs = [s for s in PROBE_SPECS if s.group == group]
        if not specs:
            raise click.ClickException(f"未登记分组: {group}")
    elif probe_all:
        specs = list(PROBE_SPECS)
    else:
        click.echo("已登记探测规格（未执行探测；使用 --all / --source / --group 发起）：")
        for s in PROBE_SPECS:
            click.echo(f"  [{s.group:10s}] {s.source_id:14s} {s.name}")
        return

    out_dir = output_dir or str(root / "data" / "source_probes")
    db = None if no_write else Database(root / "data" / "sqlite" / "research.db")

    referer = None
    for spec in specs:
        click.echo(f"=== 探测 {spec.source_id} ({spec.name}) ===")
        try:
            probe = probe_source(spec, referer=referer)
        except Exception as exc:  # noqa: BLE001
            click.echo(f"[FAIL] {spec.source_id}: 探测失败 {exc}", err=True)
            continue
        click.echo(f"  状态: {probe.status}  HTTP: {probe.http_status}  "
                   f"访问级别: {probe.access_level_detected}  "
                   f"JS依赖: {probe.requires_javascript}  登录: {probe.requires_login}")
        if probe.fields_detected:
            click.echo(f"  确认字段: {', '.join(probe.fields_detected)}")
        for n in probe.notes:
            click.echo(f"  注: {n}")
        for e in probe.errors:
            click.echo(f"  错: {e}")
        if not no_write:
            path = save_probe(root, probe, db=db)
            click.echo(f"  证据: {path}")
    if db is not None:
        db.close()
    click.echo("")
    click.echo("探测完成。结论写入 data/source_probes/；来源注册表状态更新见 registry/changelog.md。")


if __name__ == "__main__":
    cli()
