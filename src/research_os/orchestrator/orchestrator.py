"""Orchestrator（统一研究计划器与执行控制面）。

负责：
- 任务创建（Task 必须通过 Schema 校验）
- 三个核心场景注册与非空 Plan
- 统一场景执行、预算、模型/降级策略和结果
- 运行目录创建（指南 50 节，全部原子写入）
- SQLite 持久化（幂等 upsert）
- 相同 task_id 幂等（补跑机制基础，指南 56 节）
- 失败状态持久化：task.json/validation.json/数据库 同步 failed + finished_at
- 结构化错误记录（JSONL，含异常类型/时间/组件，敏感字段过滤）

具体研究算法仍由既有 Pipeline 承担，Orchestrator 只做控制面治理。
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from research_os.models import Task
from research_os.orchestrator.run_directory import RunDirectory
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.storage import Database
from research_os.utils.id import new_uuid
from research_os.utils.logging import ErrorLog
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance


class Plan(BaseModel):
    """研究计划（运行记录，非核心对象 Schema）。"""

    plan_id: str
    task_id: str
    scenario: str
    version: str = "1.0.0"
    depth: str
    created_at: str
    requested_at: str
    as_of: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    data_requirements: List[str] = Field(default_factory=list)
    runtime_budget: Dict[str, Any] = Field(default_factory=dict)
    model_policy: str = "flash_default"
    fallback_policy: List[str] = Field(default_factory=list)
    output_paths: List[str] = Field(default_factory=list)
    # 兼容旧产物字段。
    retrieval_budget: Dict[str, Any] = Field(default_factory=dict)
    model_route: str = "flash_default"
    notes: List[str] = Field(default_factory=list)


@dataclass
class RunOutcome:
    """任务执行结果。status: created / idempotent_skipped / failed"""

    status: str
    task: Optional[Task] = None
    plan: Optional[Plan] = None
    run_dir: Optional[Path] = None
    message: str = ""
    errors: List[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.errors is None:
            self.errors = []


class Orchestrator:
    """统一控制面；具体业务由注册的 ScenarioRunner 执行。"""

    def __init__(self, project_root: str | Path, db: Optional[Database] = None,
                 registry: Optional[ScenarioRegistry] = None):
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "reports" / "runs"
        self._db = db
        if self._db is not None:
            self._db.initialize()
        self.registry = registry or ScenarioRegistry()
        if registry is None:
            from research_os.orchestrator.runners import DEFAULT_RUNNER_TYPES

            for runner_type in DEFAULT_RUNNER_TYPES:
                self.registry.register(runner_type())

    @property
    def db(self) -> Database:
        """仅真实执行时初始化数据库，保证 dry-run 不因控制面产生副作用。"""
        if self._db is None:
            self._db = Database(self.project_root / "data" / "sqlite" / "research.db")
            self._db.initialize()
        return self._db

    # ---------- 失败状态持久化 ----------

    def _mark_failed(self, task: Task, run_dir: RunDirectory, exc: BaseException) -> None:
        """将任务持久化为 failed 状态（尽力而为，任何二次失败都要记录）。"""
        task.status = "failed"
        task.finished_at = now_iso()
        error_log = ErrorLog(run_dir.errors_log, task_id=task.task_id)

        # 1. task.json 原子更新为 failed（文件状态优先，失败也继续）
        try:
            run_dir.write_task(task.model_dump())
        except Exception as inner:  # noqa: BLE001
            error_log.record_exception(
                "orchestrator", "二次失败：无法写入 task.json failed 状态", inner,
                module="task_state", retryable=False,
            )

        # 2. validation.json 标明任务未完成
        try:
            run_dir.write_validation({
                "status": "failed", "task_id": task.task_id,
                "checks": [], "message": "任务执行失败，未完成，禁止视为成功产物",
            })
        except Exception as inner:  # noqa: BLE001
            error_log.record_exception(
                "orchestrator", "二次失败：无法写入 validation.json", inner,
                module="task_state", retryable=False,
            )

        # 3. 数据库同步为 failed（失败则记录二次失败，但文件状态已尽力保留）
        try:
            self.db.upsert(task)
        except Exception as inner:  # noqa: BLE001
            error_log.record_exception(
                "orchestrator", "二次失败：数据库无法同步 failed 状态", inner,
                module="task_state", retryable=False,
            )

        # 4. 主错误记录（结构化，含异常类型与堆栈）
        error_log.record_exception(
            "orchestrator", f"任务执行失败: {exc}", exc,
            task_id=task.task_id, retryable=False, attempt=1,
        )

    # ---------- 任务创建 ----------

    def create_task(
        self,
        scenario: str = "morning_brief",
        entities: Optional[List[str]] = None,
        depth: str = "standard",
        as_of: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> Task:
        """创建 Task（确定性构造 + Schema 校验，失败必须显式返回）。"""
        now = now_iso()
        task = Task(
            task_id=task_id or new_uuid(),
            scenario=scenario,
            status="planned",
            requested_at=now,
            as_of=as_of or now,
            timezone="Asia/Shanghai",
            entities=entities or [],
            depth=depth,  # type: ignore[arg-type]
        )
        errors = validate_instance(task.model_dump(), "task")
        if errors:
            raise ValueError(f"Task 未通过 Schema 校验: {errors}")
        return task

    # ---------- 计划生成 ----------

    def create_plan(self, task: Task, request: Optional[Dict[str, Any]] = None) -> Plan:
        """由注册 Runner 生成含真实步骤、数据需求与策略的 Plan。"""
        runner = self.registry.get(task.scenario)
        budgets = {"fast": 480, "standard": 1200, "deep": 1800}
        runtime = budgets.get(task.depth, 1200)
        spec = runner.build_plan(request or {}, {
            "project_root": self.project_root, "task": task,
        })
        raw_steps = spec.get("steps") or []
        steps = [s if isinstance(s, dict) else {"step": s, "status": "planned"}
                 for s in raw_steps]
        data_requirements = list(spec.get("data_requirements") or [])
        if not steps or not data_requirements:
            raise ValueError(f"场景 {task.scenario} 返回空 Plan")
        return Plan(
            plan_id=new_uuid(),
            task_id=task.task_id,
            scenario=task.scenario,
            version=runner.version,
            depth=task.depth,
            created_at=now_iso(),
            requested_at=task.requested_at,
            as_of=task.as_of,
            steps=steps,
            data_requirements=data_requirements,
            runtime_budget={"depth": task.depth, "max_runtime_seconds": runtime},
            model_policy=spec.get("model_policy", "flash_default"),
            fallback_policy=list(spec.get("fallback_policy") or []),
            output_paths=list(spec.get("output_paths") or []),
            retrieval_budget={"max_runtime_seconds": runtime},
            model_route=spec.get("model_policy", "flash_default"),
            notes=["由 ScenarioRunner 注册表生成"],
        )

    def execute(self, scenario: str, request: Dict[str, Any]) -> ScenarioExecutionResult:
        """统一执行入口；未注册场景、请求错误和 Runner 异常均转为结构化失败。"""
        started = perf_counter()
        task_id = str(request.get("task_id") or new_uuid())
        task: Optional[Task] = None
        plan: Optional[Plan] = None
        control_run_dir: Optional[RunDirectory] = None
        try:
            runner = self.registry.get(scenario)
            normalized = runner.validate_request(dict(request))
            task = self.create_task(
                scenario=scenario,
                entities=list(normalized.get("entities") or []),
                depth=normalized.get("depth", "standard"),
                as_of=normalized.get("as_of"),
                task_id=task_id,
            )
            plan = self.create_plan(task, normalized)
            context: Dict[str, Any] = {
                "project_root": self.project_root, "task": task, "plan": plan,
            }
            if not normalized.get("dry_run"):
                context["db"] = self.db
                control_run_dir = RunDirectory(self.runs_root, task.task_id)
                control_run_dir.create()
                task.status = "running"
                control_run_dir.write_task(task.model_dump())
                control_run_dir.write_plan(plan.model_dump())
                self.db.upsert(task)
                context["run_dir"] = control_run_dir
        except ValueError as exc:
            result = ScenarioExecutionResult(
                status="failed", exit_code=2, task_id=task_id,
                validation_status="not_run", message=str(exc),
            )
        else:
            try:
                result = runner.execute(normalized, context)
                result.runtime_seconds = round(perf_counter() - started, 6)
                if control_run_dir is not None and task is not None and plan is not None:
                    self._finalize_execution(task, plan, result, control_run_dir)
            except Exception as exc:  # noqa: BLE001
                run_dir = control_run_dir or RunDirectory(self.runs_root, task_id)
                if task is not None and run_dir.exists():
                    self._mark_failed(task, run_dir, exc)
                result = ScenarioExecutionResult(
                    status="failed", exit_code=5, task_id=task_id,
                    run_dir=str(run_dir.root) if run_dir.exists() else None,
                    validation_status="fail", message=f"场景执行失败: {type(exc).__name__}: {exc}",
                )
        if not result.runtime_seconds:
            result.runtime_seconds = round(perf_counter() - started, 6)
        if control_run_dir is not None and not (control_run_dir.root / "scenario_execution_result.json").exists():
            control_run_dir.write_json("scenario_execution_result.json", result.model_dump())
        return result

    def _finalize_execution(
        self, task: Task, plan: Plan, result: ScenarioExecutionResult,
        run_dir: RunDirectory,
    ) -> None:
        """校验并持久化统一控制面血缘；任何断链都使任务失败。"""
        if result.task_id != task.task_id:
            raise ValueError(
                f"Runner Task ID 断链: expected={task.task_id}, actual={result.task_id}")
        expected = run_dir.root.resolve()
        if result.run_dir is not None and Path(result.run_dir).resolve() != expected:
            raise ValueError(
                f"Runner 运行目录断链: expected={expected}, actual={Path(result.run_dir).resolve()}")
        result.run_dir = str(run_dir.root)
        self._validate_business_lineage(run_dir, task.task_id)
        task.status = "failed" if result.exit_code != 0 or result.status == "failed" else "completed"
        task.finished_at = now_iso()
        run_dir.write_plan(plan.model_dump())
        run_dir.write_task(task.model_dump())
        run_dir.write_json("scenario_execution_result.json", result.model_dump())
        self.db.upsert(task)

    @staticmethod
    def _validate_business_lineage(run_dir: RunDirectory, task_id: str) -> None:
        """已生成的场景 Request/Run 必须沿用控制面 Task ID。"""
        for filename in (
            "abnormal_move_request.json", "abnormal_move_run.json",
            "equity_research_request.json", "equity_research_run.json",
            "evening_brief_request.json", "evening_brief_run.json",
            "daily_review_request.json", "daily_review_run.json",
            "stock_review_request.json", "stock_review_run.json",
            "industry_research_request.json", "industry_research_run.json",
            "theme_discovery_request.json", "theme_discovery_run.json",
            "earnings_expectation_request.json", "earnings_expectation_run.json",
            "first_coverage_request.json", "first_coverage_run.json",
        ):
            path = run_dir.root / filename
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            actual = payload.get("task_id")
            if actual != task_id:
                raise ValueError(
                    f"{filename} Task ID 断链: expected={task_id}, actual={actual}")

    def close(self) -> None:
        """关闭由控制面持有的数据库连接。"""
        if self._db is not None:
            self._db.close()
            self._db = None

    # ---------- 执行 ----------

    def run(
        self,
        scenario: str = "morning_brief",
        entities: Optional[List[str]] = None,
        depth: str = "standard",
        task_id: Optional[str] = None,
        as_of: Optional[str] = None,
        force: bool = False,
    ) -> RunOutcome:
        """兼容旧的计划任务入口（不执行研究 Pipeline）。

        幂等规则：
        - 运行目录存在且状态 completed -> 幂等跳过（不重复生成）；
        - 状态 failed -> 返回失败（不覆盖失败证据），--force 可重跑；
        - force=True 时重建。
        """
        task = self.create_task(scenario=scenario, entities=entities, depth=depth,
                                as_of=as_of, task_id=task_id)
        run_dir = RunDirectory(self.runs_root, task.task_id)

        if run_dir.exists() and not force:
            existing = run_dir.read_task()
            if existing and existing.get("status") == "completed":
                return RunOutcome(
                    status="idempotent_skipped",
                    task=task,
                    run_dir=run_dir.root,
                    message=f"任务 {task.task_id} 已存在且已完成，幂等跳过（--force 可重建）",
                )
            if existing and existing.get("status") == "failed":
                return RunOutcome(
                    status="failed",
                    task=task,
                    run_dir=run_dir.root,
                    message=f"任务 {task.task_id} 此前已失败（失败状态已持久化），--force 可重跑",
                    errors=["此前执行失败"],
                )

        plan = self.create_plan(task, {"entities": entities or [], "depth": depth, "as_of": as_of})

        try:
            # 1. 创建运行目录
            run_dir.create()
            # 2. 写入 task / plan（先过 Schema 再落盘）
            task_errors = validate_instance(task.model_dump(), "task")
            if task_errors:
                raise ValueError(f"Task 未通过 Schema 校验: {task_errors}")
            run_dir.write_task(task.model_dump())
            run_dir.write_plan(plan.model_dump())
            # 3. 运行记录
            run_dir.append_retrieval_log(
                {"ts": now_iso(), "event": "task_created",
                 "task_id": task.task_id, "scenario": task.scenario}
            )
            run_dir.write_validation(
                {"status": "pending", "task_id": task.task_id,
                 "checks": [], "message": "控制面计划任务：未执行研究 Pipeline"}
            )
            # 4. SQLite 持久化（幂等 upsert）
            task.status = "completed"
            task.finished_at = now_iso()
            self.db.upsert(task)
            # 5. 回写 task.json 最终状态
            run_dir.write_task(task.model_dump())
            return RunOutcome(
                status="created",
                task=task,
                plan=plan,
                run_dir=run_dir.root,
                message=f"控制面计划任务完成：{task.task_id}",
            )
        except Exception as exc:  # noqa: BLE001 —— 失败必须显式记录
            self._mark_failed(task, run_dir, exc)
            return RunOutcome(
                status="failed",
                task=task,
                run_dir=run_dir.root,
                message=f"任务执行失败: {exc}",
                errors=[str(exc)],
            )
