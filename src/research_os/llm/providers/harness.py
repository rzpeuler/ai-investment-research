"""Opt-in Harness LLM provider for the P8-B2 internal trial (INTERNAL-TRIAL-001).

``HarnessLlmProvider`` implements the same ``LlmProvider`` protocol as
``DeepSeekChatCompletionsProvider`` so the unified ``LlmClient`` entry
(budget, validation, fallback, audit recording) is unchanged. The provider
routes each ``complete_json`` call through the pinned DeepSeek Harness control
plane (a real dsh session) instead of a direct provider HTTP call.

This is an internal-trial verification entry only: it is never the default.
The default runtime remains ``legacy`` and the default provider remains the
direct DeepSeek Chat Completions adapter. There is no second AI execution
path — ``LlmClient`` stays the single entry; only the provider behind it is
swapped under the explicit ``P8_B2_SCENARIO_TRIAL=1`` opt-in.

Usage accounting: only provider-reported values from the Harness session are
exposed; nothing is estimated or inferred.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from research_os.agent_runtime.config import AgentRuntimeConfig
from research_os.agent_runtime.production_runtime import build_production_harness_adapter
from research_os.llm.normalization import normalize_harness_output
from research_os.llm.schema_context import build_harness_prompt
from research_os.llm.structured_output import detect_structured_output_capability

# Opt-in marker; identical semantics to the trial's P8_B2_INTERNAL_TRIAL=1.
SCENARIO_TRIAL_ENV = "P8_B2_SCENARIO_TRIAL"

_MAX_INPUT_CHARS = 120_000
_TIMEOUT_SECONDS = 120


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Deterministically extract the first balanced JSON object from text.

    The Harness returns free text; the provider must not accept prose as a
    structured result. Only a balanced ``{...}`` block parses as output.
    """
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    value = json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
                return value if isinstance(value, dict) else None
    return None


class HarnessLlmProvider:
    """LlmProvider that executes each structured call through the Harness."""

    provider_id = "deepseek-harness"

    def __init__(self, adapter: Any = None, *, timeout_seconds: int = _TIMEOUT_SECONDS,
                 max_input_chars: int = _MAX_INPUT_CHARS, resolved_model_id: str | None = None,
                 structured_output: bool = False):
        if adapter is None:
            adapter, resolved_model_id = build_harness_adapter()
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        # Observed from the composed runtime config (agent-default-model);
        # the Harness session itself does not expose the model per call.
        self.resolved_model_id = resolved_model_id or "deepseek-v4-flash"
        self.structured_output = structured_output
        self.calls: list[dict[str, Any]] = []

    def capability(self) -> dict[str, Any]:
        """Return probe metadata without changing runtime behavior."""
        if not self.structured_output:
            return {
                "provider": self.provider_id,
                "model": self.resolved_model_id,
                "structured_output_supported": callable(
                    getattr(self.adapter, "send_structured_message", None)),
                "mode": "normal",
                "status": "NOT_REQUESTED",
                "configuration": {"transport": "provider_level"},
            }
        return detect_structured_output_capability(self, self.resolved_model_id).as_dict()

    def complete_json(self, request, output_schema: dict[str, Any]) -> dict[str, Any]:
        if len(request.prompt) > self.max_input_chars:
            return self._error("invalid_response", "Prompt 超过输入上限", False)
        prompt = build_harness_prompt(
            request, output_schema,
            task_name=getattr(request, "module", "").split(".")[-1] or "",
            evidence="\n".join(f"- {item}" for item in getattr(request, "input_evidence_ids", []) or []),
        )
        started_at = self.calls.__len__()
        entry = {"call_id": request.call_id, "task_id": request.task_id,
                 "model_class": request.requested_model_class, "started_at": started_at}
        send_structured = None
        if self.structured_output:
            send_structured = getattr(self.adapter, "send_structured_message", None)
            if not callable(send_structured):
                entry["status"] = "unsupported"
                self.calls.append(entry)
                return self._error(
                    "structured_output_unsupported",
                    "Harness adapter has no provider-level structured-output method",
                    False,
                )
        try:
            session = self.adapter.create_session({"provider": self.provider_id,
                                                   "task_id": request.task_id,
                                                   "call_id": request.call_id})
            try:
                if self.structured_output:
                    assert send_structured is not None
                    result = send_structured(session, prompt, output_schema)
                else:
                    result = self.adapter.send_message(session, prompt)
            finally:
                try:
                    self.adapter.close_session(session)
                except Exception:  # noqa: BLE001 — session close is best-effort
                    pass
        except Exception as exc:  # noqa: BLE001 — harness failure → typed provider error
            code = getattr(exc, "code", "network_error")
            retryable = code in {"PROVIDER_TIMEOUT", "TURN_TIMEOUT", "HARNESS_BOOT_FAILED"}
            entry["status"] = "failed"
            entry["error_type"] = code
            self.calls.append(entry)
            return self._error(code, getattr(exc, "message", str(exc))[:200], retryable)

        response_text = str(result.get("response", ""))
        output = _extract_json_object(response_text)
        if output is None:
            entry["status"] = "invalid_response"
            self.calls.append(entry)
            return self._error("invalid_response", "Harness 响应缺少有效 JSON content", False)
        # R1: deterministic normalization (unwrap / key conformance / prune).
        # Missing required fields still fail validation honestly.
        output = normalize_harness_output(output, output_schema)
        usage = result.get("operational_metadata", {}).get("usage") if isinstance(
            result.get("operational_metadata"), dict) else None
        # Only numeric provider-reported values may enter usage evidence;
        # strings (the only possible secret carrier) are never passed through.
        sanitized_usage = {
            key: value for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        } if isinstance(usage, dict) else {}
        sanitized_usage["resolved_model_id"] = self.resolved_model_id
        entry["status"] = "completed"
        self.calls.append(entry)
        return {
            "ok": True,
            "provider": self.provider_id,
            "model_id": f"{self.provider_id}/{request.requested_model_class}",
            "resolved_model_id": self.resolved_model_id,
            "output": output,
            "error": None,
            "error_type": None,
            "retryable": False,
            "usage": sanitized_usage,
        }

    @staticmethod
    def _error(error_type: str, message: str, retryable: bool) -> dict[str, Any]:
        return {"ok": False, "provider": "deepseek-harness", "model_id": None,
                "output": None, "error": message, "error_type": error_type,
                "retryable": retryable, "usage": {}}


def build_harness_adapter(config: AgentRuntimeConfig | None = None):
    """Boot the pinned Harness (owned process) and return (adapter, resolved_model_id).

    Used only under the internal-trial opt-in; the caller owns cleanup via
    ``adapter.supervisor.stop()`` (owned process-tree cleanup).
    ``resolved_model_id`` is observed from the composed runtime config
    (``agent-default-model``), never guessed.
    """
    from research_os.agent_runtime.harness_adapter import HarnessAgentRuntimeAdapter

    config = config or AgentRuntimeConfig(mode="harness", max_turns=2,
                                          turn_timeout_seconds=_TIMEOUT_SECONDS)
    adapter, evidence = build_production_harness_adapter(config, require_credential=True)
    assert isinstance(adapter, HarnessAgentRuntimeAdapter)
    resolved_model_id = _observe_default_model(evidence)
    return adapter, resolved_model_id


def _observe_default_model(evidence: dict) -> str:
    """Extract the agent-default-model from the observed composed config."""
    composed = evidence.get("composed_config") or ""
    match = re.search(r"(?ms)^- id: agent-default-model.*?^model:\s*(\S+)", composed)
    if match:
        return match.group(1).strip()
    return "deepseek-v4-flash"
