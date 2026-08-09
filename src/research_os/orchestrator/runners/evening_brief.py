"""晚报场景适配器（Phase 6B）。

evening_brief 是 morning_brief 的同构复用场景（DECISIONS #43）：采集、标准化、
去重、聚类、分类、过滤、评分、事件合并、Evidence/Claim、渲染、校验全部复用
共享 BriefPipeline；唯一业务差异为信息采集时间窗口 [08:00, 20:00) Asia/Shanghai
（inclusive start, exclusive end；延迟补跑不漂移）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class EveningBriefScenarioRunner:
    scenario = "evening_brief"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.brief.window import evening_policy, parse_report_date
        from research_os.utils.time import shanghai_now, validate_iso

        policy = evening_policy()
        normalized = dict(request)
        try:
            day = parse_report_date(request["report_date"]) if request.get("report_date") else shanghai_now().date()
        except ValueError as exc:
            raise ValueError(f"--date 非法: {exc}（需要 YYYY-MM-DD）") from None
        normalized["report_date"] = day.isoformat()
        if request.get("as_of") and not validate_iso(request["as_of"]):
            raise ValueError(f"--as-of 非法: {request['as_of']!r}（需要 ISO-8601）")
        normalized["as_of"] = request.get("as_of") or policy.as_of(day)
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
            "output_paths": ["reports/evening/{year}/{year_month}", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.brief.window import (
            evening_policy, parse_report_date,
        )
        from research_os.utils.time import now_iso

        root: Path = context["project_root"]
        task = context["task"]
        policy = evening_policy()
        day = parse_report_date(request["report_date"])
        window_start, window_end = policy.window(day)
        as_of = request.get("as_of") or policy.as_of(day)
        if request.get("dry_run"):
            return ScenarioExecutionResult(
                status="planned", exit_code=0, task_id=task.task_id,
                report_path=policy.report_path_for(day, str(root / "reports")),
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
        from research_os.brief.pipeline import BriefPipeline, PipelineConfig
        from research_os.collectors.manual import ManualInboxService
        from research_os.models import EveningBriefRequest, EveningBriefRun
        from research_os.brief import validated_payload
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.reports import validate_report
        from research_os.utils.id import new_uuid

        db = context["db"]
        report_path = Path(policy.report_path_for(day, str(root / "reports")))
        if report_path.exists() and not request.get("force"):
            check = validate_report(report_path)
            if check.ok:
                return ScenarioExecutionResult(
                    status="idempotent_skipped", exit_code=0, task_id=task.task_id,
                    report_path=str(report_path), validation_status="pass",
                    model_route={"mode": "deterministic_fallback", "llm_called": False},
                    message=f"{day.isoformat()} 晚报已存在且通过校验: {report_path}",
                )

        raw_items = inbox_to_raw_items(ManualInboxService(db).list(status="submitted"))
        if request.get("live"):
            append_live_items(raw_items)
        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())

        # Artifact Contract：晚报 Request 携带 Task ID（血缘：Task=Plan=Request=Run=Result）
        request_payload = EveningBriefRequest(
            request_id=new_uuid(), task_id=task.task_id,
            report_date=day.isoformat(), as_of=as_of,
            depth=request.get("depth", "standard"),
            entities=list(request.get("entities") or []),
            force=bool(request.get("force")), dry_run=False,
            live=bool(request.get("live")), status="validated",
            warnings=list(request.get("warnings") or []),
            requested_at=now_iso(),
        )
        run_dir.write_json("evening_brief_request.json", validated_payload(request_payload, "evening_brief_request"))

        artifacts = BriefPipeline(PipelineConfig(
            source_tiers=BRIEF_SOURCE_TIERS, source_status={}, channel_map=BRIEF_CHANNEL_MAP,
        ), window_policy=policy).run(raw_items, day, task_id=task.task_id,
            run_dir=run_dir, started_at=now_iso(), as_of=as_of, db=db)

        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_suffix(report_path.suffix + ".tmp")
        tmp.write_text(artifacts.markdown, encoding="utf-8")
        os.replace(tmp, report_path)
        check = validate_report(report_path)
        run_dir.write_validation({
            "status": "ok" if check.ok else "failed", "task_id": task.task_id,
            "checks": len(check.errors), "errors": check.errors[:20],
        })

        run_payload = EveningBriefRun(
            report_id=artifacts.task_id, task_id=task.task_id, as_of=as_of,
            window_start=window_start, window_end=window_end,
            actual_started_at=now_iso(), actual_finished_at=now_iso(),
            scheduled_for=policy.scheduled_for(day), delayed=False, delay_seconds=0,
            coverage=artifacts.coverage,
            selected_cluster_ids=artifacts.selected_cluster_ids,
            missing_data=artifacts.missing_data, warnings=artifacts.warnings,
            status="success" if check.ok else "failed",
        )
        run_dir.write_json("evening_brief_run.json", validated_payload(run_payload, "evening_brief_run"))

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
            message=f"晚报 {day.isoformat()} 生成: {report_path}",
        )
