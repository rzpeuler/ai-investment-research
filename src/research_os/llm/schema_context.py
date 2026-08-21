"""Schema-aware context builder for the Harness agent prompt (P8-B2-R3).

Deterministic, pure helpers that turn a Sol schema into (a) a required-field
list, (b) a per-field constraint summary, (c) a complete schema-valid example
object. These are CONTEXT HINTS for the model — they never change the schema,
the validator or the normalizer, and they never fabricate the model's output.
The example's values are placeholders; the model must generate its own values
from the evidence.
"""
from __future__ import annotations

from typing import Any


def _constraint_text(name: str, prop: dict[str, Any]) -> str:
    parts: list[str] = []
    prop_type = prop.get("type")
    if prop_type:
        parts.append(f"type: {prop_type}")
    if "enum" in prop:
        parts.append("enum: " + ", ".join(str(v) for v in prop["enum"]))
    if prop.get("pattern"):
        parts.append(f"pattern: {prop['pattern']}")
    if prop.get("format"):
        parts.append(f"format: {prop['format']}")
    if "minimum" in prop:
        parts.append(f"minimum: {prop['minimum']}")
    if "oneOf" in prop:
        types = [item.get("type") for item in prop["oneOf"] if isinstance(item, dict)]
        parts.append("oneOf: " + "/".join(str(t) for t in types if t))
    if "anyOf" in prop:
        types = [item.get("type") for item in prop["anyOf"] if isinstance(item, dict)]
        parts.append("anyOf: " + "/".join(str(t) for t in types if t))
    return f"- {name}: " + "; ".join(parts) if parts else f"- {name}: any"


def describe_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return the required list, constraint summary and a valid example."""
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return {"required": [], "constraints": [], "example": {}}
    required = list(schema.get("required", []))
    constraints = [_constraint_text(name, prop) for name, prop in properties.items()
                   if name in required]
    return {"required": required, "constraints": constraints,
            "example": build_schema_example(schema)}


def _pick_branch(branches: list[Any]) -> dict[str, Any]:
    """Prefer an object branch with properties, then a non-null typed branch."""
    for branch in branches:
        if isinstance(branch, dict) and branch.get("type") == "object" and branch.get("properties"):
            return branch
    for branch in branches:
        if isinstance(branch, dict) and branch.get("type") != "null":
            return branch
    return {"type": "null"}


def _branch_value(branch: dict[str, Any], prefix: str = "v") -> Any:
    if branch.get("type") == "null":
        return None
    if branch.get("type") == "object" and branch.get("properties"):
        return _example_object(branch, prefix)
    return _example_value(branch, prefix)


def _example_value(prop: dict[str, Any], prefix: str = "v") -> Any:
    prop_type = prop.get("type")
    if "enum" in prop:
        return prop["enum"][0]
    if "oneOf" in prop and isinstance(prop["oneOf"], list) and prop["oneOf"]:
        return _branch_value(_pick_branch(prop["oneOf"]), prefix)
    if "anyOf" in prop and isinstance(prop["anyOf"], list) and prop["anyOf"]:
        return _branch_value(_pick_branch(prop["anyOf"]), prefix)
    if prop_type == "array":
        return [prefix]
    if prop_type == "number":
        return prop.get("minimum", 0)
    if prop_type == "integer":
        return prop.get("minimum", 0) or 1
    if prop_type == "boolean":
        return False
    if prop.get("format") == "date-time":
        return "2026-08-01T00:00:00+08:00"
    if prop.get("format") == "date":
        return "2026-08-01"
    if prop.get("pattern") == "^company:":
        return "company:example"
    if prop.get("pattern"):
        return prefix
    return prefix


def _example_object(schema: dict[str, Any], prefix: str = "v") -> dict[str, Any]:
    properties = schema.get("properties") if isinstance(schema, dict) else {}
    if not isinstance(properties, dict):
        return {}
    example: dict[str, Any] = {}
    for name, prop in properties.items():
        example[name] = _example_value(prop, prefix)
    return example


def build_schema_example(schema: dict[str, Any]) -> dict[str, Any]:
    """Deterministic schema-valid example object (placeholder values only)."""
    return _example_object(schema)


def build_harness_prompt(request, output_schema: dict[str, Any], *,
                         task_name: str = "", evidence: str = "") -> str:
    """Full Harness prompt: JSON-only instruction + schema + constraints +
    example + task context + evidence."""
    import json
    schema_text = json.dumps(output_schema, ensure_ascii=False, separators=(",", ":"))
    described = describe_schema(output_schema)
    example_text = json.dumps(described["example"], ensure_ascii=False, separators=(",", ":"))
    lines = [
        "你必须只输出一个 JSON 对象。",
        "禁止输出 Markdown，禁止调用任何工具，禁止输出 JSON 之外的任何解释或文字。",
        "输出必须完全符合以下 JSON Schema 的所有约束：",
        schema_text,
        "",
        "必填字段（必须全部出现在输出中，不得缺失）：",
        ", ".join(described["required"]) if described["required"] else "(无)",
        "",
        "必填字段约束摘要：",
        *described["constraints"],
        "",
        "完整合法示例（仅作结构参考；内容必须基于证据自行生成，禁止照抄示例值）：",
        example_text,
    ]
    if task_name:
        lines += ["", f"任务：{task_name}"]
    if evidence:
        lines += ["", "证据：", evidence]
    if request is not None:
        prompt = str(getattr(request, "prompt", ""))
        if prompt:
            lines += ["", "用户要求：", prompt]
    return "\n".join(lines)
