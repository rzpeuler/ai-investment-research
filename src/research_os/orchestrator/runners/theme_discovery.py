"""主题发现场景适配器（Phase 6A）。

ThemeDiscoveryScenarioRunner 是编排层 adapter：
从知识图谱、证据库和关键词扫描中识别新兴投资主题。

核心约束：
- as_of 必填（禁止默认 now()），fail-closed，保证审计可追溯
- 在 pipeline 执行前写入 theme_discovery_request.json artifact（血缘：Task=Plan=Request=Run=Result）
- Pydantic 构造 + validated_payload 双重校验，schema fail-closed（errors ≠ [] 则 raise ValueError）
- 不提供 _default_as_of 辅助函数
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from research_os.orchestrator.scenario_runner import ScenarioExecutionResult

# ── pipeline discovery_mode → schema discovery_mode 映射 ──
_PIPELINE_TO_SCHEMA_MODE: Dict[str, str] = {
    "graph_based": "scanning",
    "keyword_sweep": "scanning",
    "evidence_driven": "scanning",
    "peer_diffusion": "monitoring",
}


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
        2. Pydantic 构造 ThemeDiscoveryRequest → validated_payload → 写入 artifact
        3. Schema fail-closed（errors ≠ [] 则 raise ValueError）
        4. 调用 ThemeDiscoveryPipeline.run(DICT)
        5. Pydantic 构造 ThemeDiscoveryRun → validated_payload → 写入 artifact
        6. 写入产出报告，返回 ScenarioExecutionResult
        """
        from research_os.brief import validated_payload
        from research_os.models import ThemeDiscoveryRequest, ThemeDiscoveryRun
        from research_os.orchestrator.run_directory import RunDirectory
        from research_os.storage import Database
        from research_os.theme_discovery.pipeline import ThemeDiscoveryPipeline
        from research_os.utils.id import new_uuid
        from research_os.utils.time import now_iso

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

        # ----- 2. Pydantic 构造请求 → validated_payload → fail-closed 写入 artifact -----
        schema_mode = _PIPELINE_TO_SCHEMA_MODE.get(discovery_mode, "scanning")
        request_id = new_uuid()
        requested_at = now_iso()
        request_model = ThemeDiscoveryRequest(
            request_id=request_id,
            task_id=task.task_id,
            as_of=request["as_of"],
            discovery_mode=schema_mode,
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
        run_dir.write_json("theme_discovery_request.json",
                           validated_payload(request_model, "theme_discovery_request"))

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
            })
        finally:
            if ephemeral_db is not None:
                ephemeral_db.close()

        # ----- 4. Pydantic 构造运行记录 → validated_payload → 写入 artifact -----
        run_model = ThemeDiscoveryRun(
            run_id=outcome.run_id,
            request_id=request_id,
            task_id=task.task_id,
            as_of=request["as_of"],
            discovery_mode=schema_mode,
            status=outcome.status,
            themes_discovered=len(outcome.themes),
            sort_metrics_count=getattr(outcome, "sort_metrics_count", 0),
            report_path=str(run_dir.final_md) if outcome.markdown else None,
            warnings=list(outcome.warnings),
            missing_data=list(outcome.missing_data),
            model_route=dict(outcome.model_route) if outcome.model_route else {},
            data_degraded=bool(getattr(outcome, "data_degraded", False)),
            version=1,
        )
        run_dir.write_json("theme_discovery_run.json",
                           validated_payload(run_model, "theme_discovery_run"))

        # ----- 5. 写入产出报告 -----
        report_path = None
        if outcome.markdown:
            report_path = run_dir.final_md
            run_dir.write_final(outcome.markdown)

        # ----- 6. 校验状态映射 -----
        validation = "fail" if outcome.status == "failed" else "pass"
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
