"""统一 LLM Client（Phase 3 任务书 12.1-12.5）。

- generate_json(request, output_schema)：调用 provider -> 结构化校验 -> 落库
- Flash 最多两次修复；第二次失败且符合升级条件 -> 一次 Pro；否则 deterministic fallback
- 失败降级如实记录：llm_called=true + failure_stage（已调用但失败）；
  未调用则 llm_called=false
- 只有实际模型调用且通过校验的 Claim 才能标记 MODEL_INFERENCE
"""
from __future__ import annotations

import hashlib
import os
from time import perf_counter
from typing import Any, Dict, List, Optional, Protocol

from research_os.llm.models import LlmRequest, LlmResponse
from research_os.llm.provider import FakeLlmProvider, LlmProvider
from research_os.llm.routing import ModelRouter
from research_os.llm.validation import LlmOutputValidator
from research_os.models import ModelRoute
from research_os.storage import Database
from research_os.utils.id import new_uuid

MAX_FLASH_FIX_ATTEMPTS = 2   # Flash 最多两次结构修复（12.4）
MAX_PRO_CALLS = 1            # 每个任务最多一次 Pro（12.3）

# Provider 配置状态由环境变量决定（与 config/model_routing.yaml 接入方式一致）
_PROVIDER_ENV_VARS = ("LLM_API_KEY", "DASHSCOPE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")


def is_provider_configured() -> bool:
    """真实 Provider 是否已配置（幂等键/模型路由状态依据）。"""
    return any(bool(os.environ.get(k)) for k in _PROVIDER_ENV_VARS)


class CallBudget(Protocol):
    """可选的任务级调用预算；在每次真实 Provider 调用边界执行。"""

    def can_call(self, model_class: str) -> bool: ...
    def record(self, model_class: str) -> None: ...
    def summary(self) -> Dict[str, Any]: ...


