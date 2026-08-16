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
    def fetch(query, time_window):
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
    assert batch.items == [{"id": 2}]
    assert batch.fields_present == {"title", "published_at", "url"}


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
    items, fields = fetcher({"q": "x"}, {"start": None, "end": None})
    assert fake.calls == ["discover", "fetch:1", "normalize:1", "fetch:2", "normalize:2"]
    assert [item.external_id for item in items] == ["1", "3", "2"]
    assert fields == set(items[0].model_dump(exclude_none=True))
    assert "author" not in fields
    assert "raw_category" not in fields


@pytest.mark.parametrize("boundary", ["ref", "payload", "item"])
def test_bridge_rejects_source_mismatch_at_every_boundary(boundary):
    fake = FakeCollector()
    if boundary == "ref":
        fake.refs[0] = fake.refs[0].model_copy(update={"source_id": "other"})
    elif boundary == "payload":
        fake.payload_source = "other"
    else:
        fake.item_source = "other"
    with pytest.raises(RuntimeError, match="source_id mismatch"):
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]({}, {})


def test_bridge_invalid_raw_item_fails_closed():
    fake = FakeCollector()
    fake.invalid_item = True
    with pytest.raises(RuntimeError, match="RawItem Schema validation failed"):
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]({}, {})


@pytest.mark.parametrize(
    ("error_message", "secret"),
    [
        ("Authorization: Bearer top-secret-token", "top-secret-token"),
        ('{"Authorization": "Bearer json-secret-token"}', "json-secret-token"),
        ("headers={'Authorization': 'Bearer dict-secret-token'}", "dict-secret-token"),
        ("headers={'Cookie': 'sessionid=top-secret-cookie'}", "top-secret-cookie"),
        ('{"Cookie": "sessionid=cookie-secret-with\'quote"}', "cookie-secret-with'quote"),
        ('headers={"X-API-Key": "x-api-key-secret"}', "x-api-key-secret"),
        ("api_key='api-key-secret'", "api-key-secret"),
        ('headers={"access_token": "access-token-secret"}', "access-token-secret"),
        ("headers={'X-Auth-Token': 'x-auth-token-secret'}", "x-auth-token-secret"),
        ("token=plain-token-secret", "plain-token-secret"),
    ],
)
def test_bridge_any_ref_failure_rejects_entire_source_and_sanitizes_secret(
    error_message, secret
):
    fake = FakeCollector()
    fake.fail_fetch_for = "2"
    fake.fetch_error = error_message
    with pytest.raises(RuntimeError) as raised:
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]({}, {})
    message = str(raised.value)
    assert secret not in message
    assert "[REDACTED]" in message


def test_bridge_sanitizer_does_not_over_redact_ordinary_error_text():
    fake = FakeCollector()
    fake.fail_fetch_for = "2"
    fake.fetch_error = "token refresh failed before a credential was returned"
    with pytest.raises(RuntimeError) as raised:
        CollectorFetcherBridge({"fake": fake}).fetchers["fake"]({}, {})
    assert "token refresh failed" in str(raised.value)
    assert "[REDACTED]" not in str(raised.value)


def test_bridge_empty_discover_proves_no_fields_and_does_no_more_work():
    fake = FakeCollector(refs=[])
    items, fields = CollectorFetcherBridge({"fake": fake}).fetchers["fake"]({}, {})
    assert items == []
    assert fields == set()
    assert fake.calls == ["discover"]


def test_bridge_is_injected_only_and_does_nothing_on_construction():
    fake = FakeCollector()
    bridge = CollectorFetcherBridge({"fake": fake})
    assert set(bridge.fetchers) == {"fake"}
    assert fake.calls == []
