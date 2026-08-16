from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

import pytest

from research_os.data_layer.execution import (
    AcquisitionExecutionService,
    AcquisitionPersistenceResult,
    AcquisitionStepFailure,
    RouteExecutionInput,
)
from research_os.data_layer.execution_policy import ExecutionPolicy
from research_os.models import AcquisitionPlan, AcquisitionStep, DataRoute
from research_os.routing.router import RoutedDataBatch
from research_os.validators.schema_validator import validate_instance


AS_OF = "2026-08-16T09:30:00+08:00"
NOW = "2026-08-16T10:00:00+08:00"


@dataclass
class _Requirement:
    requirement_id: str = "req-1"
    scenario: str = "morning_brief"
    data_type: str = "fake_data"


@dataclass
class _Capability:
    automatic_acquisition_lifecycle: str = "BUSINESS_SUFFICIENT"


class _Requirements:
    def __init__(self, requirement: _Requirement | None = None):
        self.requirement = requirement

    def get(self, requirement_id: str):
        if self.requirement and self.requirement.requirement_id == requirement_id:
            return self.requirement
        return None

    def for_scenario(self, scenario: str):
        if self.requirement and self.requirement.scenario == scenario:
            return [self.requirement]
        return []


class _Capabilities:
    def __init__(self, capability: _Capability | None = None):
        self.capability = capability

    def get(self, data_type: str):
        if self.capability is None:
            raise KeyError(data_type)
        return self.capability


class _Router:
    def __init__(self, batch: RoutedDataBatch | None = None, error: Exception | None = None):
        self.batch = batch or _batch(items=(object(),))
        self.error = error
        self.calls = []

    def resolve_with_items(self, data_type, query=None, time_window=None):
        self.calls.append((data_type, query, time_window))
        if self.error:
            raise self.error
        return self.batch


class _Repository:
    def __init__(self, result: AcquisitionPersistenceResult | None = None,
                 error: Exception | None = None):
        self.result = result or AcquisitionPersistenceResult(
            inserted_raw_item_ids=("raw-1",), reused_raw_item_ids=(),
        )
        self.error = error
        self.calls = []

    def persist_batch(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


def _route(selected="fake-source", status="success"):
    return DataRoute(
        data_type="fake_data", requested_sources=["fake-source"],
        attempted_sources=["fake-source"], selected_source=selected,
        fallback_used=False, status=status, missing_fields=[], warnings=[],
    )


def _batch(items=()):
    return RoutedDataBatch(route=_route(), items=tuple(items), fields_present=frozenset())


def _plan(action="route_existing_sources"):
    return AcquisitionPlan(
        task_id="task-1", scenario="morning_brief", as_of=AS_OF,
        steps=[AcquisitionStep(
            step_id="step-1", requirement_id="req-1", data_type="fake_data",
            action=action, dependencies=[], status="pending", warnings=[],
        )], warnings=[],
    )


def _service(*, policy=None, requirements=None, capabilities=None, router=None,
             repository=None):
    return AcquisitionExecutionService(
        policy=policy or ExecutionPolicy(
            enabled=True, allowed_actions=("route_existing_sources",),
            production_collector_ids=(),
        ),
        requirement_registry=requirements or _Requirements(_Requirement()),
        capability_registry=capabilities or _Capabilities(_Capability()),
        router=router or _Router(), repository=repository or _Repository(),
        clock=lambda: NOW,
    )


def _execute(service, plan=None, **overrides):
    args = dict(
        plan=plan or _plan(), task_id="task-1", scenario="morning_brief",
        as_of=AS_OF, dry_run=False, live_authorized=True,
    )
    args.update(overrides)
    return service.execute(**args)


@pytest.mark.parametrize(
    ("service_kwargs", "execute_kwargs", "reason"),
    [
        ({}, {"dry_run": True}, "DRY_RUN_PROHIBITS_EXECUTION"),
        ({"policy": ExecutionPolicy(False, ("route_existing_sources",), ())}, {},
         "EXECUTION_DISABLED"),
        ({}, {"live_authorized": False}, "LIVE_GATE_DISABLED"),
        ({}, {"task_id": "other"}, "PLAN_CONTEXT_MISMATCH"),
        ({}, {"scenario": "daily_review"}, "PLAN_CONTEXT_MISMATCH"),
        ({}, {"as_of": "2026-08-15T09:30:00+08:00"}, "PLAN_CONTEXT_MISMATCH"),
    ],
)
def test_global_gates_are_complete_zero_io_audits(service_kwargs, execute_kwargs, reason):
    router, repository = _Router(), _Repository()
    service = _service(router=router, repository=repository, **service_kwargs)
    result = _execute(service, **execute_kwargs)
    assert result.status == "not_executable"
    assert [step.status for step in result.steps] == ["not_executable"]
    assert result.steps[0].reason_codes == [reason]
    assert router.calls == []
    assert repository.calls == []
    assert validate_instance(result.model_dump(), "acquisition_execution_result") == []


def test_invalid_plan_and_schema_invalid_action_fail_before_io():
    router, repository = _Router(), _Repository()
    service = _service(router=router, repository=repository)
    payload = _plan().model_dump()
    payload["unexpected"] = True
    result = _execute(service, plan=payload)
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]

    payload = _plan().model_dump()
    payload["steps"][0]["action"] = "call_unknown_provider"
    result = _execute(service, plan=payload)
    assert result.status == "not_executable"
    assert result.steps == []  # the strict result contract cannot echo an unknown action
    assert result.errors[0].code == "CONTROL_PLANE_CONFIGURATION_ERROR"
    assert router.calls == []
    assert repository.calls == []


