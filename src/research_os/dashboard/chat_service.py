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
from research_os.dashboard.scenario_specs import (
    CHAT_SCENARIO_SPECS, CompletionRequirement, IndustryPolicy, TargetPolicy, TimePolicy,
)
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

        target = self._resolve_target(spec, draft)
        if target is not None and target.status == "failure":
            return ChatResult("failed", target.message, scenario=scenario, public_draft=draft,
                              reference_now=reference_iso, llm_calls=llm_calls)
        if target is not None and target.status == "clarification":
            return ChatResult("clarification", target.message, scenario=scenario,
                              public_draft=draft, reference_now=reference_iso,
                              llm_calls=llm_calls)
        temporal = self.temporal_resolver.resolve(
            self._temporal_expression(spec, draft), reference_now
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
        completion_message = self._completion_message(spec, draft, target, industry)
        if completion_message:
            return ChatResult("clarification", completion_message, scenario=scenario,
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

    def _resolve_target(self, spec, draft: dict):
        mentions = draft.get("company_mentions") or draft.get("entity_mentions") or []
        if not mentions:
            return None
        return self.target_resolver.resolve(mentions, spec.scenario_id)

    @staticmethod
    def _temporal_expression(spec, draft: dict):
        if spec.time_policy is TimePolicy.REPORT_DATE_OPTIONAL:
            return draft.get("report_date_expression")
        return draft.get("temporal_expression")

    def _resolve_industry(self, spec, draft: dict, target):
        mentions = draft.get("industry_mentions") or []
        if mentions:
            return self.industry_resolver.resolve(mentions)
        if (spec.industry_policy is IndustryPolicy.EXPLICIT_OR_PROFILE
                and target and target.industry_ids):
            return self.industry_resolver.resolve(authoritative_ids=target.industry_ids)
        return None

    @staticmethod
    def _completion_message(spec, draft: dict, target, industry) -> Optional[str]:
        target_required = spec.target_policy in {
            TargetPolicy.ENTITY_REQUIRED,
            TargetPolicy.PROFILE_REQUIRED,
            TargetPolicy.PROFILE_AND_INDUSTRY_REQUIRED,
        }
        if target_required and (target is None or target.status != "resolved"):
            return "请提供唯一且可由权威画像确认的研究目标。"
        if (spec.target_policy in {TargetPolicy.PROFILE_REQUIRED,
                                   TargetPolicy.PROFILE_AND_INDUSTRY_REQUIRED}
                and not target.company_entity_id):
            return "请提供可匹配权威公司画像的研究目标。"
        if (spec.target_policy is TargetPolicy.PROFILE_AND_INDUSTRY_REQUIRED
                and not target.security_entity_id):
            return "请提供可匹配权威证券画像的研究目标。"

        requirements = set(spec.completion_policy)
        if CompletionRequirement.TARGET in requirements and target is None:
            return "请提供唯一研究目标。"
        if (CompletionRequirement.INDUSTRY in requirements
                and (industry is None or industry.status != "resolved")):
            return "请提供唯一且可由权威数据确认的行业。"
        if CompletionRequirement.THEME_OR_INDUSTRY in requirements:
            has_theme = bool(draft.get("theme_keywords"))
            has_industry = industry is not None and industry.status == "resolved"
            if not has_theme and not has_industry:
                return "请提供至少一个主题关键词或唯一行业。"
        if (CompletionRequirement.FORECAST_PERIOD in requirements
                and not draft.get("forecast_period_expression")):
            return "请明确完整财年预测期间。"
        if (CompletionRequirement.ASSUMPTION in requirements
                and not draft.get("explicit_assumptions")):
            return "请至少提供一条带明确数值的用户假设。"
        return None
