"""Narrow no-LLM drafts; complex semantic extraction stays fail-closed."""
from __future__ import annotations

import re
from typing import Any, Dict


_FULL_SYMBOL = re.compile(r"\d{6}\.(?:SH|SZ|BJ)", re.IGNORECASE)


def _temporal(message: str):
    markers = ("今天", "今日", "昨天", "昨日", "最近7天", "最近一个月", "本周", "本月")
    return message if any(x in message for x in markers) or re.search(r"\d{4}[-年]\d{1,2}", message) else None


def _mention(message: str) -> str:
    match = _FULL_SYMBOL.search(message)
    return match.group(0).upper() if match else message.strip()


def brief(message: str) -> Dict[str, Any]:
    return {"entity_mentions": [], "industry_mentions": [], "report_date_expression": _temporal(message),
            "research_focus": [], "complete": True, "clarification_question": None}


def daily(message: str) -> Dict[str, Any]:
    return {"entity_mentions": [], "industry_mentions": [], "temporal_expression": _temporal(message),
            "research_focus": [], "complete": True, "clarification_question": None}


def abnormal(message: str) -> Dict[str, Any]:
    return {"entity_mentions": [_mention(message)], "temporal_expression": _temporal(message),
            "research_question": None, "metric_expressions": [], "complete": True,
            "clarification_question": None}


def stock(message: str) -> Dict[str, Any]:
    return {"company_mentions": [_mention(message)], "temporal_expression": _temporal(message),
            "research_question": None, "research_focus": [], "depth_hint": None,
            "complete": True, "clarification_question": None}


def complex_requires_llm(_message: str) -> Dict[str, Any]:
    # Deliberately invalid for scenario schemas except for the common completion fields;
    # ChatService reports the no-LLM boundary instead of pretending extraction succeeded.
    return {"complete": False, "clarification_question": "该场景需要启用 LLM 或提供结构化明确输入。"}
