"""主题发现场景适配器（Phase 6A）。

ThemeDiscoveryScenarioRunner 是编排层 adapter：
从知识图谱、证据库和关键词扫描中识别新兴投资主题。

核心约束：
- as_of 必填（禁止默认 now()），fail-closed，保证审计可追溯
- 在 pipeline 执行前写入 theme_discovery_request.json artifact（血缘：Task=Plan=Request=Run=Result）
- schema 校验 fail-closed：validate_instance 返回错误则立即 raise ValueError
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
        2. 构造 theme_triggers 并写入 theme_discovery_request.json（血缘契约）
        3. FAIL-CLOSED schema 校验
        4. 调用 ThemeDiscoveryPipeline.run(DICT)
        5. 写入 run.json
        6. 写入产出报告，返回 ScenarioExecutionResult
        """
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

        # ----- 2. 构造 theme_triggers -----
        theme_triggers = self._build_theme_triggers(request)

        # ----- 3. 构造并校验 request artifact（FAIL-CLOSED）-----
        schema_mode = _PIPELINE_TO_SCHEMA_MODE.get(discovery_mode, "scanning")
        request_payload: Dict[str, Any] = {
            "request_id": new_uuid(),
            "task_id": task.task_id,
            "theme_triggers": theme_triggers,
            "as_of": request["as_of"],
            "as_of_basis": request.get("as_of_basis", "user_provided"),
            "timezone": "Asia/Shanghai",
            "depth": request.get("depth", "standard"),
            "discovery_mode": schema_mode,
            "industry_ids": list(request.get("industry_ids") or []),
            "keywords": list(request.get("keywords") or []),
            "live": bool(request.get("live")),
            "dry_run": False,
            "force": bool(request.get("force")),
            "source_policy": request.get("source_policy", "public_first"),
            "status": "validated",
            "warnings": list(request.get("warnings") or []),
            "rule_versions": {},
            "requested_at": now_iso(),
            "version": 1,
        }

        errors = validate_instance(request_payload, "theme_discovery_request")
        if errors:
            raise ValueError(
                "theme_discovery_request schema 校验失败:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        run_dir.write_json("theme_discovery_request.json", request_payload)

        # ----- 4. 调用 ThemeDiscoveryPipeline -----
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

        # ----- 5. 写入 run.json -----
        run_payload = self._build_run_payload(
            outcome, task.task_id, request_payload["request_id"],
        )
        run_dir.write_json("run.json", run_payload)

        # ----- 6. 写入产出报告 -----
        report_path = None
        if outcome.markdown:
            report_path = run_dir.final_md
            run_dir.write_final(outcome.markdown)

        # ----- 7. 校验状态映射 -----
        validation = "fail" if outcome.status == "failed" else "pass"
        run_dir.write_validation({
            "status": "ok" if validation == "pass" else "failed",
            "task_id": task.task_id,
            "checks": len(outcome.themes),
            "errors": [],
        })

        # ----- 8. 返回 ScenarioExecutionResult -----
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

    # ---------- 内部辅助 ----------

    @staticmethod
    def _build_theme_triggers(request: Dict[str, Any]) -> List[Dict[str, Any]]:
        """从请求参数构造 schema 兼容的 theme_triggers 数组。

        schema 要求 minItems=1，每项含 trigger_type 与 description。
        """
        triggers: List[Dict[str, Any]] = []
        trigger_type = request.get("trigger_type", "user_specified")
        trigger_description = request.get("trigger_description", "")
        industry_ids: List[str] = list(request.get("industry_ids") or [])
        keywords: List[str] = list(request.get("keywords") or [])

        if industry_ids:
            desc = trigger_description or (
                f"行业列表: {', '.join(industry_ids[:5])}"
                + ("…" if len(industry_ids) > 5 else "")
            )
            triggers.append({"trigger_type": trigger_type, "description": desc})

        if keywords:
            desc = trigger_description or (
                f"关键词: {', '.join(keywords[:5])}"
                + ("…" if len(keywords) > 5 else "")
            )
            triggers.append({"trigger_type": trigger_type, "description": desc})

        if not triggers:
            triggers.append({
                "trigger_type": "user_specified",
                "description": trigger_description or "主题发现（无指定触发器）",
            })

        return triggers

    @staticmethod
    def _build_run_payload(
        outcome: Any, task_id: str, request_id: str,
    ) -> Dict[str, Any]:
        """从 pipeline ThemeDiscoveryResult 构造 run.json artifact。

        写入符合 theme_discovery_run schema 的所有必需字段。
        """
        from research_os.utils.time import now_iso

        return {
            "run_id": outcome.run_id,
            "request_id": request_id,
            "task_id": task_id,
            "as_of": outcome.as_of,
            "discovery_mode": outcome.discovery_mode,
            "status": outcome.status,
            "idempotency_key": f"{task_id}:{outcome.discovery_mode}",
            "run_version": 1,
            "started_at": outcome.as_of,
            "finished_at": now_iso(),
            "stage_statuses": [],
            "artifact_paths": [],
            "input_versions": {},
            "model_route_summary": outcome.model_route if outcome.model_route else {
                "mode": "deterministic_fallback", "llm_called": False,
            },
            "validation_status": "pass" if outcome.status != "failed" else "fail",
            "error_codes": [],
            "warnings": list(outcome.warnings),
            "missing_data": list(outcome.missing_data),
            "themes_discovered": len(outcome.themes),
            "version": 1,
        }
