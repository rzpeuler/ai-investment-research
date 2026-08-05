"""Markdown 报告 Front Matter 解析与校验（工程指南 49 节）。

必需字段：
report_id, scenario, title, created_at, as_of, timezone, entities,
time_window, data_status, source_coverage, model_route, runtime_seconds,
validator_status, knowledge_coordinates

校验不通过必须显式返回错误列表，禁止静默失败（指南 59 节机械校验器）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from research_os.utils.time import validate_iso

FRONTMATTER_REQUIRED_FIELDS = [
    "report_id",
    "scenario",
    "title",
    "created_at",
    "as_of",
    "timezone",
    "entities",
    "time_window",
    "data_status",
    "source_coverage",
    "model_route",
    "runtime_seconds",
    "validator_status",
    "knowledge_coordinates",
]

DEFAULT_TIMEZONE = "Asia/Shanghai"

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", re.DOTALL)


class _StringLoader(yaml.SafeLoader):
    """SafeLoader 变体：timestamp 保留为字符串，不解析为 datetime。

    契约要求时间字段为 ISO-8601 字符串（Asia/Shanghai 口径）。
    """


_StringLoader.add_constructor(
    "tag:yaml.org,2002:timestamp",
    lambda loader, node: loader.construct_scalar(node),
)


def _load_yaml(text: str) -> Any:
    return yaml.load(text, Loader=_StringLoader)


@dataclass
class FrontMatterValidation:
    ok: bool
    errors: List[str] = field(default_factory=list)
    frontmatter: Optional[Dict[str, Any]] = None
    body: str = ""

    def __post_init__(self) -> None:
        self.ok = not self.errors


def parse_frontmatter(text: str) -> tuple[Optional[Dict[str, Any]], str]:
    """解析 Front Matter。无 Front Matter 时返回 (None, 原文)。"""
    m = _FM_RE.match(text)
    if not m:
        return None, text
    try:
        data = _load_yaml(m.group(1)) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"Front Matter YAML 解析失败: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Front Matter 必须是 YAML 映射")
    return data, text[m.end():]


def validate_frontmatter(text: str) -> FrontMatterValidation:
    """校验报告 Front Matter。缺失必需字段即失败。"""
    try:
        fm, body = parse_frontmatter(text)
    except ValueError as exc:
        return FrontMatterValidation(ok=False, errors=[str(exc)])

    if fm is None:
        return FrontMatterValidation(ok=False, errors=["缺少 Front Matter（--- 起始的 YAML 块）"])

    errors: List[str] = []
    for field_name in FRONTMATTER_REQUIRED_FIELDS:
        if field_name not in fm:
            errors.append(f"缺少必需字段: {field_name}")

    if "timezone" in fm and fm["timezone"] != DEFAULT_TIMEZONE:
        errors.append(f"timezone 必须为 {DEFAULT_TIMEZONE}，实际: {fm['timezone']!r}")

    for dt_field in ("created_at", "as_of"):
        if dt_field in fm:
            value = fm[dt_field]
            if not isinstance(value, str) or not validate_iso(value):
                errors.append(f"{dt_field} 必须是 ISO-8601 时间字符串: {value!r}")

    if "runtime_seconds" in fm:
        if not isinstance(fm["runtime_seconds"], (int, float)) or isinstance(fm["runtime_seconds"], bool):
            errors.append(f"runtime_seconds 必须是数字: {fm['runtime_seconds']!r}")

    if "entities" in fm and not isinstance(fm["entities"], list):
        errors.append("entities 必须是列表")

    return FrontMatterValidation(ok=not errors, errors=errors, frontmatter=fm, body=body)


def validate_frontmatter_file(path: str | Path) -> FrontMatterValidation:
    """校验报告文件的 Front Matter。文件不存在或不可读即失败。"""
    p = Path(path)
    if not p.exists():
        return FrontMatterValidation(ok=False, errors=[f"文件不存在: {p}"])
    text = p.read_text(encoding="utf-8")
    return validate_frontmatter(text)
