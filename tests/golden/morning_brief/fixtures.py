"""黄金测试集 fixtures（Phase 2 任务 24.1 节）。

高价值 5 / 应拒绝 8 / 聚类 5 组 / 冲突 3 组 / 降级 3 组 / 完整晨报 3 期。
由工程方生成第一版，用户反馈后修订（tests/golden/ 下保存输入与预期）。
"""
from __future__ import annotations

from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid

T = "2026-08-05T21:00:00"
R = "2026-08-06T07:00:00"


def item(source_id="cls", title="", excerpt="", entities=None, url="https://x.example/",
         published=T, ext="", channel_ok=True) -> RawItem:
    return RawItem(
        raw_item_id=new_uuid(), source_id=source_id, external_id=ext or new_uuid(),
        url=url, title=title, publisher={"cninfo": "巨潮", "nbs": "统计局",
                                         "cls": "财联社"}.get(source_id, source_id),
        author=None, published_at=published, retrieved_at=R,
        content_hash=content_sha256(f"{title}|{ext}"),
        content_excerpt=excerpt or title,
        content_storage="metadata_and_excerpt", language="zh-CN",
        access_status="ok" if channel_ok else "failed",
        entities=entities or [], raw_category="news",
    )


# ---------- 高价值信息（5 条：应入选晨报） ----------

HIGH_VALUE = [
    item("cninfo", "贵州茅台2026年半年报：营收同比增长15%", "公司发布半年报，营收利润双增",
         entities=["company:600519.SH"], url="https://static.cninfo.com.cn/h1"),
    item("nbs", "国家统计局：7月CPI同比上涨0.5%", "7月CPI数据发布",
         url="https://www.stats.gov.cn/cpi7"),
    item("cls", "工信部发布半导体产业支持新政策", "新产业政策出台",
         entities=["industry:semiconductor"], url="https://www.cls.cn/p1"),
    item("cls", "某光伏龙头签订10GW组件长单", "大额订单落地",
         entities=["company:solar"], url="https://www.cls.cn/o1"),
    item("cninfo", "某公司公告：因违规被立案调查", "重大风险事件",
         entities=["company:bad"], url="https://static.cninfo.com.cn/risk1"),
]

# ---------- 应拒绝信息（8 条，任务 24.1 至少 8 条） ----------

REJECTED = [
    item("cls", "2026年5月旧闻重传：某公司发布旧产品", "无新进展",
         url="https://www.cls.cn/old1", published="2026-05-01T10:00:00"),
    item("cls", "限时福利：加微信领取炒股课程", "扫码报名领取",
         url="https://www.cls.cn/ad1"),
    item("cls", "震惊！内部消息某股要崩了", "", entities=[],
         url="https://www.cls.cn/emo1"),
    item("cls", "匿名爆料：某公司即将暴雷（截图）", "据匿名人士",
         url="https://www.cls.cn/anon1", entities=[]),
    item("cls", "纯标题党？？？", "", entities=[], url="https://www.cls.cn/cb1"),
    item("cls", "某明星八卦与股市无关", "娱乐消息", url="https://www.cls.cn/irr1"),
    item("xueqiu", "某股又要暴涨了！！！", "情绪帖", entities=[],
         url="https://xueqiu.com/emo2"),
    item("cls", "某公司快讯（解析失败）", "正文解析失败",
         url="https://www.cls.cn/perr1", channel_ok=False),
]

# ---------- 事件聚类（5 组） ----------

CLUSTER_GROUPS = [
    # 1. 快讯 + 官方公告
    [item("cls", "某公司中标国家电网大单", "快讯", entities=["company:A"], ext="c1"),
     item("cninfo", "某公司中标国家电网大单（公告）", "正式披露", entities=["company:A"],
          ext="a1", url="https://static.cninfo.com.cn/a1")],
    # 2. 多媒体转载
    [item("cls", "央行宣布降准0.5个百分点", "快讯", ext="m1"),
     item("cls", "央行降准落地：释放长期资金", "媒体解读", ext="m2", url="https://www.cls.cn/m2")],
    # 3. 政策原文 + 解读
    [item("nbs", "国务院发布数据要素新政", "原文", ext="g1"),
     item("cls", "数据要素新政解读：哪些环节受益", "解读", ext="g2", url="https://www.cls.cn/g2")],
    # 4. 同一公司不同事件（不得合并）
    [item("cls", "A公司签订订单X", entities=["company:A"], ext="d1"),
     item("cls", "A公司收购公司Y", entities=["company:A"], ext="d2", url="https://www.cls.cn/d2")],
    # 5. 同一项目不同阶段（不得合并）
    [item("cls", "Z项目立项获批", entities=["company:Z"], ext="e1"),
     item("cls", "Z项目正式投产", entities=["company:Z"], ext="e2", url="https://www.cls.cn/e2")],
]

# ---------- 来源冲突（3 组；各组条目 URL 必须不同，避免精确去重误合并） ----------

CONFLICT_GROUPS = [
    [item("cls", "X公司并购Y公司 估值100亿", "估值100亿", entities=["company:X"], ext="f1",
          url="https://www.cls.cn/f1"),
     item("cls", "X公司并购Y公司 估值120亿", "估值120亿", entities=["company:X"], ext="f2",
          url="https://www.cls.cn/f2")],
    [item("cls", "某事件发生", "今日发生", entities=["company:G"], ext="g1",
          url="https://www.cls.cn/g1"),
     item("cls", "某事件发生", "昨日已发生", entities=["company:G"], ext="g2",
          url="https://www.cls.cn/g2")],
    [item("cls", "Q公司重组获批", "已批准", entities=["company:Q"], ext="h1",
          url="https://www.cls.cn/h1"),
     item("cls", "Q公司重组获批", "仍在审批中", entities=["company:Q"], ext="h2",
          url="https://www.cls.cn/h2")],
]

# ---------- 覆盖降级（3 组） ----------

DEGRADED_SETS = [
    [],  # 全部来源无输入（CLS 失败）
    [item("manual_inbox", "用户分享深度文章", "用户手动导入", ext="u1",
          url="https://user.example/u1")],  # 仅人工导入
    HIGH_VALUE,  # 官方源正常，社区/机构缺失
]

# ---------- 完整晨报 3 期 ----------

FULL_BRIEFS = [
    {"name": "信息丰富日", "items": HIGH_VALUE + [item("cls", "行业价格变动", "硅料价格上调",
                                                      ext="f1")]},
    {"name": "信息稀少日", "items": [item("manual_inbox", "一条用户分享", "手动",
                                        ext="s1")]},
    {"name": "多来源故障日", "items": [item("cls", "快讯", "部分", ext="t1",
                                          channel_ok=False)]},
]
