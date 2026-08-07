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
import json
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


@cli.group(invoke_without_command=True)
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
@click.pass_context
def run(ctx, task_id, scenario, entities, depth, as_of, force) -> None:
    """运行任务。

    无子命令时运行空任务（生成 Task、Plan 和 Run 目录）。
    子命令：research run morning-brief [--date ...]（晨报流水线）。
    """
    if ctx.invoked_subcommand is not None:
        return  # 子命令自行处理
    root = _project_root()
    orch = Orchestrator(root)
    try:
        outcome = orch.run(
            scenario=scenario,
            entities=list(entities),
            depth=depth,
            task_id=task_id,
            as_of=as_of,
            force=force,
        )
    finally:
        orch.close()
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


@cli.group("llm")
def llm_group() -> None:
    """LLM Provider 配置与显式在线探测。"""


@llm_group.command("probe")
@click.option("--provider", "provider_id", default="deepseek", show_default=True,
              help="已登记 Provider ID。")
@click.option("--model-class", default="flash", show_default=True,
              type=click.Choice(["flash", "pro"]), help="探测逻辑模型等级。")
@click.option("--live", is_flag=True, help="显式允许一次低成本 Provider 网络调用。")
def llm_probe(provider_id, model_class, live) -> None:
    """输出脱敏 Provider 探测摘要；无 --live 时绝不访问网络。"""
    from research_os.llm.probe import probe_provider

    root = _project_root()
    try:
        result = probe_provider(
            root, provider_id=provider_id, model_class=model_class, live=live)
    except (KeyError, ValueError) as exc:
        raise click.ClickException(str(exc)) from None
    click.echo(json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True))
    if live and not result.reachable:
        raise SystemExit(1)

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
    if db is not None:
        db.initialize()  # 确保迁移已应用

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


@cli.group()
def inbox() -> None:
    """人工 Inbox：用户放入 URL/标题/摘要（不自动进入知识图谱）。"""


@inbox.command("add")
@click.option("--name", "source_name", required=True, help="来源名称。")
@click.option("--url", "source_url", required=True, help="来源 URL。")
@click.option("--title", required=True, help="标题。")
@click.option("--excerpt", default="", help="手动摘录（不自动视为事实）。")
@click.option("--notes", default="", help="备注。")
@click.option("--entity", "entities", multiple=True, help="意图关联实体（可重复）。")
@click.option("--published-at", "published_at", default=None,
              help="内容发布时间 ISO-8601（默认提交时间）。")
def inbox_add(source_name, source_url, title, excerpt, notes, entities,
              published_at) -> None:
    """新增 inbox 条目（submitted 状态）。"""
    from pydantic import ValidationError

    from research_os.collectors.manual import ManualInboxService
    from research_os.storage import Database

    root = _project_root()
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    service = ManualInboxService(db)
    try:
        entry = service.add(
            source_name=source_name, source_url=source_url, title=title,
            content_excerpt=excerpt, notes=notes, intended_entities=list(entities),
            published_at=published_at,
        )
    except ValidationError as exc:
        db.close()
        first = exc.errors()[0] if exc.errors() else {}
        raise click.ClickException(
            f"inbox 参数无效: {first.get('loc', '?')} {first.get('msg', '')}"
        ) from None
    db.close()
    click.echo(f"[OK] inbox 条目 {entry.inbox_id} 已提交（status=submitted）")


@inbox.command("list")
@click.option("--status", default=None,
              type=click.Choice(["submitted", "parsed", "accepted", "rejected", "needs_review"]))
def inbox_list(status) -> None:
    """列出 inbox 条目。"""
    from research_os.collectors.manual import ManualInboxService
    from research_os.storage import Database

    root = _project_root()
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    service = ManualInboxService(db)
    entries = service.list(status=status)
    db.close()
    if not entries:
        click.echo("（空）")
        return
    for e in entries:
        click.echo(f"  [{e['status']:10s}] {e['inbox_id'][:8]}  {e['title'][:40]}  {e['source_url'][:50]}")


@inbox.command("status")
@click.argument("inbox_id")
@click.argument("new_status",
                type=click.Choice(["submitted", "parsed", "accepted", "rejected", "needs_review"]))
def inbox_status(inbox_id, new_status) -> None:
    """更新 inbox 条目状态。"""
    from research_os.collectors.manual import ManualInboxService
    from research_os.storage import Database

    root = _project_root()
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    service = ManualInboxService(db)
    entry = service.update_status(inbox_id, new_status)
    db.close()
    click.echo(f"[OK] {entry.inbox_id} -> {entry.status}")


