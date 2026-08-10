"""Scenario selection with deterministic safe routes and optional schema LLM."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Optional

from research_os.dashboard.llm_budget import ChatStageBudget
from research_os.dashboard.safety import safe_llm_clarification
from research_os.llm.client import LlmClient
from research_os.orchestrator.runners import DEFAULT_SCENARIOS
from research_os.validators.schema_validator import load_schema, validate_instance


@dataclass(frozen=True)
class RouteResult:
    status: str
    scenario: Optional[str] = None
    message: str = ""
    llm_calls: int = 0


_ONLY_CODE = re.compile(r"^\s*\d{6}(?:\.(?:SH|SZ|BJ))?\s*$", re.IGNORECASE)


class ChatRouteService:
    def __init__(self, llm_client: Optional[LlmClient] = None,
                 exact_name_check: Optional[Callable[[str], bool]] = None):
        self.llm_client = llm_client
        self.exact_name_check = exact_name_check or (lambda _value: False)

    def route(self, message: str, selected_scenario: Optional[str], llm_enabled: bool) -> RouteResult:
        selected = selected_scenario or "AUTO"
        if selected != "AUTO":
            if selected not in DEFAULT_SCENARIOS:
                return RouteResult("failure", message="未知场景。")
            return RouteResult("resolved", scenario=selected)
        compact = "".join(message.split())
        if _ONLY_CODE.fullmatch(message) or self.exact_name_check(message.strip()):
            return RouteResult("clarification", message="请说明要做个股研报、个股复盘、异动分析、财报预期还是首次覆盖。")
        if "晨报" in compact:
            return RouteResult("resolved", scenario="morning_brief")
        if "晚报" in compact:
            return RouteResult("resolved", scenario="evening_brief")
        if not llm_enabled or self.llm_client is None:
            return RouteResult("clarification", message="无法确定研究场景；请选择场景，或启用 LLM 理解复杂表达。")
        budget = ChatStageBudget("route")
        prompt = (
            "将用户请求路由到一个既有研究场景。AUTO 下仅公司名或证券代码不得自行选择场景，"
            "必须 needs_clarification=true。不得提供投资建议。用户消息：" + message
        )
        request = LlmClient.make_request(
            task_id="chat-route", module="chat_route", prompt=prompt,
            output_schema_name="chat_route", requested_model_class="flash",
        )
        response = self.llm_client.generate_json(request, load_schema("chat_route"), budget=budget)
        calls = budget.flash_calls
        if (response.status != "success" or not response.schema_valid or not response.output
                or validate_instance(response.output, "chat_route")):
            return RouteResult("clarification", message="场景识别未通过结构校验，请直接选择场景。", llm_calls=calls)
        output = response.output
        scenario = output.get("scenario")
        if output.get("needs_clarification") or scenario not in DEFAULT_SCENARIOS:
            return RouteResult(
                "clarification",
                message=safe_llm_clarification(
                    output.get("clarification_question"), "请明确要使用的研究场景。"
                ),
                llm_calls=calls,
            )
        return RouteResult("resolved", scenario=scenario, llm_calls=calls)
