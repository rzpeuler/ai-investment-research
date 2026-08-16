"""P7-D2 Milestone 0 acquisition execution result contract tests."""
from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from research_os.models import (
    AcquisitionPlan,
    AcquisitionExecutionError,
    AcquisitionExecutionResult,
    AcquisitionExecutionStepResult,
)
from research_os.validators.schema_validator import SCHEMA_NAMES, validate_instance, validate_model


REASONS = {
    "EXECUTION_DISABLED",
    "LIVE_GATE_DISABLED",
    "DRY_RUN_PROHIBITS_EXECUTION",
    "PLAN_CONTEXT_MISMATCH",
    "ACTION_SKIPPED",
    "REQUIREMENT_NOT_FOUND",
    "DATA_TYPE_MISMATCH",
    "CAPABILITY_NOT_BUSINESS_SUFFICIENT",
    "ROUTE_UNAVAILABLE",
    "FETCH_FAILED",
    "NORMALIZATION_FAILED",
    "RAW_ITEM_SCHEMA_INVALID",
    "FUTURE_ITEM_REJECTED",
    "EMPTY_RESULT",
    "PERSIST_FAILED",
    "RECHECK_FAILED",
    "CONTROL_PLANE_CONFIGURATION_ERROR",
}


def _route() -> dict:
    return {
        "data_type": "fast_news",
        "requested_sources": ["fake_primary"],
        "attempted_sources": ["fake_primary"],
        "selected_source": "fake_primary",
        "fallback_used": False,
        "status": "success",
        "missing_fields": [],
        "warnings": [],
    }


def _step(**overrides: object) -> dict:
    value = {
        "step_id": "step-1",
        "requirement_id": "morning.fast_news",
        "data_type": "fast_news",
        "action": "route_existing_sources",
        "status": "completed",
        "reason_codes": [],
        "route": _route(),
        "inserted_raw_item_ids": ["raw-1"],
        "reused_raw_item_ids": [],
        "inserted_count": 1,
        "reused_count": 0,
        "rejected_future_item_count": 0,
        "warnings": [],
        "errors": [],
    }
    value.update(overrides)
    return value


def _payload(**overrides: object) -> dict:
    value = {
        "execution_id": "7ad2b090-d523-5a2e-b260-9af67af79926",
        "task_id": "task-1",
        "scenario": "morning_brief",
        "as_of": "2026-08-16T08:00:00+08:00",
        "plan_sha256": "a" * 64,
        "started_at": "2026-08-16T08:00:01+08:00",
        "finished_at": "2026-08-16T08:00:02+08:00",
        "status": "completed",
        "steps": [_step()],
        "readiness_before_requirement_ids": ["morning.fast_news"],
        "readiness_after_requirement_ids": ["morning.fast_news"],
        "warnings": [],
        "errors": [],
    }
    value.update(overrides)
    return value


def test_normal_model_dump_passes_authoritative_schema() -> None:
    model = AcquisitionExecutionResult(**_payload())
    assert validate_model(model) == []
    assert validate_instance(model.model_dump(), "acquisition_execution_result") == []
    assert isinstance(model.steps[0], AcquisitionExecutionStepResult)


def test_nullable_route_and_structured_error_are_valid_boundary() -> None:
    payload = _payload(
        status="not_executable",
        steps=[_step(
            status="not_executable",
            reason_codes=["EXECUTION_DISABLED"],
            route=None,
            inserted_raw_item_ids=[],
            inserted_count=0,
            errors=[{
                "code": "EXECUTION_DISABLED",
                "message": "execution policy is disabled",
                "component": "execution_policy",
            }],
        )],
        errors=[{
            "code": "EXECUTION_DISABLED",
            "message": "execution policy is disabled",
            "component": "execution_policy",
        }],
    )
    model = AcquisitionExecutionResult(**payload)
    assert isinstance(model.errors[0], AcquisitionExecutionError)
    assert validate_model(model) == []


@pytest.mark.parametrize("status", ["not_executable", "completed", "partial_success", "failed"])
def test_exact_overall_status_enum(status: str) -> None:
    assert validate_instance(_payload(status=status), "acquisition_execution_result") == []


@pytest.mark.parametrize(
    "status", ["not_executable", "skipped", "completed", "partial_success", "failed"],
)
def test_exact_step_status_enum(status: str) -> None:
    assert validate_instance(_payload(steps=[_step(status=status)]), "acquisition_execution_result") == []


