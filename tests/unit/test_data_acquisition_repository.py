from __future__ import annotations

import json
import uuid

import pytest

from research_os.data_layer.acquisition_repository import (
    AcquisitionRepository,
    canonicalize_http_url,
    stable_raw_item_id,
)
from research_os.data_layer.execution import AcquisitionStepFailure
from research_os.models import DataRoute, RawItem
from research_os.storage.db import Database


AS_OF = "2026-08-16T09:30:00+08:00"
RETRIEVED = "2026-08-16T10:00:00+08:00"
HASH_A = "a" * 64
HASH_B = "b" * 64


def _route() -> DataRoute:
    return DataRoute(
        data_type="fake_data", requested_sources=["fake-source"],
        attempted_sources=["fake-source"], selected_source="fake-source",
        fallback_used=False, status="success", missing_fields=[], warnings=[],
    )


def _item(
    *, external_id: str | None = "article-1", content_hash: str = HASH_A,
    url: str = "https://Example.COM:443/news?id=2&keep=x&id=1#fragment",
    published_at: str = "2026-08-16T09:00:00+08:00",
    retrieved_at: str = RETRIEVED,
) -> RawItem:
    return RawItem(
        raw_item_id=str(uuid.uuid4()), source_id="fake-source",
        external_id=external_id, url=url, title="fixture", publisher="fixture",
        author=None, published_at=published_at, retrieved_at=retrieved_at,
        content_hash=content_hash, content_excerpt="excerpt",
        content_storage="metadata_and_excerpt", language="zh-CN",
        access_status="ok", entities=[], raw_category="news_flash",
    )


@pytest.fixture
def db(tmp_path):
    value = Database(tmp_path / "research.db")
    value.initialize()
    yield value
    value.close()


def _persist(repository: AcquisitionRepository, items):
    return repository.persist_batch(
        task_id="task-1", step_id="step-1", as_of=AS_OF,
        route=_route(), items=tuple(items),
    )


def test_canonical_url_performs_only_frozen_normalization():
    assert canonicalize_http_url(
        "HTTPS://Example.COM:443/a/%2F?q=z&keep=&q=a#frag"
    ) == "https://example.com/a/%2F?keep=&q=a&q=z"
    assert canonicalize_http_url("http://EXAMPLE.com:80") == "http://example.com"
    assert canonicalize_http_url("https://EXAMPLE.com:444/A?x=%2F") == (
        "https://example.com:444/A?x=%2F"
    )
    with pytest.raises(ValueError):
        canonicalize_http_url("ftp://example.com/file")


def test_stable_identity_uses_external_id_or_canonical_http_url():
    external = _item()
    same_external_other_url = _item(url="https://different.example/item")
    assert stable_raw_item_id(external) == stable_raw_item_id(same_external_other_url)
    assert uuid.UUID(stable_raw_item_id(external)).version == 5

    by_url = _item(external_id=None)
    equivalent = _item(
        external_id=None,
        url="https://example.com/news?id=1&keep=x&id=2#other",
    )
    assert stable_raw_item_id(by_url) == stable_raw_item_id(equivalent)
    assert stable_raw_item_id(by_url) != stable_raw_item_id(
        _item(external_id=None, content_hash=HASH_B),
    )


def test_replay_reuses_first_payload_and_changed_content_is_new_version(db):
    repository = AcquisitionRepository(db, clock=lambda: RETRIEVED)
    first = _item(retrieved_at=RETRIEVED)
    result = _persist(repository, [first])
    persisted_id = result.inserted_raw_item_ids[0]

    replay = _item(retrieved_at="2026-08-16T11:00:00+08:00")
    replay_result = _persist(repository, [replay])
    assert replay_result.reused_raw_item_ids == (persisted_id,)
    assert db.get("raw_items", persisted_id)["retrieved_at"] == RETRIEVED

    changed = _item(content_hash=HASH_B)
    changed_result = _persist(repository, [changed])
    assert changed_result.inserted_raw_item_ids != (persisted_id,)
    assert db.count("raw_items") == 2
    assert db.count("data_routes") == 3


