"""P7-D2 acquisition coordinator and authoritative readiness recheck.

The coordinator owns sequencing only.  It projects Router inputs from the P7-D1 resolved
requirement contexts, delegates all execution gates to ``AcquisitionExecutionService``, and asks
the *same* ``DataPreflightService`` instance to re-evaluate readiness after persistence.
"""
from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional

from research_os.data_layer.execution import (
    AcquisitionExecutionService,
    RouteExecutionInput,
    canonical_plan_sha256,
    deterministic_execution_id,
)
from research_os.data_layer.preflight import DataPreflightBundle, DataPreflightService, _atomic_write, json_dumps
from research_os.models import AcquisitionExecutionError, AcquisitionExecutionResult
from research_os.utils.time import parse_iso, validate_iso
from research_os.validators.schema_validator import validate_instance


def _canonical_request_bytes(value: Any) -> bytes:
    """Copy exact JSON builtins into one canonical, cycle-free authority encoding."""
    active_containers: set[int] = set()

    def snapshot(item: Any) -> Any:
        item_type = type(item)
        if item_type is dict:
            identity = id(item)
            if identity in active_containers:
                raise ValueError("cyclic request container")
            active_containers.add(identity)
            try:
                result: dict[str, Any] = {}
                for key, child in item.items():
                    if type(key) is not str:
                        raise TypeError("request keys must be exact strings")
                    result[key] = snapshot(child)
                return result
            finally:
                active_containers.remove(identity)
        if item_type is list:
            identity = id(item)
            if identity in active_containers:
                raise ValueError("cyclic request container")
            active_containers.add(identity)
            try:
                return [snapshot(child) for child in item]
            finally:
                active_containers.remove(identity)
        if item is None or item_type in {str, bool, int}:
            return item
        if item_type is float and math.isfinite(item):
            return item
        raise TypeError("request contains a non-canonical JSON value")

    if type(value) is not dict:
        raise TypeError("normalized request must be an exact dict")
    canonical = snapshot(value)
    return json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class AcquisitionCoordinationResult:
    """Internal aggregate passed to the existing Runner context."""

    readiness_before: DataPreflightBundle
    execution: AcquisitionExecutionResult
    readiness_after: Optional[DataPreflightBundle]
    persistence_committed: bool


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
        try:
            authoritative_request = _canonical_request_bytes(normalized_request)
            recheck_request = json.loads(authoritative_request)
        except Exception:  # noqa: BLE001 -- request contents are untrusted
            raise ValueError(
                "CONTROL_PLANE_CONFIGURATION_ERROR: normalized request canonicalization failed"
            ) from None
        if before.acquisition_plan is None:
            raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: preflight plan missing")
        # Freeze both preflight authorities before entering the injected execution boundary.
        authoritative_plan = deepcopy(before.acquisition_plan.model_dump())
        authoritative_requirements = tuple(
            (item.requirement_id, item.data_type) for item in before.requirements
        )
        if tuple(
            (item.requirement_id, item.data_type) for item in before.readiness
        ) != authoritative_requirements:
            raise ValueError(
                "CONTROL_PLANE_CONFIGURATION_ERROR: preflight authority mismatch"
            )
        authoritative_readiness_ids = tuple(item[0] for item in authoritative_requirements)
        route_inputs = self._route_inputs(before)
        execution = self._validated_execution(self._execution.execute(
            plan=before.acquisition_plan.model_copy(deep=True),
            task_id=task_id,
            scenario=scenario,
            as_of=task_as_of,
            dry_run=dry_run,
            live_authorized=self._live_authorized,
            route_inputs=route_inputs,
        ))
        self._assert_execution_authority(
            execution,
            plan_payload=authoritative_plan,
            readiness_before_ids=authoritative_readiness_ids,
            task_id=task_id,
            scenario=scenario,
            task_as_of=task_as_of,
        )
        persistence_committed = self._has_committed_attempt(execution)

        try:
            after = self._preflight.recheck(
                scenario=scenario,
                task_id=task_id,
                task_as_of=task_as_of,
                normalized_request=recheck_request,
                project_root=project_root,
                db=db,
                runs_root=runs_root,
                graph_repo=graph_repo,
                dry_run=dry_run,
            )
            if _canonical_request_bytes(recheck_request) != authoritative_request:
                raise ValueError("normalized request collaborator mutation")
            if type(after.checked_at) is not str or not validate_iso(after.checked_at):
                raise ValueError("invalid candidate recheck checked_at")
            DataPreflightService.assert_recheck_bundle_authority(
                self._preflight,
                after,
                task_id=task_id,
                scenario=scenario,
                task_as_of=task_as_of,
                normalized_request=json.loads(authoritative_request),
            )
            authoritative_after = DataPreflightService.run(
                self._preflight,
                scenario=scenario,
                task_id=task_id,
                task_as_of=task_as_of,
                normalized_request=json.loads(authoritative_request),
                project_root=project_root,
                db=db,
                runs_root=runs_root,
                graph_repo=graph_repo,
                dry_run=dry_run,
                checked_at=after.checked_at,
            )
            DataPreflightService.assert_recheck_bundle_authority(
                self._preflight,
                authoritative_after,
                task_id=task_id,
                scenario=scenario,
                task_as_of=task_as_of,
                normalized_request=json.loads(authoritative_request),
            )
            candidate_payload = (
                DataPreflightService.canonical_recheck_bundle_authority_payload(
                    self._preflight, after,
                )
            )
            authoritative_payload = (
                DataPreflightService.canonical_recheck_bundle_authority_payload(
                    self._preflight, authoritative_after,
                )
            )
            if candidate_payload != authoritative_payload:
                raise ValueError("candidate recheck differs from independent authority")
            after = authoritative_after
        except Exception as exc:  # noqa: BLE001 -- never retain arbitrary exception detail
            if not persistence_committed:
                raise ValueError(
                    "CONTROL_PLANE_CONFIGURATION_ERROR: readiness recheck failed"
                ) from exc
            execution = self._updated_execution(execution, {
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
            })
            after = None

        if after is not None:
            execution = self._updated_execution(execution, {
                "readiness_after_requirement_ids": [
                    item.requirement_id for item in after.readiness
                ],
            })
        return AcquisitionCoordinationResult(
            before, execution, after, persistence_committed,
        )

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
            and (
                step.status in {"completed", "partial_success"}
                or (
                    step.status == "failed"
                    and "FUTURE_ITEM_REJECTED" in step.reason_codes
                )
            )
            and not set(step.reason_codes).intersection({
                "RAW_ITEM_SCHEMA_INVALID", "PERSIST_FAILED", "ROUTE_UNAVAILABLE",
            })
            for step in result.steps
        )

    @staticmethod
    def _validated_execution(value: Any) -> AcquisitionExecutionResult:
        """Reconstruct and validate every collaborator result against both authorities."""
        try:
            payload = value.model_dump() if hasattr(value, "model_dump") else value
            checked = AcquisitionExecutionResult.model_validate(payload)
            errors = validate_instance(checked.model_dump(), "acquisition_execution_result")
            if errors:
                raise ValueError(str(errors))
            return checked
        except Exception as exc:  # noqa: BLE001 -- collaborator output is untrusted
            raise ValueError(
                "CONTROL_PLANE_CONFIGURATION_ERROR: invalid acquisition execution result"
            ) from exc

    @staticmethod
    def _assert_execution_authority(
        execution: AcquisitionExecutionResult,
        *,
        plan_payload: Mapping[str, Any],
        readiness_before_ids: tuple[str, ...],
        task_id: str,
        scenario: str,
        task_as_of: str,
    ) -> None:
        """Bind a schema-valid collaborator audit to its exact invocation authorities."""
        try:
            plan_steps = tuple(
                (
                    step["step_id"], step["requirement_id"],
                    step["data_type"], step["action"],
                )
                for step in plan_payload["steps"]
            )
            audit_steps = tuple(
                (step.step_id, step.requirement_id, step.data_type, step.action)
                for step in execution.steps
            )
            plan_hash = canonical_plan_sha256(plan_payload)
            authority_matches = (
                plan_payload["task_id"] == task_id == execution.task_id
                and plan_payload["scenario"] == scenario == execution.scenario
                and parse_iso(str(plan_payload["as_of"])) == parse_iso(task_as_of)
                and parse_iso(execution.as_of) == parse_iso(task_as_of)
                and execution.plan_sha256 == plan_hash
                and execution.execution_id
                == deterministic_execution_id(task_id, plan_hash)
                and audit_steps == plan_steps
                and tuple(execution.readiness_before_requirement_ids)
                == readiness_before_ids
                # M2 initializes both sides from the same preflight authority; the
                # coordinator replaces the after-side only after authoritative recheck.
                and tuple(execution.readiness_after_requirement_ids)
                == readiness_before_ids
            )
        except Exception:  # noqa: BLE001 -- all boundary detail is untrusted
            authority_matches = False
        if not authority_matches:
            raise ValueError(
                "CONTROL_PLANE_CONFIGURATION_ERROR: execution audit authority mismatch"
            )

    @classmethod
    def _updated_execution(
        cls, execution: AcquisitionExecutionResult, updates: Mapping[str, Any],
    ) -> AcquisitionExecutionResult:
        payload = execution.model_dump()
        payload.update(dict(updates))
        return cls._validated_execution(payload)

    @staticmethod
    def persist_artifacts(run_dir: Path, result: AcquisitionCoordinationResult) -> None:
        """Prevalidate, stage, and publish the P7-D2 artifact pair as one best-effort unit."""
        execution = AcquisitionCoordinator._validated_execution(result.execution)
        execution_text = json_dumps(execution.model_dump())
        execution_path = run_dir / "acquisition_execution.json"
        if result.readiness_after is None:
            original: bytes | None = None
            existed = False
            original_captured = False
            try:
                existed = execution_path.exists()
                original = execution_path.read_bytes() if existed else None
                original_captured = True
                _atomic_write(execution_path, execution_text)
            except OSError:
                if original_captured:
                    AcquisitionCoordinator._restore_artifact_pair({
                        execution_path: original if existed else None,
                    })
                AcquisitionCoordinator._cleanup_artifact_temps((execution_path,))
                raise ValueError(
                    "CONTROL_PLANE_CONFIGURATION_ERROR: acquisition artifact publish failed"
                ) from None
            return

        readiness_text = AcquisitionCoordinator._serialize_readiness_after(
            result.readiness_after,
        )
        readiness_path = run_dir / "data_readiness_after.jsonl"
        staged_execution = execution_path.with_suffix(execution_path.suffix + ".p7d2.tmp")
        staged_readiness = readiness_path.with_suffix(readiness_path.suffix + ".p7d2.tmp")
        originals: dict[Path, bytes | None] = {}
        try:
            originals = {
                execution_path: execution_path.read_bytes() if execution_path.exists() else None,
                readiness_path: readiness_path.read_bytes() if readiness_path.exists() else None,
            }
            staged_execution.write_text(execution_text, encoding="utf-8")
            staged_readiness.write_text(readiness_text, encoding="utf-8")
            os.replace(staged_execution, execution_path)
            os.replace(staged_readiness, readiness_path)
        except OSError:
            AcquisitionCoordinator._restore_artifact_pair(originals)
            raise ValueError(
                "CONTROL_PLANE_CONFIGURATION_ERROR: acquisition artifact publish failed"
            ) from None
        finally:
            AcquisitionCoordinator._cleanup_artifact_temps((
                execution_path, readiness_path,
            ))

    @staticmethod
    def _serialize_readiness_after(bundle: DataPreflightBundle) -> str:
        lines: list[str] = []
        for readiness in bundle.readiness:
            payload = readiness.model_dump()
            errors = validate_instance(payload, "data_readiness")
            if errors:
                raise ValueError(f"DataReadiness 未通过 Schema 校验: {errors}")
            lines.append(json_dumps(payload))
        return "\n".join(lines) + "\n"

    @staticmethod
    def _restore_artifact_pair(originals: Mapping[Path, bytes | None]) -> None:
        """Best-effort rollback; never leave a newly published half-pair."""
        for path, original in originals.items():
            try:
                if original is None:
                    path.unlink(missing_ok=True)
                else:
                    rollback = path.with_suffix(path.suffix + ".rollback.tmp")
                    rollback.write_bytes(original)
                    os.replace(rollback, path)
            except Exception:  # noqa: BLE001 -- rollback is explicitly best effort
                # The original publishing exception remains authoritative.
                pass

    @staticmethod
    def _cleanup_artifact_temps(paths: tuple[Path, ...]) -> None:
        for path in paths:
            for suffix in (".p7d2.tmp", ".rollback.tmp", ".tmp"):
                temporary = path.with_suffix(path.suffix + suffix)
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


__all__ = ["AcquisitionCoordinationResult", "AcquisitionCoordinator"]
