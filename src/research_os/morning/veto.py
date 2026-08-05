"""硬性否决（Phase 2 任务 12 节）。

16 条否决规则中可确定性实现的规则（代码负责）；其余（影响路径等）
由 LLM 接口承担（Phase 2 留 TODO 接口）。被否决信息进入 quarantine
并记录原因与过期时间，不得永久堆积。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from research_os.models import CandidateItem
from research_os.models.morning import CLASSIFICATION_TREE
from research_os.utils.time import parse_iso

_EMOTION_WORDS = ["震惊", "泪目", "沸腾", "暴跌", "暴涨", "崩了", "狂泻", "无语", "炸了", "完了", "疯狂"]
_AD_WORDS = ["广告", "推广", "限时", "加微信", "扫码", "点击购买", "福利", "优惠", "免费领",
             "直播间", "带货", "报名", "领取"]
_IRRELEVANT_WORDS = ["娱乐", "八卦", "明星绯闻", "综艺", "赛事竞猜"]
_CLICKBAIT_RE = re.compile(r"[!！?？]+$")


@dataclass
class VetoResult:
    """否决结果。vetoed=True 时不得进入晨报正文。"""

    vetoed: bool = False
    reasons: List[str] = field(default_factory=list)
    quarantine_path: str = "data/quarantine/"
    expire_at: Optional[str] = None  # 过期时间（quarantine 清理用）

    def add(self, reason: str) -> None:
        self.vetoed = True
        self.reasons.append(reason)


def apply_vetoes(candidate: CandidateItem, window_start: Optional[str] = None,
                 source_status: Optional[str] = None) -> VetoResult:
    """对候选执行确定性硬性否决。window_start 用于旧闻/窗口外判定。"""
    v = VetoResult()
    text = f"{candidate.title} {candidate.summary}"

    # 1. 无法确认来源
    if not candidate.source_ids:
        v.add("无法确认来源")
    # 2. 无法确认主体（标题/摘要过短且无实体）
    if len(candidate.title.strip()) < 4 and not candidate.entities:
        v.add("无法确认主体")
    # 3. 无法确认发布时间
    if not candidate.published_at:
        v.add("无法确认发布时间")
    # 5. 广告或营销软文
    if any(w in text for w in _AD_WORDS):
        v.add(f"广告或营销软文（命中: {[w for w in _AD_WORDS if w in text]}）")
    # 8. 只有情绪没有事实或论据
    emotion_hits = [w for w in _EMOTION_WORDS if w in text]
    has_fact = bool(candidate.entities) or bool(re.search(r"\d", text))
    if emotion_hits and not has_fact:
        v.add("只有情绪没有事实或论据")
    # 4. 纯标题党（以感叹/问号结尾或连续感叹问号，且无实体）
    clickbait = (_CLICKBAIT_RE.search(candidate.title)
                 or candidate.title.count("！") >= 3 or candidate.title.count("？") >= 3
                 or candidate.title.count("!") >= 3 or candidate.title.count("?") >= 3)
    if clickbait and not candidate.entities:
        v.add("纯标题党")
    # 9. 匿名单一爆料
    if any(w in text for w in ("匿名", "爆料", "内部消息", "据传")):
        v.add("匿名单一爆料")
    # 10. 截图无原始出处
    if "截图" in candidate.title and "公告" not in text and "披露" not in text:
        v.add("截图无原始出处")
    # 11. 与投资研究无实质关联
    if any(w in text for w in _IRRELEVANT_WORDS):
        v.add("与投资研究无实质关联")
    # 14. 内容主体位于窗口外且无窗口内新更新
    if window_start and candidate.published_at:
        try:
            if parse_iso(candidate.published_at) < parse_iso(window_start):
                v.add("发布时间早于窗口开始（旧闻重传且无新更新）")
        except ValueError:
            v.add("发布时间无法解析")
    # 15. 机器解析明显错误
    if candidate.warnings and any("解析" in w or "failed" in w.lower() for w in candidate.warnings):
        v.add("机器解析明显错误")
    # 16. 来源状态 blocked/unavailable
    if source_status in ("blocked", "unavailable"):
        v.add(f"来源状态 {source_status}")

    if v.vetoed:
        # quarantine 过期时间：窗口结束后 7 天（不永久堆积）
        v.expire_at = _expiry(window_start)
    return v


def _expiry(window_start: Optional[str]) -> Optional[str]:
    from datetime import timedelta

    if not window_start:
        return None
    try:
        return (parse_iso(window_start) + timedelta(days=7)).isoformat(timespec="seconds")
    except ValueError:
        return None
