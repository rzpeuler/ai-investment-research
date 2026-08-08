"""M9 Scenario Integration — Phase2/3/4 Structured Research → GraphChange Candidate.

职责：
  scenario run artifacts → 定位结构化 ID → SQLite 权威重载 → CandidatePipeline

M9 是 Research→Candidate 单向集成。不实现 Graph→Research。
不修改 M3 source whitelist / Schema / migration。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from research_os.utils.time import now_iso


# ---------------------------------------------------------------------------
# 错误与错误码
# ---------------------------------------------------------------------------

class IntegrationError(Exception):
    """M9 集成错误，携带结构化 error_code。"""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


# 硬上限
MAX_INTEGRATION_SOURCES = 20


# ---------------------------------------------------------------------------
# IntegrationResult
# ---------------------------------------------------------------------------

@dataclass
class IntegrationResult:
    """M9 integration 调用结果。"""

    status: str = ""  # "ok" | "dry_run" | "preflight_only" | "error"
    error_code: Optional[str] = None
    errors: List[str] = field(default_factory=list)
    scenario: str = ""
    run_dir: str = ""
    resolved_source_refs: List[str] = field(default_factory=list)
    selected_source_refs: List[str] = field(default_factory=list)
    pipeline_result: Optional[Dict[str, Any]] = None
    warnings: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# ScenarioCandidateIntegrator
# ---------------------------------------------------------------------------

class ScenarioCandidateIntegrator:
    """从 scenario run artifacts 定位结构化研究对象 → CandidatePipeline。

    使用：
        from research_os.storage import Database
        from research_os.knowledge.scenario_integration import (
            ScenarioCandidateIntegrator,
        )

        db = Database(...)
        integrator = ScenarioCandidateIntegrator(
            db=db,
            project_root=Path("."),
        )
        result = integrator.integrate(
            scenario="stock_research_report",
            run_dir=Path("reports/runs/<task_id>"),
            live=True,
            provider=llm_provider,
        )
    """

    _SCENARIO_CANONICAL = {
        "morning_brief",
        "abnormal_move_analysis",
        "stock_research_report",
    }

    def __init__(
        self,
        db: Any,
        *,
        project_root: Optional[Path] = None,
        knowledge_dir: Optional[Path] = None,
        provider: Any = None,
        live: bool = False,
        dry_run: bool = False,
    ) -> None:
        self._db = db
        self._project_root = project_root or Path.cwd()
        self._knowledge_dir = knowledge_dir or (self._project_root / "knowledge")
        self._provider = provider
        self._live = live
        self._dry_run = dry_run

    # ---- 公共入口 ----

    def integrate(
        self,
        scenario: str,
        run_dir: Path,
        *,
        selected_sources: Optional[Sequence[str]] = None,
        requested_model_class: str = "flash",
    ) -> IntegrationResult:
        """从 scenario run artifacts 定位 source refs → CandidatePipeline。

        Args:
            scenario: canonical name（morning_brief/abnormal_move_analysis/stock_research_report）
            run_dir: reports/runs/<task_id> 目录路径。
            selected_sources: 显式子集 filter（"Type:ID"），必须是 resolver 发现的子集。
            requested_model_class: "flash" | "pro"（透传给 CandidatePipeline）。

        Returns:
            IntegrationResult。
        """
        result = IntegrationResult(
            scenario=scenario,
            run_dir=str(run_dir),
        )

        try:
            # 1. 校验 scenario
            if scenario not in self._SCENARIO_CANONICAL:
                raise IntegrationError(
                    "INTEGRATION_SCENARIO_UNSUPPORTED",
                    f"不支持场景: {scenario!r}，允许: {sorted(self._SCENARIO_CANONICAL)}",
                )

            # 2. 校验 run_dir 安全
            run_dir = self._validate_run_dir(run_dir)

            # 3. 解析 source refs（scenario-specific）
            resolved, warnings = self._resolve_sources(scenario, run_dir)

            result.resolved_source_refs = sorted(dict.fromkeys(resolved))
            result.warnings.extend(warnings)

            # 4. 应用 source filter
            if selected_sources is not None:
                resolved_set = set(result.resolved_source_refs)
                sel_list = list(selected_sources)
                invalid = [s for s in sel_list if s not in resolved_set]
                if invalid:
                    raise IntegrationError(
                        "INTEGRATION_SOURCE_FILTER_INVALID",
                        f"source filter 包含未被 resolver 发现的源: {invalid}",
                    )
                selected = sorted(dict.fromkeys(sel_list))
            else:
                selected = result.resolved_source_refs

            result.selected_source_refs = selected

            if not selected:
                result.status = "error"
                result.error_code = "INTEGRATION_NO_ELIGIBLE_SOURCES"
                result.errors.append("无可供集成的结构化 source")
                return result

            if len(selected) > MAX_INTEGRATION_SOURCES:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_LIMIT_EXCEEDED",
                    f"source 数量 {len(selected)} 超过上限 {MAX_INTEGRATION_SOURCES}；"
                    f"请使用 --source 显式子集过滤",
                )

            # 5. 解析 "Type:ID" → [(Type, ID), ...]
            sources = []
            for ref in selected:
                st, sid = ref.split(":", 1)
                sources.append((st, sid))

            # 6. 调用 CandidatePipeline（唯一 authority）
            pipeline_result = self._run_pipeline(sources, requested_model_class)
            result.pipeline_result = pipeline_result

            # 管道自身返回的状态映射
            if pipeline_result.get("status") in ("ok", "dry_run", "preflight_only"):
                result.status = pipeline_result["status"]
            else:
                result.status = "error"
                result.error_code = "PIPELINE_FAILED"
                result.errors.extend(pipeline_result.get("errors", []))

        except IntegrationError as exc:
            result.status = "error"
            result.error_code = exc.error_code
            result.errors.append(str(exc))
        except Exception as exc:
            result.status = "error"
            result.error_code = "INTEGRATION_READ_FAILED"
            result.errors.append(f"{type(exc).__name__}: {exc}")

        return result

    # ---- run_dir 安全 ----

    def _validate_run_dir(self, run_dir: Path) -> Path:
        """验证 run_dir 在 project_root/reports/runs/ 下，拒绝逃逸。"""
        run_dir = run_dir.resolve()

        runs_root = (self._project_root / "reports" / "runs").resolve()
        try:
            run_dir.relative_to(runs_root)
        except ValueError:
            raise IntegrationError(
                "INTEGRATION_RUN_DIR_INVALID",
                f"run_dir 必须在 {runs_root} 下，实际: {run_dir}",
            )

        if not run_dir.is_dir():
            raise IntegrationError(
                "INTEGRATION_RUN_DIR_INVALID",
                f"run_dir 不存在或不是目录: {run_dir}",
            )

        return run_dir

    # ---- Source resolution ----

    def _resolve_sources(
        self, scenario: str, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """路由到对应 scenario 解析器。返回 (refs, warnings)。"""
        return {
            "morning_brief": self._resolve_morning_sources,
            "abnormal_move_analysis": self._resolve_abnormal_sources,
            "stock_research_report": self._resolve_equity_sources,
        }[scenario](run_dir)

    def _resolve_morning_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """晨报: claims.json → Claim:<claim_id>。"""
        refs: List[str] = []
        warnings: List[str] = []

        claims_path = run_dir / "claims.json"
        if not claims_path.is_file():
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_MISSING",
                f"缺少 claims.json: {claims_path}",
            )

        claims_data = self._read_json(claims_path, "claims.json")
        if not isinstance(claims_data, list):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "claims.json 必须是数组",
            )

        task_data = self._read_optional_json(run_dir / "task.json")
        if task_data is not None and not isinstance(task_data, dict):
            warnings.append("task.json 格式异常，跳过完整性校验")

        for idx, raw in enumerate(claims_data):
            prefix = f"claims.json[{idx}]"

            if not isinstance(raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 每项必须是对象",
                )

            claim_id = raw.get("claim_id")
            if not claim_id or not isinstance(claim_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 claim_id",
                )

            # 验证 DB 中存在且 artifact 与 DB 一致
            db_claim = self._load_source("Claim", claim_id)
            if db_claim is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: claim_id={claim_id!r} 在 SQLite claims 表中不存在",
                )

            # artifact JSON vs DB row 一致性（关键字段）
            for key in ("claim_id", "claim_type", "statement", "evidence_ids"):
                art_val = raw.get(key)
                db_val = db_claim.get(key)
                if art_val is not None and art_val != db_val:
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: {key} 不一致: "
                        f"artifact={art_val!r} vs DB={db_val!r}",
                    )

            refs.append(f"Claim:{claim_id}")

        # 验证 validation
        val = self._read_optional_json(run_dir / "validation.json")
        if val is not None:
            if not isinstance(val, dict):
                warnings.append("validation.json 格式异常")
            else:
                val_status = val.get("status", val.get("verdict", ""))
                if val_status not in ("pass", "pass_with_warnings", ""):
                    warnings.append(
                        f"晨报报告校验状态非 pass: {val_status}，"
                        f"candidate 质量可能受影响"
                    )

        return refs, warnings

    def _resolve_abnormal_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """异动: cause_evidence_links.json → Evidence:<evidence_id>。

        禁止 CauseCandidate / AttributionResult / Observation。
        """
        refs: List[str] = []
        warnings: List[str] = []

        links_path = run_dir / "cause_evidence_links.json"
        if not links_path.is_file():
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_MISSING",
                f"缺少 cause_evidence_links.json: {links_path}",
            )

        links_data = self._read_json(links_path, "cause_evidence_links.json")
        if not isinstance(links_data, list):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "cause_evidence_links.json 必须是数组",
            )

        # 读取 proof-of-chain 文件
        run_data = self._read_optional_json(run_dir / "abnormal_move_run.json")
        cause_data = self._read_optional_json(run_dir / "cause_candidates.json")
        val = self._read_optional_json(run_dir / "validation.json")

        if run_data is None:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_MISSING",
                "缺少 abnormal_move_run.json，无法验证请求隶属",
            )
        if not isinstance(run_data, dict):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "abnormal_move_run.json 必须是对象",
            )

        run_request_id = run_data.get("request_id")

        # 索引 DB cause_candidates 以验证隶属关系
        cause_lookup: Dict[str, Dict[str, Any]] = {}
        if run_request_id and cause_data and isinstance(cause_data, list):
            for c_raw in cause_data:
                if not isinstance(c_raw, dict):
                    continue
                cid = c_raw.get("cause_candidate_id")
                if cid and isinstance(cid, str):
                    cause_lookup[cid] = c_raw

        seen_evidence: Dict[str, bool] = {}

        for idx, raw in enumerate(links_data):
            prefix = f"cause_evidence_links.json[{idx}]"

            if not isinstance(raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 每项必须是对象",
                )

            link_id = raw.get("link_id")
            cause_candidate_id = raw.get("cause_candidate_id")
            evidence_id = raw.get("evidence_id")

            if not link_id or not isinstance(link_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 link_id",
                )
            if not cause_candidate_id or not isinstance(cause_candidate_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 cause_candidate_id",
                )
            if not evidence_id or not isinstance(evidence_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 evidence_id",
                )

            # 验证 cause_candidate 隶属
            if cause_candidate_id in cause_lookup:
                cc = cause_lookup[cause_candidate_id]
                if run_request_id and cc.get("request_id") != run_request_id:
                    raise IntegrationError(
                        "INTEGRATION_SOURCE_RUN_MISMATCH",
                        f"{prefix}: cause_candidate={cause_candidate_id!r} "
                        f"属于不同的 request，拒绝跨 run 泄露",
                    )
            else:
                warnings.append(
                    f"{prefix}: cause_candidate={cause_candidate_id!r} 未在 "
                    f"cause_candidates.json 中找到，无法验证隶属"
                )

            # 验证 DB 中 link 存在
            self._verify_db_row(
                "cause_evidence_links",
                "link_id",
                link_id,
                raw,
                prefix,
            )

            # 验证 DB 中 Evidence 存在
            ev = self._load_source("Evidence", evidence_id)
            if ev is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: evidence_id={evidence_id!r} 在 SQLite evidence 表中不存在",
                )

            # dedup
            if evidence_id not in seen_evidence:
                seen_evidence[evidence_id] = True
                refs.append(f"Evidence:{evidence_id}")

        # 验证 validation
        if val is not None and isinstance(val, dict):
            val_status = val.get("status", val.get("verdict", ""))
            if val_status not in ("pass", "pass_with_warnings", ""):
                warnings.append(
                    f"异动分析校验状态非 pass: {val_status}，"
                    f"Evidence 质量可能受影响"
                )

        return refs, warnings

    def _resolve_equity_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """个股研报 v1: research_findings.json → ResearchFinding:<finding_id>。

        验证 run.request_id == finding.request_id。
        """
        refs: List[str] = []
        warnings: List[str] = []

        findings_path = run_dir / "research_findings.json"
        if not findings_path.is_file():
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_MISSING",
                f"缺少 research_findings.json: {findings_path}",
            )

        findings_data = self._read_json(findings_path, "research_findings.json")
        if not isinstance(findings_data, list):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "research_findings.json 必须是数组",
            )

        # 读取 run 以获取 request_id
        run_data = self._read_optional_json(
            run_dir / "equity_research_run.json"
        )
        req_data = self._read_optional_json(
            run_dir / "equity_research_request.json"
        )
        val = self._read_optional_json(run_dir / "validation.json")

        run_request_id: Optional[str] = None
        if run_data and isinstance(run_data, dict):
            run_request_id = run_data.get("request_id")
        if not run_request_id and req_data and isinstance(req_data, dict):
            run_request_id = req_data.get("request_id")

        for idx, raw in enumerate(findings_data):
            prefix = f"research_findings.json[{idx}]"

            if not isinstance(raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 每项必须是对象",
                )

            finding_id = raw.get("finding_id")
            if not finding_id or not isinstance(finding_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 finding_id",
                )

            # 验证 DB 中存在且 artifact 与 DB 一致
            db_finding = self._load_source("ResearchFinding", finding_id)
            if db_finding is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: finding_id={finding_id!r} 在 SQLite "
                    f"research_findings 表中不存在",
                )

            # cross-run attack
            if run_request_id and db_finding.get("request_id") != run_request_id:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_RUN_MISMATCH",
                    f"{prefix}: finding={finding_id!r} 的 "
                    f"request_id={db_finding.get('request_id')!r} "
                    f"≠ run.request_id={run_request_id!r}",
                )

            # 关键字段一致性
            for key in ("finding_id", "finding_type", "statement", "evidence_ids"):
                art_val = raw.get(key)
                db_val = db_finding.get(key)
                if art_val is not None and art_val != db_val:
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: {key} 不一致: "
                        f"artifact={art_val!r} vs DB={db_val!r}",
                    )

            refs.append(f"ResearchFinding:{finding_id}")

        if not run_request_id:
            warnings.append(
                "未在 equity_research_run.json 中找到 request_id，"
                "无法执行 cross-run 隶属验证"
            )

        if val is not None and isinstance(val, dict):
            val_status = val.get("status", val.get("verdict", ""))
            if val_status not in ("pass", "pass_with_warnings", ""):
                warnings.append(
                    f"个股研报校验状态非 pass: {val_status}，"
                    f"candidate 质量可能受影响"
                )

        return refs, warnings

    # ---- 工具方法 ----

    def _run_pipeline(
        self,
        sources: List[Tuple[str, str]],
        requested_model_class: str = "flash",
    ) -> Dict[str, Any]:
        """调用 CandidatePipeline.run()（唯一 authority）。"""
        from research_os.knowledge.candidate_pipeline import CandidatePipeline

        pipeline = CandidatePipeline(
            db=self._db,
            provider=self._provider,
            live=self._live,
            dry_run=self._dry_run,
        )
        return pipeline.run(
            sources=sources,
            knowledge_dir=self._knowledge_dir,
            requested_model_class=requested_model_class,
        )

    def _load_source(
        self, source_type: str, source_id: str
    ) -> Optional[Dict[str, Any]]:
        """从 SQLite 加载结构化对象（Schema→Pydantic→Schema 严格验证）。"""
        from research_os.knowledge.candidate_sources import SourceAdapter

        adapter = SourceAdapter(self._db)
        try:
            obj = adapter.load(source_type, source_id)
            return obj.model_dump() if hasattr(obj, "model_dump") else obj
        except Exception:
            return None

    def _verify_db_row(
        self,
        table: str,
        pk_col: str,
        pk_val: str,
        artifact: Dict[str, Any],
        prefix: str,
    ) -> None:
        """验证 DB 行存在且关键字段与 artifact 一致。"""
        try:
            db_row = self._db.get(table, pk_val)
        except Exception as exc:
            raise IntegrationError(
                "INTEGRATION_READ_FAILED",
                f"读取 {table}.{pk_col}={pk_val!r} 失败: {exc}",
            )

        if db_row is None:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                f"{prefix}: {pk_col}={pk_val!r} 在 SQLite {table} 表中不存在",
            )

        for key, art_val in artifact.items():
            db_val = db_row.get(key)
            if art_val is not None and db_val is not None:
                # 字符串化比较（处理类型差异如 int vs str）
                if str(art_val) != str(db_val):
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: {key} 不一致: "
                        f"artifact={art_val!r} vs DB={db_val!r}",
                    )

    def _read_json(self, path: Path, label: str) -> Any:
        """读取并解析 JSON 文件。"""
        try:
            raw = path.read_text(encoding="utf-8")
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                f"{label} JSON 解析失败: {exc}",
            )
        except Exception as exc:
            raise IntegrationError(
                "INTEGRATION_READ_FAILED",
                f"读取 {label} 失败: {exc}",
            )

    def _read_optional_json(self, path: Path) -> Any:
        """读取可选 JSON，不存在或解析失败返回 None。"""
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None
