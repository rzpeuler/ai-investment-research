"""GenerationControlledProvider: bounded generate-validate-repair loop (R5-A).

A provider-wrapper layer implementing the same ``LlmProvider`` protocol as
``DeepSeekChatCompletionsProvider`` / ``HarnessLlmProvider``, so the unified
``LlmClient`` entry (budget, audit, fallback) is unchanged. The controller:

  - calls the base provider (pass 1);
  - validates through the EXISTING ``LlmOutputValidator`` (never modified);
  - if the output fails, runs a BOUNDED repair loop (``max_repair_passes``)
    whose prompt fixes ONLY the field-level errors reported by the validator;
  - every provider call is recorded (base provider call list) and every repair
    round is exposed in the result's usage metadata (audit carrier, backward
    compatible);
  - repair exhaustion returns a typed non-retryable error so the LlmClient
    falls back honestly — no fake MODEL_INFERENCE, no validator bypass.

The validator remains the ONLY quality judgment source; repair never bypasses
the schema and never fabricates fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from research_os.llm.repair import build_repair_prompt, extract_field_errors
from research_os.llm.validation import LlmOutputValidator


@dataclass
class GenerationState:
    """Per-task in-memory generation state; never persisted, never shared."""

    task_id: str = ""
    attempt: int = 0
    repair_round: int = 0
    validation_errors: list[str] = field(default_factory=list)
    partial_output: dict[str, Any] | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    provider_calls: int = 0


class GenerationControlledProvider:
    """LlmProvider wrapper with a bounded validator-driven repair loop."""

    provider_id = "deepseek-harness-controlled"

    def __init__(self, base_provider: Any, *, max_repair_passes: int = 2,
                 validator: Any | None = None):
        self.base_provider = base_provider
        self.max_repair_passes = max_repair_passes
        self.validator = validator or LlmOutputValidator()
        self.states: list[GenerationState] = []

    def complete_json(self, request, output_schema: dict[str, Any]) -> dict[str, Any]:
        schema_name = getattr(request, "output_schema_name", "") or "module_result"
        state = GenerationState(task_id=getattr(request, "task_id", ""))
        self.states.append(state)

        result = self._generate(request, output_schema, state)
        if not result.get("ok"):
            return self._result(state, ok=False, output=None,
                                error_type=result.get("error_type") or "provider_error",
                                message=result.get("error") or "provider call failed",
                                retryable=bool(result.get("retryable")))
        output = result.get("output")
        if not isinstance(output, dict):
            state.validation_errors = ["输出必须是 JSON 对象"]
            return self._result(state, ok=False, output=None,
                                error_type="invalid_response", message="输出不是 JSON 对象",
                                retryable=False)
        valid, parsed, errors = self.validator.validate(output, schema_name)
        state.validation_errors = list(errors or [])
        state.partial_output = parsed if isinstance(parsed, dict) else output
        state.usage = self._merge_usage(state, result)
        if valid:
            return self._result(state, ok=True, output=parsed, message=None,
                                error_type=None, retryable=False)

        for round_index in range(1, self.max_repair_passes + 1):
            state.repair_round = round_index
            repair_prompt = build_repair_prompt(
                request, state.partial_output or {}, state.validation_errors,
                schema_name, evidence="\n".join(
                    f"- {item}" for item in getattr(request, "input_evidence_ids", []) or []))
            repair_request = _copy_request_with_prompt(request, repair_prompt)
            repair_result = self._generate(repair_request, output_schema, state)
            if not repair_result.get("ok"):
                # Provider failed during repair: propagate the typed error;
                # the LlmClient handles retry semantics (no hidden retry).
                return self._result(state, ok=False, output=None,
                                    error_type=repair_result.get("error_type") or "provider_error",
                                    message=repair_result.get("error") or "repair call failed",
                                    retryable=bool(repair_result.get("retryable")))
            repaired = repair_result.get("output")
            state.usage = self._merge_usage(state, repair_result)
            if not isinstance(repaired, dict):
                state.validation_errors = ["修复输出不是 JSON 对象"]
                state.partial_output = state.partial_output
                continue
            valid, parsed, errors = self.validator.validate(repaired, schema_name)
            state.validation_errors = list(errors or [])
            state.partial_output = parsed if isinstance(parsed, dict) else repaired
            if valid:
                return self._result(state, ok=True, output=parsed, message=None,
                                    error_type=None, retryable=False)

        # Repair exhausted: typed non-retryable error -> honest fallback.
        summary = extract_field_errors(state.validation_errors)
        return self._result(state, ok=False, output=None,
                            error_type="repair_exhausted",
                            message=f"repair exhausted after {state.repair_round} pass(es): "
                                    f"missing={summary['missing_required'][:5]}",
                            retryable=False)

    def _generate(self, request, output_schema: dict[str, Any],
                  state: GenerationState) -> dict[str, Any]:
        state.attempt += 1
        state.provider_calls += 1
        return self.base_provider.complete_json(request, output_schema)

    def _merge_usage(self, state: GenerationState, result: dict[str, Any]) -> dict[str, Any]:
        usage = dict(result.get("usage") or {})
        usage["generation_pass"] = state.attempt
        usage["repair_round"] = state.repair_round
        usage["provider_calls"] = state.provider_calls
        usage["validation_error_summary"] = [
            f"{key}:{len(items)}" for key, items in
            extract_field_errors(state.validation_errors).items() if items
        ]
        return usage

    def _result(self, state: GenerationState, *, ok: bool, output: Any, error_type: str | None,
                message: str | None, retryable: bool) -> dict[str, Any]:
        return {
            "ok": ok,
            "provider": self.provider_id,
            "model_id": f"{self.provider_id}/{state.repair_round}",
            "output": output,
            "error": message,
            "error_type": error_type,
            "retryable": retryable,
            "usage": dict(state.usage),
        }


def _copy_request_with_prompt(request, prompt: str):
    """Return a shallow copy of the LlmRequest with a different prompt."""
    import copy
    clone = copy.copy(request)
    clone.prompt = prompt
    return clone
