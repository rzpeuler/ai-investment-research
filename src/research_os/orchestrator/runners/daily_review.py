"""每日复盘场景适配器（Phase 6B B2）。"""
from __future__ import annotations

import os
from datetime import date, time
from pathlib import Path
from typing import Any, Dict

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class DailyReviewScenarioRunner:
    scenario = "daily_review"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.utils.time import shanghai_now, validate_iso

        normalized = dict(request)
        try:
            day = (date.fromisoformat(request["review_business_date"])
                   if request.get("review_business_date") else shanghai_now().date())
        except ValueError as exc:
            raise ValueError(f"review_business_date 非法: {exc}（需要 YYYY-MM-DD）") from None
        normalized["review_business_date"] = day.isoformat()
        if request.get("as_of") and not validate_iso(request["as_of"]):
            raise ValueError(f"--as-of 非法: {request['as_of']!r}（需要 ISO-8601）")
        normalized["as_of"] = request.get("as_of") or _default_as_of(day)
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "resolve_business_date", "load_observed_facts", "load_previous_views",
                "collect_new_evidence", "evaluate_interpretations", "render", "validate", "persist",
            ],
            "data_requirements": ["evidence", "claims", "run_artifacts", "source_registry"],
            "model_policy": "flash_default_with_deterministic_fallback",
            "fallback_policy": ["metadata_only", "partial_success"],
            "output_paths": ["reports/daily_review/{year}/{year_month}", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.models import DailyReviewRequest, DailyReviewRun
        from research_os.brief import validated_payload
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.reports import validate_report
        from research_os.review.daily import DailyReviewPipeline, report_path_for
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso

        root: Path = context["project_root"]
        task = context["task"]
        db = context["db"]
        day = date.fromisoformat(request["review_business_date"])
        as_of = request["as_of"]
        report_path = Path(report_path_for(day, root))
        if report_path.exists() and not request.get("force"):
            check = validate_report(report_path)
            if check.ok:
                return ScenarioExecutionResult(
                    status="idempotent_skipped", exit_code=0, task_id=task.task_id,
                    report_path=str(report_path), validation_status="pass",
                    model_route={"mode": "deterministic_fallback", "llm_called": False},
                    message=f"{day.isoformat()} 每日复盘已存在且通过校验: {report_path}",
                )

        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())

        request_payload = DailyReviewRequest(
            request_id=new_uuid(), task_id=task.task_id,
            review_business_date=day.isoformat(), as_of=as_of,
            previous_run_ids=list(request.get("previous_run_ids") or []),
            previous_report_paths=list(request.get("previous_report_paths") or []),
            entities=list(request.get("entities") or []),
            depth=request.get("depth", "standard"), force=bool(request.get("force")),
            dry_run=False, status="validated",
            warnings=list(request.get("warnings") or []), requested_at=now_iso(),
        )
        run_dir.write_json("daily_review_request.json", validated_payload(request_payload, "daily_review_request"))

        artifacts = DailyReviewPipeline(root, db).run(
            day, as_of, task_id=task.task_id,
            previous_run_ids=request_payload.previous_run_ids,
            previous_report_paths=request_payload.previous_report_paths,
            previous_cutoff=request.get("previous_cutoff"),
            entities=request_payload.entities,
        )

        report_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = report_path.with_suffix(report_path.suffix + ".tmp")
        tmp.write_text(artifacts.markdown, encoding="utf-8")
        os.replace(tmp, report_path)
        check = validate_report(report_path)
        run_dir.write_validation({
            "status": "ok" if check.ok else "failed", "task_id": task.task_id,
            "checks": len(check.errors), "errors": check.errors[:20],
        })

        counts = {"supported": 0, "weakened": 0, "falsified": 0, "unchanged": 0, "unknown": 0}
        for interp in artifacts.interpretations:
            counts[interp["verdict"]] = counts.get(interp["verdict"], 0) + 1
        run_payload = DailyReviewRun(
            run_id=new_uuid(), task_id=task.task_id,
            review_business_date=day.isoformat(), as_of=as_of,
            previous_cutoff=artifacts.previous_cutoff,
            observed_fact_count=len(artifacts.observed_facts),
            previous_view_count=len(artifacts.previous_views),
            new_evidence_count=len(artifacts.new_evidence),
            supported_count=counts["supported"], weakened_count=counts["weakened"],
            falsified_count=counts["falsified"], unchanged_count=counts["unchanged"],
            unknown_count=counts["unknown"],
            report_path=str(report_path),
            missing_data=artifacts.missing_data, warnings=artifacts.warnings,
            status="partial_success" if artifacts.missing_data else "success",
        )
        run_dir.write_json("daily_review_run.json", validated_payload(run_payload, "daily_review_run"))

        task.status = "completed" if check.ok else "failed"
        task.finished_at = now_iso()
        db.upsert(task)
        run_dir.write_task(task.model_dump())
        return ScenarioExecutionResult(
            status=run_payload.status if check.ok else "failed",
            exit_code=0 if check.ok else 1, task_id=task.task_id,
            run_id=run_payload.run_id, run_dir=str(run_dir.root),
            report_path=str(report_path),
            validation_status="pass" if check.ok else "fail",
            warnings=artifacts.warnings + check.warnings,
            missing_data=artifacts.missing_data,
            model_route={"mode": "deterministic_fallback", "llm_called": False},
            message=f"每日复盘 {day.isoformat()} 生成: {report_path}",
        )


def _default_as_of(day: date) -> str:
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
    return datetime.combine(day, time(20, 0), tzinfo=tz).isoformat(timespec="seconds")