@pytest.mark.parametrize("reason", sorted(REASONS))
def test_exact_reason_enum_includes_taskbook_codes(reason: str) -> None:
    payload = _payload(steps=[_step(reason_codes=[reason])])
    assert validate_instance(payload, "acquisition_execution_result") == []


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("status",), "success"),
        (("steps", 0, "status"), "pending"),
        (("steps", 0, "reason_codes"), ["UNKNOWN_REASON"]),
    ],
)
def test_unknown_enums_are_rejected(path: tuple[object, ...], value: object) -> None:
    payload = deepcopy(_payload())
    target = payload
    for part in path[:-1]:
        target = target[part]  # type: ignore[index]
    target[path[-1]] = value  # type: ignore[index]
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("execution_id", "not-a-uuid"),
        ("execution_id", "3fa85f64-5717-4562-b3fc-2c963f66afa6"),
        ("plan_sha256", "A" * 64),
        ("plan_sha256", "a" * 63),
        ("started_at", "2026-08-16 08:00:01"),
        ("finished_at", "not-a-time"),
    ],
)
def test_uuid_hash_and_time_validation(field: str, value: str) -> None:
    payload = _payload(**{field: value})
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


def test_finished_at_cannot_precede_started_at() -> None:
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**_payload(
            started_at="2026-08-16T08:00:02+08:00",
            finished_at="2026-08-16T08:00:01+08:00",
        ))


@pytest.mark.parametrize(
    "mutation",
    [
        lambda p: p.update({"unexpected": True}),
        lambda p: p["steps"][0].update({"unexpected": True}),
        lambda p: p["steps"][0]["route"].update({"unexpected": True}),
        lambda p: p.update({"errors": [{
            "code": "X", "message": "x", "component": "test", "secret": "no",
        }]}),
    ],
)
def test_additional_properties_false_at_every_object_level(mutation) -> None:
    payload = _payload()
    mutation(payload)
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


def test_all_object_fields_are_required() -> None:
    payload = _payload()
    del payload["warnings"]
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


def test_schema_registry_count_is_exactly_86() -> None:
    assert len(SCHEMA_NAMES) == 86
    assert len(set(SCHEMA_NAMES)) == 86
    assert "acquisition_execution_result" in SCHEMA_NAMES


@pytest.mark.parametrize("count", [True, "1"])
@pytest.mark.parametrize(
    "field", ["inserted_count", "reused_count", "rejected_future_item_count"],
)
def test_count_fields_reject_pydantic_coercion_and_match_schema(
    field: str, count: object,
) -> None:
    payload = _payload(steps=[_step(**{field: count})])
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


@pytest.mark.parametrize(
    "field",
    [
        "inserted_raw_item_ids",
        "reused_raw_item_ids",
        "readiness_before_requirement_ids",
        "readiness_after_requirement_ids",
    ],
)
def test_identifier_lists_reject_empty_items_with_model_schema_parity(field: str) -> None:
    if field in {"inserted_raw_item_ids", "reused_raw_item_ids"}:
        payload = _payload(steps=[_step(**{field: [""]})])
    else:
        payload = _payload(**{field: [""]})
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


@pytest.mark.parametrize(
    "route_update",
    [
        {"fallback_used": "false"},
        {"requested_sources": [1]},
    ],
)
def test_nested_route_rejects_coercive_primitives(route_update: dict) -> None:
    route = _route()
    route.update(route_update)
    payload = _payload(steps=[_step(route=route)])
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


def test_nested_route_requires_all_data_route_fields() -> None:
    route = _route()
    del route["warnings"]
    payload = _payload(steps=[_step(route=route)])
    assert validate_instance(payload, "acquisition_execution_result")
    with pytest.raises(ValidationError):
        AcquisitionExecutionResult(**payload)


@pytest.mark.parametrize("leaked_field", ["source_id", "selected_source", "provider_id"])
def test_acquisition_plan_rejects_source_leakage_in_model_and_schema(leaked_field: str) -> None:
    payload = {
        "task_id": "task-1",
        "scenario": "morning_brief",
        "as_of": "2026-08-16T08:00:00+08:00",
        "steps": [{
            "step_id": "step-1",
            "requirement_id": "morning.fast_news",
            "data_type": "fast_news",
            "action": "route_existing_sources",
            "dependencies": [],
            "status": "pending",
            "warnings": [],
            leaked_field: "forbidden-source",
        }],
        "warnings": [],
    }
    assert validate_instance(payload, "acquisition_plan")
    with pytest.raises(ValidationError):
        AcquisitionPlan(**payload)
