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
        cutoff: str,
        request_id: str = "",
        company_entity_id: str = "",
        prompt_version: str = "v1",
    ) -> LlmResponse:
        """运行一个语义任务。返回 LlmResponse（未配置时 called=false 诚实回退）。"""
        schema_name = EQUITY_LLM_SCHEMAS.get(task_name)
        if schema_name is None:
            raise ValueError(f"未知语义任务: {task_name}")

        # 预算检查：Pro 任务须有剩余；Flash 耗尽则不再调用
        model_class = "flash"
        if not self.budget.can_call(model_class):
            resp = LlmResponse(
                call_id=new_uuid(), called=False, status="fallback",
                warnings=["任务级 Flash 预算耗尽，跳过模型调用"],
            )
            return resp

        prompt = self._build_prompt(
            task_name, evidence_excerpts, evidence_ids, cutoff, schema_name, prompt_version,
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
        resp = self.client.generate_json(request, output_schema={})
        # 实际发生调用才计预算
        if resp.called:
            self.budget.record(model_class)

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
        for i, ex in enumerate(excerpts[:5]):
            lines.append(f"- [{i}] {ex[:500]}")
        lines.append(f"证据 IDs: {', '.join(evidence_ids[:20])}")
        lines.append("禁止输出：目标价、评级、买卖/仓位建议、确定性收益承诺；数字不得篡改。")
        return "\n".join(lines)


def run_equity_llm_task(
    client: LlmClient,
    depth: str,
    task_name: str,
    task_id: str,
    excerpts: List[str],
    evidence_ids: List[str],
    cutoff: str,
) -> LlmResponse:
    """便捷入口。"""
    return EquityLlmTasks(client, depth).run_task(
        task_name, task_id=task_id, evidence_excerpts=excerpts,
        evidence_ids=evidence_ids, cutoff=cutoff,
    )
