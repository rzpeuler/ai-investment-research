from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from types import SimpleNamespace

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
        route_inputs={"req-1": RouteExecutionInput(
            query={}, time_window={"start": None, "end": AS_OF},
        )},
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


@pytest.mark.parametrize(("field", "value"), [
    ("dry_run", "false"), ("dry_run", 0), ("dry_run", None),
    ("live_authorized", "true"), ("live_authorized", 1),
    ("live_authorized", None),
])
def test_gate_flags_require_exact_booleans(field, value):
    router, repository = _Router(), _Repository()
    result = _execute(
        _service(router=router, repository=repository), **{field: value},
    )
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert router.calls == repository.calls == []


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


def test_all_route_step_gates_are_preflighted_before_any_io():
    class Requirements:
        def get(self, requirement_id):
            return _Requirement() if requirement_id == "req-1" else None

        def for_scenario(self, scenario):
            return [_Requirement()]

    plan = _plan()
    plan.steps.append(AcquisitionStep(
        step_id="step-2", requirement_id="missing", data_type="fake_data",
        action="route_existing_sources", dependencies=[], status="pending", warnings=[],
    ))
    plan.steps.append(AcquisitionStep(
        step_id="step-3", requirement_id="manual", data_type="manual",
        action="request_manual_input", dependencies=[], status="pending", warnings=[],
    ))
    router, repository = _Router(), _Repository()
    result = _execute(
        _service(requirements=Requirements(), router=router, repository=repository),
        plan=plan,
    )
    assert router.calls == repository.calls == []
    assert [step.status for step in result.steps] == [
        "not_executable", "not_executable", "skipped",
    ]
    assert [step.reason_codes for step in result.steps] == [
        ["CONTROL_PLANE_CONFIGURATION_ERROR"],
        ["REQUIREMENT_NOT_FOUND"],
        ["ACTION_SKIPPED"],
    ]


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


@pytest.mark.parametrize("policy", [
    None,
    object(),
    SimpleNamespace(enabled=True, allowed_actions=None, production_collector_ids=()),
    SimpleNamespace(enabled=True, allowed_actions=["route_existing_sources"],
                    production_collector_ids=()),
    SimpleNamespace(enabled=1, allowed_actions=("route_existing_sources",),
                    production_collector_ids=()),
    SimpleNamespace(enabled=True, allowed_actions=("route_existing_sources",),
                    production_collector_ids=None),
    SimpleNamespace(enabled=True, allowed_actions=("route_existing_sources",),
                    production_collector_ids=[]),
])
def test_malformed_injected_policy_is_total_and_zero_io(policy):
    router, repository = _Router(), _Repository()
    service = AcquisitionExecutionService(
        policy=policy, requirement_registry=_Requirements(_Requirement()),
        capability_registry=_Capabilities(_Capability()), router=router,
        repository=repository, clock=lambda: NOW,
    )
    result = _execute(service)
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert router.calls == repository.calls == []


def test_plan_and_authoritative_as_of_compare_by_instant_not_text():
    result = _execute(_service(), as_of="2026-08-16T01:30:00Z")
    assert result.status == "completed"


def test_malformed_authoritative_as_of_fails_closed_with_valid_audit():
    router, repository = _Router(), _Repository()
    result = _execute(
        _service(router=router, repository=repository), as_of="not-a-time",
    )
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["PLAN_CONTEXT_MISMATCH"]
    assert result.as_of == AS_OF
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
    router = _Router(_batch(items=("normalized-new", "normalized-reused")))
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


@pytest.mark.parametrize(
    "route_inputs",
    [
        {},
        {"req-1": RouteExecutionInput(query={}, time_window={})},
        {"req-1": RouteExecutionInput(query={}, time_window={"end": "not-a-time"})},
        {"req-1": RouteExecutionInput(
            query={}, time_window={"end": "2026-08-16T09:31:00+08:00"},
        )},
    ],
)
def test_missing_or_invalid_route_context_fails_before_io(route_inputs):
    router, repository = _Router(), _Repository()
    result = _execute(
        _service(router=router, repository=repository), route_inputs=route_inputs,
    )
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert router.calls == repository.calls == []


def test_route_window_end_accepts_equivalent_timezone_instant():
    router = _Router()
    result = _execute(
        _service(router=router),
        route_inputs={"req-1": RouteExecutionInput(
            query={}, time_window={"end": "2026-08-16T01:30:00Z"},
        )},
    )
    assert result.status == "completed"
    assert len(router.calls) == 1


