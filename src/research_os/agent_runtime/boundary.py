from collections.abc import Callable
from typing import Any


ALLOWED_TOOLS = frozenset({
    "get_company_profile", "check_data_readiness", "query_industry_graph", "run_research_scenario",
})
PROHIBITED_TOOLS = frozenset({"cninfo_fetch", "nbs_fetch", "collector_execute", "graph_write", "graph_apply"})


class ResearchOSToolFacade:
    """Only capability-level calls cross the Harness → Research OS boundary."""

    def __init__(self, handlers: dict[str, Callable[..., dict[str, Any]]]):
        unknown = set(handlers) - ALLOWED_TOOLS
        if unknown:
            raise ValueError(f"unsupported Research OS tools: {sorted(unknown)}")
        self.handlers = handlers

    def call(self, name: str, **kwargs: Any) -> dict[str, Any]:
        if name in PROHIBITED_TOOLS or name not in ALLOWED_TOOLS:
            raise PermissionError(f"tool is not exposed at the agent boundary: {name}")
        handler = self.handlers.get(name)
        if handler is None:
            return {"status": "unavailable", "tool": name, "reason": "capability not wired in spike"}
        result = handler(**kwargs)
        if not isinstance(result, dict):
            raise TypeError("Research OS tool results must be structured objects")
        return result


class HarnessBoundary:
    def __init__(self, facade: ResearchOSToolFacade, profile: Any):
        self.facade = facade
        self.profile = profile

    def select_tool(self, request: str) -> str:
        text = request.lower()
        if "产业链" in request or "industry" in text or "风险" in request:
            return "query_industry_graph"
        if "现金流" in request or "财务" in request or "financial" in text:
            return "run_research_scenario"
        if "准备" in request or "就绪" in request or "readiness" in text:
            return "check_data_readiness"
        return "get_company_profile"

    def handle(self, request: str, **kwargs: Any) -> dict[str, Any]:
        tool = self.select_tool(request)
        return {"selected_tool": tool, "result": self.facade.call(tool, **kwargs)}
