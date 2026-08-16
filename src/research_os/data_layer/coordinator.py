"""P7-D2 acquisition coordinator and authoritative readiness recheck.

The coordinator owns sequencing only.  It projects Router inputs from the P7-D1 resolved
requirement contexts, delegates all execution gates to ``AcquisitionExecutionService``, and asks
the *same* ``DataPreflightService`` instance to re-evaluate readiness after persistence.
"""
from __future__ import annotations

import os
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
        if before.acquisition_plan is None:
            raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: preflight plan missing")
        route_inputs = self._route_inputs(before)
        execution = self._validated_execution(self._execution.execute(
            plan=before.acquisition_plan,
            task_id=task_id,
            scenario=scenario,
            as_of=task_as_of,
            dry_run=dry_run,
            live_authorized=self._live_authorized,
            route_inputs=route_inputs,
        ))
        persistence_committed = self._has_committed_attempt(execution)

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
