"""P7-D2 M1: existing Router batch return and injected Collector bridge."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from research_os.collectors import (
    CollectorAdapter,
    HealthStatus,
    ItemRef,
    RateLimitPolicy,
    RawPayload,
)
from research_os.data_layer.collector_bridge import CollectorFetcherBridge
from research_os.models import RawItem
from research_os.routing.requirements import DataRequirementRegistry
from research_os.routing.router import Router


REQS = """
requirements:
  document:
    primary: [primary]
    secondary: [secondary]
    fallback: [manual]
    minimum_acceptable:
      fields: [title, published_at, url]
    failure_policy: degraded
"""


@pytest.fixture()
def requirements(tmp_path: Path) -> DataRequirementRegistry:
    path = tmp_path / "requirements.yaml"
    path.write_text(REQS, encoding="utf-8")
    return DataRequirementRegistry(path)


def _fetch(items: Optional[List[Any]] = None, fields=(), error: Exception | None = None):
    def fetch(data_type, query, time_window):
        if error is not None:
            raise error
        return list(items or []), set(fields)

    return fetch


@pytest.mark.parametrize(
    ("fetchers", "fallbacks", "expected"),
    [
        (
            {"primary": _fetch([{"id": 1}], {"title", "published_at", "url"})},
            {},
            {
                "requested_sources": ["primary", "secondary"],
                "attempted_sources": ["primary"],
                "selected_source": "primary",
                "fallback_used": False,
                "status": "success",
                "missing_fields": [],
                "warnings": [],
            },
        ),
        (
            {
                "primary": _fetch(error=RuntimeError("primary failed")),
                "secondary": _fetch([{"id": 2}], {"title", "published_at", "url"}),
            },
            {},
            {
                "attempted_sources": ["primary", "secondary"],
                "selected_source": "secondary",
                "fallback_used": False,
                "status": "success",
                "warnings": ["primary 获取失败: primary failed"],
            },
        ),
        (
            {
                "primary": _fetch(error=RuntimeError("p")),
                "secondary": _fetch(error=RuntimeError("s")),
            },
            {"manual": _fetch([{"id": 3}], {"title", "published_at", "url"})},
            {
                "attempted_sources": ["primary", "secondary", "manual"],
                "selected_source": "manual",
                "fallback_used": True,
                "status": "degraded",
            },
        ),
        (
            {"primary": _fetch([{"id": 1}], {"title"})},
            {},
            {
                "attempted_sources": ["primary", "secondary", "manual"],
                "selected_source": None,
                "status": "insufficient_data",
                "missing_fields": ["published_at", "url"],
            },
        ),
        (
            {"primary": _fetch([], {"title", "published_at", "url"})},
            {},
            {
                "attempted_sources": ["primary"],
                "selected_source": "primary",
                "status": "success",
                "warnings": ["返回为空结果（不等于无事件，调用方不得据此推断业务无变化）"],
            },
        ),
        (
            {},
            {},
            {
                "attempted_sources": ["primary", "secondary", "manual"],
                "selected_source": None,
                "status": "insufficient_data",
                "warnings": [
                    "primary 无可用获取器",
                    "secondary 无可用获取器",
                    "manual 无可用兜底获取器",
                ],
            },
        ),
        (
            {
                "primary": _fetch(error=RuntimeError("p")),
                "secondary": _fetch(error=RuntimeError("s")),
            },
            {"manual": _fetch(error=RuntimeError("m"))},
            {
                "attempted_sources": ["primary", "secondary", "manual"],
                "selected_source": None,
                "status": "insufficient_data",
                "warnings": [
                    "primary 获取失败: p",
                    "secondary 获取失败: s",
                    "manual 兜底失败: m",
                ],
            },
        ),
    ],
)
def test_resolve_compatibility(requirements, fetchers, fallbacks, expected):
    route = Router(requirements, fetchers, fallbacks).resolve("document")
    dumped = route.model_dump()
    for key, value in expected.items():
        assert dumped[key] == value


def test_resolve_with_items_has_exact_decision_parity(requirements):
    def make_router():
        return Router(
            requirements,
            {
                "primary": _fetch(error=RuntimeError("p")),
                "secondary": _fetch([{"id": 2}], {"title", "published_at", "url"}),
            },
        )

    route = make_router().resolve("document", {"q": "x"}, {"end": "2026-08-16"})
    batch = make_router().resolve_with_items(
        "document", {"q": "x"}, {"end": "2026-08-16"}
    )
    assert batch.route == route
    assert batch.items == ({"id": 2},)
    assert batch.fields_present == frozenset({"title", "published_at", "url"})


def test_resolve_with_items_fallback_and_failure_batches(requirements):
    fallback = Router(
        requirements,
        {
            "primary": _fetch(error=RuntimeError("p")),
            "secondary": _fetch(error=RuntimeError("s")),
        },
        {"manual": _fetch([{"id": "manual"}], {"title", "published_at", "url"})},
    ).resolve_with_items("document")
    assert fallback.route.status == "degraded"
    assert fallback.route.selected_source == "manual"
    assert fallback.items == ({"id": "manual"},)

    failed = Router(
        requirements,
        {
            "primary": _fetch(error=RuntimeError("p")),
            "secondary": _fetch(error=RuntimeError("s")),
        },
        {"manual": _fetch(error=RuntimeError("m"))},
    ).resolve_with_items("document")
    assert failed.route.status == "insufficient_data"
    assert failed.items == ()
    assert failed.fields_present == frozenset()


def test_resolve_with_items_does_not_leak_rejected_source_items(requirements):
    batch = Router(
        requirements,
        {
            "primary": _fetch([{"id": "rejected"}], {"title"}),
            "secondary": _fetch(
                [{"id": "selected"}], {"title", "published_at", "url"}
            ),
        },
    ).resolve_with_items("document")
    assert batch.route.selected_source == "secondary"
    assert batch.items == ({"id": "selected"},)


def test_routed_batch_defensively_isolates_fetcher_mutables(requirements):
    shared_item = {"nested": ["original"]}
    shared_items = [shared_item]
    shared_fields = {"title", "published_at", "url"}

    def shared_fetcher(data_type, query, time_window):
        return shared_items, shared_fields

    router = Router(requirements, {"primary": shared_fetcher})
    batch = router.resolve_with_items("document")

    shared_item["nested"].append("fetcher mutation")
    shared_items.append({"nested": ["new"]})
    shared_fields.add("company")
    assert batch.items == ({"nested": ["original"]},)
    assert "company" not in batch.fields_present

    batch.items[0]["nested"].append("batch mutation")
    batch.route.warnings.append("batch route mutation")
    assert shared_item["nested"] == ["original", "fetcher mutation"]
    fresh = router.resolve_with_items("document")
    assert "batch route mutation" not in fresh.route.warnings


def test_legacy_resolve_does_not_copy_discarded_fetch_items(requirements):
    class UncopyableItem:
        def __deepcopy__(self, memo):
            raise RuntimeError("item snapshot prohibited")

    def fetcher(data_type, query, time_window):
        return [UncopyableItem()], {"title", "published_at", "url"}

    router = Router(requirements, {"primary": fetcher})
    assert router.resolve("document").status == "success"
    with pytest.raises(RuntimeError, match="item snapshot prohibited"):
        router.resolve_with_items("document")


def _raw(source_id: str, suffix: str) -> RawItem:
    return RawItem(
        raw_item_id=f"00000000-0000-0000-0000-{int(suffix):012d}",
        source_id=source_id,
        external_id=suffix,
        url=f"https://example.test/{suffix}",
        title=f"title-{suffix}",
        publisher="publisher",
        author=None,
        published_at="2026-08-16T08:00:00+08:00",
        retrieved_at="2026-08-16T09:00:00+08:00",
        content_hash=hashlib.sha256(suffix.encode()).hexdigest(),
        content_excerpt="excerpt",
        content_storage="metadata_and_excerpt",
        language="zh-CN",
        access_status="ok",
        entities=[],
        raw_category=None,
    )


class FakeCollector(CollectorAdapter):
    source_id = "fake"
    version = "1.2.3"

    def __init__(self, refs: List[ItemRef] | None = None):
        self.refs = refs if refs is not None else [
            ItemRef(source_id="fake", external_id="1", url="https://example.test/1"),
            ItemRef(source_id="fake", external_id="2", url="https://example.test/2"),
        ]
        self.calls: List[str] = []
        self.payload_source = "fake"
        self.item_source = "fake"
        self.fail_fetch_for: str | None = None
        self.fetch_error = "Authorization: Bearer top-secret-token"
        self.invalid_item = False
        self.extra_item = False

    def healthcheck(self) -> HealthStatus:
        raise AssertionError("bridge must not healthcheck or access network by default")

    def discover(self, query: Dict[str, Any], time_window: Dict[str, Optional[str]]):
        self.calls.append("discover")
        return self.refs

    def fetch(self, item_ref: ItemRef) -> RawPayload:
        self.calls.append(f"fetch:{item_ref.external_id}")
        if item_ref.external_id == self.fail_fetch_for:
            raise RuntimeError(self.fetch_error)
        return RawPayload(
            source_id=self.payload_source,
            external_id=item_ref.external_id,
            url=item_ref.url,
            title=item_ref.external_id,
            publisher="publisher",
            retrieved_at="2026-08-16T09:00:00+08:00",
        )

    def normalize(self, raw_payload: RawPayload) -> List[RawItem]:
        self.calls.append(f"normalize:{raw_payload.external_id}")
        item = _raw(self.item_source, raw_payload.external_id)
        if raw_payload.external_id == "1":
            object.__setattr__(item, "entities", ["company:1"])
            object.__setattr__(item, "raw_category", "news")
        if self.invalid_item:
            object.__setattr__(item, "content_hash", "invalid")
        result = [item]
        if self.extra_item and raw_payload.external_id == "1":
            result.append(_raw(self.item_source, "3"))
        return result

    def rate_limit_policy(self) -> RateLimitPolicy:
        return RateLimitPolicy(requests_per_minute=12, max_retries=2)


def test_bridge_discover_fetch_normalize_order_multiple_refs_and_items():
    fake = FakeCollector()
    fake.extra_item = True
    fetcher = CollectorFetcherBridge({"fake": fake}).fetchers["fake"]
    items, fields = fetcher("macro_data", {"q": "x"}, {"start": None, "end": None})
    assert fake.calls == ["discover", "fetch:1", "normalize:1", "fetch:2", "normalize:2"]
    assert [item.external_id for item in items] == ["1", "3", "2"]
    assert isinstance(fields, frozenset)
    assert fields == frozenset({
        "raw_item_id", "source_id", "external_id", "url", "title", "publisher",
        "published_at", "retrieved_at", "content_hash", "content_excerpt",
        "content_storage", "language", "access_status",
    })
    assert items[0].entities == ["company:1"]
    assert items[0].raw_category == "news"
    assert "author" not in fields
    assert "raw_category" not in fields
    assert "entities" not in fields


def test_bridge_fields_are_raw_item_contract_only_without_semantic_aliases():
    fake = FakeCollector(refs=[ItemRef(
        source_id="fake",
        external_id="1",
        url="https://example.test/1",
        extra={"company": "company:1", "publish_date": "2026-08-16"},
    )])
    _, fields = CollectorFetcherBridge({"fake": fake}).fetchers["fake"]("macro_data", {}, {})
    assert "published_at" in fields
    assert "company" not in fields
    assert "publish_date" not in fields


@pytest.mark.parametrize("boundary", ["ref", "payload", "item"])
def test_bridge_rejects_source_mismatch_at_every_boundary(boundary):
    fake = FakeCollector()
    if boundary == "ref":
        fake.refs[0] = fake.refs[0].model_copy(update={"source_id": "other"})
    elif boundary == "payload":
        fake.payload_source = "other"
    else:
        fake.item_source = "other"
    with pytest.raises(RuntimeError, match="collector fake attempt failed"):
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]("macro_data", {}, {})


def test_bridge_invalid_raw_item_fails_closed():
    fake = FakeCollector()
    fake.invalid_item = True
    with pytest.raises(RuntimeError, match="collector fake attempt failed"):
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]("macro_data", {}, {})


@pytest.mark.parametrize(
    "error_message",
    [
        "Authorization Bearer delimiter-free-secret",
        "Cookie sessionid delimiter-free-cookie",
        "token top-secret",
        "<html><body>private upstream page and full payload</body></html>",
        "token refresh failed before a credential was returned",
        "ordinary adapter failure prose",
    ],
)
def test_bridge_discards_all_untrusted_adapter_exception_detail(error_message):
    fake = FakeCollector()
    fake.fail_fetch_for = "2"
    fake.fetch_error = error_message
    with pytest.raises(RuntimeError) as raised:
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]("macro_data", {}, {})
    assert str(raised.value) == "collector fake attempt failed"
    assert error_message not in str(raised.value)


@pytest.mark.parametrize("legacy", [False, True])
def test_bridge_failure_is_constant_through_router_primary_fallback_warning(
    requirements, legacy,
):
    fake = FakeCollector()
    fake.fail_fetch_for = "2"
    fake.fetch_error = "Authorization Bearer delimiter-free-secret full upstream payload"
    bridge = CollectorFetcherBridge({"fake": fake})
    router = Router(
        requirements,
        {"primary": bridge.fetchers["fake"]},
        {"manual": _fetch([{"id": "fallback"}], {"title", "published_at", "url"})},
    )
    result = router.resolve("document") if legacy else router.resolve_with_items("document").route
    warnings = " ".join(result.warnings)
    assert result.selected_source == "manual"
    assert "collector fake attempt failed" in warnings
    assert "delimiter-free-secret" not in warnings
    assert "upstream payload" not in warnings


def test_bridge_empty_discover_proves_no_fields_and_does_no_more_work():
    fake = FakeCollector(refs=[])
    items, fields = CollectorFetcherBridge({"fake": fake}).fetchers["fake"]("macro_data", {}, {})
    assert items == []
    assert fields == frozenset()
    assert fake.calls == ["discover"]


def test_bridge_is_injected_only_and_does_nothing_on_construction():
    fake = FakeCollector()
    bridge = CollectorFetcherBridge({"fake": fake})
    assert set(bridge.fetchers) == {"fake"}
    assert fake.calls == []
