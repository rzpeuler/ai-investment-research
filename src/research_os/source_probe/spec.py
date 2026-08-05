"""来源探测：探测规格（ProbeSpec）与内置来源清单。

Phase 1 任务 5 节。每个来源的探测规格描述：
- 探测 URL 与目的
- 期望字段
- 需要检查的特性（JS 依赖、登录、搜索入口等）

禁止猜测未验证的接口；规格中的 URL 均为来源公开主页/已知公开入口，
实际可达性以探测结果为准。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ProbeUrl(BaseModel):
    """单个探测 URL。"""

    url: str
    purpose: str                      # 目的说明（主页/公告查询/数据页）
    expect_status: int = 200          # 期望 HTTP 状态
    expect_contains: List[str] = Field(default_factory=list)   # 期望出现的文本特征
    require_https: bool = True
    referer: Optional[str] = None     # 需要的 Referer 头（部分公开接口要求）


class ProbeSpec(BaseModel):
    """来源探测规格。"""

    source_id: str
    name: str
    group: str                        # official / government / market / news / company
    urls: List[ProbeUrl] = Field(default_factory=list)
    expected_fields: List[str] = Field(default_factory=list)
    check_js_dependency: bool = False
    check_login: bool = False
    check_search_entry: bool = False
    note: str = ""
    timeout_seconds: float = 20.0


# 内置探测清单（Phase 1 第一批，任务 6 节）
PROBE_SPECS: List[ProbeSpec] = [
    ProbeSpec(
        source_id="cninfo",
        name="巨潮资讯",
        group="official",
        urls=[
            ProbeUrl(url="http://www.cninfo.com.cn/new/index",
                     purpose="巨潮资讯主页（公告查询入口）",
                     expect_contains=["巨潮", "公告"]),
            ProbeUrl(url="http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
                     purpose="公告查询页面（公开搜索入口）",
                     expect_contains=["公告查询", "关键词"]),
        ],
        expected_fields=["code", "orgId", "announcementTitle", "announcementTime",
                         "adjunctUrl", "pdfName"],
        check_js_dependency=True,
        check_search_entry=True,
        note="法定披露主源候选；存在公开 JSON 接口但需探测确认稳定性",
    ),
    ProbeSpec(
        source_id="sse",
        name="上海证券交易所",
        group="official",
        urls=[
            ProbeUrl(url="http://www.sse.com.cn/",
                     purpose="上交所主页",
                     expect_contains=["上海证券交易所"]),
            ProbeUrl(url="http://www.sse.com.cn/disclosure/listedinfo/announcement/",
                     purpose="上市公司公告查询页",
                     expect_contains=["公告"]),
        ],
        expected_fields=["SECURITY_CODE", "SECURITY_NAME_ABBR", "TITLE", "SSEDATE",
                         "URL"],
        check_js_dependency=True,
        check_search_entry=True,
        note="公告查询依赖 JS 渲染，需探测是否提供可结构化数据",
    ),
    ProbeSpec(
        source_id="szse",
        name="深圳证券交易所",
        group="official",
        urls=[
            ProbeUrl(url="http://www.szse.cn/",
                     purpose="深交所主页",
                     expect_contains=["深圳证券交易所"]),
            ProbeUrl(url="http://www.szse.cn/disclosure/listed/notice/index.html",
                     purpose="信息披露公告页",
                     expect_contains=["公告"]),
        ],
        expected_fields=["secCode", "secName", "title", "time", "url"],
        check_js_dependency=True,
        check_search_entry=True,
        note="同上，待探测",
    ),
    ProbeSpec(
        source_id="csrc",
        name="中国证监会",
        group="official",
        urls=[
            ProbeUrl(url="http://www.csrc.gov.cn/csrc/c100028/common_list.shtml",
                     purpose="证监会信息公开页",
                     expect_contains=["证监会"]),
        ],
        expected_fields=["title", "publishDate", "url"],
        check_js_dependency=True,
        note="监管公开信息；页面结构可能变更",
    ),
    ProbeSpec(
        source_id="nbs",
        name="国家统计局",
        group="government",
        urls=[
            ProbeUrl(url="https://www.stats.gov.cn/",
                     purpose="统计局主页",
                     expect_contains=["国家统计局"]),
            ProbeUrl(url="https://www.stats.gov.cn/sj/",
                     purpose="数据发布页",
                     expect_contains=["数据"]),
        ],
        expected_fields=["title", "date", "url", "指标名称"],
        note="宏观数据主源候选",
    ),
    ProbeSpec(
        source_id="cls",
        name="财联社",
        group="news",
        urls=[
            ProbeUrl(url="https://www.cls.cn/telegraph",
                     purpose="财联社电报（快讯公开页）",
                     expect_contains=["电报"]),
        ],
        expected_fields=["title", "ctime", "content", "subjects"],
        check_js_dependency=True,
        note="新闻快讯候选；公开页面依赖 JS，需探测是否提供结构化数据",
    ),
    ProbeSpec(
        source_id="sina_quote",
        name="新浪行情",
        group="market",
        urls=[
            ProbeUrl(url="https://hq.sinajs.cn/list=sh000001",
                     purpose="行情接口（指数）",
                     expect_contains=["000001"],
                     referer="https://finance.sina.com.cn"),
        ],
        expected_fields=["open", "high", "low", "close", "volume", "date"],
        note="日级 OHLCV 候选（公开接口，需 Referer；本探测仅验证可达性）",
    ),
]
