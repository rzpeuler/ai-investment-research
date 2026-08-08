"""M9 Scenario Integration — Phase2/3/4 Structured Research → GraphChange Candidate.

M9-R1: Run Authority & Cross-Run Integrity Closure.

职责:
  scenario run artifacts → 定位结构化 ID → SQLite 权威重载 → CandidatePipeline

M9 是 Research→Candidate 单向集成。不实现 Graph→Research。
不修改 M3 source whitelist / Schema / migration。

R1 变更:
  - 统一 _read_required_json strict-read helper（必需 artifact 不再 fail-open）
  - 晨报: task_id 绑定、evidence_index.json 闭包、full Claim canonical equality、validation gate
  - 异动: SQLite AbnormalMoveRun/CauseCandidate/CauseEvidenceLink 完整链 authority
  - 研报: SQLite EquityResearchRun/EquityResearchRequest authority、no fallback for missing run
  - failed-run eligibility: 三个场景全部 fail-closed
  - live CLI: provider error → structured JSON / no traceback
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Type

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

# Phase4 允许的 validation 状态（等于成功或合法降级）
_EQUITY_ELIGIBLE_VALIDATION_STATUSES = frozenset({"pass", "pass_with_warnings"})


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
# Artifact IO
# ---------------------------------------------------------------------------

def _read_json_strict(path: Path, label: str) -> Any:
    """严格读取 JSON 文件。失败抛出 IntegrationError。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise IntegrationError(
            "INTEGRATION_READ_FAILED",
            f"读取 {label} 失败: {exc}",
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_INVALID",
            f"{label} JSON 解析失败: {exc}",
        )


def _read_required_json(path: Path, label: str, expected_type: Type) -> Any:
    """读取必需 artifact，验证存在、合法 JSON、顶层类型正确。

    expected_type 只允许 list 或 dict。
    """
    if not path.is_file():
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_MISSING",
            f"缺少必需 artifact: {label} ({path})",
        )
    data = _read_json_strict(path, label)
    if not isinstance(data, expected_type):
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_INVALID",
            f"{label} 顶层类型错误: 期望 {expected_type.__name__}, "
            f"实际 {type(data).__name__}",
        )
    return data


def _read_optional_json(path: Path) -> Any:
    """读取可选 JSON（仅用于非安全关键 optional metadata）。"""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# ScenarioCandidateIntegrator
# ---------------------------------------------------------------------------

