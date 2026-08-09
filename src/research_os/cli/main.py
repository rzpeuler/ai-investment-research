"""research CLI（工程指南立即执行清单第 7 条）。

命令：
  research run [--task-id UUID] [--scenario SCENARIO] [--entity CODE ...]
               [--depth fast|standard|deep] [--as-of ISO] [--force]
  research execute --scenario SCENARIO --request-file REQUEST.json [--task-id UUID]
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
from research_os.orchestrator.runners import DEFAULT_SCENARIOS
from research_os.reports import validate_report as validate_report_file
from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    validate_all_schemas,
)


SCENARIO_CHOICES = DEFAULT_SCENARIOS


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
              type=click.Choice(SCENARIO_CHOICES, case_sensitive=False))
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


@cli.command("execute")
@click.option(
    "--scenario",
    required=True,
    type=click.Choice(SCENARIO_CHOICES, case_sensitive=True),
    help="要执行的已注册研究场景。",
)
@click.option(
    "--request-file",
    required=True,
    type=click.Path(exists=True, file_okay=True, dir_okay=False, readable=True, path_type=Path),
    help="包含完整场景请求的 UTF-8 JSON object 文件。",
)
@click.option(
    "--task-id",
    default=None,
    callback=_validate_uuid,
    help="可选任务 UUID；不得与请求文件中的 task_id 冲突。",
)
def execute_scenario(scenario: str, request_file: Path, task_id: Optional[str]) -> None:
    """通过默认 Orchestrator 执行公共研究场景。"""
    if not request_file.is_file():
        _param_error(f"request-file 不是普通文件: {request_file}")
    try:
        raw_request = request_file.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        _param_error(f"request-file 必须是可读 UTF-8 文件: {exc}")
    try:
        payload = json.loads(raw_request)
    except json.JSONDecodeError as exc:
        _param_error(f"request-file 不是合法 JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})")
    if not isinstance(payload, dict):
        _param_error("request-file JSON 根节点必须是 object")

    request_scenario = payload.pop("scenario", None)
    if request_scenario is not None and request_scenario != scenario:
        _param_error(
            f"scenario 冲突: --scenario={scenario}, request.scenario={request_scenario}"
        )

    if task_id is not None:
        request_task_id = payload.get("task_id")
        if request_task_id is None:
            payload["task_id"] = task_id
        elif request_task_id != task_id:
            _param_error(
                f"task_id 冲突: --task-id={task_id}, request.task_id={request_task_id}"
            )

    root = _project_root()
    orchestrator = Orchestrator(root)
    try:
        result = orchestrator.execute(scenario, payload)
    finally:
        orchestrator.close()
    click.echo(json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True))
    if result.exit_code:
        raise SystemExit(result.exit_code)


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


@cli.group("documents")
def documents_group() -> None:
    """官方披露文档的受控导入。"""


@documents_group.command("import-disclosure")
@click.option("--entity", "entity_code", required=True,
              help="股票代码（如 600519.SH）。")
@click.option("--file", "file_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--source-id", required=True, help="已登记官方来源 ID，如 cninfo。")
@click.option("--source-url", required=True, help="官方原始文件 URL。")
@click.option("--publisher", required=True, help="披露发布者。")
@click.option("--published-at", required=True, help="披露时间 ISO-8601。")
@click.option("--document-type", required=True,
              type=click.Choice([
                  "annual_report", "interim_report", "quarterly_report", "announcement",
                  "inquiry_letter", "inquiry_response", "prospectus", "ir_record",
                  "audit_report", "other",
              ]))
@click.option("--title", default=None, help="文档标题（默认原文件名）。")
@click.option("--report-period-end", default=None, help="报告期末 YYYY-MM-DD。")
@click.option("--fiscal-year", type=int, default=None, help="财年。")
def import_disclosure_command(
    entity_code, file_path, source_id, source_url, publisher, published_at,
    document_type, title, report_period_end, fiscal_year,
) -> None:
    """导入已下载的官方原件并生成 Document/RawItem/Evidence。"""
    import re as _re

    from research_os.documents import import_disclosure
    from research_os.storage import Database

    if not _re.match(r"^\d{6}\.(SH|SZ|BJ)$", entity_code):
        _param_error(f"股票代码非法: {entity_code!r}")
    root = _project_root()
    db = Database(root / "data" / "sqlite" / "research.db")
    db.initialize()
    try:
        result = import_disclosure(
            root, db, entity_code=f"company:{entity_code}", file_path=file_path,
            source_id=source_id, source_url=source_url, publisher=publisher,
            published_at=published_at, document_type=document_type, title=title,
            report_period_end=report_period_end, fiscal_year=fiscal_year,
        )
    except (FileNotFoundError, KeyError, ValueError, RuntimeError) as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        db.close()
    click.echo(json.dumps(result.model_dump(), ensure_ascii=False, sort_keys=True))

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
@click.option("--financial-binding", "financial_bindings", multiple=True,
              help="官方财务 locator 绑定清单 JSON（可重复）。")
@click.option("--document", "documents", multiple=True, help="文档路径（PDF/HTML，可重复）。")
@click.option("--market-file", "market_file", default=None, help="市值/股本/价格输入文件。")
@click.option("--force", is_flag=True, help="已存在时强制重跑（新 run_version，不覆盖旧产物）。")
@click.option("--dry-run", is_flag=True, help="只预览能力/路径/计划/数据缺口，零副作用。")
@click.option("--live", is_flag=True, help="显式启用已批准的 DeepSeek Provider 网络调用。")
def run_equity_research(entity_code, report_date, as_of, depth, periods, peers,
                        scenario_ids, include_valuation, include_forecast,
                        financial_files, financial_bindings, documents, market_file, force, dry_run,
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
            "financial_bindings": list(financial_bindings),
            "documents": list(documents),
            "market_file": market_file,
            "force": force, "dry_run": dry_run, "live": live,
        })
    finally:
        orch.close()
    _print_scenario_outcome(outcome, dry_run=dry_run)


# ---------- Phase 5：知识图谱 ----------

@cli.group("knowledge")
def knowledge_group() -> None:
    """Phase 5 产业图谱管理（本体种子、查询、审核）。"""


@knowledge_group.command("seed")
@click.option(
    "--ontology", "ontology_path",
    default="knowledge/ontology/industry_graph_v1.yaml",
    show_default=True,
    help="本体 YAML 文件路径（相对项目根）。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="0 写入：只加载、校验和报告预期操作。",
)
def knowledge_seed(ontology_path, db_path, dry_run) -> None:
    """导入产业图谱首版本体种子（确定性、幂等、零 LLM）。

    第二次运行产生 0 插入（纯幂等）。
    本体 YAML 需先通过 dry-run 验证。
    M2 修正：全量预检查、dry-run 支持 pre-v6 DB、输出含 ontology_sha256。
    """
    import hashlib

    from research_os.knowledge.ontology import load_ontology, OntologyLoadError
    from research_os.knowledge.repository import GraphRepository
    from research_os.storage import Database

    root = _project_root()

    # 解析路径
    ont_path = root / ontology_path
    db_full = root / db_path

    # ---- 加载本体（含 SHA256） ----
    try:
        nodes, edges, meta = load_ontology(ont_path)
    except (FileNotFoundError, OntologyLoadError) as exc:
        raise click.ClickException(str(exc)) from None

    ontology_id = meta["ontology_id"]
    ontology_version = meta["ontology_version"]
    ontology_sha256 = meta["ontology_sha256"]
    nodes_total = len(nodes)
    edges_total = len(edges)

    # ---- 数据库不存在 ----
    if not db_full.exists():
        if dry_run:
            # dry-run + DB 不存在：0 写入，只报告
            summary = {
                "status": "dry_run",
                "dry_run": True,
                "ontology_id": ontology_id,
                "ontology_version": ontology_version,
                "ontology_sha256": ontology_sha256,
                "nodes_total": nodes_total,
                "edges_total": edges_total,
                "nodes_inserted": 0,
                "edges_inserted": 0,
                "nodes_idempotent": 0,
                "edges_idempotent": 0,
                "nodes_would_insert": nodes_total,
                "edges_would_insert": edges_total,
                "migration_required": True,
                "conflicts": [],
                "db_path": str(db_full),
            }
            click.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))
            return
        # 非 dry-run：创建 DB、迁移、继续走正常 seed 路径
        db = Database(db_full)
        db.initialize()
    elif dry_run:
        db = Database.open_read_only(db_full)
    else:
        db = Database(db_full)
        db.initialize()

    try:
        repo = GraphRepository(db)

        # 检查迁移状态
        db_version = db.current_version()
        migration_required = db_version < 6
        if not migration_required:
            check = db._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='graph_nodes'"
            ).fetchone()
            if check is None:
                migration_required = True

        # 使用 seed_ontology 方法（全量预检查）
        summary = repo.seed_ontology(
            nodes=nodes,
            edges=edges,
            ontology_id=ontology_id,
            ontology_version=ontology_version,
            ontology_sha256=ontology_sha256,
            dry_run=dry_run,
        )

        # 如果数据库版号不足，标记 migration_required
        if migration_required:
            summary["migration_required"] = True

        click.echo(json.dumps(summary, ensure_ascii=False, sort_keys=True))

    except ValueError as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        db.close()


@knowledge_group.command("candidates")
@click.option("--source", "sources", multiple=True, required=True,
              help="源对象 Type:ID（可重复）。如 Event:ev_xxx Claim:cl_xxx")
@click.option("--db", "db_path", default="data/sqlite/research.db", show_default=True,
              help="SQLite 数据库路径（相对项目根）。")
@click.option("--provider", "provider_id", default="deepseek", show_default=True,
              help="LLM Provider ID。")
@click.option("--live", is_flag=True, default=False,
              help="发起真实 Provider 调用生成 candidate。")
@click.option("--dry-run", is_flag=True, default=False,
              help="0 writes：仅执行预检，不调用 LLM，不写候选 DB/文件。")
def knowledge_candidates(sources, db_path, provider_id, live, dry_run) -> None:
    """从结构化源对象生成 GraphChange candidate（M3 候选管线）。

    源类型支持：Event / Claim / ResearchFinding / CompetitiveFactor /
    Catalyst / RiskFactor / BusinessSegment / CompanyProfile / Evidence。

    --live 控制是否真实调用 LLM；--dry-run 控制是否写入。
    """
    from research_os.knowledge.candidate_pipeline import CandidatePipeline
    from research_os.knowledge.candidate_sources import is_allowed_source_type
    from research_os.llm.provider_factory import create_provider
    from research_os.storage import Database

    root = _project_root()
    db_full = root / db_path

    if not db_full.exists():
        raise click.ClickException(f"数据库不存在: {db_full}")

    # 解析 source 参数
    parsed_sources = []
    for s in sources:
        if ":" not in s:
            raise click.ClickException(f"source 参数格式错误（要求 Type:ID）: {s!r}")
        st, sid = s.split(":", 1)
        if not is_allowed_source_type(st):
            raise click.ClickException(
                f"不支持的源类型: {st!r}，允许: Event/Claim/ResearchFinding/"
                f"CompetitiveFactor/Catalyst/RiskFactor/BusinessSegment/CompanyProfile/Evidence"
            )
        parsed_sources.append((st, sid))

    # dry-run：使用 read_only 模式，零写入
    if dry_run:
        db = Database.open_read_only(db_full)
        # 检查 DB 版本
        version = db.current_version()
        if version < 6:
            raise click.ClickException(
                f"数据库版本过低: {version}，要求 >=6。请先运行迁移。"
            )
    else:
        db = Database(db_full)
        db.initialize()

    try:
        provider = None
        if live and not dry_run:
            from research_os.llm.provider_factory import create_provider as _create_prov
            provider = _create_prov(root, provider_id=provider_id, live=live)
        pipeline = CandidatePipeline(
            db=db,
            provider=provider,
            live=live,
            dry_run=dry_run,
        )
        knowledge_dir = root / "knowledge"
        result = pipeline.run(
            sources=parsed_sources,
            knowledge_dir=knowledge_dir,
        )
        click.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        if result.get("status") not in ("ok", "dry_run", "preflight_only"):
            raise SystemExit(1)
    finally:
        db.close()


@knowledge_group.command("review-export")
@click.option(
    "--change-id", "change_id", required=True,
    help="GraphChange candidate 唯一 ID（UUID）。"
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="仅渲染 Markdown 并输出到 stdout，不写文件。",
)
def knowledge_review_export(change_id, db_path, dry_run) -> None:
    """将 GraphChange candidate 导出为人工审阅 Markdown。

    验证 candidate 存在且 review_status=candidate。
    包含 candidate_hash、Reviewer 模板、4 个审核选项。
    """
    from research_os.knowledge.review_workflow import ReviewWorkflow
    from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
    from research_os.knowledge.repository import GraphRepository
    from research_os.knowledge.knowledge_validator import KnowledgeValidator
    from research_os.storage import Database

    root = _project_root()
    db_full = root / db_path

    if not db_full.exists():
        raise click.ClickException(f"数据库不存在: {db_full}")

    if dry_run:
        db = Database.open_read_only(db_full)
    else:
        db = Database(db_full)
        db.initialize()

    try:
        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        workflow = ReviewWorkflow(
            db, candidate_repo, graph_repo, validator,
            knowledge_dir=root / "knowledge",
        )

        result = workflow.review_export(change_id, dry_run=dry_run)

        if result.status == "error":
            raise click.ClickException(result.error)

        # 正式 artifact workflow：输出 deterministic JSON summary
        output = {
            "status": result.status,
            "graph_change_id": result.graph_change_id,
            "candidate_hash": result.candidate_hash,
            "markdown_path": result.markdown_path,
        }
        if result.error:
            output["error"] = result.error
        if dry_run:
            # dry-run 保证 target path 未创建/未改变
            if result.markdown_path:
                output["target_path"] = result.markdown_path
                output["file_exists"] = Path(result.markdown_path).exists()
            output["dry_run"] = True
        click.echo(json.dumps(output, ensure_ascii=False, sort_keys=True))

    except Exception as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        db.close()


@knowledge_group.command("review-import")
@click.option(
    "--file", "file_path", required=True,
    help="填写后的审阅 Markdown 文件路径。"
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="完整预检（parse→load→verify→validate→patch→replacement build），零 DB 写入。",
)
def knowledge_review_import(file_path, db_path, dry_run) -> None:
    """导入人工审阅 Markdown 并持久化。

    流程：parse → load candidate → hash verify → build GraphReview →
          M4 validate_review → patch apply → atomic persist。
    dry-run 执行完整预检但零写入。
    """
    from research_os.knowledge.review_workflow import ReviewWorkflow
    from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
    from research_os.knowledge.repository import GraphRepository
    from research_os.knowledge.knowledge_validator import KnowledgeValidator
    from research_os.storage import Database

    root = _project_root()
    db_full = root / db_path

    if not db_full.exists():
        raise click.ClickException(f"数据库不存在: {db_full}")

    # 读取 Markdown 文件
    md_file = Path(file_path)
    if not md_file.is_absolute():
        md_file = root / file_path
    if not md_file.exists():
        raise click.ClickException(f"审阅文件不存在: {md_file}")

    try:
        md_text = md_file.read_text(encoding="utf-8")
    except Exception as exc:
        raise click.ClickException(f"读取审阅文件失败: {exc}")

    if dry_run:
        db = Database.open_read_only(db_full)
    else:
        db = Database(db_full)
        db.initialize()

    try:
        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        workflow = ReviewWorkflow(db, candidate_repo, graph_repo, validator)

        result = workflow.review_import(md_text, dry_run=dry_run)

        output = {
            "status": result.status,
            "review_id": result.review_id,
            "graph_change_id": result.graph_change_id,
            "decision": result.decision,
            "resulting_graph_change_id": result.resulting_graph_change_id,
            "candidate_hash": result.candidate_hash,
            "review_eligible": result.review_eligible,
            "apply_eligible": result.apply_eligible,
            "dry_run": result.dry_run,
            "warnings": result.warnings,
        }
        if result.errors:
            output["errors"] = result.errors

        click.echo(json.dumps(output, ensure_ascii=False, sort_keys=True))

        if result.status == "error":
            raise SystemExit(1)

    except Exception as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        db.close()


@knowledge_group.command("apply")
@click.option(
    "--change-id", "change_id", required=True,
    help="original reviewed GraphChange ID（UUID），不是默认 replacement ID。"
)
@click.option(
    "--review-id", "review_id", default=None,
    help="显式 GraphReview ID（同一 candidate 多条审核时必须提供）。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="完整预检（load→Schema-first→review selection→hash→replacement→M4→"
         "target→version→idempotency），零 DB 写入、零文件写入。",
)
@click.option(
    "--applied-at", "applied_at", default=None,
    help="显式 ISO 8601 时间；未提供则 capture now_iso() once（不重复读 wall clock）。",
)
def knowledge_apply(change_id, review_id, db_path, dry_run, applied_at) -> None:
    """M6 Deterministic Apply：将已批准人工审核确定性应用到图谱。

    只支持 add_node / add_edge（modify/retire → CHANGE_TYPE_REQUIRES_M7）。
    零 LLM / 零 Provider / 零 network。
    幂等：重复 apply 返回 IDEMPOTENT_NOOP（不重复写 audit）。
    """
    from research_os.knowledge.apply_engine import ApplyEngine
    from research_os.knowledge.candidate_repository import GraphChangeCandidateRepository
    from research_os.knowledge.repository import GraphRepository
    from research_os.knowledge.knowledge_validator import KnowledgeValidator
    from research_os.storage import Database

    root = _project_root()
    db_full = root / db_path

    if not db_full.exists():
        raise click.ClickException(f"数据库不存在: {db_full}")

    if dry_run:
        db = Database.open_read_only(db_full)
    else:
        db = Database(db_full)
        db.initialize()

    try:
        candidate_repo = GraphChangeCandidateRepository(db)
        graph_repo = GraphRepository(db)
        validator = KnowledgeValidator(db, graph_repo)

        engine = ApplyEngine(db, candidate_repo, graph_repo, validator)

        result = engine.apply(
            change_id,
            review_id=review_id,
            applied_at=applied_at,
            dry_run=dry_run,
        )

        output = {
            "status": result.status,
            "original_graph_change_id": result.original_graph_change_id,
            "effective_graph_change_id": result.effective_graph_change_id,
            "review_id": result.review_id,
            "application_id": result.application_id,
            "idempotency_key": result.idempotency_key,
            "target_kind": result.target_kind,
            "target_id": result.target_id,
            "target_version": result.target_version,
            "applied_at": result.applied_at,
            "dry_run": result.dry_run,
            "error_code": result.error_code,
            "warnings": list(result.warnings),
        }
        if result.errors:
            output["errors"] = list(result.errors)

        click.echo(json.dumps(output, ensure_ascii=False, sort_keys=True))

        if result.status == "APPLY_REJECTED":
            raise SystemExit(1)

    except Exception as exc:
        raise click.ClickException(str(exc)) from None
    finally:
        db.close()


@knowledge_group.command("history")
@click.option(
    "--node-id", "node_id", default=None,
    help="节点 identity（与 --edge-id 二选一）。",
)
@click.option(
    "--edge-id", "edge_id", default=None,
    help="边 identity（与 --node-id 二选一）。",
)
@click.option(
    "--as-of", "as_of", default=None,
    help="显式 ISO 8601 时间（可选）。未提供时只输出完整 history，不计算 resolved。"
         "禁止默认 now()。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
def knowledge_history(node_id, edge_id, db_path, as_of) -> None:
    """M7 Deterministic History：identity-scoped history / as_of resolution。

    零 LLM / 零 Provider / 零 network。
    exactly one of --node-id / --edge-id；错误 → non-zero exit + structured
    JSON + explicit error_code（无 traceback）。
    """
    from research_os.knowledge.history import HistoryService, HistoryError
    from research_os.knowledge.repository import GraphRepository
    from research_os.storage import Database

    if (node_id is None) == (edge_id is None):
        click.echo(json.dumps({
            "status": "error",
            "error_code": "HISTORY_IDENTITY_REQUIRED",
            "errors": ["必须且只能提供一个：--node-id 或 --edge-id"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    root = _project_root()
    db_full = root / db_path
    if not db_full.exists():
        click.echo(json.dumps({
            "status": "error",
            "error_code": "HISTORY_READ_FAILED",
            "errors": [f"数据库不存在: {db_full}"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    db = Database.open_read_only(db_full)
    try:
        graph_repo = GraphRepository(db)
        history = HistoryService(db, graph_repo)
        if node_id is not None:
            result = history.get_node_history(node_id, as_of=as_of)
        else:
            result = history.get_edge_history(edge_id, as_of=as_of)
    except HistoryError as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": exc.error_code,
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    except Exception as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "HISTORY_READ_FAILED",
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    finally:
        db.close()

    click.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


@knowledge_group.command("query")
@click.option(
    "--node-id", "node_id", default=None,
    help="节点 identity（与 --edge-id 二选一）。",
)
@click.option(
    "--edge-id", "edge_id", default=None,
    help="边 identity（与 --node-id 二选一）。",
)
@click.option(
    "--as-of", "as_of", default=None,
    help="显式 ISO 8601 时间（必填；禁止默认 now()）。",
)
@click.option(
    "--depth", "depth", default=None, type=int,
    help="遍历深度 0|1|2（仅 --node-id；--edge-id 为 direct query，禁止 >0）。",
)
@click.option(
    "--relation", "relations", multiple=True,
    help="relation 过滤（可重复；仅 18 个正式 relation）。",
)
@click.option(
    "--direction", "direction", default="both", show_default=True,
    help="outgoing|incoming|both。",
)
@click.option(
    "--assertion-type", "assertion_types", multiple=True,
    help="GOVERNANCE|FACT|MODEL_INFERENCE（可重复）。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
def knowledge_query(node_id, edge_id, as_of, depth, relations,
                    direction, assertion_types, db_path) -> None:
    """M8 Deterministic Query：direct node/edge + depth-limited traversal。

    零 LLM / 零 Provider / 零 network。只读。
    --node-id 可配 --depth（0|1|2）；--edge-id 为 direct edge query。
    as_of 必填。
    """
    from research_os.knowledge.query import GraphQueryService, QueryError
    from research_os.storage import Database

    if (node_id is None) == (edge_id is None):
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_IDENTITY_REQUIRED",
            "errors": ["必须且只能提供一个：--node-id 或 --edge-id"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    if as_of is None:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_AS_OF_REQUIRED",
            "errors": ["--as-of 必填（禁止默认 now()）"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    if edge_id is not None and depth is not None and depth > 0:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_DEPTH_EXCEEDED",
            "errors": ["--edge-id 是 direct edge query，禁止 --depth > 0"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    root = _project_root()
    db_full = root / db_path
    if not db_full.exists():
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_READ_FAILED",
            "errors": [f"数据库不存在: {db_full}"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    db = Database.open_read_only(db_full)
    try:
        svc = GraphQueryService(db)
        if edge_id is not None:
            result = svc.get_edge(edge_id, as_of)
        elif depth is None:
            result = svc.get_node(node_id, as_of)
        else:
            result = svc.query_graph(
                node_id, as_of, max_depth=depth,
                relation_filters=list(relations) or None,
                direction=direction,
                assertion_types=list(assertion_types) or None,
            )
    except QueryError as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": exc.error_code,
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    except Exception as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_READ_FAILED",
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    finally:
        db.close()

    click.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


@knowledge_group.command("context")
@click.option(
    "--node-id", "node_id", required=True,
    help="节点 identity（context 只接受 node root）。",
)
@click.option(
    "--as-of", "as_of", default=None,
    help="显式 ISO 8601 时间（必填；禁止默认 now()）。",
)
@click.option(
    "--depth", "depth", default=1, type=int, show_default=True,
    help="遍历深度 0|1|2。",
)
@click.option(
    "--relation", "relations", multiple=True,
    help="relation 过滤（可重复；仅 18 个正式 relation）。",
)
@click.option(
    "--direction", "direction", default="both", show_default=True,
    help="outgoing|incoming|both。",
)
@click.option(
    "--assertion-type", "assertion_types", multiple=True,
    help="GOVERNANCE|FACT|MODEL_INFERENCE（可重复）。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
def knowledge_context(node_id, as_of, depth, relations,
                      direction, assertion_types, db_path) -> None:
    """M8 Deterministic Knowledge Context：graph + Evidence 同一 read snapshot。

    零 LLM / 零 Provider / 零 network。只读。
    """
    from research_os.knowledge.context_builder import KnowledgeContextBuilder
    from research_os.knowledge.query import GraphQueryService, QueryError
    from research_os.storage import Database

    if as_of is None:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_AS_OF_REQUIRED",
            "errors": ["--as-of 必填（禁止默认 now()）"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    root = _project_root()
    db_full = root / db_path
    if not db_full.exists():
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_READ_FAILED",
            "errors": [f"数据库不存在: {db_full}"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    db = Database.open_read_only(db_full)
    try:
        svc = GraphQueryService(db)
        builder = KnowledgeContextBuilder(svc)
        result = builder.build(
            node_id, as_of, max_depth=depth,
            relation_filters=list(relations) or None,
            direction=direction,
            assertion_types=list(assertion_types) or None,
        )
    except QueryError as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": exc.error_code,
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    except Exception as exc:
        click.echo(json.dumps({
            "status": "error",
            "error_code": "QUERY_READ_FAILED",
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    finally:
        db.close()

    click.echo(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True))


@knowledge_group.command("integrate")
@click.option(
    "--scenario", "scenario", required=True,
    help="场景 canonical name: morning_brief / abnormal_move_analysis / stock_research_report",
)
@click.option(
    "--run-dir", "run_dir", required=True,
    help="运行目录路径（reports/runs/<task_id>）。",
)
@click.option(
    "--source", "sources", multiple=True,
    help="显式子集 filter（Type:ID，可重复）。不提供时使用所有解析到的源。",
)
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--provider", "provider_id", default=None,
    help="Provider ID（如 deepseek）；--live 时必填。",
)
@click.option(
    "--live", is_flag=True, default=False,
    help="真实调用 LLM 生成 GraphChangeProposal。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="零 Provider 调用 / 零 candidate 写入 / 零文件副作用。",
)
def knowledge_integrate(scenario, run_dir, sources, db_path,
                        provider_id, live, dry_run) -> None:
    """M9 Scenario Integration：scenario run artifacts → CandidatePipeline。

    晨报 → Claim source refs。
    异动 → Evidence source refs（CauseEvidenceLink 证据）。
    个股研报 → ResearchFinding source refs。

    --live 开启真实 LLM 调用；--dry-run 零副作用预检。
    """
    import json as _json

    from research_os.knowledge.scenario_integration import (
        ScenarioCandidateIntegrator,
        IntegrationError,
        IntegrationResult,
    )
    from research_os.llm.provider_factory import create_provider
    from research_os.storage import Database

    root = _project_root()
    db_full = root / db_path

    if not db_full.exists():
        click.echo(_json.dumps({
            "status": "error",
            "error_code": "INTEGRATION_READ_FAILED",
            "errors": [f"数据库不存在: {db_full}"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(2)

    resolved_dir = Path(run_dir)
    if not resolved_dir.is_absolute():
        resolved_dir = root / run_dir

    db = Database(db_full) if not dry_run else Database.open_read_only(db_full)
    if not dry_run:
        db.initialize()

    try:
        provider = None
        if live and not dry_run:
            if not provider_id:
                click.echo(_json.dumps({
                    "status": "error",
                    "error_code": "INTEGRATION_PROVIDER_ERROR",
                    "errors": ["--live 要求显式 --provider（如 deepseek）"],
                }, ensure_ascii=False, sort_keys=True))
                raise SystemExit(1)
            try:
                provider = create_provider(root, provider_id=provider_id, live=live)
            except (ValueError, Exception) as exc:
                click.echo(_json.dumps({
                    "status": "error",
                    "error_code": "INTEGRATION_PROVIDER_ERROR",
                    "errors": [f"Provider 创建失败: {exc}"],
                }, ensure_ascii=False, sort_keys=True))
                raise SystemExit(1) from None

        integrator = ScenarioCandidateIntegrator(
            db=db,
            project_root=root,
            provider=provider,
            live=live,
            dry_run=dry_run,
        )

        selected = list(sources) if sources else None

        result: IntegrationResult = integrator.integrate(
            scenario=scenario,
            run_dir=resolved_dir,
            selected_sources=selected,
        )

        output = {
            "status": result.status,
            "error_code": result.error_code,
            "errors": result.errors,
            "scenario": result.scenario,
            "run_dir": result.run_dir,
            "resolved_source_refs": result.resolved_source_refs,
            "selected_source_refs": result.selected_source_refs,
            "pipeline_result": result.pipeline_result,
            "warnings": result.warnings,
        }
        click.echo(_json.dumps(output, ensure_ascii=False, sort_keys=True))

        if result.status == "error":
            raise SystemExit(1)

    finally:
        db.close()


@knowledge_group.command("export")
@click.option(
    "--db", "db_path",
    default="data/sqlite/research.db",
    show_default=True,
    help="SQLite 数据库路径（相对项目根）。",
)
@click.option(
    "--project-root", "project_root",
    default=None,
    help="项目根目录（默认自动检测）。",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="完整 SQLite preflight + tree_sha256 计算，0 文件写入。",
)
def knowledge_export(db_path, project_root, dry_run) -> None:
    """M10-A Deterministic JSON Mirror Export。

    零 LLM / 零 Provider / 零 network / 零 DB 写入 / **零 DB 初始化**。
    SQLite → JSON 确定性导出（graph + history mirror）。
    **永远以 mode=ro 打开数据库。**
    """
    import json as _json

    from research_os.knowledge.exporter import (
        KnowledgeMirrorExporter,
        ExportError,
    )

    root = Path(project_root) if project_root else _project_root()
    db_full = root / db_path
    if not db_full.exists():
        click.echo(_json.dumps({
            "status": "error",
            "error_code": "EXPORT_READ_FAILED",
            "errors": [f"数据库不存在: {db_full}"],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)

    knowledge_root = root / "knowledge"

    try:
        exporter = KnowledgeMirrorExporter(
            project_root=root,
            knowledge_root=knowledge_root,
            db_path=db_full,
        )
        result = exporter.export(dry_run=dry_run)
    except ExportError as exc:
        click.echo(_json.dumps({
            "status": "error",
            "error_code": exc.error_code,
            "errors": [str(exc.message)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None
    except Exception as exc:
        click.echo(_json.dumps({
            "status": "error",
            "error_code": "EXPORT_READ_FAILED",
            "errors": [str(exc)],
        }, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1) from None

    click.echo(_json.dumps(
        result.to_dict(), ensure_ascii=False, sort_keys=True
    ))


if __name__ == "__main__":
    cli()
