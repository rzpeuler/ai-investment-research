"""P7-D3 M4：NBS production wiring 离线测试。

用真实 NbsCollector 类 + 模拟 subprocess 响应，验证完整链路：
canonical query → SourceQueryProjector → Bridge → NbsCollector(discover/fetch/normalize)
→ RawItem Schema 校验 → FieldProjector(projection evidence) → fields_present → Router
minimum-field 判定 → selected_source=nbs。

不访问真实网络；monkeypatch subprocess.run 模拟 stats.gov.cn 响应。
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from research_os.collectors.government.nbs import NbsCollector
from research_os.data_layer.collector_bridge import CollectorFetcherBridge
from research_os.data_layer.field_projector import FieldProjector
from research_os.data_layer.source_query_projector import SourceQueryProjector
from research_os.routing.requirements import DataRequirementRegistry
from research_os.routing.router import Router
from research_os.models import RawItem
from research_os.validators.schema_validator import validate_instance

HTML = """<html><head><title>国家统计局数据发布</title></head><body>
<a class="fl" href="./202608/t20260803_1964273.html" target="_blank" title='2026年7月流通领域生产资料价格变动情况'>
<a class="fl" href="./202608/t20260803_1964273.html" target="_blank" title='2026年7月流通领域生产资料价格变动情况'>
<a class="fl" href="./202608/t20260803_1964272.html" target="_blank" title='2026年7月规模以上工业增加值'>
</body></html>"""

ARTICLE_PAGE = "<html><head><title>2026年7月规模以上工业增加值</title></head><body>" + "x" * 800 + "</body></html>"


def _fake_run(*args, **kwargs):
    url = kwargs.get("args", args)[-1] if args else None
    if url and "zxfb" in str(url):
        return MagicMock(returncode=0, stdout=HTML)
    return MagicMock(returncode=0, stdout=ARTICLE_PAGE)


@pytest.fixture
def nbs_router(monkeypatch):
    monkeypatch.setattr("research_os.collectors.government.nbs.subprocess.run", _fake_run)
    adapter = NbsCollector()
    bridge = CollectorFetcherBridge(
        {"nbs": adapter},
        projector=SourceQueryProjector(),
        field_projector=FieldProjector(),
    )
    reg = DataRequirementRegistry("registry/data_requirements.yaml")
    return Router(reg, bridge.as_fetchers())


class TestNbsProductionWiring:
    def test_router_selects_nbs_with_projected_fields(self, nbs_router):
        batch = nbs_router.resolve_with_items(
            "macro_data",
            query={"entity_ids": []},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source == "nbs"
        assert batch.route.status == "success"
        assert batch.route.fallback_used is False
        # minimum fields: [title, publish_date, url] —— publish_date 来自 field projection
        assert "publish_date" in batch.fields_present
        assert "title" in batch.fields_present
        assert "url" in batch.fields_present
        assert batch.route.missing_fields == []
        assert len(batch.items) >= 1
        for item in batch.items:
            assert isinstance(item, RawItem)
            assert validate_instance(item.model_dump(), "raw_item") == []
            assert item.source_id == "nbs"
            assert item.raw_category == "statistics_release"

    def test_nbs_canonical_query_projects_to_empty(self, nbs_router):
        # NBS 投影为 {}；collector 不应收到 entity_ids 之类 canonical 字段
        batch = nbs_router.resolve_with_items(
            "macro_data",
            query={"entity_ids": ["company:x"], "peer_entity_ids": []},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source == "nbs"
        assert batch.route.status == "success"

    def test_gate_disabled_router_never_calls_collector(self, nbs_router):
        # 没有 --live-data 时，Router 不应被调用（由 execution gate 保证）。
        # 此处验证：直接构造 Router 且 fetcher 存在时才可能调用；gate 语义在
        # test_live_data_gate.py 覆盖。本测试锁定：无 fetcher 的 data_type 不触发网络。
        batch = nbs_router.resolve_with_items(
            "brief_event_content",
            query={},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source is None
        assert batch.route.status == "insufficient_data"
