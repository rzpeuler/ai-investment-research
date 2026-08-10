"""Transport-free conversational research control layer."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from research_os.dashboard.industry_resolver import IndustryResolver
from research_os.dashboard.models import ChatRequest, ChatResult, TemporalResult
from research_os.dashboard.request_builder import ClarificationRequired
from research_os.dashboard.route_service import ChatRouteService
from research_os.dashboard.safety import is_forbidden_investment_request
from research_os.dashboard.scenario_specs import CHAT_SCENARIO_SPECS
from research_os.dashboard.schema_extractor import ChatSchemaExtractor
from research_os.dashboard.target_resolver import ResearchTargetResolver
from research_os.dashboard.temporal_resolver import TemporalResolver
from research_os.utils.time import shanghai_now
from research_os.validators.schema_validator import validate_instance


class ChatService:
    def __init__(self, project_root: str | Path, db: Any, orchestrator: Any,
                 llm_client: Any = None, clock=None):
        self.project_root = Path(project_root)
        self.db = db
        self.orchestrator = orchestrator
        self.llm_client = llm_client
        self.clock = clock or shanghai_now
        self.target_resolver = ResearchTargetResolver(db)
        self.temporal_resolver = TemporalResolver()
        self.industry_resolver = IndustryResolver(db)

    def handle(self, request: ChatRequest) -> ChatResult:
        # Exactly one clock capture per turn. Everything below receives this value.
        reference_now: datetime = self.clock()
        reference_iso = reference_now.isoformat(timespec="seconds")
        if is_forbidden_investment_request(request.message):
            return ChatResult("failed", "该请求涉及禁止的交易建议、评级、仓位、目标价或荐股内容。", reference_now=reference_iso)

        route = ChatRouteService(self.llm_client, self.target_resolver.is_exact_authoritative_name).route(
            request.message, request.selected_scenario, request.llm_enabled
        )
        if route.status != "resolved" or route.scenario is None:
            state = "failed" if route.status == "failure" else "clarification"
            return ChatResult(state, route.message, reference_now=reference_iso, llm_calls=route.llm_calls)
        scenario = route.scenario
        spec = CHAT_SCENARIO_SPECS[scenario]

        if request.llm_enabled and self.llm_client is not None:
            extracted = ChatSchemaExtractor(self.llm_client).extract(request.message, spec)
            llm_calls = route.llm_calls + extracted.llm_calls
            if extracted.status != "resolved" or extracted.draft is None:
                return ChatResult("clarification", extracted.message, scenario=scenario,
                                  reference_now=reference_iso, llm_calls=llm_calls)
            draft = extracted.draft
        else:
            llm_calls = route.llm_calls
            draft = spec.deterministic_draft_builder(request.message)
            errors = validate_instance(draft, spec.chat_input_schema_name)
            if errors:
                return ChatResult("clarification", "当前表达需要启用 LLM，或请选择场景并提供完整代码/精确名称。",
                                  scenario=scenario, reference_now=reference_iso, llm_calls=llm_calls)

        if not draft.get("complete", True):
            return ChatResult("clarification", draft.get("clarification_question") or "请补充缺失信息。",
                              scenario=scenario, public_draft=draft, reference_now=reference_iso,
                              llm_calls=llm_calls)

        target = self._resolve_target(scenario, draft)
        if target is not None and target.status == "failure":
            return ChatResult("failed", target.message, scenario=scenario, public_draft=draft,
                              reference_now=reference_iso, llm_calls=llm_calls)
        if target is not None and target.status == "clarification":
            return ChatResult("clarification", target.message, scenario=scenario,
                              public_draft=draft, reference_now=reference_iso,
                              llm_calls=llm_calls)
        temporal = self.temporal_resolver.resolve(
            draft.get("report_date_expression") or draft.get("temporal_expression"), reference_now
        )
        if temporal.status == "clarification":
            return ChatResult("clarification", temporal.message, scenario=scenario,
                              public_draft=draft, reference_now=reference_iso, llm_calls=llm_calls)
        industry = self._resolve_industry(spec, draft, target)
        if industry is not None and industry.status == "failure":
            return ChatResult("failed", industry.message, scenario=scenario, public_draft=draft,
                              reference_now=reference_iso, llm_calls=llm_calls)
        if industry is not None and industry.status == "clarification":
            return ChatResult("clarification", industry.message, scenario=scenario,
                              public_draft=draft, reference_now=reference_iso,
                              llm_calls=llm_calls)
        try:
            minimal = spec.minimal_request_builder(
                draft, target, temporal, industry, reference_now, request.research_live
            )
        except ClarificationRequired as exc:
            return ChatResult("clarification", str(exc), scenario=scenario, public_draft=draft,
                              reference_now=reference_iso, llm_calls=llm_calls)
        try:
            result = self.orchestrator.execute(scenario, minimal)
        except Exception as exc:  # noqa: BLE001 - transport layer needs a closed failure state
            return ChatResult("failed", f"研究执行失败: {type(exc).__name__}", scenario=scenario,
                              public_draft=draft, minimal_request=minimal,
                              reference_now=reference_iso, llm_calls=llm_calls)
        payload = result.model_dump() if hasattr(result, "model_dump") else dict(result)
        state = "failed" if payload.get("status") == "failed" else "executed"
        return ChatResult(state, payload.get("message") or "研究执行完成。", scenario=scenario,
                          public_draft=draft, minimal_request=minimal, research_result=payload,
                          reference_now=reference_iso, llm_calls=llm_calls)

    def _resolve_target(self, scenario: str, draft: dict):
        mentions = draft.get("company_mentions") or draft.get("entity_mentions") or []
        if not mentions:
            return None
        return self.target_resolver.resolve(mentions, scenario)

    def _resolve_industry(self, spec, draft: dict, target):
        mentions = draft.get("industry_mentions") or []
        if mentions:
            return self.industry_resolver.resolve(mentions)
        if spec.industry_policy == "explicit_or_profile" and target and target.industry_ids:
            return self.industry_resolver.resolve(authoritative_ids=target.industry_ids)
        return None
