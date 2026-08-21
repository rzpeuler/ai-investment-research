"""Deterministic output normalization for the Harness LLM entry (R1).

Three-layer boundary (P8-B2-R1-HARNESS-OUTPUT-CONTRACT-STABILIZATION):

    raw harness output  ->  normalized output  ->  validated artifact
    (response text /      (this module: pure   (LlmClient validator +
     parsed JSON object)   deterministic map)   pipeline schema check)

The normalizer NEVER invents missing fields, NEVER changes values, and NEVER
lowers the schema standard. It only removes model-side format noise:

  1. unwrap  — if the top-level keys do not intersect the schema's declared
               properties and exactly one value is an object, unwrap to it
               (handles ``{"result": {...}}`` / ``{"output": {...}}`` style
               wrappers the model adds around the requested payload);
  2. key conformance — case-insensitive match of model keys to the schema's
               exact property names (``CompanyEntityId`` -> ``company_entity_id``);
  3. prune — drop keys not declared in the schema (conforms to
               ``additionalProperties: false`` instead of failing on model junk).

Anything that still violates the schema after normalization (e.g. a genuinely
missing required field) keeps failing validation and falls back honestly.
"""
from __future__ import annotations

from typing import Any


def _match_case_insensitive(key: str, properties: dict[str, Any]) -> str | None:
    lowered = key.casefold()
    for name in properties:
        if name.casefold() == lowered:
            return name
    return None


def normalize_harness_output(parsed: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Deterministically normalize a parsed model object against the schema.

    Returns a new dict; the input is never mutated. If the schema is not an
    object with ``properties``, the parsed object is returned unchanged.
    """
    if not isinstance(parsed, dict):
        return parsed
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict) or not properties:
        return dict(parsed)

    # 1. unwrap a single wrapper object when nothing matches the schema.
    candidate = parsed
    if not (set(parsed) & set(properties)):
        inner = [value for value in parsed.values() if isinstance(value, dict)]
        if len(inner) == 1:
            candidate = inner[0]

    # 2-3. exact/case-insensitive key conformance + prune unknown keys.
    normalized: dict[str, Any] = {}
    for key, value in candidate.items():
        canonical = key if key in properties else _match_case_insensitive(key, properties)
        if canonical is not None:
            normalized[canonical] = value
    return normalized
