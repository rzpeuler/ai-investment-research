"""主题发现场景适配器（Phase 6A）。

ThemeDiscoveryScenarioRunner 是编排层 adapter：
从知识图谱、证据库和关键词扫描中识别新兴投资主题。

核心约束：
- as_of 必填（禁止默认 now()），fail-closed，保证审计可追溯
- 在 pipeline 执行前写入 theme_discovery_request.json artifact（血缘：Task=Plan=Request=Run=Result）
- Pydantic 构造 + validate_instance 双重校验，schema fail-closed（errors ≠ [] 则 raise ValueError）
- 不提供 _default_as_of 辅助函数
- discovery_mode 透传 verbatim：graph_based / evidence_driven / keyword_sweep / peer_diffusion
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult


def _build_theme_triggers(request: Dict[str, Any]) -> List[Dict[str, str]]:
    """Build schema-valid theme_triggers from request fields."""
    triggers: List[Dict[str, str]] = []
    mode = request.get("discovery_mode", "graph_based")
    industry_ids = request.get("industry_ids", [])
    keywords = request.get("keywords", [])
    desc_parts: List[str] = []
    if mode:
        desc_parts.append(f"discovery_mode={mode}")
    if industry_ids:
        desc_parts.append(f"industries={','.join(industry_ids[:3])}")
    if keywords:
        desc_parts.append(f"keywords={','.join(keywords[:3])}")
    description = "; ".join(desc_parts) if desc_parts else "user_specified discovery trigger"
    triggers.append({
        "trigger_type": "user_specified",
        "description": description,
    })
    return triggers


class ThemeDiscoveryScenarioRunner:
    """主题发现 ScenarioRunner。

    validate_request → build_plan → execute。
    编排层只组合已有模块，不承载具体研究算法。
    """

    scenario = "theme_discovery"
    version = "1.0.0"

    # ---------- validate_request ----------

    def validate_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """规范化请求参数。as_of 必填——主题发现必须锁定时间断面。"""
        from research_os.utils.time import validate_iso

        if not request.get("as_of"):
            raise ValueError("theme_discovery requires explicit --as-of (ISO-8601)")
        if not validate_iso(request["as_of"]):
            raise ValueError(f"Invalid as_of: {request['as_of']!r}")

        normalized = dict(request)
        normalized["discovery_mode"] = request.get("discovery_mode", "graph_based")
        if normalized["discovery_mode"] not in {
            "graph_based", "evidence_driven", "keyword_sweep", "peer_diffusion",
        }:
            normalized["discovery_mode"] = "graph_based"
        normalized["industry_ids"] = list(request.get("industry_ids") or [])
        normalized["keywords"] = list(request.get("keywords") or [])
        normalized.setdefault("depth", "standard")
        if normalized["depth"] not in {"fast", "standard", "deep"}:
            normalized["depth"] = "standard"
        normalized.setdefault("dry_run", False)
        normalized.setdefault("live", False)
        normalized.setdefault("force", False)
        normalized.setdefault("graph_max_depth", 1)
        normalized.setdefault("research_priority_threshold", 0.0)
        normalized.setdefault("source_policy", "public_first")
        normalized.setdefault("as_of_basis", "user_provided")
        normalized.setdefault("trigger_type", "user_specified")
        normalized.setdefault("trigger_description", "")
        normalized.setdefault("warnings", [])
        return normalized

    # ---------- build_plan ----------

    def build_plan(self, request: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """生成主题发现执行计划。"""
        discovery_mode = request.get("discovery_mode", "graph_based")

        _STEPS: Dict[str, List[str]] = {
            "graph_based": [
                "resolve_industries", "load_knowledge_graph", "extract_industry_subgraphs",
                "detect_emerging_clusters", "rank_by_novelty", "filter_by_evidence",
                "synthesize_themes", "render", "validate",
            ],
            "evidence_driven": [
                "collect_evidence_stream", "build_co_occurrence", "detect_anomalous_patterns",
                "cluster_by_semantic_similarity", "rank_by_evidence_strength",
                "synthesize_themes", "render", "validate",
            ],
            "keyword_sweep": [
                "expand_keywords", "scan_documents", "rank_by_frequency_momentum",
                "filter_noise", "synthesize_themes", "render", "validate",
            ],
            "peer_diffusion": [
                "select_peer_cohort", "extract_peer_themes", "diffusion_graph_analysis",
                "detect_cross_industry_signals", "rank_by_peer_consensus",
                "synthesize_themes", "render", "validate",
            ],
        }
        _DATA: Dict[str, List[str]] = {
            "graph_based": ["knowledge_graph_snapshot", "industry_membership",
                           "entity_mapping", "evidence_index"],
            "peer_diffusion": ["knowledge_graph_snapshot", "industry_membership",
                               "entity_mapping", "evidence_index"],
            "evidence_driven": ["evidence_stream", "document_corpus", "entity_mapping",
                                "source_registry"],
            "keyword_sweep": ["document_corpus", "keyword_index", "source_registry"],
        }

        return {
            "steps": _STEPS.get(discovery_mode, _STEPS["graph_based"]),
            "data_requirements": _DATA.get(discovery_mode, _DATA["graph_based"]),
            "model_policy": "flash_default_with_pro_escalation",
            "fallback_policy": [
                "deterministic_fallback", "GRAPH_UNAVAILABLE", "THEME_DISCOVERY_DEGRADED",
            ],
            "output_paths": ["reports/themes/{discovery_mode}", "reports/runs/{task_id}"],
        }

    # ---------- execute ----------

    def execute(self, request: Dict[str, Any], context: Dict[str, Any]) -> ScenarioExecutionResult:
        """执行主题发现编排流程。

        1. 创建运行目录并写入 task/plan
        2. Pydantic 构造 ThemeDiscoveryRequest → validate_instance → 写入 artifact
        3. Schema fail-closed（errors ≠ [] 则 raise ValueError）
        4. 调用 ThemeDiscoveryPipeline.run(DICT)
        5. Pydantic 构造 ThemeDiscoveryRun → validate_instance → 写入 artifact
        6. 写入产出报告，返回 ScenarioExecutionResult
        """
        from research_os.models import ThemeDiscoveryRequest, ThemeDiscoveryRun
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.storage import Database
        from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso
        from research_os.validators.schema_validator import validate_instance

        root: Path = context["project_root"]
        task = context["task"]
        dry_run = request.get("dry_run", False)
        discovery_mode = request.get("discovery_mode", "graph_based")

        if dry_run:
            return ScenarioExecutionResult(
                status="planned", exit_code=0, task_id=task.task_id,
                validation_status="not_run",
                model_route={"mode": "deterministic_fallback", "llm_called": False},
                message=(
                    f"[dry-run] 主题发现 mode={discovery_mode} "
                    f"as_of={request['as_of']}；零副作用"
                ),
            )

        # ----- 1. 创建运行目录 -----
        run_dir = RunDirectory(root / "reports" / "runs", task.task_id)
        run_dir.create()
        run_dir.write_task(task.model_dump())
        run_dir.write_plan(context["plan"].model_dump())

        # ----- 2. Pydantic 构造请求 → validate_instance → fail-closed 写入 artifact -----
        request_id = new_uuid()
        requested_at = now_iso()
        theme_triggers = _build_theme_triggers(request)
        request_model = ThemeDiscoveryRequest(
            request_id=request_id,
            task_id=task.task_id,
            theme_triggers=theme_triggers,
            as_of=request["as_of"],
            discovery_mode=discovery_mode,
            industry_ids=list(request.get("industry_ids") or []),
            keywords=list(request.get("keywords") or []),
            depth=request.get("depth", "standard"),
            live=bool(request.get("live", False)),
            dry_run=False,
            force=bool(request.get("force", False)),
            source_policy=request.get("source_policy", "public_first"),
            status="validated",
            warnings=list(request.get("warnings") or []),
            requested_at=requested_at,
            version=1,
        )
        _payload = request_model.model_dump()
        _errs = validate_instance(_payload, "theme_discovery_request")
        if _errs:
            raise ValueError(f"theme_discovery_request schema fail-closed: {_errs}")
        run_dir.write_json("theme_discovery_request.json", _payload)

        # ----- 3. 调用 ThemeDiscoveryPipeline -----
        ephemeral_db = None
        db = context.get("db")
        if db is None:
            ephemeral_db = Database(":memory:")
            ephemeral_db.initialize()
            db = ephemeral_db
        try:
            pipeline = ThemeDiscoveryPipeline(root, db)
            outcome = pipeline.run({
                "as_of": request["as_of"],
                "discovery_mode": discovery_mode,
                "industry_ids": request.get("industry_ids", []),
                "keywords": request.get("keywords", []),
                "task_id": task.task_id,
            })
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()

        # ----- 4. Pydantic 构造运行记录 → validate_instance → 写入 artifact -----
        # Compute validation_status from actual outcome (R2-3)
        validation = (
            "fail" if outcome.status == "failed"
            else "degraded" if getattr(outcome, "data_degraded", False)
            else "pass"
        )
        run_id = outcome.run_id
        started_at = requested_at
        finished_at = (
            now_iso()
            if outcome.status in ("success", "partial_success", "degraded", "failed")
            else None
        )
        run_model = ThemeDiscoveryRun(
            run_id=run_id,
            request_id=request_id,
            task_id=task.task_id,
            as_of=request["as_of"],
            discovery_mode=discovery_mode,
            idempotency_key=f"{task.task_id}:{discovery_mode}:{request['as_of']}",
            run_version=1,
            started_at=started_at,
            finished_at=finished_at,
            status=outcome.status,
            stage_statuses=[],
            artifact_paths=[
                str(run_dir.root / "theme_discovery_request.json"),
                str(run_dir.root / "theme_discovery_run.json"),
            ],
            input_versions={"pipeline_version": "1.0.0"},
            model_route_summary=dict(outcome.model_route) if outcome.model_route else {},
            validation_status=validation,
            error_codes=[],
            warnings=list(outcome.warnings),
            missing_data=list(outcome.missing_data),
            themes_discovered=len(outcome.themes),
            industry_ids=list(request.get("industry_ids") or []),
            keywords=list(request.get("keywords") or []),
            model_route=dict(outcome.model_route) if outcome.model_route else {},
            version=1,
        )
        _rpayload = run_model.model_dump()
        _rerrs = validate_instance(_rpayload, "theme_discovery_run")
        if _rerrs:
            raise ValueError(f"theme_discovery_run schema fail-closed: {_rerrs}")
        run_dir.write_json("theme_discovery_run.json", _rpayload)

        # ----- 5. 写入产出报告 -----
        report_path = None
        if outcome.markdown:
            report_path = run_dir.final_md
            run_dir.write_final(outcome.markdown)

        # ----- 6. 校验状态映射 -----
        run_dir.write_validation({
            "status": "ok" if validation == "pass" else "failed",
            "task_id": task.task_id,
            "checks": len(outcome.themes),
            "errors": [],
        })

        # ----- 7. 返回 ScenarioExecutionResult -----
        return ScenarioExecutionResult(
            status=outcome.status,
            exit_code=1 if outcome.status == "failed" else 0,
            task_id=task.task_id,
            run_id=outcome.run_id,
            run_dir=str(run_dir.root),
            report_path=str(report_path) if report_path else None,
            validation_status=validation,
            warnings=list(outcome.warnings),
            missing_data=list(outcome.missing_data),
            model_route=outcome.model_route if outcome.model_route else {
                "mode": "deterministic_fallback", "llm_called": False,
            },
            message=(
                f"主题发现完成: mode={discovery_mode}, "
                f"status={outcome.status}, "
                f"themes={len(outcome.themes)}"
            ),
        )