@cli.command()
@click.option("--source", "source_id", default=None, help="仅检查指定来源。")
def health(source_id) -> None:
    """运行来源健康检查（可达性/结构探测，不抓取内容）。"""
    from research_os.collectors.market import SinaQuoteCollector
    from research_os.collectors.official import CninfoCollector
    from research_os.source_health import SourceHealthMonitor
    from research_os.source_registry import SourceRegistry
    from research_os.storage import Database

    root = _project_root()
    registry = SourceRegistry(root / "registry" / "sources.yaml")
    adapters = {
        "cninfo": CninfoCollector(),
        "sina_quote": SinaQuoteCollector(),
    }
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    monitor = SourceHealthMonitor(registry, adapters, db)
    records = monitor.check(source_ids=[source_id] if source_id else None)
    db.close()
    if not records:
        click.echo("（无可检查来源；已实现适配器: cninfo, sina_quote）")
    for r in records:
        msg = r.payload.get("message", "")
        click.echo(f"  [{r.status:15s}] {r.source_id:12s} {msg}")


@run.command("morning-brief")
@click.option("--date", "report_date", default=None, help="报告日期 YYYY-MM-DD（默认今天 Asia/Shanghai）。")
@click.option("--as-of", default=None, help="数据截止时间 ISO-8601（默认窗口结束）。")
@click.option("--depth", default="standard", type=click.Choice(["fast", "standard", "deep"]))
@click.option("--force", is_flag=True, help="已存在通过校验的报告时强制重跑（产生新版本，不覆盖旧报告）。")
@click.option("--dry-run", is_flag=True, help="只计算窗口/来源/模块计划与输出路径，不写入任何产物。")
@click.option("--live", is_flag=True, help="发起真实网络采集（默认仅使用 manual_inbox，离线）。")
def run_morning_brief(report_date, as_of, depth, force, dry_run, live) -> None:
    """生成每日晨报（Phase 2 流水线）。

    默认窗口：前一日 20:00 至当日 08:00（Asia/Shanghai）。
    幂等键：scenario + report_date + window_start + window_end。
    """
    root = _project_root()
    orch = Orchestrator(root)
    try:
        outcome = orch.execute("morning_brief", {
            "report_date": report_date, "as_of": as_of, "depth": depth,
            "force": force, "dry_run": dry_run, "live": live,
        })
    finally:
        orch.close()
    _print_scenario_outcome(outcome, dry_run=dry_run)


@cli.group()
def market_data() -> None:
    """市场数据管理：人工日线导入（Phase 3）。"""


@market_data.command("import-daily")
@click.option("--file", "file_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=str),
              help="CSV/Parquet 文件路径。")
@click.option("--source", "source_id", default="manual_import",
              help="来源 ID（默认 manual_import）。")
@click.option("--adjustment", default="none",
              type=click.Choice(["none", "qfq", "hfq"]),
              help="复权口径（一个批次只能一种）。")
@click.option("--calendar", "calendar_id", default="cn-exchange",
              help="交易日历 ID（默认 cn-exchange，周一至周五）。")
@click.option("--imported-by", default="user", help="导入人标识。")
@click.option("--data-version", default=None, help="数据版本号（默认自动生成）。")
@click.option("--dry-run", is_flag=True, default=False,
              help="只解析和校验，展示预计写入行数/日期范围/重复行/问题；不写数据库、不建 manifest。")
def market_data_import_daily(file_path, source_id, adjustment, calendar_id,
                             imported_by, data_version, dry_run) -> None:
    """人工导入历史日线（最低字段 symbol/trade_date/open/high/low/close/volume）。

    质量检查：日期、重复键、OHLC 关系、负值、停牌缺口、交易日。
    失败导入（存在 rejected 行）不写入正式日线表；不允许静默修改用户数据。
    """
    from research_os.abnormal_move.market_data_loader import DailyImportService
    from research_os.storage import Database

    root = _project_root()
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    service = DailyImportService(db)
    try:
        result = service.import_file(
            path=file_path, source_id=source_id, adjustment=adjustment,
            calendar_id=calendar_id, imported_by=imported_by,
            data_version=data_version, dry_run=dry_run,
        )
    except (FileNotFoundError, ValueError) as exc:
        db.close()
        raise click.ClickException(str(exc)) from None
    db.close()

    p = result.preview
    prefix = "[DRY-RUN]" if dry_run else "[OK]"
    click.echo(f"{prefix} 文件: {p.file_name}  复权: {p.adjustment_method}  日历: {p.calendar_id}")
    click.echo(f"{prefix} 行数: {p.rows_total}（accepted={p.rows_accepted}, rejected={p.rows_rejected}）")
    click.echo(f"{prefix} 符号: {', '.join(p.symbols) or '（空）'}")
    click.echo(f"{prefix} 日期范围: {p.date_start or '?'} 至 {p.date_end or '?'}")
    if p.duplicate_keys:
        click.echo(f"{prefix} 重复行: {len(p.duplicate_keys)}（{', '.join(p.duplicate_keys[:5])}...）")
    for issue in p.issues[:20]:
        click.echo(f"{prefix}  问题: {issue}")
    for w in p.warnings[:20]:
        click.echo(f"{prefix}  警告: {w}")
    if dry_run:
        click.echo("[DRY-RUN] 未写入数据库、未创建 manifest、未修改任何报告或知识库。")
        return
    if result.validation_status == "rejected":
        click.echo(f"[WARN] 存在 rejected 行（{p.rows_rejected}），正式日线表仅写入 accepted 行（{result.written_rows} 行）；manifest validation_status=rejected。")
    else:
        click.echo(f"[OK] 已写入正式日线表 {result.written_rows} 行；manifest {result.manifest.import_id}（{result.validation_status}）。")


