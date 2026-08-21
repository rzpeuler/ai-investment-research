"""Field-level validation error extraction and repair prompt builder (R5-A).

Consumes the EXISTING validator's error strings (the validator itself is never
modified) and produces (a) structured field-level error categories and (b) a
deterministic repair prompt that instructs the model to fix ONLY the error
fields while keeping everything else unchanged. Repair never bypasses the
schema and never fabricates fields: the repaired output must still pass the
same validator, and any repair that still fails falls back honestly.
"""
from __future__ import annotations

import json
import re
from typing import Any


def extract_field_errors(errors: list[str]) -> dict[str, list[str]]:
    """Classify validator error strings into field-level categories."""
    missing_required: list[str] = []
    enum_errors: list[str] = []
    value_format: list[str] = []
    json_format: list[str] = []
    other: list[str] = []
    for error in errors or []:
        text = str(error)
        if "invalid_response" in text or "JSON 解析失败" in text or "缺少有效 JSON" in text:
            json_format.append(text[:160])
        else:
            match = re.search(r"'([^']+)' is a required property", text)
            if match:
                missing_required.append(match.group(1))
                continue
            if "is not one of" in text:
                fields_split = text.split(":", 1)
                enum_errors.append(fields_split[0].strip().strip("'\"") if fields_split else text[:160])
                continue
            if ("does not match" in text or "is not of type" in text or "is not a" in text
                    or "less than" in text or "greater than" in text):
                fields_split = text.split(":", 1)
                value_format.append(fields_split[0].strip().strip("'\"") if fields_split else text[:160])
                continue
            other.append(text[:160])
    return {"missing_required": sorted(set(missing_required)),
            "enum_error": sorted(set(enum_errors)),
            "value_format": sorted(set(value_format)),
            "json_format": json_format,
            "other": other}


def build_repair_prompt(request, partial_output: dict[str, Any], errors: list[str],
                        schema_name: str, evidence: str = "") -> str:
    """Deterministic repair prompt: fix ONLY the error fields."""
    fields = extract_field_errors(errors)
    lines = [
        "你之前生成的研究输出未通过 Schema 校验。",
        "请仅修复以下错误字段，保持其余内容不变，不要重新生成无关内容。",
        "修复后的输出仍必须是完整的 JSON 对象（包含全部必填字段），"
        "且必须通过同一 Schema 校验。",
        "",
    ]
    if fields["json_format"]:
        lines += ["错误类型：输出不是合法 JSON 对象，请只输出一个 JSON 对象。", ""]
    if fields["missing_required"]:
        lines += ["缺失的必填字段（必须补齐，值必须基于证据生成，禁止虚构证据引用）：",
                  ", ".join(fields["missing_required"]), ""]
    if fields["enum_error"]:
        lines += [f"以下字段的取值不在允许的枚举集合内，必须改为合法枚举值：",
                  ", ".join(fields["enum_error"]), ""]
    if fields["value_format"]:
        lines += [f"以下字段的类型/格式/取值不符合约束，必须修正：",
                  ", ".join(fields["value_format"]), ""]
    lines += [
        "校验错误（原样提供）：",
        *(str(e)[:160] for e in (errors or [])[:10]),
        "",
        "当前输出（JSON）：",
        json.dumps(partial_output, ensure_ascii=False, separators=(",", ":")),
    ]
    if evidence:
        lines += ["", "证据（修复字段的值必须来源于此）：", evidence]
    if request is not None:
        original = str(getattr(request, "prompt", ""))
        if original:
            lines += ["", "原任务要求：", original[:4000]]
    lines += ["", "禁止输出解释文字；只输出修复后的 JSON 对象。"]
    return "\n".join(lines)