class LlmClient:
    """业务模块统一入口。"""

    def __init__(self, provider: Optional[LlmProvider] = None,
                 router: Optional[ModelRouter] = None,
                 validator: Optional[LlmOutputValidator] = None,
                 db: Optional[Database] = None,
                 configured: bool = False):
        """configured=False 表示未接入真实 Provider（诚实回退 deterministic_fallback）。"""
        self.provider = provider
        self.router = router or ModelRouter()
        self.validator = validator or LlmOutputValidator()
        self.db = db
        self.configured = configured

    # ---------- 主接口 ----------

    def generate_json(self, request: LlmRequest,
                      output_schema: Dict[str, Any],
                      budget: Optional[CallBudget] = None) -> LlmResponse:
        """调用模型并返回通过 Schema 校验的结构化输出。

        未配置 Provider 时：返回 called=False 的失败响应（诚实回退）。
        """
        if not self.configured or self.provider is None:
            resp = LlmResponse(
                call_id=request.call_id, called=False, status="fallback",
                provider="", warnings=["LLM 客户端未配置：确定性回退"],
            )
            self._record(request, resp)
            return resp

        schema_name = request.output_schema_name
        call_started = perf_counter()
        flash_schema_failures = 0
        errors: List[str] = []
        provider_fallback_used = False
        provider_fallback_reason: Optional[str] = None
        selected_model: Optional[str] = None
        total_attempts = 0
        flash_attempts = 0
        pro_attempts = 0
        budget_denied_model: Optional[str] = None
        provider_name = request.provider or type(self.provider).__name__

        while True:
            is_pro = flash_schema_failures >= MAX_FLASH_FIX_ATTEMPTS
            model_class = "pro" if is_pro else "flash"
            if (is_pro and pro_attempts >= MAX_PRO_CALLS) or (
                not is_pro and flash_attempts >= MAX_FLASH_FIX_ATTEMPTS
            ):
                break
            if budget is not None and not budget.can_call(model_class):
                budget_denied_model = model_class
                errors.append(f"任务级 {model_class} 预算耗尽，拒绝 Provider 调用")
                break
            if budget is not None:
                budget.record(model_class)
            if is_pro:
                pro_attempts += 1
            else:
                flash_attempts += 1
            req = LlmRequest(
                call_id=request.call_id, task_id=request.task_id,
                module=request.module, prompt=request.prompt,
                prompt_template_version=request.prompt_template_version,
                prompt_hash=request.prompt_hash,
                input_evidence_ids=request.input_evidence_ids,
                requested_model_class=model_class,
                provider=request.provider, output_schema_name=schema_name,
                timeout_seconds=request.timeout_seconds,
            )
            total_attempts += 1
            try:
                result = self.provider.complete_json(req, output_schema)
            except Exception as exc:  # noqa: BLE001 —— provider 故障回退（不触发业务升级）
                provider_fallback_used = True
                provider_fallback_reason = str(exc)
                errors.append(f"provider 故障: {exc}")
                continue

            if not result.get("ok"):
                errors.append(result.get("error", "provider 返回失败"))
                continue

            valid, parsed, verr = self.validator.validate(
                result.get("output"), schema_name)
            selected_model = result.get("model_id") or ("pro" if is_pro else "flash")
            if valid and parsed is not None:
                resp = LlmResponse(
                    call_id=request.call_id, provider=result.get("provider") or provider_name,
                    model_id=selected_model, called=True, status="success",
                    schema_valid=True, attempt_count=total_attempts,
                    provider_fallback_used=provider_fallback_used,
                    provider_fallback_reason=provider_fallback_reason,
                    business_escalation_used=is_pro,
                    business_escalation_reason=(
                        "Flash 两次结构修复失败，升级 Pro" if is_pro else None),
                    usage_metadata={
                        "attempts_by_model": {"flash": flash_attempts, "pro": pro_attempts},
                        "task_budget": budget.summary() if budget is not None else None,
                    },
                    latency_seconds=round(perf_counter() - call_started, 6),
                    output=parsed,
                )
                self._record(request, resp)
                return resp
            errors.extend(verr)
            if not is_pro:
                flash_schema_failures += 1

        # 全部尝试失败 -> deterministic fallback（如实记录 failure_stage）
        resp = LlmResponse(
            call_id=request.call_id, provider=provider_name,
            model_id=selected_model or ("pro" if flash_schema_failures >= MAX_FLASH_FIX_ATTEMPTS else "flash"),
            called=total_attempts > 0, status="fallback",
            schema_valid=False, attempt_count=total_attempts,
            provider_fallback_used=provider_fallback_used,
            provider_fallback_reason=provider_fallback_reason,
            business_escalation_used=pro_attempts > 0,
            business_escalation_reason=(
                "Flash 两次结构修复失败，升级 Pro"
                if pro_attempts > 0 else None),
            validation_errors=errors[:20],
            usage_metadata={
                "attempts_by_model": {"flash": flash_attempts, "pro": pro_attempts},
                "task_budget": budget.summary() if budget is not None else None,
                "budget_denied_model": budget_denied_model,
            },
            latency_seconds=round(perf_counter() - call_started, 6),
            warnings=[
                (f"任务级 {budget_denied_model} 预算耗尽，确定性回退"
                 if budget_denied_model else "LLM 输出未通过校验，确定性回退")
            ],
        )
        self._record(request, resp)
        return resp

    # ---------- 落库 ----------

    def _record(self, request: LlmRequest, response: LlmResponse) -> None:
        if self.db is None:
            return
        import json as _json

        payload = _json.dumps(response.model_dump(), ensure_ascii=False)
        try:
            with self.db._conn:  # noqa: SLF001
                self.db._conn.execute(  # noqa: SLF001
                    "INSERT INTO llm_call_records (call_id, payload, task_id, module, status, called_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (response.call_id, payload, request.task_id, request.module,
                     response.status, response.recorded_at),
                )
        except Exception:  # noqa: BLE001 —— 记录失败不阻断业务
            pass

    # ---------- 工具 ----------

    @staticmethod
    def make_request(task_id: str, module: str, prompt: str,
                     output_schema_name: str,
                     input_evidence_ids: Optional[List[str]] = None,
                     requested_model_class: str = "flash") -> LlmRequest:
        return LlmRequest(
            call_id=new_uuid(), task_id=task_id, module=module, prompt=prompt,
            prompt_hash=hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
            input_evidence_ids=input_evidence_ids or [],
            requested_model_class=requested_model_class,
            output_schema_name=output_schema_name,
        )
