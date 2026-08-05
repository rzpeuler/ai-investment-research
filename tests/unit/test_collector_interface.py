"""CollectorAdapter 抽象接口与 stub 契约测试（工程指南 21 节）。

Phase 0 验收：stub 显式返回"未探测"状态，禁止任何网络行为。
"""
from __future__ import annotations

import pytest

from research_os.collectors import CollectorAdapter, HealthStatus, ItemRef, RateLimitPolicy
from research_os.collectors.stub import NotProbedError, StubCollector


@pytest.fixture()
def stub():
    return StubCollector(source_id="sse", version="0.0.0")


def test_stub_healthcheck_reports_not_probed(stub):
    status = stub.healthcheck()
    assert isinstance(status, HealthStatus)
    assert status.ok is False
    assert status.source_id == "sse"
    assert status.access == "unavailable"
    assert "Phase 0 stub" in status.message


def test_stub_discover_raises_not_probed(stub):
    with pytest.raises(NotProbedError):
        stub.discover({"query": "茅台"}, {"start": None, "end": None})


def test_stub_fetch_raises_not_probed(stub):
    ref = ItemRef(source_id="sse", external_id="1", url="https://x")
    with pytest.raises(NotProbedError):
        stub.fetch(ref)


def test_stub_normalize_raises_not_probed(stub):
    from research_os.collectors import RawPayload

    payload = RawPayload(source_id="sse", external_id="1", url="https://x",
                         title="t", publisher="p", retrieved_at="2026-08-05T08:00:00")
    with pytest.raises(NotProbedError):
        stub.normalize(payload)


def test_stub_rate_limit_policy(stub):
    policy = stub.rate_limit_policy()
    assert isinstance(policy, RateLimitPolicy)
    assert policy.requests_per_minute == 0  # 未探测：不声称限速能力


def test_abstract_cannot_instantiate():
    with pytest.raises(TypeError):
        CollectorAdapter()  # type: ignore[abstract]


def test_item_ref_fields():
    ref = ItemRef(source_id="cninfo", external_id="ann-1", url="https://x",
                  title="公告", published_at="2026-08-05T08:00:00")
    assert ref.source_id == "cninfo"
    assert ref.published_at == "2026-08-05T08:00:00"
    assert ref.extra == {}