def _param_error(message: str) -> None:
    """参数错误：退出码 2（任务书 17 节），不显示 traceback。"""
    exc = click.ClickException(message)
    exc.exit_code = 2
    raise exc


def _print_scenario_outcome(outcome, *, dry_run: bool = False) -> None:
    """统一打印场景结果并映射退出码。"""
    if dry_run or outcome.status == "planned":
        click.echo(f"[DRY-RUN] {outcome.message}")
    elif outcome.status == "idempotent_skipped":
        click.echo(f"[IDEMPOTENT] {outcome.message}")
    elif outcome.status == "insufficient_data":
        click.echo(f"[DATA_INSUFFICIENT] {outcome.message}")
    elif outcome.status == "failed":
        click.echo(f"[FAILED] {outcome.message}", err=True)
    else:
        click.echo(f"[OK] {outcome.message}")
    if outcome.report_path:
        click.echo(f"[OK] 报告: {outcome.report_path}")
    if outcome.run_dir:
        click.echo(f"[OK] 运行目录: {outcome.run_dir}")
    if outcome.exit_code:
        raise SystemExit(outcome.exit_code)


@run.command("abnormal-move")
@click.option("--entity", "entity_code", default=None, help="股票代码（如 600519.SH）。")
@click.option("--industry", "industry_id", default=None, help="行业实体 ID（如 industry:白酒）。")
@click.option("--concept", "concept_id", default=None, help="概念实体 ID（如 concept:白酒概念）。")
@click.option("--date", "analysis_date", default=None, help="分析日期 YYYY-MM-DD（默认最近完整收盘交易日）。")
@click.option("--depth", default="standard", type=click.Choice(["fast", "standard", "deep"]))
@click.option("--granularity", default="daily", type=click.Choice(["daily", "minute"]))
@click.option("--force", is_flag=True, help="已存在通过验证的结果时强制重跑（新 run_version，不覆盖旧产物）。")
@click.option("--dry-run", is_flag=True, help="只计算不写入任何产物。")
@click.option("--as-of", default=None, help="数据截止时间 ISO-8601。")
@click.option("--window-start", default=None, help="分析窗口开始 YYYY-MM-DD。")
@click.option("--window-end", default=None, help="分析窗口结束 YYYY-MM-DD。")
@click.option("--peer", "peers", multiple=True, help="同行股票代码（可重复）。")
@click.option("--name", "entity_name", default="", help="报告显示名称。")
def run_abnormal_move(entity_code, industry_id, concept_id, analysis_date, depth,
                      granularity, force, dry_run, as_of, window_start, window_end,
                      peers, entity_name) -> None:
    """异动分析流水线（Phase 3）。

    --entity / --industry / --concept 三选一；股票代码必须通过实体解析。
    UNEXPLAINED_MOVE 是合法报告（退出码 0）；数据不足退出码 3；
    Validator 失败退出码 4；内部异常退出码 5；参数错误退出码 2。
    """
    import re

    # 参数校验：三选一
    chosen = [x for x in (entity_code, industry_id, concept_id) if x]
    if len(chosen) != 1:
        _param_error("必须且只能指定一个：--entity / --industry / --concept")
    if granularity == "minute":
        _param_error("minute 粒度暂无数据源（仅 Schema/模型/Loader Protocol），请使用 daily")
    if entity_code is not None:
        if not re.match(r"^\d{6}\.(SH|SZ)$", entity_code):
            _param_error(
                f"股票代码非法: {entity_code!r}（需要 6 位数字 + .SH/.SZ，如 600519.SH）")
        entity_id = entity_code
        entity_type = "company"
    else:
        entity_id = industry_id or concept_id
        entity_type = "industry" if industry_id else "concept"

    root = _project_root()
    orch = Orchestrator(root)
    try:
        outcome = orch.execute("abnormal_move_analysis", {
            "entity_id": entity_id, "entity_type": entity_type,
            "analysis_date": analysis_date, "depth": depth, "granularity": granularity,
            "force": force, "dry_run": dry_run, "as_of": as_of,
            "window_start": window_start, "window_end": window_end,
            "peers": list(peers), "entity_name": entity_name,
        })
    finally:
        orch.close()
    _print_scenario_outcome(outcome, dry_run=dry_run)


