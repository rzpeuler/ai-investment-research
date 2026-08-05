"""LLM 请求/响应模型（Phase 3 任务书 12.1）。

统一请求至少记录：call_id/task_id/module/prompt_template_version/prompt_hash/
input_evidence_ids/requested_model_class/provider/output_schema_name/timeout_seconds。
统一响应至少记录：call_id/provider/model_id/called/status/schema_valid/
attempt_count/provider_fallback_used/business_escalation_used/output/
validation_errors/usage_metadata/warnings。

禁止记录：密钥、Cookie、Authorization 或模型私有思维过程。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import Field

from research_os.models.core import StrictModel
from research_os.utils.time import now_iso


class LlmRequest(StrictModel):
    """一次 LLM 调用请求。"""

    call_id: str = Field(..., min_length=1)
    task_id: str = Field(..., min_length=1)
    module: str = Field(..., min_length=1)
    prompt: str = Field(..., min_length=1)
    prompt_template_version: str = "v1"
    prompt_hash: str = Field(..., min_length=1)
    input_evidence_ids: List[str] = Field(default_factory=list)
    requested_model_class: str = "flash"          # flash | pro
    provider: str = ""
    output_schema_name: str = Field(..., min_length=1)
    timeout_seconds: int = Field(60, ge=1, le=600)


class LlmResponse(StrictModel):
    """一次 LLM 调用响应（失败也如实记录，不伪造）。"""

    call_id: str = Field(..., min_length=1)
    provider: str = ""
    model_id: Optional[str] = None
    called: bool = False
    status: str = "failed"        # success | failed | fallback
    schema_valid: bool = False
    attempt_count: int = Field(0, ge=0)
    provider_fallback_used: bool = False
    provider_fallback_reason: Optional[str] = None
    business_escalation_used: bool = False
    business_escalation_reason: Optional[str] = None
    output: Optional[Dict[str, Any]] = None
    validation_errors: List[str] = Field(default_factory=list)
    usage_metadata: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    recorded_at: str = Field(default_factory=now_iso)