@pytest.mark.parametrize(
    ("requirements", "capabilities", "data_type", "reason"),
    [
        (_Requirements(None), _Capabilities(_Capability()), "fake_data", "REQUIREMENT_NOT_FOUND"),
        (_Requirements(_Requirement()), _Capabilities(_Capability()), "other", "DATA_TYPE_MISMATCH"),
        (_Requirements(_Requirement()), _Capabilities(None), "fake_data",
         "CAPABILITY_NOT_BUSINESS_SUFFICIENT"),
        (_Requirements(_Requirement()), _Capabilities(_Capability("WORKFLOW_WIRED")), "fake_data",
         "CAPABILITY_NOT_BUSINESS_SUFFICIENT"),
    ],
)
def test_step_gates_are_zero_io(requirements, capabilities, data_type, reason):
    router, repository = _Router(), _Repository()
    plan = _plan().model_copy(deep=True)
    plan.steps[0].data_type = data_type
    result = _execute(_service(
        requirements=requirements, capabilities=capabilities,
        router=router, repository=repository,
    ), plan=plan)
    assert result.status == "not_executable"
    assert result.steps[0].status == "not_executable"
    assert result.steps[0].reason_codes == [reason]
    assert router.calls == []
    assert repository.calls == []


def test_invalid_in_memory_policy_fails_closed_before_io():
    router, repository = _Router(), _Repository()
    service = _service(
        policy=ExecutionPolicy(True, ("route_existing_sources", "unknown"), ()),
        router=router, repository=repository,
    )
    result = _execute(service)
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert router.calls == repository.calls == []


def test_plan_is_not_mutated_and_identity_is_canonical_and_stable():
    plan = _plan()
    before = deepcopy(plan.model_dump())
    service = _service()
    first = _execute(service, plan=plan)
    second = _execute(_service(), plan=plan)
    assert plan.model_dump() == before
    assert first.plan_sha256 == second.plan_sha256
    assert first.execution_id == second.execution_id
    assert first.execution_id[14] == "5"
    assert first.steps[0].status == "completed"
    assert first.readiness_before_requirement_ids == ["req-1"]
    assert first.readiness_after_requirement_ids == ["req-1"]


