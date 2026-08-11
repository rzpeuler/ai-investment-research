"""P7-D0 Router regression：现有 Router 主/备/fallback 行为完全不回归。

P7-D0 不重写 Router；本测试锁定 resolve() 的来源选择语义
（primary → secondary → fallback，degraded / insufficient_data 状态判定）。
"""
from __future__ import annotations

from pathlib import Path

from research_os.routing.requirements import DataRequirementRegistry
from research_os.routing.router import Router

ROOT = Path(__file__).resolve().parents[2]


def _registry() -> DataRequirementRegistry:
    return DataRequirementRegistry(ROOT / "registry" / "data_requirements.yaml")


def _ok_fetcher(items=None, fields=None):
    items = items if items is not None else [{"id": 1}]
    fields = fields if fields is not None else {"title", "published_at", "url"}

    def fetcher(query, time_window):
        return items, fields

    return fetcher


def _fail_fetcher():
    def fetcher(query, time_window):
        raise RuntimeError("boom")

    return fetcher


class TestRouterRegression:
    def test_primary_success(self):
        reg = _registry()
        router = Router(reg, {"cls": _ok_fetcher()})
        route = router.resolve("news_flash")
        assert route.selected_source == "cls"
        assert route.status == "success"
        assert route.fallback_used is False

    def test_primary_fail_secondary_success(self):
        reg = _registry()
        router = Router(reg, {"cls": _fail_fetcher()})
        # news_flash secondary 为空：主源失败后应走 fallback
        route = router.resolve("news_flash")
        assert route.selected_source is None
        assert route.status == "insufficient_data"
        assert "cls" in route.attempted_sources

    def test_primary_fail_fallback_success(self):
        reg = _registry()
        router = Router(reg, {"cls": _fail_fetcher()},
                        fallback_fetchers={"manual_inbox": _ok_fetcher()})
        route = router.resolve("news_flash")
        assert route.selected_source == "manual_inbox"
        assert route.fallback_used is True
        assert route.status == "degraded"

    def test_secondary_used_before_fallback(self):
        # company_announcement: primary=cninfo, secondary=[sse, szse], fallback=[company_ir, manual_inbox]
        reg = _registry()
        router = Router(
            reg,
            {"cninfo": _fail_fetcher(), "sse": _ok_fetcher(fields={"title", "published_at", "url", "company"})},
            fallback_fetchers={"company_ir": _ok_fetcher()},
        )
        route = router.resolve("company_announcement")
        assert route.selected_source == "sse"
        assert route.fallback_used is False
        assert route.status == "success"
        assert route.attempted_sources == ["cninfo", "sse"]

    def test_unknown_data_type_raises(self):
        reg = _registry()
        router = Router(reg, {})
        try:
            router.resolve("not_a_type")
        except KeyError:
            return
        raise AssertionError("未知 data_type 应抛 KeyError")

    def test_empty_result_success_not_no_event(self):
        """空响应 + 字段齐全 = success，并带 warning（不等于无事件）。"""
        reg = _registry()
        router = Router(reg, {"cls": _ok_fetcher(items=[])},
                        fallback_fetchers={"manual_inbox": _ok_fetcher()})
        route = router.resolve("news_flash")
        assert route.status == "success"
        assert any("不等于无事件" in w for w in route.warnings)

    def test_brief_event_content_no_primary(self):
        """brief_event_content primary/secondary 为空：无 fetcher 时如实 insufficient_data。"""
        reg = _registry()
        router = Router(reg, {})
        route = router.resolve("brief_event_content")
        assert route.selected_source is None
        assert route.status == "insufficient_data"
        assert route.requested_sources == []
