"""信息分类（Phase 2 任务 8 节）。

保留用户定义的四类主分类树。确定性关键词规则完成主分类，
LLM 负责语义细化（Phase 2 提供规则回退，LLM 接口留 TODO）。

monitoring_channel 由来源类型映射（与信息分类相互独立，任务 5 节）。
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from research_os.models.morning import CLASSIFICATION_TREE

# 来源类型 -> monitoring_channel（任务 5.1 枚举）
SOURCE_CHANNEL_MAP = {
    "official_disclosure": "official_disclosure",
    "exchange_disclosure": "official_disclosure",
    "regulatory_disclosure": "government_and_regulator",
    "government_statistics": "government_and_regulator",
    "news_flash": "fast_news",
    "community": "community_sentiment",
    "market_quote": "market_data",
    "institution_material": "institutional_activity",
    "client_shared_knowledge": "manual_submission",
}

# 分类关键词（确定性规则；命中顺序：macro -> company -> market -> industry）
_MACRO_KEYWORDS = [
    ("policy", ["政策", "央行", "降准", "降息", "国常会", "发改委", "监管新规", "征求意见稿"]),
    ("liquidity", ["流动性", "逆回购", "MLF", "LPR", "资金面", "社融", "M2"]),
    ("economic_data", ["CPI", "PPI", "PMI", "GDP", "社零", "工业增加值", "统计局", "进出口", "通胀"]),
    ("geopolitics", ["地缘", "制裁", "关税", "贸易摩擦", "国际关系", "冲突"]),
    ("emergency", ["突发事件", "紧急", "熔断", "恐慌"]),
]
_COMPANY_KEYWORDS = [
    ("announcement", ["公告", "披露", "业绩预告", "年报", "半年报", "股东大会", "回购", "分红"]),
    ("operation", ["中标", "订单", "投产", "量产", "交付", "签署", "合同", "签约", "扩产", "产能"]),
    ("interaction_and_research", ["调研", "投资者关系", "互动易", "电话会议"]),
    ("financing", ["定增", "可转债", "发债", "融资", "增发", "IPO", "上市"]),
    ("risk", ["处罚", "立案", "风险提示", "诉讼", "违规", "问询函", "退市", "警示"]),
]
_MARKET_KEYWORDS = [
    ("a_share", ["A股", "沪指", "深成指", "创业板", "两市", "北向", "涨停", "跌停", "龙虎榜", "开盘", "收盘"]),
    ("hong_kong", ["港股", "恒生", "恒指", "南向"]),
    ("us_market", ["美股", "纳斯达克", "道指", "标普", "中概股"]),
    ("commodity", ["原油", "黄金", "铜", "铝", "铁矿石", "期货", "商品", "锂价", "硅料", "猪价"]),
    ("rates", ["利率", "国债", "收益率", "美债"]),
    ("foreign_exchange", ["汇率", "人民币", "美元", "离岸", "在岸"]),
]
_INDUSTRY_KEYWORDS = [
    ("event", ["发布", "投产", "中试", "产能", "涨价", "降价", "订单", "收购", "认证", "出货", "签约", "量产"]),
    ("trend", ["趋势", "展望", "预判", "景气", "回暖", "下行", "格局", "渗透率", "需求"]),
    ("data", ["数据", "出货量", "装机", "产量", "销量", "份额", "同比", "环比"]),
    ("policy", ["产业政策", "补贴", "规划", "标准", "准入"]),
    ("technology_breakthrough", ["突破", "实验室", "样机", "验证", "研发", "专利", "技术路线", "性能"]),
]

# 技术突破 vs 行业事件的判别：已进入商业/产线/客户验证 -> industry.event（任务 8.5）
_COMMERCIALIZATION_HINTS = ["商业化", "产线", "量产", "客户认证", "交付", "订单", "量产验证"]


def source_to_channel(source_type: str) -> str:
    """来源类型 -> monitoring_channel。未知映射返回 unknown。"""
    return SOURCE_CHANNEL_MAP.get(source_type, "unknown")


def classify_text(title: str, summary: str, source_type: str = "") -> Tuple[List[str], List[str]]:
    """确定性分类：返回 (classification_path, tags)。

    path 形如 ["industry", "event"]；无法判定返回 ["unknown"]。
    """
    text = f"{title} {summary}"
    for sub, kws in _COMPANY_KEYWORDS:
        if any(k in text for k in kws):
            return ["company", sub], [k for k in kws if k in text][:3]
    for sub, kws in _MACRO_KEYWORDS:
        if any(k in text for k in kws):
            return ["macro", sub], [k for k in kws if k in text][:3]
    for sub, kws in _MARKET_KEYWORDS:
        if any(k in text for k in kws):
            return ["market", sub], [k for k in kws if k in text][:3]
    for sub, kws in _INDUSTRY_KEYWORDS:
        if any(k in text for k in kws):
            path = ["industry", sub]
            # 技术突破已进入商业验证 -> 归入 industry.event 并附加技术标签（8.5）
            if sub == "technology_breakthrough" and \
               any(h in text for h in _COMMERCIALIZATION_HINTS):
                path = ["industry", "event"]
                return path, [k for k in kws if k in text][:3] + ["技术商业化"]
            return path, [k for k in kws if k in text][:3]
    return ["unknown"], []


def validate_path(path: List[str]) -> bool:
    """校验分类路径合法性（首项在主分类树内，次项在其子分类内）。"""
    if not path or path == ["unknown"]:
        return True
    if path[0] not in CLASSIFICATION_TREE:
        return False
    if len(path) > 1 and path[1] not in CLASSIFICATION_TREE[path[0]]:
        return False
    return True


def all_paths() -> Dict[str, List[str]]:
    return CLASSIFICATION_TREE
