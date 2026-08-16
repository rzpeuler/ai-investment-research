"""Atomic, idempotent persistence for P7-D2 normalized acquisition batches.

The repository owns no collection or routing behavior.  It validates a complete routed batch,
replaces adapter IDs with deterministic UUID5 identities, and writes the route audit plus all new
RawItems in one existing SQLite v6 transaction.
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Sequence
from urllib.parse import urlsplit, urlunsplit

from research_os.data_layer.execution import (
    AcquisitionPersistenceResult,
    AcquisitionStepFailure,
)
from research_os.models import DataRoute, RawItem
from research_os.storage.db import Database
from research_os.utils.time import now_iso, parse_iso
from research_os.validators.schema_validator import validate_instance


_RAW_ITEM_NAMESPACE = uuid.UUID("6e666b4d-68ea-53c5-8ec8-b7f9ba66790f")


def canonicalize_http_url(value: str) -> str:
    """Apply only the URL normalization operations frozen by P7-D2."""
    if type(value) is not str or not value:
        raise ValueError("a nonempty HTTP URL is required")
    try:
        parts = urlsplit(value)
        scheme = parts.scheme.lower()
        if scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("a canonical HTTP URL requires scheme and host")
        # Accessing port performs strict numeric/range validation.
        port = parts.port
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid HTTP URL") from exc

    host = parts.hostname.lower()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    userinfo = ""
    if parts.username is not None:
        userinfo = parts.username
        if parts.password is not None:
            userinfo += f":{parts.password}"
        userinfo += "@"
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = f"{userinfo}{host}" + (f":{port}" if port is not None and not default_port else "")
    # Sort raw components so arbitrary names, duplicates, blanks, and escaping are preserved.
    query = "&".join(sorted(parts.query.split("&"))) if parts.query else ""
    return urlunsplit((scheme, netloc, parts.path, query, ""))


def _identity_components(item: RawItem) -> tuple[str, str, str, str]:
    if item.external_id is not None:
        if type(item.external_id) is not str or not item.external_id:
            raise ValueError("external_id must be null or a nonempty string")
        key_kind, key = "external_id", item.external_id
    else:
        key_kind, key = "canonical_url", canonicalize_http_url(item.url)
    return item.source_id, key_kind, key, item.content_hash


def stable_raw_item_id(item: RawItem) -> str:
    """Return the frozen UUID5 identity for a normalized RawItem."""
    components = _identity_components(item)
    name = json.dumps(components, ensure_ascii=False, separators=(",", ":"))
    return str(uuid.uuid5(_RAW_ITEM_NAMESPACE, name))


@dataclass(frozen=True)
class _PreparedItem:
    item: RawItem
    identity: tuple[str, str, str, str]
    is_future: bool


class AcquisitionRepository:
    """Persist one routed step without per-object commits or migration changes."""

    def __init__(self, db: Database, *, clock: Callable[[], str] = now_iso):
        self._db = db
        self._clock = clock

    def persist_batch(
        self,
        *,
        task_id: str,
        step_id: str,
        as_of: str,
        route: DataRoute,
        items: Sequence[Any],
    ) -> AcquisitionPersistenceResult:
        try:
            prepared_route, authoritative_as_of, created_at = self._validate_context(
                task_id=task_id, step_id=step_id, as_of=as_of, route=route,
            )
            prepared = self._prepare_all(
                items, selected_source=prepared_route.selected_source,
                authoritative_as_of=authoritative_as_of,
            )
        except AcquisitionStepFailure:
            raise
        except Exception as exc:
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID") from exc

        unique: list[_PreparedItem] = []
        seen: set[str] = set()
        deduplicated = 0
        for candidate in prepared:
            raw_id = candidate.item.raw_item_id
            if raw_id in seen:
                deduplicated += 1
                continue
            seen.add(raw_id)
            unique.append(candidate)

        future = [candidate for candidate in unique if candidate.is_future]
        eligible = [candidate for candidate in unique if not candidate.is_future]
        inserted: list[_PreparedItem] = []
        reused_ids: list[str] = []
        try:
            # Classification happens only after complete batch validation and before writes.
            for candidate in eligible:
                row = self._db.query(
                    "SELECT payload FROM raw_items WHERE raw_item_id = ?",
                    (candidate.item.raw_item_id,),
                )
                if not row:
                    inserted.append(candidate)
                    continue
                existing = self._load_existing(row[0]["payload"])
                if _identity_components(existing) != candidate.identity:
                    raise AcquisitionStepFailure("PERSIST_FAILED")
                reused_ids.append(candidate.item.raw_item_id)

            route_payload = self._dump(prepared_route.model_dump())
            with self._db.transaction() as conn:
                conn.execute(
                    "INSERT INTO data_routes "
                    "(data_type, payload, status, selected_source, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        prepared_route.data_type, route_payload, prepared_route.status,
                        prepared_route.selected_source, created_at,
                    ),
                )
                for candidate in inserted:
                    self._insert_raw_item(conn, candidate.item)
        except AcquisitionStepFailure:
            raise
        except Exception as exc:
            raise AcquisitionStepFailure("PERSIST_FAILED") from exc

        return AcquisitionPersistenceResult(
            inserted_raw_item_ids=tuple(candidate.item.raw_item_id for candidate in inserted),
            reused_raw_item_ids=tuple(reused_ids),
            rejected_future_item_count=len(future),
            deduplicated_input_count=deduplicated,
        )

    def _validate_context(
        self, *, task_id: str, step_id: str, as_of: str, route: DataRoute,
    ) -> tuple[DataRoute, Any, str]:
        if type(task_id) is not str or not task_id or type(step_id) is not str or not step_id:
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        if type(as_of) is not str:
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        authoritative_as_of = parse_iso(as_of)
        if not isinstance(route, DataRoute):
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        payload = route.model_dump()
        if validate_instance(payload, "data_route"):
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        checked = DataRoute.model_validate(payload)
        if (
            checked.status not in {"success", "degraded"}
            or not checked.selected_source
            or checked.missing_fields
        ):
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        created_at = self._clock()
        if type(created_at) is not str:
            raise AcquisitionStepFailure("PERSIST_FAILED")
        parse_iso(created_at)
        return checked.model_copy(deep=True), authoritative_as_of, created_at

    @staticmethod
    def _prepare_all(
        items: Sequence[Any], *, selected_source: str | None, authoritative_as_of: Any,
    ) -> list[_PreparedItem]:
        if isinstance(items, (str, bytes, bytearray)):
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
        try:
            snapshot = tuple(items)
        except TypeError as exc:
            raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID") from exc

        prepared = []
        for value in snapshot:
            if not isinstance(value, RawItem):
                raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
            payload = value.model_dump()
            if validate_instance(payload, "raw_item"):
                raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID")
            try:
                checked = RawItem.model_validate(payload)
                published = parse_iso(checked.published_at)
                parse_iso(checked.retrieved_at)
                if checked.source_id != selected_source:
                    raise ValueError("normalized item source differs from selected route")
                identity = _identity_components(checked)
                canonical_id = stable_raw_item_id(checked)
                checked = checked.model_copy(update={"raw_item_id": canonical_id}, deep=True)
                if validate_instance(checked.model_dump(), "raw_item"):
                    raise ValueError("canonical RawItem failed schema validation")
            except Exception as exc:
                raise AcquisitionStepFailure("RAW_ITEM_SCHEMA_INVALID") from exc
            prepared.append(_PreparedItem(
                item=checked, identity=identity, is_future=published > authoritative_as_of,
            ))
        return prepared

    @staticmethod
    def _load_existing(payload: str) -> RawItem:
        try:
            decoded = json.loads(payload)
            if validate_instance(decoded, "raw_item"):
                raise ValueError("stored RawItem is schema-invalid")
            return RawItem.model_validate(decoded)
        except Exception as exc:
            raise AcquisitionStepFailure("PERSIST_FAILED") from exc

    @staticmethod
    def _dump(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        )

    def _insert_raw_item(self, conn: Any, item: RawItem) -> None:
        payload = self._dump(item.model_dump())
        conn.execute(
            "INSERT INTO raw_items "
            "(raw_item_id, payload, source_id, content_hash, published_at, retrieved_at, "
            "access_status) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                item.raw_item_id, payload, item.source_id, item.content_hash,
                item.published_at, item.retrieved_at, item.access_status,
            ),
        )


__all__ = ["AcquisitionRepository", "canonicalize_http_url", "stable_raw_item_id"]