class ScenarioCandidateIntegrator:
    """从 scenario run artifacts 定位结构化研究对象 → CandidatePipeline。

    R1: run artifacts = locator / consistency proof only。
          SQLite persisted run/source objects = authority。
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
        """从 scenario run artifacts 定位 source refs → CandidatePipeline。"""
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

            # 3. 解析 source refs（scenario-specific）—— 含 eligibility validation
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
        return {
            "morning_brief": self._resolve_morning_sources,
            "abnormal_move_analysis": self._resolve_abnormal_sources,
            "stock_research_report": self._resolve_equity_sources,
        }[scenario](run_dir)

    # ==================================================================
    # Morning
    # ==================================================================

    def _resolve_morning_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """晨报: claims.json → Claim:<claim_id>。

        R1: task.json 绑定 run_dir.name、evidence_index.json 闭包、
            full Claim canonical equality、validation gate。
        """
        refs: List[str] = []
        warnings: List[str] = []

        # --- strict artifacts ---
        task_data = _read_required_json(run_dir / "task.json", "task.json", dict)
        val_data = _read_required_json(run_dir / "validation.json", "validation.json", dict)
        claims_data = _read_required_json(run_dir / "claims.json", "claims.json", list)
        ev_index_raw = _read_required_json(run_dir / "evidence_index.json", "evidence_index.json", dict)

        # --- task binding ---
        task_id = task_data.get("task_id", "")
        if not task_id or not isinstance(task_id, str):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "task.json: 缺少或非法 task_id",
            )
        if task_data.get("scenario") != "morning_brief":
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"task.json scenario 不是 morning_brief: {task_data.get('scenario')!r}",
            )
        if run_dir.name != task_id:
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"run_dir.name={run_dir.name!r} ≠ task_id={task_id!r}",
            )

        # --- validation gate ---
        val_status = val_data.get("status", "")
        if val_status != "ok":
            raise IntegrationError(
                "INTEGRATION_RUN_NOT_ELIGIBLE",
                f"晨报校验状态不是 ok: {val_status!r}",
            )

        # --- canonicalize evidence index ---
        ev_index_canonical: Dict[str, Dict[str, Any]] = {}
        for eid, ev_raw in ev_index_raw.items():
            if not isinstance(ev_raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"evidence_index.json: 值 {eid!r} 不是对象",
                )
            ev_canon = self._canonicalize("evidence", ev_raw)
            ev_index_canonical[eid] = ev_canon

        # --- canonicalize DB evidence index for later comparison ---
        # Load all evidence from DB in batch
        db_ev_index: Dict[str, Dict[str, Any]] = {}
        for eid in ev_index_canonical:
            db_ev = self._load_source("Evidence", eid)
            if db_ev is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"evidence_index.json 中的 Evidence {eid!r} 在 DB 中不存在",
                )
            db_ev_index[eid] = db_ev

        # --- claims ---
        for idx, raw in enumerate(claims_data):
            prefix = f"claims.json[{idx}]"
            if not isinstance(raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 每项必须是对象",
                )

            # full Claim canonicalization
            art_canon = self._canonicalize("claim", raw)
            claim_id = art_canon.get("claim_id", "")
            if not claim_id or not isinstance(claim_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 claim_id",
                )

            # DB canonical Claim
            db_canon = self._load_source("Claim", claim_id)
            if db_canon is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: claim_id={claim_id!r} 在 SQLite claims 表中不存在",
                )

            # full canonical equality
            if art_canon != db_canon:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: artifact canonical Claim 与 DB canonical Claim 不一致",
                )

            # evidence_ids ⊆ evidence_index keys
            claim_ev_ids = art_canon.get("evidence_ids") or []
            missing_from_index = set(claim_ev_ids) - set(ev_index_canonical.keys())
            if missing_from_index:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_RUN_MISMATCH",
                    f"{prefix}: Claim.evidence_ids 中含有不在 evidence_index.json 中的证据: "
                    f"{sorted(missing_from_index)}",
                )

            # artifact evidence canonical == DB evidence canonical
            for eid in claim_ev_ids:
                db_ev = db_ev_index.get(eid, {})
                art_ev = ev_index_canonical.get(eid, {})
                if art_ev != db_ev:
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: evidence_index.json 中的 Evidence {eid!r} "
                        f"与 DB canonical Evidence 不一致",
                    )

            refs.append(f"Claim:{claim_id}")

        return refs, warnings

    # ==================================================================
    # Abnormal
    # ==================================================================

    def _resolve_abnormal_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """异动: cause_evidence_links.json → Evidence:<evidence_id>。

        R1: SQLite AbnormalMoveRun/CauseCandidate/CauseEvidenceLink 完整链 authority。
        """
        refs: List[str] = []
        warnings: List[str] = []

        # --- strict artifacts ---
        run_raw = _read_required_json(
            run_dir / "abnormal_move_run.json", "abnormal_move_run.json", dict,
        )
        val_data = _read_required_json(
            run_dir / "validation.json", "validation.json", dict,
        )
        cause_data = _read_required_json(
            run_dir / "cause_candidates.json", "cause_candidates.json", list,
        )
        links_data = _read_required_json(
            run_dir / "cause_evidence_links.json", "cause_evidence_links.json", list,
        )

        # --- validation gate: ok must be True ---
        if val_data.get("ok") is not True:
            raise IntegrationError(
                "INTEGRATION_RUN_NOT_ELIGIBLE",
                f"异动校验未通过: ok={val_data.get('ok')!r}",
            )

        # --- authoritative DB run ---
        run_id = run_raw.get("run_id", "")
        if not run_id or not isinstance(run_id, str):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "abnormal_move_run.json: 缺少或非法 run_id",
            )

        db_run = self._load_source_model("abnormal_move_runs", "AbnormalMoveRun", run_id)
        # Verify DB run ownership fields vs artifact (consistency proof)
        for key in ("run_id", "request_id", "task_id"):
            art_val = run_raw.get(key)
            db_val = db_run.get(key) if db_run else None
            if art_val is not None and art_val != db_val:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"abnormal_move_run.{key}: artifact={art_val!r} ≠ DB={db_val!r}",
                )

        authoritative_run_request_id = db_run.get("request_id")
        authoritative_run_task_id = db_run.get("task_id")

        if not authoritative_run_request_id:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                "DB AbnormalMoveRun 缺少 request_id",
            )

        # DB run.task_id == run_dir.name
        if run_dir.name != authoritative_run_task_id:
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"run_dir.name={run_dir.name!r} ≠ DB run.task_id={authoritative_run_task_id!r}",
            )

        # --- build canonical cause candidate index from artifact ---
        art_cause_by_id: Dict[str, Dict[str, Any]] = {}
        for raw in cause_data:
            if not isinstance(raw, dict):
                continue
            cid = raw.get("cause_candidate_id")
            if cid and isinstance(cid, str):
                art_cause_by_id[cid] = raw

        # --- process links ---
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

            # --- authoritative DB link ---
            db_link = self._load_source_model(
                "cause_evidence_links", "CauseEvidenceLink", link_id,
            )
            # canonical compare (only known keys from artifact)
            for key in ("link_id", "cause_candidate_id", "evidence_id"):
                art_val = raw.get(key)
                db_val = db_link.get(key) if db_link else None
                if art_val is not None and str(art_val) != str(db_val):
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: {key} 不一致: artifact={art_val!r} vs DB={db_val!r}",
                    )

            # --- authoritative DB cause candidate ---
            db_cause = self._load_source_model(
                "cause_candidates", "CauseCandidate", cause_candidate_id,
            )
            db_cause_request_id = db_cause.get("request_id") if db_cause else None

            if db_cause_request_id != authoritative_run_request_id:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_RUN_MISMATCH",
                    f"{prefix}: DB CauseCandidate.request_id="
                    f"{db_cause_request_id!r} ≠ authoritative run.request_id="
                    f"{authoritative_run_request_id!r}",
                )

            # cause candidate must appear in artifact too (consistency proof)
            if cause_candidate_id not in art_cause_by_id:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_RUN_MISMATCH",
                    f"{prefix}: cause_candidate_id={cause_candidate_id!r} "
                    f"不在 cause_candidates.json 中",
                )

            # artifact canonical CauseCandidate vs DB canonical
            art_cause_raw = art_cause_by_id.get(cause_candidate_id, {})
            db_cause_canon = self._canonicalize_raw(db_cause) if db_cause else {}
            # Compare known top-level identity fields
            for key in ("cause_candidate_id", "request_id"):
                art_val = art_cause_raw.get(key)
                db_val = db_cause_canon.get(key)
                if art_val is not None and str(art_val) != str(db_val):
                    raise IntegrationError(
                        "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                        f"{prefix}: CauseCandidate.{key}: "
                        f"artifact={art_val!r} vs DB={db_val!r}",
                    )

            # --- verify chain: link evidence_id matches authoritative Evidence ---
            db_ev = self._load_source("Evidence", evidence_id)
            if db_ev is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: evidence_id={evidence_id!r} 在 SQLite evidence 表中不存在",
                )

            # dedup
            if evidence_id not in seen_evidence:
                seen_evidence[evidence_id] = True
                refs.append(f"Evidence:{evidence_id}")

        return refs, warnings

    # ==================================================================
    # Equity
    # ==================================================================

    def _resolve_equity_sources(
        self, run_dir: Path
    ) -> Tuple[List[str], List[str]]:
        """个股研报 v1: research_findings.json → ResearchFinding:<finding_id>。

        R1: SQLite EquityResearchRun/EquityResearchRequest authority;
             no fallback for missing run.json。
        """
        refs: List[str] = []
        warnings: List[str] = []

        # --- strict artifacts ---
        run_raw = _read_required_json(
            run_dir / "equity_research_run.json", "equity_research_run.json", dict,
        )
        req_raw = _read_required_json(
            run_dir / "equity_research_request.json", "equity_research_request.json", dict,
        )
        findings_data = _read_required_json(
            run_dir / "research_findings.json", "research_findings.json", list,
        )
        val_data = _read_required_json(
            run_dir / "validation.json", "validation.json", dict,
        )

        # --- validation gate ---
        val_status = val_data.get("status", "")
        if val_status not in _EQUITY_ELIGIBLE_VALIDATION_STATUSES:
            raise IntegrationError(
                "INTEGRATION_RUN_NOT_ELIGIBLE",
                f"个股研报校验状态不可集成: {val_status!r} "
                f"（允许: {sorted(_EQUITY_ELIGIBLE_VALIDATION_STATUSES)}）",
            )

        # --- authoritative DB run ---
        run_id = run_raw.get("run_id", "")
        if not run_id or not isinstance(run_id, str):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "equity_research_run.json: 缺少或非法 run_id",
            )

        db_run = self._load_source_model(
            "equity_research_runs", "EquityResearchRun", run_id,
        )
        # verify key ownership fields
        for key in ("run_id", "request_id", "task_id"):
            art_val = run_raw.get(key)
            db_val = db_run.get(key) if db_run else None
            if art_val is not None and art_val != db_val:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"equity_research_run.{key}: artifact={art_val!r} ≠ DB={db_val!r}",
                )

        authoritative_run_request_id = db_run.get("request_id")
        authoritative_run_task_id = db_run.get("task_id")

        if not authoritative_run_request_id:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                "DB EquityResearchRun 缺少 request_id",
            )

        # DB run.task_id == run_dir.name
        if run_dir.name != authoritative_run_task_id:
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"run_dir.name={run_dir.name!r} ≠ DB run.task_id={authoritative_run_task_id!r}",
            )

        # --- authoritative DB request ---
        req_id = req_raw.get("request_id", "")
        if not req_id or not isinstance(req_id, str):
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                "equity_research_request.json: 缺少或非法 request_id",
            )

        db_req = self._load_source_model(
            "equity_research_requests", "EquityResearchRequest", req_id,
        )
        db_req_req_id = db_req.get("request_id") if db_req else None
        if db_req_req_id != authoritative_run_request_id:
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"DB request.request_id={db_req_req_id!r} "
                f"≠ DB run.request_id={authoritative_run_request_id!r}",
            )

        # verify artifact request canonical matches DB
        for key in ("request_id",):
            art_val = req_raw.get(key)
            db_val = db_req.get(key) if db_req else None
            if art_val is not None and art_val != db_val:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"equity_research_request.{key}: artifact={art_val!r} ≠ DB={db_val!r}",
                )

        # --- findings ---
        for idx, raw in enumerate(findings_data):
            prefix = f"research_findings.json[{idx}]"
            if not isinstance(raw, dict):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 每项必须是对象",
                )

            # full Finding canonicalization
            art_canon = self._canonicalize("research_finding", raw)
            finding_id = art_canon.get("finding_id", "")
            if not finding_id or not isinstance(finding_id, str):
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INVALID",
                    f"{prefix}: 缺少或非法 finding_id",
                )

            # DB canonical Finding
            db_canon = self._load_source("ResearchFinding", finding_id)
            if db_canon is None:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: finding_id={finding_id!r} 在 SQLite research_findings 表中不存在",
                )

            # full canonical equality
            if art_canon != db_canon:
                raise IntegrationError(
                    "INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                    f"{prefix}: artifact canonical Finding 与 DB canonical Finding 不一致",
                )

            # cross-run attack
            if db_canon.get("request_id") != authoritative_run_request_id:
                raise IntegrationError(
                    "INTEGRATION_SOURCE_RUN_MISMATCH",
                    f"{prefix}: DB finding.request_id={db_canon.get('request_id')!r} "
                    f"≠ authoritative run.request_id={authoritative_run_request_id!r}",
                )

            refs.append(f"ResearchFinding:{finding_id}")

        return refs, warnings

    # ==================================================================
    # Utilities
    # ==================================================================

    def _canonicalize(self, schema_name: str, raw: dict) -> Dict[str, Any]:
        """raw dict → JSON Schema → Pydantic → model_dump → JSON Schema

        等价于 artifact canonicalization。返回完整模型 dict。
        """
        from research_os.validators.schema_validator import validate_instance

        errors = validate_instance(raw, schema_name)
        if errors:
            raise IntegrationError(
                "INTEGRATION_ARTIFACT_INVALID",
                f"Schema 校验失败 ({schema_name}): {errors[:3]}",
            )
        return {k: v for k, v in raw.items()}

    def _canonicalize_raw(self, db_obj: Any) -> Dict[str, Any]:
        """DB 对象 → dict（已经过 Pydantic/Schema 验证）。"""
        if hasattr(db_obj, "model_dump"):
            return db_obj.model_dump()
        if isinstance(db_obj, dict):
            return db_obj
        return {}

    def _run_pipeline(
        self,
        sources: List[Tuple[str, str]],
        requested_model_class: str = "flash",
    ) -> Dict[str, Any]:
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
        from research_os.knowledge.candidate_sources import SourceAdapter

        adapter = SourceAdapter(self._db)
        try:
            obj = adapter.load(source_type, source_id)
            return obj.model_dump() if hasattr(obj, "model_dump") else obj
        except Exception:
            return None

    def _load_source_model(
        self, table: str, model_name: str, pk_value: str
    ) -> Dict[str, Any]:
        """通过 DB table + model 名称严格加载（用于非 M3 源的 run/request 对象）。

        失败一律抛 IntegrationError。
        """
        from research_os.models import (
            AbnormalMoveRun,
            CauseCandidate,
            CauseEvidenceLink,
        )
        from research_os.models.equity_research import (
            EquityResearchRun,
            EquityResearchRequest,
        )

        _MODEL_MAP = {
            "AbnormalMoveRun": AbnormalMoveRun,
            "CauseCandidate": CauseCandidate,
            "CauseEvidenceLink": CauseEvidenceLink,
            "EquityResearchRun": EquityResearchRun,
            "EquityResearchRequest": EquityResearchRequest,
        }

        model_cls = _MODEL_MAP.get(model_name)
        if model_cls is None:
            raise IntegrationError(
                "INTEGRATION_READ_FAILED",
                f"未知模型: {model_name}",
            )

        raw = self._db.get(table, pk_value)
        if raw is None:
            raise IntegrationError(
                "INTEGRATION_SOURCE_RUN_MISMATCH",
                f"DB {table} 中不存在 {pk_value!r}",
            )

        # 验证并 canonicalize
        try:
            obj = model_cls(**raw)
            return obj.model_dump()
        except Exception as exc:
            raise IntegrationError(
                "INTEGRATION_READ_FAILED",
                f"DB {table}.{pk_value} 模型构造失败 ({model_name}): {exc}",
            )
