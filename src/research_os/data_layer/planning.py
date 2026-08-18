"""AcquisitionPlanner（P7-D1）。

输入：Task + Scenario + DataGap[]；输出 AcquisitionPlan。
只为 classification != AVAILABLE 创建 step；一条 Gap 最多一个主 step；
step 顺序必须与 ScenarioDataRequirementRegistry 原始 Requirement 顺序一致；
step_id 确定性（UUID5，禁止随机 UUID）；禁止 source 泄露。
Planner 输出后即停止——不执行 AcquisitionPlan（执行属于 P7-D2）。
"""
from __future__ import annotations

import uuid
from typing import List, Mapping, Optional

from research_os.data_layer.gaps import _RECOMMENDED_ACTION
from research_os.models import AcquisitionPlan, AcquisitionStep, DataGap

_STEP_ACTION = {
    "AVAILABLE": None,
    "AUTO_ACQUIRABLE": "route_existing_sources",
    "AUTO_DERIVABLE": "derive_existing",
    "STALE_REFRESHABLE": "route_existing_sources",
    "MANUAL_INPUT_REQUIRED": "request_manual_input",
    "HUMAN_REVIEW_REQUIRED": "request_human_review",
    "GOVERNED_WORKFLOW_REQUIRED": "governed_workflow",
    "UNAVAILABLE": "unavailable",
}

_UUID5_NS = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")


def _deterministic_step_id(task_id: str, requirement_id: str, action: str) -> str:
    return str(uuid.uuid5(
        _UUID5_NS,
        f"acquisition-plan-step:{task_id}:{requirement_id}:{action}",
    ))


class AcquisitionPlanner:
    """确定性 Acquisition 计划器。

    derivation_prerequisites：data_type → prerequisite data_type（如
    {financial_statement_data: company_document}）；当两个 requirement 都有 step 时，
    derive step 的 dependencies 指向 prereq step_id（taskbook P7-D4 §22）。
    """

    def __init__(self, derivation_prerequisites: Mapping[str, str] | None = None):
        self._derivation_prerequisites = dict(derivation_prerequisites or {})

    def plan(
        self,
        task_id: str,
        scenario: str,
        as_of: str,
        gaps: List[DataGap],
        requirement_order: List[str],
    ) -> AcquisitionPlan:
        """gaps 按 requirement_order 排序（中央 Registry 原始顺序）。"""
        gap_by_req = {g.requirement_id: g for g in gaps}
        steps: List[AcquisitionStep] = []
        warnings: List[str] = []
        step_by_req: dict[str, AcquisitionStep] = {}
        for requirement_id in requirement_order:
            gap = gap_by_req.get(requirement_id)
            if gap is None:
                continue
            action = _STEP_ACTION[gap.classification]
            if action is None:
                continue  # AVAILABLE → no step
            dependencies: List[str] = []
            if action == "derive_existing":
                prereq_data_type = self._derivation_prerequisites.get(gap.data_type)
                if prereq_data_type is not None:
                    prereq_step = step_by_req.get(
                        self._requirement_id_for(requirement_order, gap_by_req,
                                                 prereq_data_type))
                    if prereq_step is not None:
                        dependencies = [prereq_step.step_id]
            step = AcquisitionStep(
                step_id=_deterministic_step_id(task_id, requirement_id, action),
                requirement_id=requirement_id,
                data_type=gap.data_type,
                action=action,
                dependencies=dependencies,
                status="pending",
                warnings=list(gap.warnings),
            )
            steps.append(step)
            step_by_req[requirement_id] = step
            if action == "unavailable":
                warnings.append(f"{requirement_id}: UNAVAILABLE")
        return AcquisitionPlan(
            task_id=task_id,
            scenario=scenario,
            as_of=as_of,
            steps=steps,
            warnings=warnings,
        )

    @staticmethod
    def _requirement_id_for(
        requirement_order: List[str], gap_by_req: dict, data_type: str
    ) -> Optional[str]:
        for rid in requirement_order:
            gap = gap_by_req.get(rid)
            if gap is not None and gap.data_type == data_type:
                return rid
        return None
