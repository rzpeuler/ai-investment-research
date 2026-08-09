"""个股增量复盘场景适配器（Phase 6B B3）。"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Any, Dict

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class StockReviewScenarioRunner:
    scenario = "stock_review"
    version = "1.0.0"

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        from research_os.utils.time import shanghai_now, validate_iso

        if not request.get("entity"):
            raise ValueError("stock_review 缺少 entity（证券/公司标识）")
        normalized = dict(request)
        try:
            review_end = (date.fromisoformat(request["review_end"])
                          if request.get("review_end") else shanghai_now().date())
            review_start = (date.fromisoformat(request["review_start"])
                            if request.get("review_start") else review_end)
        except ValueError as exc:
            raise ValueError(f"review_start/review_end 非法: {exc}（需要 YYYY-MM-DD）") from None
        if review_start > review_end:
            raise ValueError("review_start 不得晚于 review_end")
        normalized["review_start"] = review_start.isoformat()
        normalized["review_end"] = review_end.isoformat()
        if request.get("as_of") and not validate_iso(request["as_of"]):
            raise ValueError(f"--as-of 非法: {request['as_of']!r}（需要 ISO-8601）")
        normalized["as_of"] = request.get("as_of") or _default_as_of(review_end)
        if request.get("previous_cutoff") and not validate_iso(request["previous_cutoff"]):
            raise ValueError(f"previous_cutoff 非法: {request['previous_cutoff']!r}")
        return normalized

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "steps": [
                "resolve_entity", "resolve_review_window", "load_window_evidence",
                "load_phase4_findings", "evaluate_incremental_changes", "render", "validate", "persist",
            ],
            "data_requirements": ["evidence", "research_findings", "entity_mapping", "source_registry"],
            "model_policy": "flash_default_with_deterministic_fallback",
            "fallback_policy": ["metadata_only", "partial_success"],
            "output_paths": ["reports/stock_review/{entity}", "reports/runs/{task_id}"],
        }

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        from research_os.models import StockReviewRequest, StockReviewRun
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.reports import validate_report
        from research_os.review.stock import StockReviewPipeline, report_path_for
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso

        root: Path = context["project_root"]
        task = context["task"]
        db = context["db"]
        entity = request["entity"]
        review_end = date.fromisoformat(request["review_end"])
        as_of = request["as_of"]
        report_path = Path(report_path_for(entity, review_end, root))
        if report_path.exists() and not request.get("force"):
            check = validate_report(report_path)
            if check.ok:
                return ScenarioExecutionResult(
                    status="idempotent_skipped", exit_code=0, task_id=task.task_id,
                    report_path=str(report_path), validation_status="pass",
                    model_route={"mode": "deterministic_fallback", "llm_called": False},
                    message=f"{entity} 个股复盘已存在且通过校验: {report_path}",
                )

        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())

        request_payload = StockReviewRequest(
            request_id=new_uuid(), task_id=task.task_id, entity=entity,
            review_start=request["review_start"], review_end=request["review_end"],
            as_of=as_of, previous_cutoff=request.get("previous_cutoff"),
            depth=request.get("depth", "standard"), force=bool(request.get("force")),
            dry_run=False, status="validated",
            warnings=list(request.get("warnings") or []), requested_at=now_iso(),
        )
        run_dir.write_json("stock_review_request.json", request_payload.model_dump())

        artifacts = StockReviewPipeline(root, db).run(
            entity, date.fromisoformat(request["review_start"]), review_end, as_of,
            task_id=task.task_id, previous_cutoff=request_payload.previous_cutoff,
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

        run_payload = StockReviewRun(
            run_id=new_uuid(), task_id=task.task_id, entity=entity,
            review_start=request["review_start"], review_end=request["review_end"],
            as_of=as_of, previous_cutoff=request_payload.previous_cutoff,
            what_changed=artifacts.what_changed,
            new_evidence_count=len(artifacts.new_evidence),
            thesis_supported=artifacts.thesis_supported,
            thesis_weakened=artifacts.thesis_weakened,
            risk_changed=artifacts.risk_changed,
            catalyst_changed=artifacts.catalyst_changed,
            valuation_assumption_changed=artifacts.valuation_assumption_changed,
            remaining_questions=artifacts.remaining_questions,
            report_path=str(report_path),
            missing_data=artifacts.missing_data, warnings=artifacts.warnings,
            status="partial_success" if artifacts.missing_data else "success",
        )
        run_dir.write_json("stock_review_run.json", run_payload.model_dump())

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
            message=f"{entity} 个股复盘生成: {report_path}",
        )


def _default_as_of(day: date) -> str:
    from datetime import datetime, timedelta, timezone

    tz = timezone(timedelta(hours=8), name="Asia/Shanghai")
    return datetime.combine(day, __import__("datetime").time(20, 0), tzinfo=tz).isoformat(timespec="seconds")