@pytest.mark.parametrize(
    "start",
    ["not-a-time", "2026-08-16T09:31:00+08:00"],
)
def test_malformed_or_after_end_route_window_start_fails_before_io(start):
    router, repository = _Router(), _Repository()
    result = _execute(
        _service(router=router, repository=repository),
        route_inputs={"req-1": RouteExecutionInput(
            query={}, time_window={"start": start, "end": AS_OF},
        )},
    )
    assert result.status == "not_executable"
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert router.calls == repository.calls == []


@pytest.mark.parametrize("start", [None, "2026-08-16T01:00:00Z"])
def test_null_or_offset_equivalent_valid_route_window_start_is_accepted(start):
    router = _Router()
    result = _execute(
        _service(router=router),
        route_inputs={"req-1": RouteExecutionInput(
            query={}, time_window={"start": start, "end": AS_OF},
        )},
    )
    assert result.status == "completed"
    assert len(router.calls) == 1


def test_empty_result_persists_route_audit_and_is_partial_success():
    router = _Router(_batch(items=()))
    repository = _Repository(AcquisitionPersistenceResult((), ()))
    result = _execute(_service(router=router, repository=repository))
    assert len(repository.calls) == 1
    assert result.status == "partial_success"
    assert result.steps[0].status == "partial_success"
    assert result.steps[0].reason_codes == ["EMPTY_RESULT"]


@pytest.mark.parametrize(
    ("items", "persistence"),
    [
        ((), AcquisitionPersistenceResult(("unexpected",), ())),
        ((), AcquisitionPersistenceResult((), (), rejected_future_item_count=1)),
        ((object(),), AcquisitionPersistenceResult((), ())),
        ((object(),), AcquisitionPersistenceResult(
            (), (), rejected_future_item_count=2,
        )),
        ((object(), object()), AcquisitionPersistenceResult(("one",), ())),
    ],
)
def test_inconsistent_persistence_accounting_fails_instead_of_claiming_success(
    items, persistence,
):
    result = _execute(_service(
        router=_Router(_batch(items=items)), repository=_Repository(persistence),
    ))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["PERSIST_FAILED"]
    assert result.steps[0].inserted_count == 0
    assert result.steps[0].reused_count == 0


def test_persistence_result_defensively_copies_mutable_sequences():
    inserted = ["inserted"]
    reused = ["reused"]
    warnings = ["warning"]
    value = AcquisitionPersistenceResult(inserted, reused, warnings=warnings)
    inserted.append("changed")
    reused.clear()
    warnings[0] = "changed"
    assert value.inserted_raw_item_ids == ("inserted",)
    assert value.reused_raw_item_ids == ("reused",)
    assert value.warnings == ("warning",)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"inserted_raw_item_ids": "raw-id", "reused_raw_item_ids": ()},
        {"inserted_raw_item_ids": (), "reused_raw_item_ids": "raw-id"},
        {"inserted_raw_item_ids": ("same", "same"), "reused_raw_item_ids": ()},
        {"inserted_raw_item_ids": (), "reused_raw_item_ids": ("same", "same")},
        {"inserted_raw_item_ids": ("same",), "reused_raw_item_ids": ("same",)},
        {"inserted_raw_item_ids": (), "reused_raw_item_ids": (),
         "warnings": "warning"},
    ],
)
def test_persistence_result_rejects_ambiguous_sequences_and_id_sets(kwargs):
    with pytest.raises((TypeError, ValueError)):
        AcquisitionPersistenceResult(**kwargs)


def test_route_unavailable_is_failed_and_never_persists():
    router, repository = _Router(RoutedDataBatch(
        route=_route(selected=None, status="failed"), items=(), fields_present=frozenset(),
    )), _Repository()
    result = _execute(_service(router=router, repository=repository))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["ROUTE_UNAVAILABLE"]
    assert repository.calls == []


