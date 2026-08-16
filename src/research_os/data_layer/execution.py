"""Fail-closed P7-D2 acquisition-plan execution foundation.

The service is collaborator-injected and has no production adapter, network, model, graph, or
database authority of its own.  It validates every pre-network gate before delegating to the
existing Router and a narrow batch-persistence protocol.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol, Sequence, cast

from research_os.data_layer.execution_policy import ExecutionPolicy
from research_os.models import (
    AcquisitionExecutionError,
    AcquisitionExecutionReason,
    AcquisitionExecutionResult,
    AcquisitionExecutionStepResult,
    AcquisitionPlan,
    AcquisitionStep,
    DataRoute,
)
from research_os.routing.router import RoutedDataBatch
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_instance


_EXECUTION_NAMESPACE = uuid.UUID("20509024-d8a9-5a6d-82f1-bb2266fd66b7")
_FOUNDATION_ACTIONS = ("route_existing_sources",)
_SCENARIOS = {
    "morning_brief", "evening_brief", "daily_review",
    "abnormal_move_analysis", "stock_research_report", "first_coverage",
    "stock_review", "industry_research", "theme_discovery",
    "earnings_expectation",
}
_KNOWN_ACTIONS = {
    "route_existing_sources", "derive_existing", "request_manual_input",
    "request_human_review", "governed_workflow", "unavailable",
}
_REASON_CODES = {
    "EXECUTION_DISABLED", "LIVE_GATE_DISABLED", "DRY_RUN_PROHIBITS_EXECUTION",
    "PLAN_CONTEXT_MISMATCH", "ACTION_SKIPPED", "REQUIREMENT_NOT_FOUND",
    "DATA_TYPE_MISMATCH", "CAPABILITY_NOT_BUSINESS_SUFFICIENT", "ROUTE_UNAVAILABLE",
    "FETCH_FAILED", "NORMALIZATION_FAILED", "RAW_ITEM_SCHEMA_INVALID",
    "FUTURE_ITEM_REJECTED", "EMPTY_RESULT", "PERSIST_FAILED", "RECHECK_FAILED",
    "CONTROL_PLANE_CONFIGURATION_ERROR",
}
_REPOSITORY_OWNED_REASONS = {
    "RAW_ITEM_SCHEMA_INVALID", "FUTURE_ITEM_REJECTED", "EMPTY_RESULT", "PERSIST_FAILED",
}


@dataclass(frozen=True)
class RouteExecutionInput:
    """Deterministic Router inputs projected by the coordinator from requirement context."""

    query: Mapping[str, Any]
    time_window: Mapping[str, str | None]

    def __post_init__(self) -> None:
        object.__setattr__(self, "query", MappingProxyType(deepcopy(dict(self.query))))
        object.__setattr__(
            self, "time_window", MappingProxyType(deepcopy(dict(self.time_window))),
        )


@dataclass(frozen=True)
class AcquisitionPersistenceResult:
    """Narrow M2/M3 boundary; M3 owns identity, validation, and transaction semantics."""

    inserted_raw_item_ids: tuple[str, ...]
    reused_raw_item_ids: tuple[str, ...]
    rejected_future_item_count: int = 0
    deduplicated_input_count: int = 0
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        inserted = self._normalize_sequence(
            self.inserted_raw_item_ids, "inserted_raw_item_ids",
        )
        reused = self._normalize_sequence(
            self.reused_raw_item_ids, "reused_raw_item_ids",
        )
        warnings = self._normalize_sequence(self.warnings, "warnings", allow_empty_items=True)
        if any(not item for item in (*inserted, *reused)):
            raise ValueError("persisted RawItem IDs must be nonempty strings")
        if len(inserted) != len(set(inserted)) or len(reused) != len(set(reused)):
            raise ValueError("persisted RawItem IDs must be unique within each result set")
        if set(inserted) & set(reused):
            raise ValueError("inserted and reused RawItem IDs must be disjoint")
        if type(self.rejected_future_item_count) is not int or self.rejected_future_item_count < 0:
            raise ValueError("rejected_future_item_count must be a nonnegative integer")
        if type(self.deduplicated_input_count) is not int or self.deduplicated_input_count < 0:
            raise ValueError("deduplicated_input_count must be a nonnegative integer")
        object.__setattr__(self, "inserted_raw_item_ids", inserted)
        object.__setattr__(self, "reused_raw_item_ids", reused)
        object.__setattr__(self, "warnings", warnings)

    @staticmethod
    def _normalize_sequence(
        value: Any, field: str, *, allow_empty_items: bool = False,
    ) -> tuple[str, ...]:
        if isinstance(value, (str, bytes, bytearray)):
            raise TypeError(f"{field} must be a sequence, not a string")
        try:
            normalized = tuple(value)
        except TypeError as exc:
            raise TypeError(f"{field} must be a sequence") from exc
        if any(not isinstance(item, str) for item in normalized):
            raise ValueError(f"{field} must contain only strings")
        if not allow_empty_items and any(not item for item in normalized):
            raise ValueError(f"{field} must contain nonempty strings")
        return normalized


class AcquisitionStepFailure(RuntimeError):
    """Typed collaborator failure whose reason code may enter the execution audit."""

    def __init__(self, reason_code: str, detail: str = "") -> None:
        if reason_code not in _REASON_CODES:
            raise ValueError("unknown acquisition execution reason code")
        super().__init__(detail)
        self.reason_code = cast(AcquisitionExecutionReason, reason_code)


class _RequirementRegistry(Protocol):
    def get(self, requirement_id: str) -> Any | None: ...

    def for_scenario(self, scenario: str) -> Sequence[Any]: ...


class _CapabilityRegistry(Protocol):
    def get(self, data_type: str) -> Any: ...


class _Router(Protocol):
    def resolve_with_items(
        self, data_type: str, query: Mapping[str, Any] | None = None,
        time_window: Mapping[str, str | None] | None = None,
    ) -> RoutedDataBatch: ...


class _WriteRepository(Protocol):
    def persist_batch(self, **kwargs: Any) -> AcquisitionPersistenceResult: ...


class AcquisitionExecutionService:
    """Validate and execute an immutable ``AcquisitionPlan`` with fail-closed gates."""

    def __init__(
        self,
        *,
        policy: ExecutionPolicy,
        requirement_registry: _RequirementRegistry,
        capability_registry: _CapabilityRegistry,
        router: _Router,
        repository: _WriteRepository,
        clock: Callable[[], str] = now_iso,
    ) -> None:
        self._policy = policy
        self._requirements = requirement_registry
        self._capabilities = capability_registry
        self._router = router
        self._repository = repository
        self._clock = clock

    def execute(
        self,
        *,
        plan: AcquisitionPlan | Mapping[str, Any],
        task_id: str,
        scenario: str,
        as_of: str,
        dry_run: bool,
        live_authorized: bool,
        route_inputs: Mapping[str, RouteExecutionInput] | None = None,
    ) -> AcquisitionExecutionResult:
        """Return a complete audit; ordinary acquisition failures never escape this boundary."""
        started_at = self._clock()
        payload = self._snapshot_payload(plan)
        plan_sha256 = self._plan_sha256(payload)
        invocation_valid = self._invocation_context_is_valid(task_id, scenario, as_of)
        if invocation_valid:
            audit_task_id = task_id
            audit_scenario = scenario
            audit_as_of = as_of
        else:
            safe_plan = self._schema_valid_plan(payload)
            if safe_plan is None:
                raise ValueError(
                    "invalid invocation and plan provide no schema-safe audit envelope"
                )
            audit_task_id = safe_plan.task_id
            audit_scenario = safe_plan.scenario
            audit_as_of = safe_plan.as_of
        execution_id = str(uuid.uuid5(
            _EXECUTION_NAMESPACE, f"{audit_task_id}:{plan_sha256}",
        ))
        audit_steps = self._parse_auditable_steps(payload)

        if not invocation_valid:
            return self._global_rejection(
                audit_steps, "CONTROL_PLANE_CONFIGURATION_ERROR", execution_id,
                audit_task_id, audit_scenario, audit_as_of, plan_sha256, started_at,
                error_component="invocation_context",
            )

        # Fixed global gate order.  None of these paths can reach Router or repository.
        if type(dry_run) is not bool:
            return self._global_rejection(
                audit_steps, "CONTROL_PLANE_CONFIGURATION_ERROR", execution_id,
                task_id, scenario, audit_as_of, plan_sha256, started_at,
                error_component="execution_gate",
            )
        if dry_run:
            return self._global_rejection(
                audit_steps, "DRY_RUN_PROHIBITS_EXECUTION", execution_id, task_id,
                scenario, audit_as_of, plan_sha256, started_at,
            )
        if not self._policy_is_valid():
            return self._global_rejection(
                audit_steps, "CONTROL_PLANE_CONFIGURATION_ERROR", execution_id,
                task_id, scenario, audit_as_of, plan_sha256, started_at,
                error_component="execution_policy",
            )
        if not self._policy.enabled:
            return self._global_rejection(
                audit_steps, "EXECUTION_DISABLED", execution_id, task_id,
                scenario, audit_as_of, plan_sha256, started_at,
            )
        if type(live_authorized) is not bool:
            return self._global_rejection(
                audit_steps, "CONTROL_PLANE_CONFIGURATION_ERROR", execution_id,
                task_id, scenario, audit_as_of, plan_sha256, started_at,
                error_component="execution_gate",
            )
        if not live_authorized:
            return self._global_rejection(
                audit_steps, "LIVE_GATE_DISABLED", execution_id, task_id,
                scenario, audit_as_of, plan_sha256, started_at,
            )

        schema_errors = validate_instance(payload, "acquisition_plan")
        try:
            checked_plan = AcquisitionPlan.model_validate(payload) if not schema_errors else None
        except Exception:  # noqa: BLE001 -- strict model detail may contain untrusted input
            checked_plan = None
        if checked_plan is None:
            return self._global_rejection(
                audit_steps, "CONTROL_PLANE_CONFIGURATION_ERROR", execution_id,
                task_id, scenario, audit_as_of, plan_sha256, started_at,
                error_component="acquisition_plan",
            )
        if (
            checked_plan.task_id != task_id
            or checked_plan.scenario != scenario
            or not self._same_instant(checked_plan.as_of, as_of)
        ):
            return self._global_rejection(
                list(checked_plan.steps), "PLAN_CONTEXT_MISMATCH", execution_id,
                task_id, scenario, audit_as_of, plan_sha256, started_at,
            )

        requirement_ids, registry_error = self._requirement_ids(scenario)
        if registry_error:
            return self._global_rejection(
                list(checked_plan.steps), "CONTROL_PLANE_CONFIGURATION_ERROR",
                execution_id, task_id, scenario, audit_as_of, plan_sha256, started_at,
                error_component="requirement_registry",
            )

        try:
            inputs = dict(route_inputs or {})
        except (TypeError, ValueError):
            inputs = {}
        preflight: list[AcquisitionExecutionReason | None] = []
        has_rejected_route_step = False
        for step in checked_plan.steps:
            if step.action != "route_existing_sources":
                preflight.append(None)
                continue
            rejection = self._route_step_rejection(
                step, scenario=scenario, as_of=as_of,
                route_input=inputs.get(step.requirement_id),
            )
            preflight.append(rejection)
            has_rejected_route_step = has_rejected_route_step or rejection is not None

        # A plan is a single pre-network control-plane unit.  One rejected route step prevents
        # earlier valid route steps from performing I/O before the rejection is discovered.
        if has_rejected_route_step:
            rejected_results = []
            for step, rejection in zip(checked_plan.steps, preflight):
                if step.action != "route_existing_sources":
                    rejected_results.append(self._step(
                        step, "skipped", ("ACTION_SKIPPED",),
                    ))
                else:
                    rejected_results.append(self._step(
                        step, "not_executable",
                        (rejection or "CONTROL_PLANE_CONFIGURATION_ERROR",),
                    ))
            return self._result(
                execution_id=execution_id, task_id=task_id, scenario=scenario,
                as_of=audit_as_of, plan_sha256=plan_sha256, started_at=started_at,
                status=self._aggregate(rejected_results), steps=rejected_results,
                readiness_ids=requirement_ids,
            )

        step_results = [
            self._execute_step(step, task_id=task_id, scenario=scenario, as_of=as_of,
                               route_input=inputs.get(step.requirement_id))
            for step in checked_plan.steps
        ]
        return self._result(
            execution_id=execution_id, task_id=task_id, scenario=scenario,
            as_of=audit_as_of,
            plan_sha256=plan_sha256, started_at=started_at,
            status=self._aggregate(step_results), steps=step_results,
            readiness_ids=requirement_ids,
        )

    def _execute_step(
        self,
        step: AcquisitionStep,
        *,
        task_id: str,
        scenario: str,
        as_of: str,
        route_input: RouteExecutionInput | None,
    ) -> AcquisitionExecutionStepResult:
        if step.action != "route_existing_sources":
            return self._step(step, "skipped", ("ACTION_SKIPPED",))
        # All route steps were validated as one unit before this method was entered.
        assert route_input is not None
        router_input = route_input
        try:
            batch = self._router.resolve_with_items(
                step.data_type,
                query=deepcopy(dict(router_input.query)),
                time_window=deepcopy(dict(router_input.time_window)),
            )
            if not isinstance(batch, RoutedDataBatch) or not isinstance(batch.route, DataRoute):
                raise TypeError("invalid routed batch")
        except Exception:  # noqa: BLE001 -- never echo arbitrary exception content
            return self._step(
                step, "failed", ("ROUTE_UNAVAILABLE",),
                errors=(self._error("ROUTE_UNAVAILABLE", "route resolution failed", "router"),),
            )

        try:
            route_payload = batch.route.model_dump()
            selected_source = batch.route.selected_source
            route_eligible = (
                not validate_instance(route_payload, "data_route")
                and batch.route.data_type == step.data_type
                and isinstance(selected_source, str)
                and bool(selected_source.strip())
                and batch.route.status in {"success", "degraded"}
                and not batch.route.missing_fields
            )
        except Exception:  # noqa: BLE001 -- malformed collaborator object fails closed
            route_eligible = False
        if not route_eligible:
            return self._step(
                step, "failed", ("ROUTE_UNAVAILABLE",),
            )
        route = batch.route.model_copy(deep=True)
        route.warnings = [_sanitize_warning(item) for item in route.warnings]

        try:
            persisted = self._repository.persist_batch(
                task_id=task_id,
                step_id=step.step_id,
                as_of=as_of,
                route=route.model_copy(deep=True),
                items=tuple(deepcopy(batch.items)),
            )
            if not isinstance(persisted, AcquisitionPersistenceResult):
                raise TypeError("invalid persistence result")
            accounted = (
                len(persisted.inserted_raw_item_ids)
                + len(persisted.reused_raw_item_ids)
                + persisted.rejected_future_item_count
                + persisted.deduplicated_input_count
            )
            if accounted != len(batch.items):
                raise ValueError("persistence result does not account for the routed batch")
        except AcquisitionStepFailure as exc:
            repository_reason = (
                exc.reason_code
                if exc.reason_code in _REPOSITORY_OWNED_REASONS
                else cast(AcquisitionExecutionReason, "PERSIST_FAILED")
            )
            return self._step(
                step, "failed", (repository_reason,), route=route,
                errors=(self._error(
                    repository_reason, "acquisition step failed", "repository",
                ),),
            )
        except Exception:  # noqa: BLE001 -- never echo arbitrary exception content
            return self._step(
                step, "failed", ("PERSIST_FAILED",), route=route,
                errors=(self._error("PERSIST_FAILED", "batch persistence failed", "repository"),),
            )

        if not batch.items:
            return self._step(
                step, "partial_success", ("EMPTY_RESULT",), route=route,
                persisted=persisted,
            )
        if persisted.rejected_future_item_count:
            accepted = len(persisted.inserted_raw_item_ids) + len(persisted.reused_raw_item_ids)
            status = "partial_success" if accepted else "failed"
            return self._step(
                step, status, ("FUTURE_ITEM_REJECTED",), route=route,
                persisted=persisted,
            )
        return self._step(step, "completed", (), route=route, persisted=persisted)

    def _global_rejection(
        self,
        steps: Sequence[AcquisitionStep],
        reason: AcquisitionExecutionReason,
        execution_id: str,
        task_id: str,
        scenario: str,
        as_of: str,
        plan_sha256: str,
        started_at: str,
        *,
        error_component: str | None = None,
    ) -> AcquisitionExecutionResult:
        errors = []
        if error_component:
            errors.append(self._error(
                reason, "control-plane validation failed", error_component,
            ))
        requirement_ids, _ = self._requirement_ids(scenario)
        return self._result(
            execution_id=execution_id, task_id=task_id, scenario=scenario, as_of=as_of,
            plan_sha256=plan_sha256, started_at=started_at, status="not_executable",
            steps=[self._step(step, "not_executable", (reason,)) for step in steps],
            readiness_ids=requirement_ids, errors=errors,
        )

    def _route_step_rejection(
        self,
        step: AcquisitionStep,
        *,
        scenario: str,
        as_of: str,
        route_input: RouteExecutionInput | None,
    ) -> AcquisitionExecutionReason | None:
        try:
            requirement = self._requirements.get(step.requirement_id)
        except Exception:  # noqa: BLE001
            requirement = None
        if requirement is None or getattr(requirement, "scenario", None) != scenario:
            return "REQUIREMENT_NOT_FOUND"
        if getattr(requirement, "data_type", None) != step.data_type:
            return "DATA_TYPE_MISMATCH"
        try:
            capability = self._capabilities.get(step.data_type)
        except Exception:  # noqa: BLE001
            capability = None
        if (
            capability is None
            or getattr(capability, "automatic_acquisition_lifecycle", None)
            != "BUSINESS_SUFFICIENT"
        ):
            return "CAPABILITY_NOT_BUSINESS_SUFFICIENT"
        if not isinstance(route_input, RouteExecutionInput):
            return "CONTROL_PLANE_CONFIGURATION_ERROR"
        end = route_input.time_window.get("end")
        try:
            if not isinstance(end, str):
                return "CONTROL_PLANE_CONFIGURATION_ERROR"
            parsed_end = parse_iso(end)
            if parsed_end != parse_iso(as_of):
                return "CONTROL_PLANE_CONFIGURATION_ERROR"
            start = route_input.time_window.get("start")
            if start is not None:
                if not isinstance(start, str) or parse_iso(start) > parsed_end:
                    return "CONTROL_PLANE_CONFIGURATION_ERROR"
        except (TypeError, ValueError):
            return "CONTROL_PLANE_CONFIGURATION_ERROR"
        return None

    def _result(
        self,
        *,
        execution_id: str,
        task_id: str,
        scenario: str,
        as_of: str,
        plan_sha256: str,
        started_at: str,
        status: str,
        steps: Sequence[AcquisitionExecutionStepResult],
        readiness_ids: Sequence[str],
        errors: Sequence[AcquisitionExecutionError] = (),
    ) -> AcquisitionExecutionResult:
        return AcquisitionExecutionResult(
            execution_id=execution_id, task_id=task_id, scenario=scenario, as_of=as_of,
            plan_sha256=plan_sha256, started_at=started_at, finished_at=self._clock(),
            status=status, steps=list(steps),
            readiness_before_requirement_ids=list(readiness_ids),
            readiness_after_requirement_ids=list(readiness_ids),
            warnings=[], errors=list(errors),
        )

    @staticmethod
    def _step(
        step: AcquisitionStep,
        status: str,
        reasons: Sequence[AcquisitionExecutionReason],
        *,
        route: DataRoute | None = None,
        persisted: AcquisitionPersistenceResult | None = None,
        errors: Sequence[AcquisitionExecutionError] = (),
    ) -> AcquisitionExecutionStepResult:
        persisted = persisted or AcquisitionPersistenceResult((), ())
        return AcquisitionExecutionStepResult(
            step_id=step.step_id, requirement_id=step.requirement_id,
            data_type=step.data_type, action=step.action, status=status,
            reason_codes=list(reasons), route=route,
            inserted_raw_item_ids=list(persisted.inserted_raw_item_ids),
            reused_raw_item_ids=list(persisted.reused_raw_item_ids),
            inserted_count=len(persisted.inserted_raw_item_ids),
            reused_count=len(persisted.reused_raw_item_ids),
            rejected_future_item_count=persisted.rejected_future_item_count,
            warnings=(
                [_sanitize_warning(item) for item in step.warnings]
                + [_sanitize_warning(item) for item in persisted.warnings]
            ),
            errors=list(errors),
        )

    @staticmethod
    def _error(code: str, message: str, component: str) -> AcquisitionExecutionError:
        # Messages are selected from local constants.  Exception text is never retained.
        return AcquisitionExecutionError(code=code, message=message, component=component)

    def _policy_is_valid(self) -> bool:
        try:
            enabled = self._policy.enabled
            actions = self._policy.allowed_actions
            collectors = self._policy.production_collector_ids
            return (
                type(enabled) is bool
                and type(actions) is tuple
                and actions == _FOUNDATION_ACTIONS
                and type(collectors) is tuple
                and collectors == ()
            )
        except Exception:  # noqa: BLE001 -- arbitrary injected config must be total
            return False

    @staticmethod
    def _same_instant(left: str, right: str) -> bool:
        try:
            return parse_iso(left) == parse_iso(right)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _invocation_context_is_valid(task_id: Any, scenario: Any, as_of: Any) -> bool:
        if type(task_id) is not str or not task_id:
            return False
        if type(scenario) is not str or scenario not in _SCENARIOS:
            return False
        if type(as_of) is not str:
            return False
        try:
            parse_iso(as_of)
        except ValueError:
            return False
        return True

    @staticmethod
    def _schema_valid_plan(payload: Mapping[str, Any]) -> AcquisitionPlan | None:
        try:
            if validate_instance(payload, "acquisition_plan"):
                return None
            return AcquisitionPlan.model_validate(payload)
        except Exception:  # noqa: BLE001 -- untrusted plan cannot escape validation
            return None

    def _requirement_ids(self, scenario: str) -> tuple[list[str], bool]:
        try:
            requirements = self._requirements.for_scenario(scenario)
            ids = [item.requirement_id for item in requirements]
            if any(not isinstance(item, str) or not item for item in ids):
                raise ValueError("invalid requirement ID")
            return ids, False
        except Exception:  # noqa: BLE001
            return [], True

    @staticmethod
    def _snapshot_payload(plan: AcquisitionPlan | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(plan, AcquisitionPlan):
            return deepcopy(plan.model_dump())
        if isinstance(plan, Mapping):
            return deepcopy(dict(plan))
        return {"invalid_plan_type": type(plan).__name__}

    @staticmethod
    def _plan_sha256(payload: Mapping[str, Any]) -> str:
        try:
            canonical = json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            )
        except (TypeError, ValueError):
            canonical = "invalid-plan"
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _parse_auditable_steps(payload: Mapping[str, Any]) -> list[AcquisitionStep]:
        raw_steps = payload.get("steps", [])
        if not isinstance(raw_steps, list):
            return []
        parsed = []
        for raw in raw_steps:
            if not isinstance(raw, Mapping) or raw.get("action") not in _KNOWN_ACTIONS:
                continue
            try:
                parsed.append(AcquisitionStep.model_validate(raw))
            except Exception:  # noqa: BLE001
                continue
        return parsed

    @staticmethod
    def _aggregate(steps: Sequence[AcquisitionExecutionStepResult]) -> str:
        if not steps:
            return "completed"
        statuses = [step.status for step in steps]
        if "partial_success" in statuses:
            return "partial_success"
        if "completed" in statuses:
            return (
                "partial_success"
                if any(status in {"failed", "not_executable"} for status in statuses)
                else "completed"
            )
        if "failed" in statuses:
            return "failed"
        if "not_executable" in statuses:
            return "not_executable"
        return "completed"


def _sanitize_warning(value: str) -> str:
    """Warnings cross an untrusted collaborator boundary, so their text is never persisted."""
    return "[REDACTED]"


__all__ = [
    "AcquisitionExecutionService",
    "AcquisitionPersistenceResult",
    "AcquisitionStepFailure",
    "RouteExecutionInput",
]
