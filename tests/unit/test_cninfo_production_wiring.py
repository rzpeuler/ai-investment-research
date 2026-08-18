"""P7-D3 M4：CNINFO production wiring 离线测试。

用真实 CninfoCollector 类 + 模拟 subprocess 响应，验证完整链路：
canonical entity_ids → SourceQueryProjector（权威 security 映射）→ stock query
→ Bridge → CninfoCollector(discover/fetch/normalize) → RawItem Schema 校验
→ FieldProjector(company evidence) → fields_present → Router minimum-field 判定
→ selected_source=cninfo。

不访问真实网络；monkeypatch subprocess.run 模拟 cninfo 公告接口与附件 HEAD。
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from research_os.collectors.official.cninfo import CninfoCollector
from research_os.data_layer.collector_bridge import CollectorFetcherBridge
from research_os.data_layer.field_projector import FieldProjector
from research_os.data_layer.source_query_projector import SourceQueryProjector
from research_os.models import RawItem
from research_os.routing.requirements import DataRequirementRegistry
from research_os.routing.router import Router
from research_os.validators.schema_validator import validate_instance

_SECURITIES = {"company:maotai": "600519.SH", "company:catl": "300750.SZ"}

ANNOUNCEMENTS = {
    "announcements": [
        {
            "announcementId": "1612345678",
            "secCode": "600519",
            "secName": "贵州茅台",
            "announcementTitle": "贵州茅台：关于2026年半年度报告的公告",
            "announcementTime": 1785600000000,  # 2026-08-01 附近
            "adjunctUrl": "finalpage/2026-08-01/1200000000.PDF",
            "adjunctType": "PDF",
            "announcementType": "定期报告",
        },
        {
            "announcementId": "1612345679",
            "secCode": "600519",
            "secName": "贵州茅台",
            "announcementTitle": "贵州茅台：独立董事关于公司对外担保情况的专项说明",
            "announcementTime": 1785686400000,
            "adjunctUrl": "finalpage/2026-08-02/1200000001.PDF",
            "adjunctType": "PDF",
            "announcementType": "其他",
        },
    ]
}


def _fake_run(*args, **kwargs):
    cmd = list(kwargs.get("args", args)[0] if args and isinstance(args[0], list) else args)
    flags = " ".join(str(c) for c in cmd)
    if "-I" in flags:
        # fetch: HEAD 附件可达性（text=True → stdout 为 str）
        return MagicMock(returncode=0, stdout="HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n")
    if "topSearch" in flags:
        # topSearch: 股票代码 → orgId（官方映射）
        import re
        data = " ".join(str(c) for c in cmd)
        m = re.search(r"keyWord=(\d{6})", data)
        stock = m.group(1) if m else "600519"
        org = {"600519": "gssh0600519", "300750": "GD165627"}.get(stock, stock)
        return MagicMock(returncode=0, stdout=json.dumps(
            [{"code": stock, "orgId": org}]).encode("utf-8"))
    # discover: POST 公告查询（无 text → stdout 为 bytes）
    return MagicMock(returncode=0, stdout=json.dumps(ANNOUNCEMENTS).encode("utf-8"))


@pytest.fixture
def cninfo_router(monkeypatch):
    monkeypatch.setattr("research_os.collectors.official.cninfo.subprocess.run", _fake_run)
    adapter = CninfoCollector()
    bridge = CollectorFetcherBridge(
        {"cninfo": adapter},
        projector=SourceQueryProjector(security_resolver=lambda e: _SECURITIES.get(e)),
        field_projector=FieldProjector(),
    )
    reg = DataRequirementRegistry("registry/data_requirements.yaml")
    return Router(reg, bridge.as_fetchers())


class TestCninfoProductionWiring:
    def test_sh_symbol_router_selects_cninfo_with_company(self, cninfo_router):
        batch = cninfo_router.resolve_with_items(
            "company_announcement",
            query={"entity_ids": ["company:maotai"]},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source == "cninfo"
        assert batch.route.status == "success"
        # minimum fields: [title, published_at, url, company] —— company 来自 field projection
        assert "company" in batch.fields_present
        assert "title" in batch.fields_present
        assert "published_at" in batch.fields_present
        assert "url" in batch.fields_present
        assert batch.route.missing_fields == []
        assert len(batch.items) == 2
        for item in batch.items:
            assert isinstance(item, RawItem)
            assert validate_instance(item.model_dump(), "raw_item") == []
            assert item.source_id == "cninfo"
            assert item.raw_category == "announcement"
            assert item.publisher == "贵州茅台"  # secName → publisher

    def test_sz_symbol_router_selects_cninfo(self, cninfo_router):
        batch = cninfo_router.resolve_with_items(
            "company_announcement",
            query={"entity_ids": ["company:catl"]},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source == "cninfo"
        assert batch.route.status == "success"

    def test_unknown_entity_fails_closed_no_network(self, cninfo_router):
        # 实体无 security 映射 → 投影失败 → cninfo attempt 失败 → 无备源 → 不联网
        batch = cninfo_router.resolve_with_items(
            "company_announcement",
            query={"entity_ids": ["company:unknown"]},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        assert batch.route.selected_source is None
        assert batch.route.status == "insufficient_data"
        assert "cninfo" in batch.route.attempted_sources

    def test_empty_result_is_not_no_event(self, monkeypatch):
        def _empty_run(*args, **kwargs):
            cmd = list(kwargs.get("args", args)[0] if args and isinstance(args[0], list) else args)
            flags = " ".join(str(c) for c in cmd)
            if "-I" in flags:
                return MagicMock(returncode=0, stdout="HTTP/1.1 200 OK\r\n\r\n")
            if "topSearch" in flags:
                return MagicMock(returncode=0, stdout=json.dumps(
                    [{"code": "600519", "orgId": "gssh0600519"}]).encode("utf-8"))
            return MagicMock(returncode=0, stdout=json.dumps({"announcements": []}).encode("utf-8"))

        monkeypatch.setattr("research_os.collectors.official.cninfo.subprocess.run", _empty_run)
        adapter = CninfoCollector()
        bridge = CollectorFetcherBridge(
            {"cninfo": adapter},
            projector=SourceQueryProjector(security_resolver=lambda e: _SECURITIES.get(e)),
            field_projector=FieldProjector(),
        )
        reg = DataRequirementRegistry("registry/data_requirements.yaml")
        router = Router(reg, bridge.as_fetchers())
        batch = router.resolve_with_items(
            "company_announcement",
            query={"entity_ids": ["company:maotai"]},
            time_window={"start": "2026-08-01T00:00:00", "end": "2026-08-16T00:00:00"},
        )
        # 空公告列表 → 空结果（≠ 无公告）；minimum 字段不齐 → insufficient_data
        # Router 不选中 cninfo，也不得出现"无公告/无事件"类业务结论
        assert batch.route.selected_source is None
        assert batch.route.status == "insufficient_data"
        assert "cninfo" in batch.route.attempted_sources
        assert batch.items == ()
        joined = " ".join(batch.route.warnings)
        assert "无公告" not in joined and "无重大事件" not in joined


class TestCninfoDiscoverWindowAndIdentity:
    """D3 独立验收修复：discover 窗口后置过滤 + 缺 announcementId 跳过。"""

    @staticmethod
    def _collector_with(response):
        c = CninfoCollector()
        c._post_query = lambda params, timeout=25.0: response
        return c

    def test_discover_filters_outside_window(self):
        from datetime import datetime

        ts_in = 1785600000000  # 本地 2026-08-02T00:00:00（基准时刻）
        day_ms = 86400 * 1000
        # 窗口基于同一本地时间基准构造：窗口内公告落在 [start, end)
        start = datetime.fromtimestamp((ts_in - day_ms) / 1000).isoformat()
        end = datetime.fromtimestamp((ts_in + day_ms) / 1000).isoformat()
        c = self._collector_with({"announcements": [
            {"announcementId": "in1", "secCode": "600519", "secName": "贵州茅台",
             "announcementTitle": "窗口内公告", "announcementTime": ts_in,
             "adjunctUrl": "finalpage/x.PDF", "adjunctType": "PDF"},
            {"announcementId": "out1", "secCode": "600519", "secName": "贵州茅台",
             "announcementTitle": "窗口外公告（2 天后）", "announcementTime": ts_in + 2 * day_ms,
             "adjunctUrl": "finalpage/y.PDF", "adjunctType": "PDF"},
        ]})
        refs = c.discover({}, {"start": start, "end": end})
        assert [r.title for r in refs] == ["窗口内公告"]
        assert [r.external_id for r in refs] == ["in1"]

    def test_discover_skips_missing_announcement_id(self):
        c = self._collector_with({"announcements": [
            {"announcementId": "id1", "secCode": "600519", "secName": "贵州茅台",
             "announcementTitle": "有 ID 公告", "announcementTime": 1785600000000,
             "adjunctUrl": "finalpage/x.PDF", "adjunctType": "PDF"},
            {"secCode": "600519", "secName": "贵州茅台",  # 缺 announcementId
             "announcementTitle": "无 ID 公告", "announcementTime": 1785600000000,
             "adjunctUrl": "finalpage/y.PDF", "adjunctType": "PDF"},
        ]})
        refs = c.discover({}, {"start": None, "end": None})
        assert [r.external_id for r in refs] == ["id1"]

    def test_discover_no_window_keeps_all(self):
        c = self._collector_with({"announcements": [
            {"announcementId": "a1", "secCode": "600519", "secName": "贵州茅台",
             "announcementTitle": "任意时间公告", "announcementTime": 1785600000000,
             "adjunctUrl": "finalpage/x.PDF", "adjunctType": "PDF"},
        ]})
        refs = c.discover({}, {})
        assert len(refs) == 1