@run.command("equity-research")
@click.option("--entity", "entity_code", default=None, help="股票代码（如 600519.SH）。必填。")
@click.option("--date", "report_date", default=None, help="报告日期 YYYY-MM-DD。")
@click.option("--as-of", default=None, help="数据截止时间 ISO-8601。")
@click.option("--depth", default="standard", type=click.Choice(["fast", "standard", "deep"]))
@click.option("--periods", default=5, type=int, help="可比年度数（2-10）。")
@click.option("--peer", "peers", multiple=True, help="同行股票代码（可重复；只加入候选，不自动合格）。")
@click.option("--scenario", "scenario_ids", multiple=True, help="情景 ID（可重复；需先有情景数据）。")
@click.option("--include-valuation", "include_valuation", is_flag=True, default=True,
              help="计算估值（默认开）。")
@click.option("--no-include-valuation", "include_valuation", is_flag=True, default=True,
              help="不计算估值。", flag_value=False)
@click.option("--include-forecast", is_flag=True, default=False,
              help="启用情景预测（默认关闭；无 Scenario 时拒绝）。")
@click.option("--financial-file", "financial_files", multiple=True,
              help="财务文件路径（CSV/JSON/XLSX，可重复）。")
@click.option("--document", "documents", multiple=True, help="文档路径（PDF/HTML，可重复）。")
@click.option("--market-file", "market_file", default=None, help="市值/股本/价格输入文件。")
@click.option("--force", is_flag=True, help="已存在时强制重跑（新 run_version，不覆盖旧产物）。")
@click.option("--dry-run", is_flag=True, help="只预览能力/路径/计划/数据缺口，零副作用。")
@click.option("--live", is_flag=True, help="只允许调用已批准来源（本阶段无已批准自动来源）。")
def run_equity_research(entity_code, report_date, as_of, depth, periods, peers,
                        scenario_ids, include_valuation, include_forecast,
                        financial_files, documents, market_file, force, dry_run,
                        live) -> None:
    """个股研报流水线（Phase 4）。

    退出码：0 成功/部分成功/合法降级/幂等跳过；2 参数或实体解析错误；
    3 核心数据不足；4 Validator 失败；5 内部错误。
    不允许公司名模糊猜代码；--peer 只加入候选不自动合格；--include-forecast
    无 Scenario 时参数错误；--dry-run 零副作用；--force 不覆盖旧产物。
    """
    import re as _re

    # 参数规则：不静默猜代码
    if not entity_code:
        _param_error("--entity 必填（股票代码，如 600519.SH）；不允许公司名模糊猜代码")
    if not _re.match(r"^\d{6}\.(SH|SZ|BJ)$", entity_code):
        _param_error(f"股票代码非法: {entity_code!r}（需要 6 位数字 + .SH/.SZ/.BJ）")
    if not (2 <= periods <= 10):
        _param_error("--periods 必须在 2-10 之间")
    if include_forecast and not scenario_ids:
        _param_error("--include-forecast 需要 --scenario（无 Scenario 时明确拒绝）")
    if live:
        _param_error("--live 只允许已批准来源；本阶段无已批准自动来源")
    if as_of and report_date and as_of[:10] > report_date:
        _param_error("--as-of 不得晚于 --date")

    root = _project_root()
    orch = Orchestrator(root)
    try:
        outcome = orch.execute("stock_research_report", {
            "entity": entity_code, "date": report_date, "as_of": as_of,
            "depth": depth, "periods": periods, "peers": list(peers),
            "scenario_ids": list(scenario_ids),
            "include_valuation": include_valuation,
            "include_forecast": include_forecast,
            "financial_files": list(financial_files),
            "documents": list(documents),
            "market_file": market_file,
            "force": force, "dry_run": dry_run, "live": live,
        })
    finally:
        orch.close()
    _print_scenario_outcome(outcome, dry_run=dry_run)


if __name__ == "__main__":
    cli()
