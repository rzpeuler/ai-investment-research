"""Single-attempt schema-driven extraction through the shared LlmClient."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict, Optional

from research_os.dashboard.llm_budget import ChatStageBudget
from research_os.dashboard.scenario_specs import ScenarioChatSpec
from research_os.dashboard.target_resolver import normalize_mention
from research_os.llm.client import LlmClient
from research_os.validators.schema_validator import load_schema, validate_instance


@dataclass(frozen=True)
class ExtractionResult:
    status: str
    draft: Optional[Dict[str, Any]] = None
    message: str = ""
    llm_calls: int = 0


class ChatSchemaExtractor:
    def __init__(self, llm_client: Optional[LlmClient]):
        self.llm_client = llm_client

    def extract(self, message: str, spec: ScenarioChatSpec) -> ExtractionResult:
        if self.llm_client is None:
            return ExtractionResult("clarification", message="LLM 未配置，无法抽取复杂自然语言。")
        schema = load_schema(spec.chat_input_schema_name)
        prompt = (
            "只抽取用户明确表达的语义，禁止生成内部 ID、证券映射、系统时间或默认假设。"
            "若信息不足，complete=false 并给出一个澄清问题。输出必须严格满足给定 JSON Schema。"
            f"场景={spec.scenario_id}；用户消息={json.dumps(message, ensure_ascii=False)}"
        )
        budget = ChatStageBudget("extract")
        request = LlmClient.make_request(
            task_id="chat-extract", module=f"chat_extract:{spec.scenario_id}", prompt=prompt,
            output_schema_name=spec.chat_input_schema_name, requested_model_class="flash",
        )
        response = self.llm_client.generate_json(request, schema, budget=budget)
        provenance_errors = self._provenance_errors(message, response.output or {})
        if (response.status != "success" or not response.schema_valid or not response.output
                or validate_instance(response.output, spec.chat_input_schema_name)
                or provenance_errors):
            return ExtractionResult(
                "clarification", message="语义抽取未通过结构校验，请补充明确字段或重试。",
                llm_calls=budget.flash_calls,
            )
        return ExtractionResult("resolved", draft=response.output, llm_calls=budget.flash_calls)

    @staticmethod
    def _provenance_errors(message: str, draft: Dict[str, Any]) -> list[str]:
        """Critical user-semantic mentions must be traceable to the actual message."""
        haystack = normalize_mention(message)
        errors = []
        for field in ("entity_mentions", "company_mentions", "industry_mentions"):
            for value in draft.get(field) or []:
                if normalize_mention(str(value)) not in haystack:
                    errors.append(f"{field} contains text not present in user message")
        for field in ("theme_keywords", "metric_expressions", "scenario_expressions"):
            for value in draft.get(field) or []:
                if normalize_mention(str(value)) not in haystack:
                    errors.append(f"{field} contains text not present in user message")
        for field in ("temporal_expression", "report_date_expression", "forecast_period_expression"):
            value = draft.get(field)
            if value and normalize_mention(str(value)) not in haystack:
                errors.append(f"{field} contains text not present in user message")
        for item in draft.get("explicit_assumptions") or []:
            for field in ("statement", "metric_expression", "value_expression", "period_expression"):
                value = item.get(field)
                if value and normalize_mention(str(value)) not in haystack:
                    errors.append(f"explicit_assumptions.{field} contains text not present in user message")
        depth = draft.get("depth_hint")
        if depth and not ChatSchemaExtractor._depth_is_anchored(message, depth):
            errors.append("depth_hint is not deterministically anchored in user message")
        return errors

    @staticmethod
    def _depth_is_anchored(message: str, depth: str) -> bool:
        normalized = normalize_mention(message)
        markers = {
            "fast": ("fast", "快速", "简要", "简版"),
            "standard": ("standard", "标准"),
            "deep": ("deep", "深度", "深入", "详细"),
        }
        return any(normalize_mention(marker) in normalized for marker in markers.get(depth, ()))