@pytest.mark.parametrize(
    "action",
    ["derive_existing", "request_manual_input", "request_human_review",
     "governed_workflow", "unavailable"],
)
def test_valid_non_route_actions_are_explicitly_skipped(action):
    router, repository = _Router(), _Repository()
    result = _execute(_service(router=router, repository=repository), plan=_plan(action))
    assert result.status == "completed"
    assert result.steps[0].status == "skipped"
    assert result.steps[0].reason_codes == ["ACTION_SKIPPED"]
    assert router.calls == repository.calls == []


def test_route_input_and_persistence_result_are_reported_exactly():
    router = _Router(_batch(items=("normalized",)))
    repository = _Repository(AcquisitionPersistenceResult(
        inserted_raw_item_ids=("raw-new",), reused_raw_item_ids=("raw-old",),
    ))
    result = _execute(
        _service(router=router, repository=repository),
        route_inputs={"req-1": RouteExecutionInput(
            query={"subject": "600000.SH"},
            time_window={"start": "2026-08-15T09:30:00+08:00", "end": AS_OF},
        )},
    )
    assert router.calls == [("fake_data", {"subject": "600000.SH"}, {
        "start": "2026-08-15T09:30:00+08:00", "end": AS_OF,
    })]
    assert result.status == "completed"
    assert result.steps[0].inserted_raw_item_ids == ["raw-new"]
    assert result.steps[0].reused_raw_item_ids == ["raw-old"]
    assert result.steps[0].inserted_count == result.steps[0].reused_count == 1
    assert repository.calls[0]["task_id"] == "task-1"


def test_empty_result_persists_route_audit_and_is_partial_success():
    router = _Router(_batch(items=()))
    repository = _Repository(AcquisitionPersistenceResult((), ()))
    result = _execute(_service(router=router, repository=repository))
    assert len(repository.calls) == 1
    assert result.status == "partial_success"
    assert result.steps[0].status == "partial_success"
    assert result.steps[0].reason_codes == ["EMPTY_RESULT"]


def test_route_unavailable_is_failed_and_never_persists():
    router, repository = _Router(RoutedDataBatch(
        route=_route(selected=None, status="failed"), items=(), fields_present=frozenset(),
    )), _Repository()
    result = _execute(_service(router=router, repository=repository))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["ROUTE_UNAVAILABLE"]
    assert repository.calls == []


def test_status_aggregation_is_exact_for_mixed_steps():
    plan = _plan()
    plan.steps.append(AcquisitionStep(
        step_id="step-2", requirement_id="req-2", data_type="other",
        action="route_existing_sources", dependencies=[], status="pending", warnings=[],
    ))
    result = _execute(_service(), plan=plan)
    assert [s.status for s in result.steps] == ["completed", "not_executable"]
    assert result.status == "partial_success"


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Authorization: Bearer top-secret"),
        RuntimeError("Cookie=session=top-secret"),
        RuntimeError("api_key=top-secret"),
        RuntimeError("<html>complete private page</html>"),
    ],
)
def test_arbitrary_runtime_errors_are_sanitized(error):
    result = _execute(_service(router=_Router(error=error)))
    dumped = str(result.model_dump()).lower()
    assert "top-secret" not in dumped
    assert "private page" not in dumped
    assert result.steps[0].errors[0].message == "route resolution failed"


def test_typed_step_failure_preserves_only_allowlisted_reason_and_generic_message():
    repository = _Repository(error=AcquisitionStepFailure(
        "RAW_ITEM_SCHEMA_INVALID", "payload Authorization=secret",
    ))
    result = _execute(_service(repository=repository))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["RAW_ITEM_SCHEMA_INVALID"]
    assert result.steps[0].errors[0].message == "acquisition step failed"
    assert "secret" not in str(result.model_dump())
