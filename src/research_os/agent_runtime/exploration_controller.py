"""P8-A3-R1 ExplorationController: bounded, deterministic exploration execution.

Authority: P8-A3-R1-HARNESS-EXPLORATION-CONTROL. Fixes the P8-A3 open-ended
agent-loop finding. The controller wraps a Harness session and enforces the
Exploration Execution Contract deterministically:

  - objective is injected into a contract-bounded prompt;
  - agent turns are bounded by ``max_turns`` (per-turn wall-clock budget
    ``turn_timeout_seconds``, no infinite wait);
  - tool calls are bounded by ``max_tool_calls`` (counted from the MCP event
    log, never LLM-decided);
  - completion is detected by REQUIRED OUTPUT MARKERS (substring check on the
    final response) — NOT by an LLM judge;
  - empty/insufficient tool results are recorded as ``data_gap`` and the
    exploration stops (no auto-retry loop);
  - budget exhaustion returns ``exploration_incomplete`` (fail closed).

The controller NEVER calls an LLM to judge completion; it only counts turns,
counts tool calls, and checks deterministic markers.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from research_os.agent_runtime.exploration_contract import ExplorationContract

# Marker aliases mapped from required output fields to substring markers.
# The response is checked case-insensitively for these markers.
DEFAULT_MARKER_ALIASES = {
    "findings": ("findings", "发现", "结论"),
    "unanswered_questions": ("unanswered", "未解答", "待验证问题", "open question"),
    "next_actions": ("next", "下一步", "后续", "next action"),
}

EMPTY_STATUSES = frozenset({"insufficient_evidence", "data_degraded", "no_data"})


@dataclass
class ExplorationRunResult:
    """Bounded result of one contract-bounded exploration run."""

    task_id: str
    status: str = ""                 # completed | exploration_incomplete | data_gap_stop | failed
    actual_turns: int = 0
    actual_tool_calls: int = 0
    completion_status: str = ""      # completed | incomplete | budget_exhausted | data_gap
    data_gaps: list[str] = field(default_factory=list)
    response_sha256: str = ""
    error: str = ""
    harness_session_id: str = ""     # bounded harness session id (if surfaced)
    # Bounded last-response text used ONLY for deterministic quality proxies;
    # never persisted to audit (see RuntimeLineage._FORBIDDEN_FIELDS).
    last_response_text: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "actual_turns": self.actual_turns,
            "actual_tool_calls": self.actual_tool_calls,
            "completion_status": self.completion_status,
            "data_gaps": self.data_gaps,
            "response_sha256": self.response_sha256,
            "error": self.error,
            "harness_session_id": self.harness_session_id,
            "last_response_text": self.last_response_text,
        }


def build_contract_prompt(contract: ExplorationContract, base_prompt: str) -> str:
    """Deterministic contract-bounded prompt (no LLM).

    Injects the objective, the allowed-tool surface, the budgets, the required
    output fields, the empty-data rule and the stop condition so the agent has
    an explicit exploration boundary.
    """
    lines = [
        "【Exploration Execution Contract】",
        f"objective: {contract.objective}",
        f"allowed_tools: {', '.join(contract.allowed_tools)}",
        f"max_turns: {contract.max_turns}",
        f"max_tool_calls: {contract.max_tool_calls}",
        f"required_output_fields: {', '.join(contract.required_fields)}",
        "empty_data_rule: 如果工具返回空/数据不足，记录 data_gap 并立即结束，不要重试。",
        "stop_condition: 输出包含全部 required_output_fields 后立即结束；不要继续探索。",
        "failure_condition: 达到 max_turns 或 max_tool_calls 仍未完成 -> exploration_incomplete。",
        "",
        "任务描述：",
        base_prompt,
    ]
    return "\n".join(lines)


def build_follow_up_prompt(contract: ExplorationContract, turn_index: int) -> str:
    """Deterministic bounded follow-up for turn N>1 (no LLM).

    Does not re-send the full task; asks the agent to conclude immediately with
    the required output fields so the loop cannot continue indefinitely.
    """
    return (
        f"【turn {turn_index}/{contract.max_turns}】请在本次回复中直接输出 "
        f"{', '.join(contract.required_fields)} 三部分并结束探索。"
        "不要调用更多工具；不要继续扩展任务。若数据不足，记录 data_gap 并结束。"
    )


def detect_completion(response_text: str, contract: ExplorationContract,
                      marker_aliases: dict[str, tuple[str, ...]] | None = None) -> bool:
    """Deterministic completion check (substring markers, no LLM)."""
    aliases = marker_aliases or DEFAULT_MARKER_ALIASES
    text = (response_text or "").lower()
    for field_name in contract.required_fields:
        candidates = aliases.get(field_name, (field_name,))
        if not any(candidate.lower() in text for candidate in candidates):
            return False
    return True


class ExplorationController:
    """Enforces the exploration contract around a Harness session."""

    def __init__(
        self,
        *,
        send_turn: Callable[[str], dict[str, Any]],
        count_tool_calls: Callable[[], int],
        marker_aliases: dict[str, tuple[str, ...]] | None = None,
    ):
        """``send_turn`` runs one agent turn (bounded by the caller's timeout);
        ``count_tool_calls`` returns the tool-call count for the current turn."""
        self.send_turn = send_turn
        self.count_tool_calls = count_tool_calls
        self.marker_aliases = marker_aliases or DEFAULT_MARKER_ALIASES

    def run(self, contract: ExplorationContract, base_prompt: str) -> ExplorationRunResult:
        import hashlib

        result = ExplorationRunResult(task_id=contract.task_id)
        accumulated_tool_calls = 0

        for turn_index in range(1, contract.max_turns + 1):
            result.actual_turns = turn_index
            # Turn 1 carries the full contract; later turns are bounded
            # follow-ups that demand immediate conclusion (no infinite loop).
            prompt = (build_contract_prompt(contract, base_prompt)
                      if turn_index == 1 else build_follow_up_prompt(contract, turn_index))
            try:
                turn_result = self.send_turn(prompt)
            except Exception as exc:  # noqa: BLE001 — bounded per-turn failure
                result.status = "failed"
                result.completion_status = "turn_failed"
                result.error = f"{type(exc).__name__}: {str(exc)[:120]}"
                return result

            turn_tool_calls = self.count_tool_calls()
            accumulated_tool_calls += turn_tool_calls
            result.actual_tool_calls = accumulated_tool_calls

            response_text = str(turn_result.get("response") or "")
            result.last_response_text = response_text
            # Surface the bounded harness session id if the runner provided one.
            if not result.harness_session_id:
                result.harness_session_id = str(turn_result.get("harness_session_id") or "")

            # Empty-data detection: if a tool returned an empty/insufficient
            # result, record the data gap and stop (no infinite retry).
            gaps = self._detect_data_gaps(turn_result)
            if gaps:
                result.data_gaps.extend(gaps)
                result.status = "data_gap_stop"
                result.completion_status = "data_gap"
                result.response_sha256 = hashlib.sha256(
                    response_text.encode("utf-8")).hexdigest()[:16]
                return result

            # Deterministic completion: required output markers present.
            if detect_completion(response_text, contract, self.marker_aliases):
                result.status = "completed"
                result.completion_status = "completed"
                result.response_sha256 = hashlib.sha256(
                    response_text.encode("utf-8")).hexdigest()[:16]
                return result

            # Tool budget exhausted: fail closed.
            if accumulated_tool_calls >= contract.max_tool_calls:
                result.status = "exploration_incomplete"
                result.completion_status = "budget_exhausted"
                result.response_sha256 = hashlib.sha256(
                    response_text.encode("utf-8")).hexdigest()[:16]
                return result

        # Turn budget exhausted without completion.
        result.status = "exploration_incomplete"
        result.completion_status = "budget_exhausted"
        return result

    @staticmethod
    def _detect_data_gaps(turn_result: dict[str, Any]) -> list[str]:
        """Detect empty/insufficient tool results in the turn result."""
        gaps: list[str] = []
        tool_results = turn_result.get("tool_results") or []
        if isinstance(tool_results, dict):
            for tool, payload in tool_results.items():
                status = payload.get("status") if isinstance(payload, dict) else None
                if status in EMPTY_STATUSES:
                    gaps.append(f"{tool}:{status}")
        elif isinstance(tool_results, list):
            for item in tool_results:
                if not isinstance(item, dict):
                    continue
                status = item.get("status")
                tool = item.get("tool") or item.get("tool_name") or "tool"
                if status in EMPTY_STATUSES:
                    gaps.append(f"{tool}:{status}")
        return gaps


__all__ = ["ExplorationController", "ExplorationRunResult", "build_contract_prompt",
           "build_follow_up_prompt", "detect_completion", "DEFAULT_MARKER_ALIASES",
           "EMPTY_STATUSES"]
