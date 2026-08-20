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
                 max_input_chars: int = _MAX_INPUT_CHARS):
        if adapter is None:
            adapter = build_harness_adapter()
        self.adapter = adapter
        self.timeout_seconds = timeout_seconds
        self.max_input_chars = max_input_chars
        self.calls: list[dict[str, Any]] = []

    def complete_json(self, request, output_schema: dict[str, Any]) -> dict[str, Any]:
        if len(request.prompt) > self.max_input_chars:
            return self._error("invalid_response", "Prompt 超过输入上限", False)
        schema_text = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
        prompt = (
            "只输出一个 JSON 对象，不要输出 Markdown。输出必须符合此 JSON Schema："
            + schema_text + "\n\n" + request.prompt
        )
        started_at = self.calls.__len__()
        try:
            session = self.adapter.create_session({"provider": self.provider_id,
                                                   "task_id": request.task_id,
                                                   "call_id": request.call_id})
            try:
                result = self.adapter.send_message(session, prompt)
            finally:
                try:
                    self.adapter.close_session(session)
                except Exception:  # noqa: BLE001 — session close is best-effort
                    pass
        except Exception as exc:  # noqa: BLE001 — harness failure → typed provider error
            code = getattr(exc, "code", "network_error")
            retryable = code in {"PROVIDER_TIMEOUT", "TURN_TIMEOUT", "HARNESS_BOOT_FAILED"}
            return self._error(code, getattr(exc, "message", str(exc))[:200], retryable)

        response_text = str(result.get("response", ""))
        output = _extract_json_object(response_text)
        if output is None:
            return self._error("invalid_response", "Harness 响应缺少有效 JSON content", False)
        usage = result.get("operational_metadata", {}).get("usage") if isinstance(
            result.get("operational_metadata"), dict) else None
        # Only numeric provider-reported values may enter usage evidence;
        # strings (the only possible secret carrier) are never passed through.
        sanitized_usage = {
            key: value for key, value in usage.items()
            if isinstance(value, (int, float)) and not isinstance(value, bool)
        } if isinstance(usage, dict) else {}
        self.calls.append({"call_id": request.call_id, "task_id": request.task_id,
                           "model_class": request.requested_model_class,
                           "status": "completed", "started_at": started_at})
        return {
            "ok": True,
            "provider": self.provider_id,
            "model_id": f"{self.provider_id}/{request.requested_model_class}",
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
    """Boot the pinned Harness (owned process) and return its adapter.

    Used only under the internal-trial opt-in; the caller owns cleanup via
    ``adapter.supervisor.stop()`` (owned process-tree cleanup).
    """
    from research_os.agent_runtime.harness_adapter import HarnessAgentRuntimeAdapter

    config = config or AgentRuntimeConfig(mode="harness", max_turns=2,
                                          turn_timeout_seconds=_TIMEOUT_SECONDS)
    adapter, _evidence = build_production_harness_adapter(config, require_credential=True)
    assert isinstance(adapter, HarnessAgentRuntimeAdapter)
    return adapter
