"""时间因果检查（Phase 3 任务书 10 节）。

必须保存并区分：event_time / first_disclosed_at / published_at / retrieved_at /
move_start_at / move_end_at / market_close_at / official_confirmation_at。

时间关系：BEFORE_MOVE / DURING_MOVE / AFTER_MOVE / UNKNOWN_ORDER。

硬规则（确定性代码，不得由模型放宽）：
1. 报道发布时间晚于异动开始，默认不能是直接触发
2. 收盘后发布的"原因分析"属于 after_the_fact_explanation
3. 窗口前已广泛公开的旧闻不能因股价上涨被重新标为直接原因
4. 旧事件在窗口内出现新数据/正式确认/政策落地/传播升级时，可把新增部分作为变量
5. 社区先传播、官方后确认：社区首次传播时间不被改写；官方确认可构成次级催化
6. 只有日期没有分钟：同日关系标记 UNKNOWN_ORDER；直接触发置信度上限 medium
7. 事件发生在异动后时，除非是对持续第二阶段异动的新增触发，否则不能作为原始异动原因
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from research_os.utils.time import parse_iso

BEFORE_MOVE = "BEFORE_MOVE"
DURING_MOVE = "DURING_MOVE"
AFTER_MOVE = "AFTER_MOVE"
UNKNOWN_ORDER = "UNKNOWN_ORDER"


@dataclass
class TimingCheck:
    timing_relation: str = UNKNOWN_ORDER
    direct_eligible: bool = False
    confidence_cap: Optional[str] = None          # medium/high
    warnings: list = field(default_factory=list)
    reason: str = ""


def _dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parse_iso(value)
    except ValueError:
        # date-only（YYYY-MM-DD）视为当天 00:00（Asia/Shanghai）
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None


def _has_time_precision(value: Optional[str]) -> bool:
    """是否精确到分钟（ISO 含 T 与 HH:MM）。date-only 视为无分钟精度。"""
    return bool(value) and "T" in value and len(value) >= 16


def classify_timing(published_at: Optional[str], move_start_at: Optional[str],
                    move_end_at: Optional[str]) -> TimingCheck:
    """按发布时间与异动窗口判断时间关系（规则 1、2、6）。"""
    check = TimingCheck()
    pub = _dt(published_at)
    start = _dt(move_start_at)
    end = _dt(move_end_at)
    if pub is None:
        check.reason = "发布时间缺失，时间关系 UNKNOWN_ORDER"
        check.warnings.append("证据时间缺失")
        return check
    if start is None:
        check.reason = "异动开始时间缺失"
        return check

    if pub < start:
        check.timing_relation = BEFORE_MOVE
        check.direct_eligible = True
        check.confidence_cap = "high"
        check.reason = "发布时间早于异动开始"
    elif end is not None and pub <= end:
        check.timing_relation = DURING_MOVE
        # 异动进行中发布的报道：可为催化，但直接触发证据弱
        check.direct_eligible = False
        check.confidence_cap = "medium"
        check.reason = "发布时间位于异动窗口内（DURING_MOVE）"
    elif pub > (end or start):
        check.timing_relation = AFTER_MOVE
        check.direct_eligible = False
        check.confidence_cap = "low"
        check.reason = "发布时间晚于异动结束/开始（AFTER_MOVE，属于事后解释）"
        check.warnings.append("异动后报道不得标为直接触发")

    # 规则 6：只有日期没有分钟 -> UNKNOWN_ORDER + 置信度上限 medium
    if check.timing_relation == BEFORE_MOVE and not _has_time_precision(published_at):
        # 若发布时间与异动开始同一天且无分钟信息
        if pub.date() == start.date():
            check.timing_relation = UNKNOWN_ORDER
            check.confidence_cap = "medium"
            check.reason = "同日事件但无分钟级先后，标记 UNKNOWN_ORDER，直接触发置信度上限 medium"
            check.warnings.append("同日先后未知，不得输出分钟级因果表述")
    return check


def check_direct_trigger(
    published_at: Optional[str],
    first_disclosed_at: Optional[str],
    move_start_at: Optional[str],
    move_end_at: Optional[str],
    is_old_news: bool = False,
    has_new_development: bool = False,
) -> TimingCheck:
    """直接触发资格检查（规则 1-5、7）。

    返回的 direct_eligible 决定候选是否可进入 direct_trigger 类别；
    最终门槛由 cause_candidate_scorer（任务书 11.5）叠加证据要求。
    """
    check = TimingCheck()
    pub = _dt(published_at)
    first = _dt(first_disclosed_at)
    start = _dt(move_start_at)

    if pub is None:
        check.reason = "发布时间缺失，无法通过直接触发资格"
        check.warnings.append("证据时间缺失")
        return check
    if start is None:
        check.reason = "异动开始时间缺失"
        return check

    # 规则 1：报道晚于异动开始 -> 不能直接触发
    if pub > start:
        check.timing_relation = AFTER_MOVE
        check.direct_eligible = False
        check.confidence_cap = "low"
        check.reason = "报道发布时间晚于异动开始，不能作为直接触发"
        check.warnings.append("异动后报道不得标为 direct_trigger")
        return check

    # 规则 3：旧闻（首次披露远早于窗口）无新增 -> 不能直接触发
    if is_old_news and not has_new_development:
        check.timing_relation = BEFORE_MOVE
        check.direct_eligible = False
        check.confidence_cap = "medium"
        check.reason = "窗口前已广泛公开的旧闻且无新增变量，不得重新标为直接原因"
        check.warnings.append("旧闻无新增：不得标为直接触发")
        return check

    # 规则 4：旧闻 + 窗口内新增数据/确认/落地 -> 新增部分可作变量
    if is_old_news and has_new_development:
        check.timing_relation = BEFORE_MOVE
        check.direct_eligible = True
        check.confidence_cap = "medium"
        check.reason = "旧闻在窗口内出现新增变量（新数据/确认/落地），新增部分可作原因变量"
        return check

    # 规则 7：事件发生在异动后（以首次披露判断）-> 不能作为原始异动原因
    if first is not None and start is not None and first > start:
        check.timing_relation = AFTER_MOVE
        check.direct_eligible = False
        check.confidence_cap = "low"
        check.reason = "事件首次披露晚于异动开始，不能作为原始异动原因（除非是持续第二阶段的新增触发）"
        return check

    # 正常路径
    check.timing_relation = BEFORE_MOVE
    check.direct_eligible = True
    check.confidence_cap = "high" if _has_time_precision(published_at) else "medium"
    if check.confidence_cap == "medium":
        check.warnings.append("无分钟级时间信息，直接触发置信度上限 medium")
    check.reason = "发布时间早于异动开始且无旧闻/反序问题"
    return check


def official_confirmation_boost(
    community_first_at: Optional[str],
    official_at: Optional[str],
    move_start_at: Optional[str],
) -> Dict[str, Any]:
    """规则 5：社区先传播、官方后确认。社区首次传播时间不被改写；
    官方确认提高确定性；官方确认本身可构成次级催化，但不能伪造更早时间。"""
    result = {
        "community_first_at": community_first_at,
        "official_at": official_at,
        "community_time_preserved": True,
        "confirmation_boost": False,
        "secondary_catalyst": False,
        "warnings": [],
    }
    cf = _dt(community_first_at)
    of = _dt(official_at)
    if cf is None or of is None:
        result["warnings"].append("社区或官方时间缺失，无法判定确认升级")
        return result
    if of > cf:
        result["confirmation_boost"] = True
        result["secondary_catalyst"] = True
        result["warnings"].append("官方确认晚于社区传播：官方确认构成次级催化，不得改写社区首次传播时间")
    return result
