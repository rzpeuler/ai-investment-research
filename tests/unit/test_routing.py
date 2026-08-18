"""主备路由测试（Phase 1 任务 11.4 节）。

覆盖：主源成功 / 主源失败备源成功 / 主备均失败 / 最低字段不足 /
人工 Inbox 回退 / 空响应不等于无事件。
"""
from __future__ import annotations

import yaml

import pytest

from research_os.routing import DataRequirementRegistry, Router

REQS_YAML = """
requirements:
  company_announcement:
    primary: [cninfo]
    secondary: [sse]
    fallback: [manual_inbox]
    minimum_acceptable:
      fields: [title, published_at, url, company]
    failure_policy: degraded
"""


@pytest.fixture()
def requirements(tmp_path):
    p = tmp_path / "data_requirements.yaml"
    p.write_text(REQS_YAML, encoding="utf-8")
    return DataRequirementRegistry(p)


def _fetcher(items, fields, exc=None):
    def f(data_type, query, time_window):
        if exc:
            raise exc
        return items, set(fields)
    return f


def test_router_primary_success(requirements):
    router = Router(requirements, {
        "cninfo": _fetcher([{"t": "公告"}], ["title", "published_at", "url", "company"]),
    })
    route = router.resolve("company_announcement")
    assert route.status == "success"
    assert route.selected_source == "cninfo"
    assert route.fallback_used is False
    assert route.missing_fields == []


def test_router_primary_fails_secondary_succeeds(requirements):
    router = Router(requirements, {
        "cninfo": _fetcher([], [], exc=RuntimeError("主源挂了")),
        "sse": _fetcher([{"t": "备源公告"}], ["title", "published_at", "url", "company"]),
    })
    route = router.resolve("company_announcement")
    assert route.status == "success"
    assert route.selected_source == "sse"
    assert route.attempted_sources == ["cninfo", "sse"]
    assert any("主源挂了" in w for w in route.warnings)


def test_router_all_fail_explicit(requirements):
    """主备均失败：无数据 -> 最低字段不满足 -> insufficient_data（显式）。"""
    router = Router(requirements, {
        "cninfo": _fetcher([], [], exc=RuntimeError("a")),
        "sse": _fetcher([], [], exc=RuntimeError("b")),
    })
    route = router.resolve("company_announcement")
    assert route.status == "insufficient_data"
    assert route.selected_source is None
    assert "cninfo" in route.attempted_sources and "sse" in route.attempted_sources
    assert len(route.missing_fields) > 0
    # fallback 已尝试但无获取器（不伪装成可用）
    assert any("manual_inbox" in w for w in route.warnings)


def test_router_minimum_fields_missing(requirements):
    """最低字段不足：不选该源，最终 insufficient_data。"""
    router = Router(requirements, {
        "cninfo": _fetcher([{"t": "x"}], ["title"]),  # 缺 url/company
        "sse": _fetcher([], [], exc=RuntimeError("b")),
    })
    route = router.resolve("company_announcement")
    assert route.status == "insufficient_data"
    assert route.selected_source is None
    assert "url" in route.missing_fields


def test_router_manual_inbox_fallback(requirements):
    """主备均失败 -> 人工 Inbox 兜底。"""
    router = Router(requirements, {
        "cninfo": _fetcher([], [], exc=RuntimeError("a")),
        "sse": _fetcher([], [], exc=RuntimeError("b")),
    }, fallback_fetchers={
        "manual_inbox": _fetcher([{"t": "用户分享"}], ["title", "published_at", "url", "company"]),
    })
    route = router.resolve("company_announcement")
    assert route.status == "degraded"
    assert route.selected_source == "manual_inbox"
    assert route.fallback_used is True


def test_router_empty_response_not_no_event(requirements):
    """空响应（字段齐全但 0 条）≠ 无事件：仍为 success 且带警告。"""
    router = Router(requirements, {
        "cninfo": _fetcher([], ["title", "published_at", "url", "company"]),
    })
    route = router.resolve("company_announcement")
    assert route.status == "success"
    assert route.selected_source == "cninfo"
    assert any("空结果" in w for w in route.warnings)


def test_router_unknown_data_type_raises(requirements):
    router = Router(requirements, {})
    with pytest.raises(KeyError):
        router.resolve("no_such_type")


def test_requirement_registry_priority_order(requirements):
    assert requirements.source_priority("company_announcement") == \
        ["cninfo", "sse", "manual_inbox"]
