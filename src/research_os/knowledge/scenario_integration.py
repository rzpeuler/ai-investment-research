"""M9 Scenario Integration — Phase2/3/4 Structured Research → GraphChange Candidate.

M9-R2: Run Eligibility + Full Canonical Integrity Finalization.

职责:
  scenario run artifacts → 定位结构化 ID → SQLite 权威重载 → CandidatePipeline

M9 是 Research→Candidate 单向集成。不实现 Graph→Research。
不修改 M3 source whitelist / Schema / migration。

R2 变更:
  - 真正的 Schema→Pydantic→model_dump→Schema canonical round-trip
  - SQLite load 同样 Schema round-trip（不再仅 Pydantic）
  - Phase3/4 DB eligibility authority（artifact + DB 双 gate）
  - full canonical equality for all objects（不再 field-by-field）
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


MAX_INTEGRATION_SOURCES = 20
_EQUITY_ELIGIBLE_VALIDATION_STATUSES = frozenset({"pass", "pass_with_warnings"})
_EQUITY_FAILURE_STATUSES = frozenset({"validation_failed", "failed"})
_ABNORMAL_FAILURE_STATUSES = frozenset({"failed", "validation_failed"})


# ---------------------------------------------------------------------------
# Canonical model registry（Schema name → Pydantic model）
# ---------------------------------------------------------------------------

def _build_canonical_registry() -> Tuple[Dict[str, Any], Dict[str, str]]:
    from research_os.models import (
        AbnormalMoveRun, CauseCandidate, CauseEvidenceLink,
        Claim, Evidence,
    )
    from research_os.models.equity_research import (
        EquityResearchRun, EquityResearchRequest, ResearchFinding,
    )

    _model_by_schema: Dict[str, Any] = {
        "claim": Claim,
        "evidence": Evidence,
        "research_finding": ResearchFinding,
        "abnormal_move_run": AbnormalMoveRun,
        "cause_candidate": CauseCandidate,
        "cause_evidence_link": CauseEvidenceLink,
        "equity_research_run": EquityResearchRun,
        "equity_research_request": EquityResearchRequest,
    }

    _schema_by_model: Dict[str, str] = {
        "Claim": "claim",
        "Evidence": "evidence",
        "ResearchFinding": "research_finding",
        "AbnormalMoveRun": "abnormal_move_run",
        "CauseCandidate": "cause_candidate",
        "CauseEvidenceLink": "cause_evidence_link",
        "EquityResearchRun": "equity_research_run",
        "EquityResearchRequest": "equity_research_request",
    }

    return _model_by_schema, _schema_by_model


_CANONICAL_MODEL_BY_SCHEMA, _SCHEMA_BY_MODEL = _build_canonical_registry()


# ---------------------------------------------------------------------------
# IntegrationResult
# ---------------------------------------------------------------------------

@dataclass
class IntegrationResult:
    status: str = ""
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
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as exc:
        raise IntegrationError("INTEGRATION_READ_FAILED", f"读取 {label} 失败: {exc}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{label} JSON 解析失败: {exc}")


def _read_required_json(path: Path, label: str, expected_type: Type) -> Any:
    if not path.is_file():
        raise IntegrationError("INTEGRATION_ARTIFACT_MISSING", f"缺少必需 artifact: {label} ({path})")
    data = _read_json_strict(path, label)
    if not isinstance(data, expected_type):
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_INVALID",
            f"{label} 顶层类型错误: 期望 {expected_type.__name__}, 实际 {type(data).__name__}",
        )
    return data


# ---------------------------------------------------------------------------
# Canonical round-trip helpers
# ---------------------------------------------------------------------------

def _schema_pydantic_roundtrip(raw: dict, model_cls: Type, schema_name: str) -> Dict[str, Any]:
    """DB payload / artifact dict → JSON Schema → Pydantic → model_dump → JSON Schema。

    返回 canonical dict。任何一步失败抛 IntegrationError。
    """
    from research_os.validators.schema_validator import validate_instance

    # Step 1: JSON Schema validation
    errors = validate_instance(raw, schema_name)
    if errors:
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_INVALID",
            f"Schema 校验失败 ({schema_name}): {errors[:3]}",
        )

    # Step 2: Pydantic construction（语义验证）
    try:
        obj = model_cls(**raw)
    except Exception as exc:
        raise IntegrationError(
            "INTEGRATION_ARTIFACT_INVALID",
            f"Pydantic 构造失败 ({schema_name}): {exc}",
        )

    # Step 3: model_dump
    try:
        canonical = obj.model_dump()
    except Exception as exc:
        raise IntegrationError(
            "INTEGRATION_READ_FAILED",
            f"model_dump 失败 ({schema_name}): {exc}",
        )

    # Step 4: re-validate canonical output
    errors2 = validate_instance(canonical, schema_name)
    if errors2:
        raise IntegrationError(
            "INTEGRATION_READ_FAILED",
            f"canonical re-validate 失败 ({schema_name}): {errors2[:3]}",
        )

    return canonical


def _canonicalize_artifact(raw: dict, schema_name: str) -> Dict[str, Any]:
    """Artifact dict → full canonical round-trip。"""
    model_cls = _CANONICAL_MODEL_BY_SCHEMA.get(schema_name)
    if model_cls is None:
        raise IntegrationError("INTEGRATION_READ_FAILED", f"未知 schema: {schema_name}")
    return _schema_pydantic_roundtrip(raw, model_cls, schema_name)


def _canonicalize_db(raw: dict, model_name: str) -> Dict[str, Any]:
    """DB payload dict → full canonical round-trip。"""
    schema_name = _SCHEMA_BY_MODEL.get(model_name)
    if schema_name is None:
        raise IntegrationError("INTEGRATION_READ_FAILED", f"未知模型: {model_name}")
    model_cls = _CANONICAL_MODEL_BY_SCHEMA.get(schema_name)
    if model_cls is None:
        raise IntegrationError("INTEGRATION_READ_FAILED", f"registry 不一致: {schema_name}")
    return _schema_pydantic_roundtrip(raw, model_cls, schema_name)


# ---------------------------------------------------------------------------
# ScenarioCandidateIntegrator
# ---------------------------------------------------------------------------

class ScenarioCandidateIntegrator:
    """M9 集成器。

    R2: eligibility = artifact validation PASS + SQLite authoritative run validation PASS。
        所有 canonical objects: Schema → Pydantic → model_dump → Schema。
    """

    _SCENARIO_CANONICAL = {"morning_brief", "abnormal_move_analysis", "stock_research_report"}

    def __init__(
        self, db: Any, *, project_root: Optional[Path] = None,
        knowledge_dir: Optional[Path] = None, provider: Any = None,
        live: bool = False, dry_run: bool = False,
    ) -> None:
        self._db = db
        self._project_root = project_root or Path.cwd()
        self._knowledge_dir = knowledge_dir or (self._project_root / "knowledge")
        self._provider = provider
        self._live = live
        self._dry_run = dry_run

    def integrate(
        self, scenario: str, run_dir: Path, *,
        selected_sources: Optional[Sequence[str]] = None,
        requested_model_class: str = "flash",
    ) -> IntegrationResult:
        result = IntegrationResult(scenario=scenario, run_dir=str(run_dir))
        try:
            if scenario not in self._SCENARIO_CANONICAL:
                raise IntegrationError(
                    "INTEGRATION_SCENARIO_UNSUPPORTED",
                    f"不支持场景: {scenario!r}，允许: {sorted(self._SCENARIO_CANONICAL)}",
                )
            run_dir = self._validate_run_dir(run_dir)
            resolved, warnings = self._resolve_sources(scenario, run_dir)
            result.resolved_source_refs = sorted(dict.fromkeys(resolved))
            result.warnings.extend(warnings)

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
                    f"source 数量 {len(selected)} 超过上限 {MAX_INTEGRATION_SOURCES}",
                )

            sources = [(ref.split(":", 1)[0], ref.split(":", 1)[1]) for ref in selected]
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

    def _validate_run_dir(self, run_dir: Path) -> Path:
        run_dir = run_dir.resolve()
        runs_root = (self._project_root / "reports" / "runs").resolve()
        try:
            run_dir.relative_to(runs_root)
        except ValueError:
            raise IntegrationError("INTEGRATION_RUN_DIR_INVALID", f"run_dir 必须在 {runs_root} 下，实际: {run_dir}")
        if not run_dir.is_dir():
            raise IntegrationError("INTEGRATION_RUN_DIR_INVALID", f"run_dir 不存在或不是目录: {run_dir}")
        return run_dir

    def _resolve_sources(self, scenario: str, run_dir: Path) -> Tuple[List[str], List[str]]:
        return {
            "morning_brief": self._resolve_morning_sources,
            "abnormal_move_analysis": self._resolve_abnormal_sources,
            "stock_research_report": self._resolve_equity_sources,
        }[scenario](run_dir)

    # ==================================================================
    # Morning
    # ==================================================================

    def _resolve_morning_sources(self, run_dir: Path) -> Tuple[List[str], List[str]]:
        refs: List[str] = []
        warnings: List[str] = []

        task_data = _read_required_json(run_dir / "task.json", "task.json", dict)
        val_data = _read_required_json(run_dir / "validation.json", "validation.json", dict)
        claims_data = _read_required_json(run_dir / "claims.json", "claims.json", list)
        ev_index_raw = _read_required_json(run_dir / "evidence_index.json", "evidence_index.json", dict)

        task_id = task_data.get("task_id", "")
        if not task_id or not isinstance(task_id, str):
            raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", "task.json: 缺少或非法 task_id")
        if task_data.get("scenario") != "morning_brief":
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                   f"task.json scenario 不是 morning_brief: {task_data.get('scenario')!r}")
        if run_dir.name != task_id:
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                   f"run_dir.name={run_dir.name!r} ≠ task_id={task_id!r}")

        if val_data.get("status") != "ok":
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"晨报校验状态不是 ok: {val_data.get('status')!r}")

        # canonicalize evidence index
        ev_index_canon: Dict[str, Dict[str, Any]] = {}
        for eid, ev_raw in ev_index_raw.items():
            if not isinstance(ev_raw, dict):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID",
                                       f"evidence_index.json: 值 {eid!r} 不是对象")
            ev_index_canon[eid] = _canonicalize_artifact(ev_raw, "evidence")

        db_ev_index: Dict[str, Dict[str, Any]] = {}
        for eid in ev_index_canon:
            db_ev = self._load_source("Evidence", eid)
            if db_ev is None:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"evidence_index.json 中的 Evidence {eid!r} 在 DB 中不存在")
            db_ev_index[eid] = db_ev

        for idx, raw in enumerate(claims_data):
            prefix = f"claims.json[{idx}]"
            if not isinstance(raw, dict):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 每项必须是对象")

            art_canon = _canonicalize_artifact(raw, "claim")
            claim_id = art_canon.get("claim_id", "")
            if not claim_id or not isinstance(claim_id, str):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 缺少或非法 claim_id")

            db_canon = self._load_source("Claim", claim_id)
            if db_canon is None:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: claim_id={claim_id!r} 在 DB 中不存在")

            if art_canon != db_canon:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: artifact canonical Claim 与 DB canonical Claim 不一致")

            claim_ev_ids = art_canon.get("evidence_ids") or []
            missing = set(claim_ev_ids) - set(ev_index_canon.keys())
            if missing:
                raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                       f"{prefix}: Claim.evidence_ids 不在 evidence_index 中: {sorted(missing)}")

            for eid in claim_ev_ids:
                if ev_index_canon.get(eid, {}) != db_ev_index.get(eid, {}):
                    raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                           f"{prefix}: Evidence {eid!r} artifact≠DB")

            refs.append(f"Claim:{claim_id}")

        return refs, warnings

    # ==================================================================
    # Abnormal
    # ==================================================================

    def _resolve_abnormal_sources(self, run_dir: Path) -> Tuple[List[str], List[str]]:
        refs: List[str] = []
        warnings: List[str] = []

        run_raw = _read_required_json(run_dir / "abnormal_move_run.json", "abnormal_move_run.json", dict)
        val_data = _read_required_json(run_dir / "validation.json", "validation.json", dict)
        cause_data = _read_required_json(run_dir / "cause_candidates.json", "cause_candidates.json", list)
        links_data = _read_required_json(run_dir / "cause_evidence_links.json", "cause_evidence_links.json", list)

        if val_data.get("ok") is not True:
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"异动校验未通过: ok={val_data.get('ok')!r}")

        # authoritative DB run (strict load)
        run_id = run_raw.get("run_id", "")
        if not run_id or not isinstance(run_id, str):
            raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", "abnormal_move_run.json: 缺少或非法 run_id")

        db_run_raw = self._db_get_or_fail("abnormal_move_runs", run_id)
        db_run = _canonicalize_db(db_run_raw, "AbnormalMoveRun")

        # DB eligibility: validation_status must be "passed"
        if db_run.get("validation_status") != "passed":
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"DB run.validation_status={db_run.get('validation_status')!r}，不是 passed")

        # Phase3 explicit failure status is ineligible even when validation_status == passed
        if db_run.get("status") in _ABNORMAL_FAILURE_STATUSES:
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"DB run.status={db_run.get('status')!r}，属于明确失败状态")

        # full artifact↔DB equality
        art_run = _canonicalize_artifact(run_raw, "abnormal_move_run")
        if art_run != db_run:
            raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                   "artifact canonical AbnormalMoveRun ≠ DB canonical AbnormalMoveRun")

        authoritative_run_request_id = db_run.get("request_id")
        authoritative_run_task_id = db_run.get("task_id")
        if not authoritative_run_request_id:
            raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT", "DB AbnormalMoveRun 缺少 request_id")
        if run_dir.name != authoritative_run_task_id:
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                   f"run_dir.name={run_dir.name!r} ≠ DB run.task_id={authoritative_run_task_id!r}")

        # canonicalize artifact cause candidates
        art_cause_canon: Dict[str, Dict[str, Any]] = {}
        for raw in cause_data:
            if not isinstance(raw, dict):
                continue
            cid = raw.get("cause_candidate_id")
            if cid and isinstance(cid, str):
                art_cause_canon[cid] = _canonicalize_artifact(raw, "cause_candidate")

        seen_evidence: Dict[str, bool] = {}

        for idx, raw in enumerate(links_data):
            prefix = f"cause_evidence_links.json[{idx}]"
            if not isinstance(raw, dict):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 每项必须是对象")

            link_id = raw.get("link_id")
            cause_candidate_id = raw.get("cause_candidate_id")
            evidence_id = raw.get("evidence_id")
            if not link_id or not isinstance(link_id, str):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 缺少或非法 link_id")
            if not cause_candidate_id or not isinstance(cause_candidate_id, str):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 缺少或非法 cause_candidate_id")
            if not evidence_id or not isinstance(evidence_id, str):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 缺少或非法 evidence_id")

            # --- authoritative DB link（full canonical）---
            db_link_raw = self._db_get_or_fail("cause_evidence_links", link_id)
            db_link = _canonicalize_db(db_link_raw, "CauseEvidenceLink")
            art_link = _canonicalize_artifact(raw, "cause_evidence_link")
            if art_link != db_link:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: artifact canonical CauseEvidenceLink ≠ DB canonical")

            # --- authoritative DB cause candidate（full canonical）---
            db_cause_raw = self._db_get_or_fail("cause_candidates", cause_candidate_id)
            db_cause = _canonicalize_db(db_cause_raw, "CauseCandidate")
            if db_cause.get("request_id") != authoritative_run_request_id:
                raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                       f"{prefix}: DB CauseCandidate.request_id="
                                       f"{db_cause.get('request_id')!r} ≠ {authoritative_run_request_id!r}")

            if cause_candidate_id not in art_cause_canon:
                raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                       f"{prefix}: cause_candidate_id={cause_candidate_id!r} 不在 cause_candidates.json 中")

            if art_cause_canon[cause_candidate_id] != db_cause:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: artifact canonical CauseCandidate ≠ DB canonical")

            # --- verify chain: link evidence_id → authoritative Evidence ---
            db_ev = self._load_source("Evidence", evidence_id)
            if db_ev is None:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: evidence_id={evidence_id!r} 在 DB 中不存在")

            if evidence_id not in seen_evidence:
                seen_evidence[evidence_id] = True
                refs.append(f"Evidence:{evidence_id}")

        return refs, warnings

    # ==================================================================
    # Equity
    # ==================================================================

    def _resolve_equity_sources(self, run_dir: Path) -> Tuple[List[str], List[str]]:
        refs: List[str] = []
        warnings: List[str] = []

        run_raw = _read_required_json(run_dir / "equity_research_run.json", "equity_research_run.json", dict)
        req_raw = _read_required_json(run_dir / "equity_research_request.json", "equity_research_request.json", dict)
        findings_data = _read_required_json(run_dir / "research_findings.json", "research_findings.json", list)
        val_data = _read_required_json(run_dir / "validation.json", "validation.json", dict)

        if val_data.get("status") not in _EQUITY_ELIGIBLE_VALIDATION_STATUSES:
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"校验状态不可集成: {val_data.get('status')!r}")

        # authoritative DB run（full canonical）
        run_id = run_raw.get("run_id", "")
        if not run_id or not isinstance(run_id, str):
            raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", "equity_research_run.json: 缺少或非法 run_id")

        db_run_raw = self._db_get_or_fail("equity_research_runs", run_id)
        db_run = _canonicalize_db(db_run_raw, "EquityResearchRun")

        # DB eligibility: validation_status + status
        db_val_status = db_run.get("validation_status", "")
        if db_val_status not in _EQUITY_ELIGIBLE_VALIDATION_STATUSES:
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"DB run.validation_status={db_val_status!r}，不可集成")
        if db_run.get("status") in _EQUITY_FAILURE_STATUSES:
            raise IntegrationError("INTEGRATION_RUN_NOT_ELIGIBLE",
                                   f"DB run.status={db_run.get('status')!r}，不可集成")

        # full artifact↔DB equality
        art_run = _canonicalize_artifact(run_raw, "equity_research_run")
        if art_run != db_run:
            raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                   "artifact canonical EquityResearchRun ≠ DB canonical")

        authoritative_run_request_id = db_run.get("request_id")
        authoritative_run_task_id = db_run.get("task_id")
        if not authoritative_run_request_id:
            raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT", "DB run 缺少 request_id")
        if run_dir.name != authoritative_run_task_id:
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                   f"run_dir.name={run_dir.name!r} ≠ DB run.task_id={authoritative_run_task_id!r}")

        # authoritative DB request（full canonical）
        req_id = req_raw.get("request_id", "")
        if not req_id or not isinstance(req_id, str):
            raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", "equity_research_request.json: 缺少或非法 request_id")

        db_req_raw = self._db_get_or_fail("equity_research_requests", req_id)
        db_req = _canonicalize_db(db_req_raw, "EquityResearchRequest")
        if db_req.get("request_id") != authoritative_run_request_id:
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                   f"DB request.request_id={db_req.get('request_id')!r} ≠ {authoritative_run_request_id!r}")

        art_req = _canonicalize_artifact(req_raw, "equity_research_request")
        if art_req != db_req:
            raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                   "artifact canonical EquityResearchRequest ≠ DB canonical")

        for idx, raw in enumerate(findings_data):
            prefix = f"research_findings.json[{idx}]"
            if not isinstance(raw, dict):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 每项必须是对象")

            art_canon = _canonicalize_artifact(raw, "research_finding")
            finding_id = art_canon.get("finding_id", "")
            if not finding_id or not isinstance(finding_id, str):
                raise IntegrationError("INTEGRATION_ARTIFACT_INVALID", f"{prefix}: 缺少或非法 finding_id")

            db_canon = self._load_source("ResearchFinding", finding_id)
            if db_canon is None:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: finding_id={finding_id!r} 在 DB 中不存在")
            if art_canon != db_canon:
                raise IntegrationError("INTEGRATION_ARTIFACT_INTEGRITY_CONFLICT",
                                       f"{prefix}: artifact canonical Finding ≠ DB canonical")
            if db_canon.get("request_id") != authoritative_run_request_id:
                raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH",
                                       f"{prefix}: DB finding.request_id={db_canon.get('request_id')!r} "
                                       f"≠ {authoritative_run_request_id!r}")

            refs.append(f"ResearchFinding:{finding_id}")

        return refs, warnings

    # ==================================================================
    # Utilities
    # ==================================================================

    def _db_get_or_fail(self, table: str, pk_value: str) -> Dict[str, Any]:
        """从 DB 加载 raw payload，不存在则 fail。"""
        raw = self._db.get(table, pk_value)
        if raw is None:
            raise IntegrationError("INTEGRATION_SOURCE_RUN_MISMATCH", f"DB {table} 中不存在 {pk_value!r}")
        return raw

    def _run_pipeline(self, sources: List[Tuple[str, str]], requested_model_class: str = "flash") -> Dict[str, Any]:
        from research_os.knowledge.candidate_pipeline import CandidatePipeline
        pipeline = CandidatePipeline(db=self._db, provider=self._provider,
                                     live=self._live, dry_run=self._dry_run)
        return pipeline.run(sources=sources, knowledge_dir=self._knowledge_dir,
                            requested_model_class=requested_model_class)

    def _load_source(self, source_type: str, source_id: str) -> Optional[Dict[str, Any]]:
        from research_os.knowledge.candidate_sources import SourceAdapter
        adapter = SourceAdapter(self._db)
        try:
            obj = adapter.load(source_type, source_id)
            return obj.model_dump() if hasattr(obj, "model_dump") else obj
        except Exception:
            return None
