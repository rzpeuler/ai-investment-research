"""LLM 输出校验流水线（Phase 3 任务书 12.4）。

LLM 原始输出不得直接进入报告：
LLM raw JSON -> JSON 解析 -> 对应 Schema 校验 -> Pydantic 构造 -> model_dump
-> 再次 JSON Schema 校验 -> 确定性业务规则校验 -> 进入流水线。

Flash 最多允许两次结构修复；第二次仍失败：符合升级条件则调用一次 Pro，
否则进入 deterministic fallback。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from research_os.validators.schema_validator import load_schema, validate_instance


class LlmOutputValidator:
    """LLM 输出结构化校验器。"""

    def __init__(self, model_factory=None):
        # model_factory: schema_name -> Pydantic 模型类（可选，用于 Pydantic 构造）
        self.model_factory = model_factory or {}

    def validate(self, raw_output: Any, schema_name: str) -> Tuple[bool, Optional[dict], List[str]]:
        """解析并校验 LLM 输出。返回 (valid, dict, errors)。"""
        errors: List[str] = []

        # 1. JSON 解析
        if isinstance(raw_output, str):
            try:
                parsed = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                return False, None, [f"JSON 解析失败: {exc}"]
        else:
            parsed = raw_output
        if not isinstance(parsed, dict):
            return False, None, [f"输出必须是 JSON 对象，实际 {type(parsed).__name__}"]

        # 2. Schema 校验（严格）
        errs = validate_instance(parsed, schema_name)
        if errs:
            return False, None, errs[:20]

        # 3. Pydantic 构造 + dump + 再校验
        model_cls = self.model_factory.get(schema_name)
        if model_cls is not None:
            try:
                model = model_cls(**parsed)
                dumped = model.model_dump()
            except Exception as exc:  # noqa: BLE001
                return False, None, [f"Pydantic 构造失败: {exc}"]
            errs2 = validate_instance(dumped, schema_name)
            if errs2:
                return False, None, errs2[:20]
            return True, dumped, []
        return True, parsed, []