def test_duplicate_normalized_items_are_first_wins_and_accounted(db):
    repository = AcquisitionRepository(db)
    result = _persist(repository, [
        _item(retrieved_at=RETRIEVED),
        _item(retrieved_at="2026-08-16T11:00:00+08:00"),
    ])
    assert len(result.inserted_raw_item_ids) == 1
    assert result.deduplicated_input_count == 1
    assert db.get("raw_items", result.inserted_raw_item_ids[0])["retrieved_at"] == RETRIEVED


def test_future_items_compare_instants_and_are_not_written(db):
    repository = AcquisitionRepository(db)
    result = _persist(repository, [
        _item(external_id="future", published_at="2026-08-16T01:31:00Z"),
        _item(external_id="eligible", published_at="2026-08-16T01:30:00Z"),
    ])
    assert result.rejected_future_item_count == 1
    assert len(result.inserted_raw_item_ids) == 1
    assert db.count("raw_items") == 1
    assert db.count("data_routes") == 1


@pytest.mark.parametrize("field,value", [
    ("published_at", ""), ("published_at", "not-a-time"),
    ("retrieved_at", ""), ("retrieved_at", "not-a-time"),
])
def test_malformed_timestamps_fail_before_transaction(db, monkeypatch, field, value):
    repository = AcquisitionRepository(db)
    item = _item().model_construct(**{**_item().model_dump(), field: value})
    entered = []
    original = db.transaction

    def transaction():
        entered.append(True)
        return original()

    monkeypatch.setattr(db, "transaction", transaction)
    with pytest.raises(AcquisitionStepFailure) as exc:
        _persist(repository, [item])
    assert exc.value.reason_code == "RAW_ITEM_SCHEMA_INVALID"
    assert entered == []
    assert db.count("raw_items") == db.count("data_routes") == 0


def test_any_invalid_item_prevents_all_writes_and_source_mismatch_fails_closed(db):
    repository = AcquisitionRepository(db)
    invalid = _item().model_copy(update={"source_id": "other-source"})
    with pytest.raises(AcquisitionStepFailure) as exc:
        _persist(repository, [_item(external_id="valid"), invalid])
    assert exc.value.reason_code == "RAW_ITEM_SCHEMA_INVALID"
    assert db.count("raw_items") == db.count("data_routes") == 0


def test_uuid_collision_with_incompatible_identity_fails_closed(db, monkeypatch):
    repository = AcquisitionRepository(db)
    original_id = _persist(repository, [_item()]).inserted_raw_item_ids[0]
    monkeypatch.setattr(
        "research_os.data_layer.acquisition_repository.stable_raw_item_id",
        lambda item: original_id,
    )
    with pytest.raises(AcquisitionStepFailure) as exc:
        _persist(repository, [_item(external_id="different", content_hash=HASH_B)])
    assert exc.value.reason_code == "PERSIST_FAILED"
    assert db.count("raw_items") == 1
    assert db.count("data_routes") == 1


def test_second_item_failure_rolls_back_route_and_all_items(db, monkeypatch):
    repository = AcquisitionRepository(db)
    original = repository._insert_raw_item
    calls = []

    def fail_second(conn, item):
        calls.append(item.raw_item_id)
        if len(calls) == 2:
            raise RuntimeError("injected failure")
        return original(conn, item)

    monkeypatch.setattr(repository, "_insert_raw_item", fail_second)
    with pytest.raises(AcquisitionStepFailure) as exc:
        _persist(repository, [
            _item(external_id="one"), _item(external_id="two", content_hash=HASH_B),
        ])
    assert exc.value.reason_code == "PERSIST_FAILED"
    assert db.count("raw_items") == db.count("data_routes") == 0


def test_empty_batch_persists_only_route_audit(db):
    result = _persist(AcquisitionRepository(db), [])
    assert result.inserted_raw_item_ids == result.reused_raw_item_ids == ()
    assert result.rejected_future_item_count == result.deduplicated_input_count == 0
    assert db.count("raw_items") == 0
    assert db.count("data_routes") == 1
    payload = json.loads(db.query("SELECT payload FROM data_routes")[0]["payload"])
    assert payload == _route().model_dump()


def test_repository_never_uses_generic_upsert(db, monkeypatch):
    monkeypatch.setattr(db, "upsert", lambda *args, **kwargs: pytest.fail("upsert called"))
    _persist(AcquisitionRepository(db), [_item()])
    assert db.count("raw_items") == db.count("data_routes") == 1
