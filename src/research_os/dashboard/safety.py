"""Deterministic investment-advice boundary for conversational input."""
from __future__ import annotations

import re
import unicodedata


_ZH_HARD_FORBIDDEN = re.compile(
    r"目标价(?:格)?|仓位(?:建议|配置)?|自动(?:化)?荐股|推荐.{0,4}股票|交易信号|买卖评级|交易建议|"
    r"(?:明日|次日).{0,6}(?:交易|买入|卖出)|上车|"
    r"(?:买入|卖出|增持|减持).{0,6}(?:评级|建议)|(?:评级|建议).{0,6}(?:买入|卖出|增持|减持)"
)

_EN_HARD_FORBIDDEN = re.compile(
    r"\btarget\s+price\b|\b(?:buy|sell|overweight|underweight)\s+(?:rating|recommendation|advice)\b|"
    r"\bposition(?:\s+sizing)?\s+(?:advice|recommendation)\b|"
    r"\b(?:tomorrow|next[- ]day)\s+(?:trade|trading|buy|sell)\b|"
    r"\b(?:trade|trading|investment)\s+(?:advice|recommendation)\b|"
    r"\brecommend(?:\s+\w+){0,3}\s+stocks?\b|\bstock\s+(?:picks?|recommendations?)\b|"
    r"\btrading\s+signals?\b|\bget\s+on\s+board\b"
)

_ZH_TRADE_VERB = r"(?:买入|卖出|买|卖)"
_ZH_DIRECT_DECISION = re.compile(
    rf"(?:你|您)会(?:不会)?.{{0,12}}?{_ZH_TRADE_VERB}.{{0,24}}?(?:吗|\?)|"
    rf"(?:值得|应该|现在适合|适合|要不要|能不能|该不该).{{0,12}}?{_ZH_TRADE_VERB}|"
    rf"{_ZH_TRADE_VERB}不{_ZH_TRADE_VERB}|"
    rf"(?:要|能|可以).{{0,3}}?{_ZH_TRADE_VERB}.{{0,2}}?吗|"
    rf"{_ZH_TRADE_VERB}.{{0,4}}?(?:还是|或).{{0,4}}?{_ZH_TRADE_VERB}|"
    rf"该.{{0,3}}?{_ZH_TRADE_VERB}.{{0,6}}?(?:还是|吗)|可以买|可以跟"
)

_EN_DIRECT_DECISION = re.compile(
    r"\bwould\s+you\s+(?:buy|sell)\b|"
    r"\bworth\s+(?:buying|selling)\b|"
    r"\b(?:buy|sell)\s+or\s+(?:buy|sell)\b|"
    r"\bgood\s+time(?:\s+\w+){0,6}?\s+to\s+(?:buy|sell)\b|"
    r"\bshould\s+(?:i|we)\s+(?:buy|sell)\b|"
    r"\bcan\s+(?:i|we)\s+(?:buy|sell|follow)\b"
)

_ZH_SECURITY_CONTEXT = re.compile(r"股票|个股|证券|股份|持仓|仓位|该股|这只股|A股|港股|美股|基金|债券|可转债")
_EN_SECURITY_CONTEXT = re.compile(
    r"\b(?:stock|stocks|security|securities|shares?|holdings?|position|portfolio|bond|bonds|fund|funds)\b"
)

_ZH_ANY_TRADE_ACTION = re.compile(r"买入|卖出|买|卖|交易")
_ZH_DECISION_CUE = re.compile(r"\?|吗|是否|合适|会不会|该不该|要不要|应该|能不能|值得")
_EN_ANY_TRADE_ACTION = re.compile(r"\b(?:buy|buying|bought|sell|selling|sold|trade|trading)\b")
_EN_DECISION_CUE = re.compile(r"\?|\b(?:would|do|does|should|can|could|is|are|will)\b")

_ZH_OPERATING_OBJECT = r"(?:设备|原料|资产|子公司|业务|产能|土地|厂房|机器|库存|专利|技术|牌照|项目|矿产|商品)"
_ZH_OPERATING_ACTION = r"(?:买入|卖出|购买|出售|收购|处置|买|卖)"
_ZH_OPERATING_TRANSACTION = re.compile(
    rf"{_ZH_OPERATING_ACTION}(?:其|该|部分|全部|相关|核心|现有|新增|一批)?{_ZH_OPERATING_OBJECT}"
)

_EN_OPERATING_TRANSACTION = re.compile(
    r"\b(?:buy|sell|buying|selling|acquire|dispose\s+of)\s+"
    r"(?:(?:its|the|some|new|additional|part\s+of)\s+)?"
    r"(?:equipment|raw\s+materials?|assets?|subsidiar(?:y|ies)|business|capacity|land|factory|"
    r"inventory|patents?|technology|licen[cs]es?|projects?|minerals?|commodities)\b"
)


def _normalized_views(message: str) -> tuple[str, str]:
    normalized = unicodedata.normalize("NFKC", message)
    compact = "".join(normalized.split())
    token_text = " ".join(normalized.casefold().split())
    return compact, token_text


def _direct_decision_is_forbidden(text: str, direct_pattern: re.Pattern,
                                  security_pattern: re.Pattern,
                                  operating_pattern: re.Pattern) -> bool:
    decisions = list(direct_pattern.finditer(text))
    if not decisions:
        return False
    if security_pattern.search(text):
        return True
    operations = list(operating_pattern.finditer(text))
    if operations and all(
        any(op.start() < decision.end() and op.end() > decision.start() for op in operations)
        for decision in decisions
    ):
        return False
    return True


def is_forbidden_investment_request(message: str) -> bool:
    """Return True for hard bans or direct security-trading decisions.

    NFKC defeats full-width variants. Chinese rules use a whitespace-free view;
    English rules use case-folded single-space tokens. Explicit security context
    wins over the deliberately narrow enterprise-operating exception.
    """
    compact, token_text = _normalized_views(message)
    if _ZH_HARD_FORBIDDEN.search(compact) or _EN_HARD_FORBIDDEN.search(token_text):
        return True
    if (_ZH_SECURITY_CONTEXT.search(compact)
            and _ZH_ANY_TRADE_ACTION.search(compact)
            and _ZH_DECISION_CUE.search(compact)):
        return True
    if (_EN_SECURITY_CONTEXT.search(token_text)
            and _EN_ANY_TRADE_ACTION.search(token_text)
            and _EN_DECISION_CUE.search(token_text)):
        return True
    if _direct_decision_is_forbidden(
        compact, _ZH_DIRECT_DECISION, _ZH_SECURITY_CONTEXT, _ZH_OPERATING_TRANSACTION
    ):
        return True
    return _direct_decision_is_forbidden(
        token_text, _EN_DIRECT_DECISION, _EN_SECURITY_CONTEXT, _EN_OPERATING_TRANSACTION
    )
