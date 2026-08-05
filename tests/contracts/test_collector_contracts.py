"""采集器合约测试（Phase 1 任务 11.2 节）。

每个真实适配器的统一接口行为验证：正常 fixture / 空结果 / 字段缺失 /
结构变化 / 超时 / 403 / 429 / 非法响应。全部离线（mock 网络层）。
"""
from __future__ import annotations

import json

import pytest

from research_os.collectors.base import ItemRef, RawPayload
from research_os.collectors.market import SinaQuoteCollector
from research_os.collectors.official import CninfoCollector
from research_os.validators.schema_validator import validate_model

T0 = "2026-08-05T08:00:00"


# ---------- cninfo 合约 ----------

def _cninfo_ok_response():
    return {"totalAnnouncement": 1, "announcements": [{
        "secCode": "300013", "secName": "新宁物流", "orgId": "9900008307",
        "announcementId": "1225459892",
        "announcementTitle": "关于变更持续督导保荐代表人的公告",
        "announcementTime": 1785923530000,
        "adjunctUrl": "finalpage/2026-08-05/1225459892.PDF",
        "adjunctType": "PDF",
    }]}


@pytest.fixture()
def cninfo(monkeypatch):
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: _cninfo_ok_response()
    return c


def test_cninfo_contract_normal_fixture(cninfo):
    refs = cninfo.discover({"stock": "300013"}, {"start": "2026-08-01T00:00:00",
                                                 "end": "2026-08-05T23:59:59"})
    assert len(refs) == 1
    r = refs[0]
    assert r.source_id == "cninfo"
    assert r.external_id == "1225459892"
    assert "变更持续督导" in r.title
    assert r.published_at  # 时间戳已转换
    assert r.url.startswith("http")


def test_cninfo_contract_empty_result(monkeypatch):
    """空结果 fixture：字段齐全但无条目 -> 返回空列表（不是失败，不等于无事件）。"""
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: {"announcements": [], "totalAnnouncement": 0}
    assert c.discover({}, {}) == []


def test_cninfo_contract_missing_field_skipped(monkeypatch):
    """字段缺失 fixture：缺 title 的条目跳过，不伪造。"""
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: {
        "announcements": [{"announcementId": "1", "announcementTitle": ""},
                          {"announcementId": "2", "announcementTitle": "有效公告"}]}
    refs = c.discover({}, {})
    assert len(refs) == 1
    assert refs[0].external_id == "2"


def test_cninfo_contract_structure_changed(monkeypatch):
    """结构变化 fixture：响应缺少 announcements -> 显式失败（禁止伪造）。"""
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: {"weird": True}
    with pytest.raises(RuntimeError):
        c.discover({}, {})


def test_cninfo_contract_timeout_fails(monkeypatch):
    """超时 fixture：接口无响应 -> 显式 RuntimeError。"""
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: None
    with pytest.raises(RuntimeError):
        c.discover({}, {})
    h = c.healthcheck()
    assert h.ok is False


def test_cninfo_contract_http_403_429(monkeypatch):
    """403/429 fixture：healthcheck 显式降级，不产生数据。"""
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: None  # 模拟被阻止
    assert c.healthcheck().ok is False


def test_cninfo_contract_invalid_json(monkeypatch):
    c = CninfoCollector()
    c._post_query = lambda params, timeout=25.0: None  # 非法响应 -> None
    with pytest.raises(RuntimeError):
        c.discover({}, {})


def test_cninfo_normalize_passes_schema(cninfo):
    refs = cninfo.discover({}, {})
    raw = cninfo.fetch(refs[0])
    items = cninfo.normalize(raw)
    assert len(items) == 1
    assert validate_model(items[0]) == []
    assert items[0].content_storage == "metadata_and_excerpt"
    assert items[0].access_status in ("ok", "failed")


def test_cninfo_rate_limit_policy(cninfo):
    p = cninfo.rate_limit_policy()
    assert p.requests_per_minute > 0
    assert p.timeout_seconds > 0


# ---------- sina_quote 合约 ----------

def test_sina_normalize_parses_quote(monkeypatch):
    """正常 fixture：GBK 报价文本解析为最小摘录。"""
    c = SinaQuoteCollector()
    monkeypatch.setattr(c, "_fetch_quote",
                        lambda symbol, timeout=15.0:
                        'var hq_str_sh600519="贵州茅台,1328.360,1328.360,1306.450,1333.800,'
                        '1303.500,1306.450,1306.460,4268859,5600615349.000,480,1306.450,'
                        '1306.470,1306.450,1306.460,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,'
                        '2026-08-05,15:00:00,00";')
    refs = c.discover({"symbol": "sh600519"}, {})
    raw = c.fetch(refs[0])
    items = c.normalize(raw)
    assert len(items) == 1
    assert "贵州茅台" in items[0].content_excerpt
    assert "现价" in items[0].content_excerpt
    assert validate_model(items[0]) == []


def test_sina_fetch_failure_explicit(monkeypatch):
    """非法响应 fixture：无响应 -> access_status=failed。"""
    c = SinaQuoteCollector()
    monkeypatch.setattr(c, "_fetch_quote", lambda symbol, timeout=15.0: None)
    refs = c.discover({"symbol": "sh600519"}, {})
    raw = c.fetch(refs[0])
    assert raw.fetch_status == "failed"
    items = c.normalize(raw)
    assert items[0].access_status == "failed"


def test_sina_healthcheck_ok(monkeypatch):
    c = SinaQuoteCollector()
    monkeypatch.setattr(c, "_fetch_quote",
                        lambda symbol, timeout=15.0: 'var hq_str_sh000001="指数,1,2,3,4,5";')
    assert c.healthcheck().ok is True


# ---------- 统一接口（所有适配器） ----------

def test_all_adapters_expose_contract_methods():
    from research_os.collectors import CollectorAdapter

    adapters = [CninfoCollector(), SinaQuoteCollector()]
    for a in adapters:
        for method in ("healthcheck", "discover", "fetch", "normalize",
                       "rate_limit_policy"):
            assert callable(getattr(a, method)), f"{a.source_id} 缺少 {method}"
        assert a.source_id
        assert a.version
