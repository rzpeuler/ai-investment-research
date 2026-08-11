"""DataPreflightService（P7-D1）。

统一 facade：组合 RequirementContextResolver + ReadinessCheckerRegistry +
DataReadinessService + AcquisitionCapabilityRegistry + GapClassifier + AcquisitionPlanner。

- Preflight 必须在 Runner.execute 之前。
- 普通数据不足（MISSING/PARTIAL/...）不得 throw，返回正常 bundle。
- 控制面配置/一致性故障（缺 checker、capability 不完整等）→ CONTROL_PLANE_CONFIGURATION_ERROR。
- 一次 preflight 一个 checked_at；所有 DataReadiness 共用；as_of = Task.as_of。
- dry-run：零 DB 写 / 零文件写 / 零网络 / 零 LLM；仅内存运行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.checkers import (
    EmptyReadView,
    ReadinessCheckerRegistry,
    SqliteReadView,
)
from research_os.data_layer.context import RequirementContextResolver
from research_os.data_layer.gaps import GapClassifier
from research_os.data_layer.planning import AcquisitionPlanner
from research_os.data_layer.readiness import DataReadinessService
from research_os.models import (
    AcquisitionPlan,
    DataGap,
    DataReadiness,
    ScenarioDataRequirement,
)
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry
from research_os.utils.time import now_iso


@dataclass
class DataPreflightBundle:
    """内部聚合（非公共 Schema，不新增 DB authority）。"""

    requirements: List[ScenarioDataRequirement] = field(default_factory=list)
    contexts: List[Any] = field(default_factory=list)
    readiness: List[DataReadiness] = field(default_factory=list)
    gaps: List[DataGap] = field(default_factory=list)
    acquisition_plan: Optional[AcquisitionPlan] = None
    checked_at: str = ""


class DataPreflightService:
    """统一数据预检控制面。"""

    def __init__(
        self,
        requirement_registry: ScenarioDataRequirementRegistry,
        capability_registry: AcquisitionCapabilityRegistry,
        checker_registry: Optional[ReadinessCheckerRegistry] = None,
    ):
        self._requirements = requirement_registry
        self._capabilities = capability_registry
        self._checkers = checker_registry or ReadinessCheckerRegistry()
        self._resolver = RequirementContextResolver()
        self._readiness = DataReadinessService(self._checkers)
        self._gaps = GapClassifier(capability_registry)
        self._planner = AcquisitionPlanner()

    # ---------- 只读访问视图 ----------

    def _build_view(
        self,
        project_root: Path,
        db: Optional[Any],
        runs_root: Optional[Path],
        graph_repo: Optional[Any] = None,
        dry_run: bool = False,
    ) -> Any:
        """dry-run：DB 存在用 open_read_only，否则空 read view（不创建 DB）。"""
        view = EmptyReadView()
        if db is not None:
            view = SqliteReadView(db)
        elif not dry_run:
            db_path = project_root / "data" / "sqlite" / "research.db"
            if db_path.is_file():
                from research_os.storage import Database
                view = SqliteReadView(Database.open_read_only(db_path))
            else:
                view = EmptyReadView()
        # 附加只读服务引用
        if graph_repo is None and db is not None:
            from research_os.knowledge.repository import GraphRepository
            try:
                graph_repo = GraphRepository(db)
            except Exception:  # noqa: BLE001
                graph_repo = None
        view.graph_repo = graph_repo  # type: ignore[attr-defined]
        view.runs_root = runs_root  # type: ignore[attr-defined]
        return view

    # ---------- 主入口 ----------

    def run(
        self,
        scenario: str,
        task_id: str,
        task_as_of: str,
        normalized_request: Dict[str, Any],
        project_root: Path,
        db: Optional[Any] = None,
        runs_root: Optional[Path] = None,
        graph_repo: Optional[Any] = None,
        dry_run: bool = False,
        checked_at: Optional[str] = None,
    ) -> DataPreflightBundle:
        # 缺 checker / capability 不完整 → CONTROL_PLANE_CONFIGURATION_ERROR（fail closed）
        required_types = {r.data_type for r in self._requirements.for_scenario(scenario)}
        for dtype in sorted(required_types):
            if not self._checkers.has(dtype):
                raise ValueError(
                    f"CONTROL_PLANE_CONFIGURATION_ERROR: data_type {dtype!r} 无 checker")
            if not self._capabilities.has(dtype):
                raise ValueError(
                    f"CONTROL_PLANE_CONFIGURATION_ERROR: capability {dtype!r} 缺失")

        checked_at_value = checked_at or now_iso()
        view = self._build_view(project_root, db, runs_root, graph_repo, dry_run)

        requirements = self._requirements.for_scenario(scenario)
        bundle = DataPreflightBundle(checked_at=checked_at_value)
        gap_by_req: Dict[str, DataGap] = {}
        requirement_order: List[str] = []
        for requirement in requirements:
            ctx = self._resolver.resolve(
                requirement, scenario, task_id, normalized_request, task_as_of,
            )
            readiness = self._readiness.evaluate(requirement, ctx, view, checked_at_value)
            gap = self._gaps.classify(requirement, readiness)
            bundle.requirements.append(requirement)
            bundle.contexts.append(ctx)
            bundle.readiness.append(readiness)
            bundle.gaps.append(gap)
            gap_by_req[gap.requirement_id] = gap
            requirement_order.append(requirement.requirement_id)
        bundle.acquisition_plan = self._planner.plan(
            task_id=task_id,
            scenario=scenario,
            as_of=task_as_of,
            gaps=list(gap_by_req.values()),
            requirement_order=requirement_order,
        )
        return bundle

    # ---------- artifact 持久化（非 dry-run） ----------

    @staticmethod
    def persist_artifacts(run_dir: Path, bundle: DataPreflightBundle) -> None:
        """原子写 data_readiness_before.jsonl / data_gaps.jsonl / acquisition_plan.json。"""
        from research_os.validators.schema_validator import validate_instance

        readiness_path = run_dir / "data_readiness_before.jsonl"
        gaps_path = run_dir / "data_gaps.jsonl"
        plan_path = run_dir / "acquisition_plan.json"

        readiness_lines: List[str] = []
        for r in bundle.readiness:
            payload = r.model_dump()
            errs = validate_instance(payload, "data_readiness")
            if errs:
                raise ValueError(f"DataReadiness 未通过 Schema 校验: {errs}")
            readiness_lines.append(json_dumps(payload))
        _atomic_write(readiness_path, "\n".join(readiness_lines) + "\n")

        gaps_lines: List[str] = []
        for g in bundle.gaps:
            payload = g.model_dump()
            errs = validate_instance(payload, "data_gap")
            if errs:
                raise ValueError(f"DataGap 未通过 Schema 校验: {errs}")
            gaps_lines.append(json_dumps(payload))
        _atomic_write(gaps_path, "\n".join(gaps_lines) + "\n")

        plan_payload = bundle.acquisition_plan.model_dump()
        errs = validate_instance(plan_payload, "acquisition_plan")
        if errs:
            raise ValueError(f"AcquisitionPlan 未通过 Schema 校验: {errs}")
        _atomic_write(plan_path, json_dumps(plan_payload))


def _atomic_write(path: Path, text: str) -> None:
    """原子写：写 .tmp 后 os.replace（复用 RunDirectory 原子写原则，不重构 RunDirectory）。"""
    import os
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def json_dumps(obj: Any, *, ensure_ascii: bool = False) -> str:
    import json
    return json.dumps(obj, ensure_ascii=ensure_ascii)