@pytest.mark.parametrize(
    "route",
    [
        DataRoute(
            data_type="other", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="fake-source",
            fallback_used=False, status="success", missing_fields=[], warnings=[],
        ),
        DataRoute(
            data_type="fake_data", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="fake-source",
            fallback_used=False, status="failed", missing_fields=[], warnings=[],
        ),
        DataRoute(
            data_type="fake_data", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="fake-source",
            fallback_used=False, status="insufficient_data", missing_fields=[], warnings=[],
        ),
        DataRoute(
            data_type="fake_data", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="",
            fallback_used=False, status="success", missing_fields=[], warnings=[],
        ),
        DataRoute(
            data_type="fake_data", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="fake-source",
            fallback_used=False, status="degraded", missing_fields=["published_at"], warnings=[],
        ),
        DataRoute.model_construct(
            data_type="fake_data", requested_sources=["fake-source"],
            attempted_sources=["fake-source"], selected_source="fake-source",
            fallback_used="not-boolean", status="success", missing_fields=[], warnings=[],
        ),
    ],
)
def test_ineligible_or_schema_invalid_route_never_reaches_repository(route):
    router = _Router(RoutedDataBatch(
        route=route, items=(object(),), fields_present=frozenset(),
    ))
    repository = _Repository()
    result = _execute(_service(router=router, repository=repository))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["ROUTE_UNAVAILABLE"]
    assert repository.calls == []


def test_all_untrusted_route_and_persistence_warnings_are_redacted_fail_closed():
    route = _route()
    route.warnings = [
        "fallback source used",
        "token expired",
        "primary failed Authorization: Bearer super-secret",
        "fallback failed Bearer loose-secret",
        "headers: {'Cookie': 'session=super-secret'}",
        "payload: complete upstream response",
        "Set-Cookie session super-secret",
        "entire private response fragment",
    ]
    repository = _Repository(AcquisitionPersistenceResult(
        ("raw-1",), (), warnings=(
            "reused canonical identity",
            "api_key=super-secret",
            "<html>complete private page</html>",
        ),
    ))
    plan = _plan()
    plan.steps[0].warnings = ["short private plan fragment"]
    result = _execute(_service(
        router=_Router(RoutedDataBatch(route, (object(),), frozenset())),
        repository=repository,
    ), plan=plan)
    dumped = str(result.model_dump())
    assert "super-secret" not in dumped
    assert "loose-secret" not in dumped
    assert "complete private page" not in dumped
    assert "complete upstream response" not in dumped
    assert "fallback source used" not in dumped
    assert "token expired" not in dumped
    assert "reused canonical identity" not in dumped
    assert "short private plan fragment" not in dumped
    assert set(result.steps[0].route.warnings) == {"[REDACTED]"}
    assert set(result.steps[0].warnings) == {"[REDACTED]"}
    assert set(repository.calls[0]["route"].warnings) == {"[REDACTED]"}


def test_route_gate_failure_prevents_an_earlier_valid_route_step_from_running():
    plan = _plan()
    plan.steps.append(AcquisitionStep(
        step_id="step-2", requirement_id="req-2", data_type="other",
        action="route_existing_sources", dependencies=[], status="pending", warnings=[],
    ))
    result = _execute(_service(), plan=plan)
    assert [s.status for s in result.steps] == ["not_executable", "not_executable"]
    assert result.steps[0].reason_codes == ["CONTROL_PLANE_CONFIGURATION_ERROR"]
    assert result.steps[1].reason_codes == ["REQUIREMENT_NOT_FOUND"]
    assert result.status == "not_executable"


@pytest.mark.parametrize(
    ("statuses", "expected"),
    [
        ([], "completed"),
        (["skipped"], "completed"),
        (["not_executable"], "not_executable"),
        (["not_executable", "skipped"], "not_executable"),
        (["failed"], "failed"),
        (["failed", "skipped"], "failed"),
        (["failed", "not_executable"], "failed"),
        (["completed", "failed"], "partial_success"),
        (["completed", "not_executable"], "partial_success"),
        (["partial_success", "failed"], "partial_success"),
        (["partial_success", "not_executable"], "partial_success"),
    ],
)
def test_exact_overall_status_matrix(statuses, expected):
    steps = [
        AcquisitionExecutionService._step(
            _plan("request_manual_input").steps[0], status, (),
        )
        for status in statuses
    ]
    assert AcquisitionExecutionService._aggregate(steps) == expected


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


@pytest.mark.parametrize(
    "forged_reason",
    ["EXECUTION_DISABLED", "ACTION_SKIPPED", "RECHECK_FAILED", "ROUTE_UNAVAILABLE"],
)
def test_repository_cannot_forge_reason_codes_owned_by_other_components(forged_reason):
    repository = _Repository(error=AcquisitionStepFailure(
        forged_reason, "Authorization=secret",
    ))
    result = _execute(_service(repository=repository))
    assert result.status == "failed"
    assert result.steps[0].reason_codes == ["PERSIST_FAILED"]
    assert result.steps[0].errors[0].code == "PERSIST_FAILED"
    assert "secret" not in str(result.model_dump())
