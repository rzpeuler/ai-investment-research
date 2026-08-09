"""行业研究场景适配器（Phase 6A）。

IndustryResearchScenarioRunner 是编排层 adapter：
根据 industry_id + as_of 调用 IndustryResearchPipeline，产出 21 维行业研报。

核心约束：
- as_of 必填（禁止默认 now()），保证审计可追溯，fail-closed
- 在 pipeline 执行前写入 industry_research_request.json artifact（血缘：Task=Plan=Request=Run=Result）
- 请求载荷必须包含 schema 全部 required 字段，validate_instance 校验 FAIL-CLOSED
- schema industry_research_request / industry_research_run 均已注册，始终走 jsonschema 校验
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


class IndustryResearchScenarioRunner:
    """行业研究 ScenarioRunner。

    validate_request → build_plan → execute。
    编排层只组合已有模块，不承载具体研究算法。
    """

    scenario = "industry_research"
    version = "1.0.0"

    # ---------- validate_request ----------

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """规范化请求参数。as_of 必填——行业研究必须锁定时间断面。"""
        from research_os.utils.time import validate_iso

        # as_of 必填，fail-closed
        if not request.get("as_of"):
            raise ValueError("industry_research requires explicit --as-of (ISO-8601)")
        if not validate_iso(request["as_of"]):
            raise ValueError(f"Invalid as_of: {request['as_of']!r}")

        # industry_id 必填
        if not request.get("industry_id"):
            raise ValueError("industry_research requires --industry-id")

        normalized = dict(request)
        normalized["depth"] = request.get("depth", "standard")
        if normalized["depth"] not in {"fast", "standard", "deep"}:
            normalized["depth"] = "standard"
        normalized["industry_name"] = request.get(
            "industry_name", request.get("industry_id", "unknown")
        )
        normalized.setdefault("deterministic_only", True)
        normalized.setdefault("dry_run", False)
        normalized.setdefault("live", False)
        normalized.setdefault("force", False)
        normalized.setdefault("warnings", [])
        normalized.setdefault("as_of_basis", "user_provided")
        normalized.setdefault("timezone", "Asia/Shanghai")
        normalized.setdefault("source_policy", "public_first")
        normalized.setdefault("rule_versions", {})
        normalized.setdefault("version", 1)
        return normalized

    # ---------- build_plan ----------

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """生成行业研究执行计划。"""
        return {
            "steps": [
                "resolve_industry_node",
                "build_research_context",
                "produce_dimension_findings",
                "assess_evidence_quality",
                "run_semantic_analysis",
                "coverage_check",
                "render_report",
                "validate",
            ],
            "data_requirements": [
                "knowledge_graph_snapshot",
                "industry_membership",
                "entity_mapping",
                "evidence_index",
                "source_registry",
            ],
            "dimensions": 21,
            "model_policy": "flash_default_with_deterministic_fallback",
            "fallback_policy": [
                "deterministic_fallback",
                "GRAPH_UNAVAILABLE",
                "INDUSTRY_NODE_NOT_FOUND",
                "INDUSTRY_RESEARCH_DEGRADED",
            ],
            "output_paths": [
                "reports/industry/{industry_id}",
                "reports/runs/{task_id}",
            ],
        }

    # ---------- execute ----------

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        """执行行业研究编排流程。

        1. 创建 RunDirectory 并写入 task/plan
        2. 构建 request_payload（含 schema 全部 required 字段）
        3. 写入 industry_research_request.json artifact
        4. 校验请求载荷 → fail-closed（errors ≠ [] 则 raise ValueError）
        5. 调用 pipeline.run(dict)
        6. 写入 industry_research_run.json artifact
        7. 返回 ScenarioExecutionResult
        """
        from research_os.industry_research.pipeline import IndustryResearchPipeline
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.storage import Database
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso

        root: Path = context["project_root"]
        task = context["task"]
        dry_run = request.get("dry_run", False)

        if dry_run:
            return ScenarioExecutionResult(
                status="planned",
                exit_code=0,
                task_id=task.task_id,
                validation_status="not_run",
                model_route={"mode": "deterministic_fallback", "llm_called": False},
                message=(
                    f"[dry-run] 行业研究 industry_id={request['industry_id']} "
                    f"as_of={request['as_of']}；零副作用"
                ),
            )

        # 1. 创建运行目录
        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())

        # 2. 构建请求载荷（schema 全部 required 字段 + industry_name/deterministic_only/requested_at）
        requested_at = now_iso()
        request_id = new_uuid()
        request_payload: Dict[str, Any] = {
            "request_id": request_id,
            "task_id": task.task_id,
            "industry_id": request["industry_id"],
            "industry_name": request["industry_name"],
            "as_of": request["as_of"],
            "as_of_basis": request.get("as_of_basis", "user_provided"),
            "timezone": request.get("timezone", "Asia/Shanghai"),
            "depth": request["depth"],
            "deterministic_only": bool(request.get("deterministic_only", True)),
            "live": bool(request.get("live", False)),
            "dry_run": False,
            "force": bool(request.get("force", False)),
            "source_policy": request.get("source_policy", "public_first"),
            "status": "validated",
            "warnings": list(request.get("warnings") or []),
            "rule_versions": dict(request.get("rule_versions") or {}),
            "requested_at": requested_at,
            "version": int(request.get("version", 1)),
        }

        # 3. 写入 artifact 并校验 —— fail-closed
        run_dir.write_json("industry_research_request.json", request_payload)
        self._validate_request_artifact(request_payload)

        # 4. 调用 IndustryResearchPipeline
        ephemeral_db = None
        db = context.get("db")
        if db is None:
            ephemeral_db = Database(":memory:")
            ephemeral_db.initialize()
            db = ephemeral_db
        try:
            pipeline = IndustryResearchPipeline(root, db)
            outcome = pipeline.run({
                "as_of": request["as_of"],
                "industry_id": request["industry_id"],
                "industry_name": request["industry_name"],
                "depth": request["depth"],
                "deterministic_only": request.get("deterministic_only", True),
                "task_id": task.task_id,
            })
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()

        # 5. 写入 industry_research_run.json artifact
        art_paths: List[str] = []
        if outcome.markdown:
            art_paths.append("final.md")

        finished_at = now_iso()
        run_payload: Dict[str, Any] = {
            "run_id": outcome.run_id,
            "request_id": request_id,
            "task_id": task.task_id,
            "idempotency_key": f"{task.task_id}:{request['industry_id']}:{request['as_of']}",
            "run_version": 1,
            "started_at": requested_at,
            "finished_at": finished_at,
            "status": outcome.status,
            "stage_statuses": [
                {
                    "stage": "build_research_context",
                    "status": "degraded" if outcome.data_degraded else "success",
                    "started_at": requested_at,
                    "finished_at": finished_at,
                    "warnings": [],
                    "missing_data": [],
                },
                {
                    "stage": "produce_dimension_findings",
                    "status": "success" if outcome.findings else "insufficient_evidence",
                    "started_at": requested_at,
                    "finished_at": finished_at,
                    "warnings": outcome.warnings,
                    "missing_data": outcome.missing_data,
                },
            ],
            "artifact_paths": art_paths,
            "input_versions": dict(request.get("rule_versions") or {}),
            "model_route_summary": outcome.model_route,
            "validation_status": "pass"
                if outcome.status not in ("failed", "insufficient_evidence")
                else "fail",
            "error_codes": [],
            "warnings": outcome.warnings,
            "version": 1,
        }
        run_dir.write_json("industry_research_run.json", run_payload)

        # 6. 写入产出报告
        report_path = None
        if outcome.markdown:
            report_path = run_dir.final_md
            run_dir.write_final(outcome.markdown)

        # 7. 校验状态
        validation = "fail" if outcome.status == "failed" else (
            "degraded" if outcome.data_degraded else "pass"
        )
        run_dir.write_validation({
            "status": "ok" if validation == "pass" else "failed",
            "task_id": task.task_id,
            "checks": len(outcome.dimensions_missing),
            "errors": outcome.dimensions_missing[:20],
        })

        return ScenarioExecutionResult(
            status=outcome.status,
            exit_code=0 if outcome.status != "failed" else 1,
            task_id=task.task_id,
            run_id=outcome.run_id,
            run_dir=str(run_dir.root),
            report_path=str(report_path) if report_path else None,
            validation_status=validation,
            warnings=outcome.warnings,
            missing_data=outcome.missing_data,
            model_route=outcome.model_route,
            message=(
                f"行业研究完成: industry={outcome.industry_name}, "
                f"status={outcome.status}, "
                f"dimensions_covered={len(outcome.dimensions_covered)}/21, "
                f"model={outcome.model_route.get('mode', 'unknown')}"
            ),
        )

    # ---------- 内部校验 ----------

    @staticmethod
    def _validate_request_artifact(payload: Dict[str, Any]) -> None:
        """校验 request artifact —— FAIL-CLOSED。

        industry_research_request schema 已注册在 SCHEMA_NAMES 中，
        任何 errors 直接 raise ValueError，禁止继续执行。
        """
        from research_os.validators.schema_validator import validate_instance

        errors = validate_instance(payload, "industry_research_request")
        if errors:
            raise ValueError(
                "industry_research_request schema 校验失败:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )
