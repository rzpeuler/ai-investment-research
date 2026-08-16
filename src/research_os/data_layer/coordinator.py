"""P7-D2 acquisition coordinator and authoritative readiness recheck.

The coordinator owns sequencing only.  It projects Router inputs from the P7-D1 resolved
requirement contexts, delegates all execution gates to ``AcquisitionExecutionService``, and asks
the *same* ``DataPreflightService`` instance to re-evaluate readiness after persistence.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from research_os.data_layer.execution import AcquisitionExecutionService, RouteExecutionInput
from research_os.data_layer.preflight import DataPreflightBundle, DataPreflightService, _atomic_write, json_dumps
from research_os.models import AcquisitionExecutionError, AcquisitionExecutionResult
from research_os.validators.schema_validator import validate_instance


@dataclass(frozen=True)
class AcquisitionCoordinationResult:
    """Internal aggregate passed to the existing Runner context."""

    readiness_before: DataPreflightBundle
    execution: AcquisitionExecutionResult
    readiness_after: Optional[DataPreflightBundle]


class AcquisitionCoordinator:
    """Coordinate optional acquisition without changing Runner result semantics."""

    def __init__(
        self,
        *,
        preflight: DataPreflightService,
        execution: AcquisitionExecutionService,
        live_authorized: bool = False,
    ) -> None:
        if type(live_authorized) is not bool:
            raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: invalid live gate")
        self._preflight = preflight
        self._execution = execution
        self._live_authorized = live_authorized

    def coordinate(
        self,
        *,
        before: DataPreflightBundle,
        scenario: str,
        task_id: str,
        task_as_of: str,
        normalized_request: Mapping[str, Any],
        project_root: Path,
        db: Optional[Any],
        runs_root: Path,
        dry_run: bool,
        graph_repo: Optional[Any] = None,
    ) -> AcquisitionCoordinationResult:
        if before.acquisition_plan is None:
            raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: preflight plan missing")
        route_inputs = self._route_inputs(before)
        execution = self._execution.execute(
            plan=before.acquisition_plan,
            task_id=task_id,
            scenario=scenario,
            as_of=task_as_of,
            dry_run=dry_run,
            live_authorized=self._live_authorized,
            route_inputs=route_inputs,
        )

        try:
            after = self._preflight.recheck(
                scenario=scenario,
                task_id=task_id,
                task_as_of=task_as_of,
                normalized_request=dict(normalized_request),
                project_root=project_root,
                db=db,
                runs_root=runs_root,
                graph_repo=graph_repo,
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001 -- never retain arbitrary exception detail
            if not self._has_committed_attempt(execution):
                raise ValueError(
                    "CONTROL_PLANE_CONFIGURATION_ERROR: readiness recheck failed"
                ) from exc
            execution = execution.model_copy(update={
                "status": "partial_success",
                "readiness_after_requirement_ids": [],
                "errors": [
                    *execution.errors,
                    AcquisitionExecutionError(
                        code="RECHECK_FAILED",
                        message="authoritative readiness recheck failed",
                        component="data_preflight",
                    ),
                ],
            }, deep=True)
            after = None

        if after is not None:
            execution = execution.model_copy(update={
                "readiness_after_requirement_ids": [
                    item.requirement_id for item in after.readiness
                ],
            }, deep=True)
        return AcquisitionCoordinationResult(before, execution, after)

    @staticmethod
    def _route_inputs(bundle: DataPreflightBundle) -> dict[str, RouteExecutionInput]:
        inputs: dict[str, RouteExecutionInput] = {}
        for context in bundle.contexts:
            requirement_id = context.requirement.requirement_id
            query = {
                "entity_ids": list(context.entity_ids),
                "peer_entity_ids": list(context.peer_entity_ids),
                "industry_ids": list(context.industry_ids),
                "watchlist_group": context.watchlist_group,
                "request_material_refs": list(context.request_material_refs),
            }
            inputs[requirement_id] = RouteExecutionInput(
                query=query,
                time_window={"start": context.window_start, "end": context.as_of},
            )
        return inputs

    @staticmethod
    def _has_committed_attempt(result: AcquisitionExecutionResult) -> bool:
        return any(
            step.route is not None
            and step.status in {"completed", "partial_success"}
            and "PERSIST_FAILED" not in step.reason_codes
            for step in result.steps
        )

    @staticmethod
    def persist_artifacts(run_dir: Path, result: AcquisitionCoordinationResult) -> None:
        """Persist P7-D2 artifacts atomically after a non-dry-run coordination."""
        payload = result.execution.model_dump()
        errors = validate_instance(payload, "acquisition_execution_result")
        if errors:
            raise ValueError(f"AcquisitionExecutionResult 未通过 Schema 校验: {errors}")
        _atomic_write(run_dir / "acquisition_execution.json", json_dumps(payload))
        if result.readiness_after is not None:
            DataPreflightService.persist_readiness_after(run_dir, result.readiness_after)


__all__ = ["AcquisitionCoordinationResult", "AcquisitionCoordinator"]
