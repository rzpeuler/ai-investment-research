"""晨报场景适配器。"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class MorningBriefScenarioRunner:
    scenario = "morning_brief"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.morning.window import as_of_for, parse_report_date
        from research_os.utils.time import shanghai_now, validate_iso

        normalized = dict(request)
        try:
            day = parse_report_date(request["report_date"]) if request.get("report_date") else shanghai_now().date()
        except ValueError as exc:
            raise ValueError(f"--date 非法: {exc}（需要 YYYY-MM-DD）") from None
        normalized["report_date"] = day.isoformat()
        if request.get("as_of") and not validate_iso(request["as_of"]):
            raise ValueError(f"--as-of 非法: {request['as_of']!r}（需要 ISO-8601）")
        normalized["as_of"] = request.get("as_of") or as_of_for(day)
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "resolve_window", "route_sources", "collect_raw_items", "build_evidence",
                "deduplicate", "cluster_events", "classify", "apply_vetoes", "score",
                "build_claims", "render", "validate", "persist",
            ],
            "data_requirements": [
                "manual_inbox", "company_announcement", "macro_data", "news_metadata", "source_registry",
            ],
            "model_policy": "flash_default_with_deterministic_fallback",
            "fallback_policy": ["manual_inbox", "metadata_only", "partial_success"],
            "output_paths": ["reports/morning/{year}/{year_month}", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.morning.window import (
            as_of_for, morning_window, parse_report_date, report_path_for, scheduled_for,
        )
        from research_os.utils.time import now_iso

        root: Path = context["project_root"]
        task = context["task"]
        day = parse_report_date(request["report_date"])
        window_start, window_end = morning_window(day)
        as_of = request.get("as_of") or as_of_for(day)
        if request.get("dry_run"):
            return ScenarioExecutionResult(
                status="planned", exit_code=0, task_id=task.task_id,
                report_path=report_path_for(day, str(root / "reports")),
                validation_status="not_run",
                model_route={"mode": "deterministic_fallback", "llm_called": False},
                message=(f"[dry-run] 报告日期 {day.isoformat()}；信息窗口 {window_start} 至 {window_end}；"
                         f"as_of {as_of}；零副作用"),
            )

        from research_os.brief.collect import (
            BRIEF_CHANNEL_MAP,
            BRIEF_SOURCE_TIERS,
            append_live_items,
            inbox_to_raw_items,
        )
        from research_os.collectors.manual import ManualInboxService
        from research_os.morning.pipeline import MorningBriefPipeline, PipelineConfig
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.reports import validate_report

        db = context["db"]
        report_path = Path(report_path_for(day, str(root / "reports")))
        if report_path.exists() and not request.get("force"):
            check = validate_report(report_path)
            if check.ok:
                return ScenarioExecutionResult(
                    status="idempotent_skipped", exit_code=0, task_id=task.task_id,
                    report_path=str(report_path), validation_status="pass",
                    model_route={"mode": "deterministic_fallback", "llm_called": False},
                    message=f"{day.isoformat()} 晨报已存在且通过校验: {report_path}",
                )

        raw_items = inbox_to_raw_items(ManualInboxService(db).list(status="submitted"))
        if request.get("live"):
            append_live_items(raw_items)
        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())
        artifacts = MorningBriefPipeline(PipelineConfig(
            source_tiers=BRIEF_SOURCE_TIERS, source_status={}, channel_map=BRIEF_CHANNEL_MAP,
        )).run(raw_items, day, task_id=task.task_id, run_dir=run_dir,
               started_at=now_iso(), as_of=as_of, db=db)

        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_suffix(report_path.suffix + ".tmp")
        tmp.write_text(artifacts.markdown, encoding="utf-8")
        os.replace(tmp, report_path)
        check = validate_report(report_path)
        run_dir.write_validation({
            "status": "ok" if check.ok else "failed", "task_id": task.task_id,
            "checks": len(check.errors), "errors": check.errors[:20],
        })
        task.status = "completed" if check.ok else "failed"
        task.finished_at = now_iso()
        db.upsert(task)
        run_dir.write_task(task.model_dump())
        return ScenarioExecutionResult(
            status="success" if check.ok and not artifacts.missing_data else (
                "partial_success" if check.ok else "failed"),
            exit_code=0 if check.ok else 1, task_id=task.task_id,
            run_id=artifacts.task_id, run_dir=str(run_dir.root), report_path=str(report_path),
            validation_status="pass" if check.ok else "fail",
            warnings=artifacts.warnings + check.warnings,
            missing_data=artifacts.missing_data,
            model_route={"mode": "deterministic_fallback", "llm_called": False},
            message=f"晨报 {day.isoformat()} 生成: {report_path}",
        )

