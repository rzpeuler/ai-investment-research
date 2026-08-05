"""基础报告机械校验器（工程指南 59 节）。

Phase 0 范围：Front Matter 完整性 + 禁止输出项扫描（目标价/买卖建议/仓位建议/
引导性语言）。绝对日期、引用覆盖率、来源观点标签等扩展项在 Phase 2+ 实现。

校验不通过时按指南 59 节处理：格式类自动修复；逻辑和证据问题返回模块重跑
（最多 2 次）；仍失败输出 partial，不得无限循环。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from research_os.reports.frontmatter import validate_frontmatter_file

# 禁止输出项（指南 4 节输出边界）。与 config/report_policy.yaml 保持一致。
FORBIDDEN_WORDS = [
    "目标价",
    "买入评级",
    "卖出评级",
    "建议买入",
    "建议卖出",
    "建议加仓",
    "建议减仓",
    "建议仓位",
    "可以买",
    "可以跟",
    "上车",
    "满仓",
    "清仓",
]


@dataclass
class ReportValidation:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.ok = not self.errors


def validate_report(path: str | Path) -> ReportValidation:
    """校验报告文件：Front Matter + 禁止项扫描。"""
    p = Path(path)
    if not p.exists():
        return ReportValidation(ok=False, errors=[f"文件不存在: {p}"])

    errors: List[str] = []
    warnings: List[str] = []

    fm_result = validate_frontmatter_file(p)
    errors.extend(fm_result.errors)

    text = p.read_text(encoding="utf-8")
    body = fm_result.body if fm_result.frontmatter is not None else text

    # 禁止输出项扫描（正文部分；Front Matter 中的实体名可能含"可以"等词，不误报）
    for word in FORBIDDEN_WORDS:
        if word in body:
            errors.append(f"检测到禁止输出词: {word!r}")

    return ReportValidation(ok=not errors, errors=errors, warnings=warnings)
