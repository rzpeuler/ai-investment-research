"""Deterministic recovery of an unambiguous JSON object boundary."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_MAX_OUTPUT_CHARS = 120_000
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.IGNORECASE | re.DOTALL)


class _DuplicateKey(ValueError):
    pass


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKey(key)
        result[key] = value
    return result


def _balanced_end(text: str, start: int) -> int | None:
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
                return index + 1
            if depth < 0:
                return None
    return None


def _parse_object(candidate: str) -> dict[str, Any] | None:
    try:
        value = json.loads(candidate, object_pairs_hook=_reject_duplicates)
    except (_DuplicateKey, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _result(raw: str, *, recovered: bool, json_text: str | None,
            recovery_type: str | None, failure_type: str | None = None,
            candidate_count: int = 0) -> dict[str, Any]:
    return {
        "recovered": recovered,
        "json_text": json_text,
        "recovery_type": recovery_type,
        "failure_type": failure_type,
        "candidate_count": candidate_count,
        "json_recovery_attempted": True,
        "json_recovery_success": recovered,
        "raw_output_length": len(raw),
        "raw_output_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    }


def recover_json_boundary(raw_output: str) -> dict[str, Any]:
    """Recover one strict JSON object without changing its contents."""
    raw = str(raw_output)
    if len(raw) > _MAX_OUTPUT_CHARS:
        return _result(raw, recovered=False, json_text=None, recovery_type=None,
                       failure_type="oversize_rejected")
    text = raw.strip()
    text = text.lstrip("\ufeff").strip()
    if not text:
        return _result(raw, recovered=False, json_text=None, recovery_type=None,
                       failure_type="no_json_boundary")

    if _parse_object(text) is not None:
        return _result(raw, recovered=True, json_text=text,
                       recovery_type="whitespace" if text != raw else "direct_json",
                       candidate_count=1)

    fences = _FENCE_RE.findall(text)
    if fences:
        if len(fences) != 1:
            return _result(raw, recovered=False, json_text=None,
                           recovery_type=None, failure_type="ambiguous_multiple_objects",
                           candidate_count=len(fences))
        candidate = fences[0].strip()
        if _parse_object(candidate) is None:
            return _result(raw, recovered=False, json_text=None,
                           recovery_type="markdown_fence", failure_type="strict_parse_error",
                           candidate_count=1)
        return _result(raw, recovered=True, json_text=candidate,
                       recovery_type="markdown_fence", candidate_count=1)

    candidates: list[str] = []
    index = 0
    while index < len(text):
        if text[index] != "{":
            index += 1
            continue
        end = _balanced_end(text, index)
        if end is None:
            break
        candidate = text[index:end]
        if _parse_object(candidate) is not None:
            candidates.append(candidate)
        index = end
    if len(candidates) == 1:
        return _result(raw, recovered=True, json_text=candidates[0],
                       recovery_type="surrounding_text", candidate_count=1)
    if len(candidates) > 1:
        return _result(raw, recovered=False, json_text=None,
                       recovery_type=None, failure_type="ambiguous_multiple_objects",
                       candidate_count=len(candidates))
    if "{" not in text:
        failure = "no_json_boundary"
    else:
        failure = "strict_parse_error" if _balanced_end(text, text.find("{")) else "unbalanced_json"
    return _result(raw, recovered=False, json_text=None,
                   recovery_type=None, failure_type=failure)
