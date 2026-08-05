"""Orchestrator（工程指南 7 节逻辑架构中的研究计划器与执行控制）。

Phase 0：空 Orchestrator。只负责：
- 任务创建（Task 必须通过 Schema 校验）
- 计划生成（Plan 占位）
- 运行目录创建（指南 50 节）
- SQLite 持久化（幂等 upsert）
- 相同 task_id 幂等（补跑机制基础，指南 56 节）

不执行任何模块，不采集任何数据。Phase 1+ 在此扩展。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from research_os.models import Task
from research_os.orchestrator.run_directory import RunDirectory
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
    depth: str
    created_at: str
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    data_requirements: List[str] = Field(default_factory=list)
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
    """空任务编排器。"""

    def __init__(self, project_root: str | Path, db: Optional[Database] = None):
        self.project_root = Path(project_root)
        self.runs_root = self.project_root / "reports" / "runs"
        self.db = db or Database(self.project_root / "data" / "sqlite" / "research.db")
        self.db.initialize()  # 确保迁移已应用（幂等）

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

    def create_plan(self, task: Task) -> Plan:
        """生成最小计划。Phase 0 不注册任何功能模块。"""
        budgets = {"fast": 480, "standard": 1200, "deep": 1800}
        return Plan(
            plan_id=new_uuid(),
            task_id=task.task_id,
            scenario=task.scenario,
            depth=task.depth,
            created_at=now_iso(),
            steps=[],  # TODO Phase 1+: 按场景注册模块调用图
            data_requirements=[],  # TODO Phase 1+: 按场景声明数据需求
            retrieval_budget={"max_runtime_seconds": budgets.get(task.depth, 1200)},
            model_route="flash_default",
            notes=["Phase 0 空计划：模块注册与调用图在 Phase 1+ 实现"],
        )

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
        """执行空任务。

        幂等规则：相同 task_id 的运行目录已存在且 task.json 状态为 completed
        时，幂等跳过（不重复生成）。force=True 时重建。
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

        plan = self.create_plan(task)

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
                 "checks": [], "message": "Phase 0 空任务：无报告产物需校验"}
            )
            # 4. SQLite 持久化（幂等 upsert）
            task.status = "completed"
            self.db.upsert(task)
            # 5. 回写 task.json 最终状态
            run_dir.write_task(task.model_dump())
            return RunOutcome(
                status="created",
                task=task,
                plan=plan,
                run_dir=run_dir.root,
                message=f"空任务完成：{task.task_id}",
            )
        except Exception as exc:  # noqa: BLE001 —— 失败必须显式记录
            error_log = ErrorLog(run_dir.errors_log)
            error_log.error("orchestrator", f"任务执行失败: {exc}")
            return RunOutcome(
                status="failed",
                task=task,
                run_dir=run_dir.root,
                message=f"任务执行失败: {exc}",
                errors=[str(exc)],
            )
