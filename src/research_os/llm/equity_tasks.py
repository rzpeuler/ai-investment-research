"""Phase 4 LLM 语义任务（任务书 3.18/Commit 14）。

- 统一经现有 LlmClient 调用；禁止旁路 SDK 或直接 HTTP 模型调用；
- 任务级 Flash/Pro 预算（fast 2/0、standard 5/1、deep 8/1）；
- 确定性回退不得产生 MODEL_INFERENCE；
- 数字篡改/目标价输出被拒绝；
- 不保存密钥、Cookie、Authorization、模型私有思维过程。
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from research_os.llm.client import LlmClient
from research_os.llm.models import LlmRequest, LlmResponse
from research_os.utils.id import new_uuid

BUDGET_PER_DEPTH = {
    "fast": {"flash_max": 2, "pro_max": 0},
    "standard": {"flash_max": 5, "pro_max": 1},
    "deep": {"flash_max": 8, "pro_max": 1},
}

# 语义任务输出 Schema 名（对应 schemas/ 中的对象）
EQUITY_LLM_SCHEMAS = {
    "business_description_normalization": "research_finding",
    "management_statement_summary": "research_finding",
    "product_name_mapping": "business_segment",
    "competitive_factor_candidates": "competitive_factor",
    "catalyst_candidates": "catalyst",
    "risk_candidates": "risk_factor",
    "counter_evidence_organizing": "research_finding",
    "research_questions": "research_finding",
    "section_draft": "research_finding",
}

SEMANTIC_EVIDENCE_POLICY = {
    "business_description_normalization": {
        "allowed_types": {"official_disclosure", "company_official", "institution_material"},
        "minimum": 1,
    },
    "competitive_factor_candidates": {
        "allowed_types": {
            "official_disclosure", "company_official", "official_statistics",
            "institution_material", "news_report", "media_report",
        },
        "minimum": 1,
    },
    "counter_evidence_organizing": {
        "allowed_types": {
            "official_disclosure", "company_official", "official_statistics",
            "institution_material", "news_report", "media_report", "manual_input",
        },
        "minimum": 1,
    },
    "research_questions": {
        "allowed_types": {
            "official_disclosure", "official_statistics", "company_official",
            "news_report", "media_report", "social_opinion", "institution_material",
            "market_data", "manual_input",
        },
        "minimum": 1,
    },
    "management_statement_summary": {
        "allowed_types": {"official_disclosure", "company_official", "institution_material"},
        "minimum": 1,
    },
    "product_name_mapping": {
        "allowed_types": {"official_disclosure", "company_official"},
        "minimum": 1,
    },
    "catalyst_candidates": {
        "allowed_types": {
            "official_disclosure", "official_statistics", "company_official",
            "institution_material", "news_report", "media_report",
        },
        "minimum": 1,
    },
    "risk_candidates": {
        "allowed_types": {
            "official_disclosure", "official_statistics", "company_official",
            "institution_material", "news_report", "media_report", "manual_input",
        },
        "minimum": 1,
    },
    "section_draft": {
        "allowed_types": {
            "official_disclosure", "official_statistics", "company_official",
            "institution_material", "news_report", "media_report", "manual_input",
            "market_data", "social_opinion",
        },
        "minimum": 1,
    },
}

FORBIDDEN_OUTPUT_TERMS = ["target_price", "fair_value", "upside", "买入", "卖出", "增持", "减持", "仓位"]


@dataclass
class BudgetTracker:
    """任务级 Flash/Pro 调用预算。"""
    depth: str
    flash_used: int = 0
    pro_used: int = 0

    def __post_init__(self):
        budget = BUDGET_PER_DEPTH.get(self.depth, BUDGET_PER_DEPTH["standard"])
        self.flash_max = budget["flash_max"]
        self.pro_max = budget["pro_max"]

    def can_call(self, model_class: str) -> bool:
        if model_class == "pro":
            return self.pro_used < self.pro_max
        return self.flash_used < self.flash_max

    def record(self, model_class: str) -> None:
        if model_class == "pro":
            self.pro_used += 1
        else:
            self.flash_used += 1

    @property
    def exhausted(self) -> bool:
        return not self.can_call("flash") and not self.can_call("pro")

    def summary(self) -> Dict[str, Any]:
        return {"depth": self.depth, "flash_used": self.flash_used, "pro_used": self.pro_used,
                "flash_max": self.flash_max, "pro_max": self.pro_max}


def _detect_forbidden(output: Any) -> List[str]:
    """拒绝模型输出目标价/评级/仓位等禁止内容。"""
    hits: List[str] = []
    blob = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
    for term in FORBIDDEN_OUTPUT_TERMS:
        if re.search(re.escape(term), blob, re.IGNORECASE):
            hits.append(term)
    return hits


class EquityLlmTasks:
    """Phase 4 语义任务执行器（统一 LlmClient，无旁路）。"""

    def __init__(self, client: LlmClient, depth: str = "standard"):
        if not isinstance(client, LlmClient):
            raise TypeError("必须使用统一 LlmClient（禁止旁路）")
        self.client = client
        self.budget = BudgetTracker(depth)

    def run_task(
        self,
        task_name: str,
        *,
        task_id: str,
        evidence_excerpts: List[str],
        evidence_ids: List[str],
        evidence_types: List[str],
        cutoff: str,
        request_id: str = "",
        company_entity_id: str = "",
        prompt_version: str = "v1",
    ) -> LlmResponse:
        """运行一个语义任务。返回 LlmResponse（未配置时 called=false 诚实回退）。"""
        schema_name = EQUITY_LLM_SCHEMAS.get(task_name)
        if schema_name is None:
            raise ValueError(f"未知语义任务: {task_name}")
        if not (len(evidence_excerpts) == len(evidence_ids) == len(evidence_types)):
            raise ValueError("语义任务 Evidence 摘录、ID 与类型数量不一致")
        policy = SEMANTIC_EVIDENCE_POLICY[task_name]
        eligible = [
            (excerpt, evidence_id, evidence_type)
            for excerpt, evidence_id, evidence_type in zip(
                evidence_excerpts, evidence_ids, evidence_types)
            if evidence_type in policy["allowed_types"]
        ]
        if len(eligible) < policy["minimum"]:
            return LlmResponse(
                call_id=new_uuid(), called=False, status="fallback",
                warnings=[f"{task_name} 最低合格 Evidence 输入不足"],
                usage_metadata={"failure_stage": "evidence_eligibility"},
            )
        evidence_excerpts = [item[0] for item in eligible]
        evidence_ids = [item[1] for item in eligible]
        evidence_types = [item[2] for item in eligible]

        model_class = "flash"

        prompt = self._build_prompt(
            task_name, evidence_excerpts, evidence_ids, evidence_types,
            cutoff, schema_name, prompt_version,
            request_id=request_id, company_entity_id=company_entity_id,
        )
        request = LlmRequest(
            call_id=new_uuid(),
            task_id=task_id,
            module=f"equity_research.{task_name}",
            prompt=prompt,
            prompt_template_version=prompt_version,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            input_evidence_ids=evidence_ids,
            requested_model_class=model_class,
            provider="",
            output_schema_name=schema_name,
            timeout_seconds=60,
        )
        resp = self.client.generate_json(request, output_schema={}, budget=self.budget)

        # 禁止内容拦截（模型输出目标价/评级等 → 拒绝）
        if resp.output is not None:
            forbidden = _detect_forbidden(resp.output)
            if forbidden:
                resp.output = None
                resp.status = "failed"
                resp.validation_errors = [f"模型输出包含禁止内容: {forbidden}"]
        return resp

    def _build_prompt(
        self,
        task_name: str,
        excerpts: List[str],
        evidence_ids: List[str],
        evidence_types: List[str],
        cutoff: str,
        schema_name: str,
        prompt_version: str,
        request_id: str = "",
        company_entity_id: str = "",
    ) -> str:
        """Prompt 只含最小必要摘录 + ID + 截止时间 + Schema + 禁止项。"""
        lines = [
            f"任务: {task_name}（输出 Schema: {schema_name}，Prompt 版本 {prompt_version}）",
            f"信息截止时间: {cutoff}",
            f"request_id: {request_id or task_name}",
            f"company_entity_id: {company_entity_id or 'UNKNOWN'}",
            "输入证据摘录（最小必要）：",
        ]
        for evidence_id, evidence_type, ex in list(zip(
            evidence_ids, evidence_types, excerpts))[:20]:
            lines.append(f"- [{evidence_id}|{evidence_type}] {ex[:500]}")
        lines.append("禁止输出：目标价、评级、买卖/仓位建议、确定性收益承诺；数字不得篡改。")
        return "\n".join(lines)


def run_equity_llm_task(
    client: LlmClient,
    depth: str,
    task_name: str,
    task_id: str,
    excerpts: List[str],
    evidence_ids: List[str],
    evidence_types: List[str],
    cutoff: str,
) -> LlmResponse:
    """便捷入口。"""
    return EquityLlmTasks(client, depth).run_task(
        task_name, task_id=task_id, evidence_excerpts=excerpts,
        evidence_ids=evidence_ids, evidence_types=evidence_types, cutoff=cutoff,
    )
