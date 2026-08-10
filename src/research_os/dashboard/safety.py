"""Deterministic investment-advice boundary for conversational input."""
from __future__ import annotations

import re


_HARD_FORBIDDEN = re.compile(
    r"目标价(?:格)?|仓位(?:建议|配置)?|自动(?:化)?荐股|推荐.{0,4}股票|交易信号|买卖评级|交易建议|"
    r"(?:明日|次日).{0,6}(?:交易|买入|卖出)|上车|"
    r"(?:买入|卖出|增持|减持).{0,6}(?:评级|建议)|(?:评级|建议).{0,6}(?:买入|卖出|增持|减持)|"
    r"\btarget\s+price\b|\b(?:buy|sell|overweight|underweight)\s+(?:rating|recommendation|advice)\b|"
    r"\bposition(?:\s+sizing)?\s+(?:advice|recommendation)\b|"
    r"\b(?:tomorrow|next[- ]day)\s+(?:trade|trading|buy|sell)\b|"
    r"\b(?:trade|trading|investment)\s+(?:advice|recommendation)\b|\bshould\s+i\s+(?:buy|sell)\b|"
    r"\brecommend(?:\s+\w+){0,3}\s+stocks?\b|\bstock\s+(?:picks?|recommendations?)\b|"
    r"\btrading\s+signals?\b|\bcan\s+(?:i|we)\s+(?:buy|follow)\b|\bget\s+on\s+board\b",
    re.IGNORECASE,
)

_TRADE_VERB = r"(?:买入|卖出|买|卖)"
_DIRECT_DECISION = re.compile(
    rf"(?:值得|应该|现在适合|适合|要不要|能不能|该不该).{{0,12}}?{_TRADE_VERB}|"
    rf"{_TRADE_VERB}不{_TRADE_VERB}|"
    rf"(?:要|能|可以).{{0,3}}?{_TRADE_VERB}.{{0,2}}?吗|"
    rf"{_TRADE_VERB}.{{0,4}}?(?:还是|或).{{0,4}}?{_TRADE_VERB}|"
    rf"该.{{0,3}}?{_TRADE_VERB}.{{0,6}}?(?:还是|吗)|可以买|可以跟"
)

_SECURITY_CONTEXT = re.compile(
    r"股票|个股|证券|持仓|仓位|该股|这只股|A股|港股|美股|基金|债券|可转债",
    re.IGNORECASE,
)

_OPERATING_OBJECT = r"(?:设备|原料|资产|子公司|业务|产能|土地|厂房|机器|库存|专利|技术|牌照|项目|矿产|商品)"
_OPERATING_ACTION = r"(?:买入|卖出|购买|出售|收购|处置|买|卖)"
_OPERATING_TRANSACTION = re.compile(
    rf"{_OPERATING_ACTION}(?:其|该|部分|全部|相关|核心|现有|新增|一批)?{_OPERATING_OBJECT}"
)


def is_forbidden_investment_request(message: str) -> bool:
    """Return True only for hard bans or direct security-trading decisions.

    Explicit security context always wins.  The operating-context exception is
    deliberately narrow and only applies when a named enterprise object is the
    object of the buy/sell action.
    """
    if _HARD_FORBIDDEN.search(message):
        return True
    direct_matches = list(_DIRECT_DECISION.finditer(message))
    if not direct_matches:
        return False
    if _SECURITY_CONTEXT.search(message):
        return True
    operating_matches = list(_OPERATING_TRANSACTION.finditer(message))
    if operating_matches and all(
        any(op.start() < decision.end() and op.end() > decision.start()
            for op in operating_matches)
        for decision in direct_matches
    ):
        return False
    return True
