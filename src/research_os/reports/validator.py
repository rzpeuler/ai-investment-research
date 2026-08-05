"""报告机械校验器（工程指南 59 节 + Phase 2 任务 22 节升级）。

通用：Front Matter 完整性 + 禁止输出项扫描。
晨报（morning_brief）专用：
- 日期：window_start < window_end、as_of 不早于窗口结束、延迟报告含 delay 信息、
  信息时间行不得用模糊日期
- 覆盖：degraded 必须有缺失说明；未覆盖方向不得写成"无信息"
- 证据：重大必读每条必须有 evidence；opinion 有说话者
- 内容质量：空章节须明确数据缺失，不得生成套话
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

from research_os.reports.frontmatter import (
    validate_frontmatter_file,
)
from research_os.utils.time import parse_iso

# 禁止输出项（指南 4 节输出边界 + Phase 2 22.5 节）。
# 用词边界避免误伤："买入"单独不判（可能出现在引文中），仅组合判定。
FORBIDDEN_WORDS = [
    "目标价",
    "买入评级",
    "卖出评级",
    "建议买入",
    "建议卖出",
    "建议加仓",
    "建议减仓",
    "建议仓位",
    "建议持股",
    "可以买",
    "可以跟",
    "上车",
    "满仓",
    "清仓",
    "明日操作",
    "跟随操作",
    "明日建议",
]

RELATIVE_DATE_WORDS = ["今天", "今日", "昨天", "昨晚", "昨日", "上周", "本月"]


@dataclass
class ReportValidation:
    ok: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.ok = not self.errors


def validate_report(path: str | Path) -> ReportValidation:
    """通用校验：Front Matter + 禁止项；scenario=morning_brief 时叠加晨报专用检查。"""
    p = Path(path)
    if not p.exists():
        return ReportValidation(ok=False, errors=[f"文件不存在: {p}"])

    errors: List[str] = []
    warnings: List[str] = []

    fm_result = validate_frontmatter_file(p)
    errors.extend(fm_result.errors)

    text = p.read_text(encoding="utf-8")
    body = fm_result.body if fm_result.frontmatter is not None else text

    for word in FORBIDDEN_WORDS:
        if word in body:
            errors.append(f"检测到禁止输出词: {word!r}")

    if fm_result.frontmatter and fm_result.frontmatter.get("scenario") == "morning_brief":
        e, w = validate_morning_brief(body, fm_result.frontmatter)
        errors.extend(e)
        warnings.extend(w)

    return ReportValidation(ok=not errors, errors=errors, warnings=warnings)


def validate_morning_brief(body: str, fm: dict) -> tuple[List[str], List[str]]:
    """晨报专用校验（22.1-22.6）。"""
    errors: List[str] = []
    warnings: List[str] = []

    # 22.1 晨报必需 Front Matter 字段
    for f in ("window_start", "window_end", "scheduled_for",
              "actual_started_at", "delayed", "delay_seconds"):
        if f not in fm:
            errors.append(f"缺少晨报必需字段: {f}")

    # 22.2 日期关系
    if fm.get("window_start") and fm.get("window_end"):
        try:
            ws, we = parse_iso(fm["window_start"]), parse_iso(fm["window_end"])
            if ws >= we:
                errors.append("window_start 必须早于 window_end")
            if fm.get("as_of") and parse_iso(fm["as_of"]) < we:
                errors.append("as_of 不得早于窗口结束")
        except ValueError as exc:
            errors.append(f"窗口日期解析失败: {exc}")
    # 延迟报告必须有 delay 信息
    if fm.get("delayed") is True:
        if not fm.get("delay_seconds"):
            errors.append("delayed=true 时必须提供 delay_seconds")
    if fm.get("delay_seconds") not in (None, 0):
        if fm.get("delayed") is not True:
            warnings.append("delay_seconds>0 但 delayed 未标记为 true")
    # 信息时间行禁止模糊日期
    for m in re.finditer(r"- \*\*时间：\*\*(.+)$", body, re.MULTILINE):
        value = m.group(1).strip()
        if any(w in value for w in RELATIVE_DATE_WORDS):
            errors.append(f"信息时间使用了模糊日期: {value!r}")

    # 22.3 覆盖：degraded/partial 必须有缺失说明
    if fm.get("data_status") in ("degraded", "partial"):
        if not fm.get("missing_data") and "缺失" not in body and "降级" not in body:
            errors.append("声明数据降级但未在报告中列缺失数据")
    # 未覆盖方向不得写成"无信息"（覆盖章节需标注状态而非简单无信息）
    if "## 六、四个监测方向覆盖" in body:
        for ch in ("7×24快讯", "财经媒体深度文章", "社区舆情", "机构动向"):
            m = re.search(rf"### {ch}\n(.*?)(?=\n### |\n## )", body, re.DOTALL)
            if m and "覆盖状态" not in m.group(1):
                errors.append(f"监测方向 {ch} 覆盖说明缺失状态标注")
            if m and re.search(rf"### {ch}\n[^#]*?(无信息|没有信息)", m.group(0), re.DOTALL):
                errors.append(f"监测方向 {ch} 不得将未覆盖写成'无信息'")

    # 22.4 证据：重大必读每条有 evidence
    must = re.findall(r"### (.+)\n- \*\*分数：\*\*(\d+)", body)
    for title, score in must:
        if int(score) >= 75:
            block = re.search(rf"### {re.escape(title)}\n(.*?)(?=\n### |\Z)", body, re.DOTALL)
            if block and "待补充" in block.group(1):
                errors.append(f"重大必读缺少证据: {title}")
    # SOURCE_OPINION 必须有说话者（信息性质行 + 涉及主体）
    for m in re.finditer(r"### (.+)\n(.*?)(?=\n### |\Z)", body, re.DOTALL):
        block = m.group(2)
        if "信息性质：**opinion" in block and "涉及主体：**待确认" in block:
            errors.append(f"来源观点缺少说话者: {m.group(1)}")

    # 22.6 空章节不得套话：已渲染为空时须明确"无合格信息"或"数据缺失"
    for m in re.finditer(r"### ([^\n]+)\n([^#]*?)$", body, re.MULTILINE):
        label, content = m.group(1), m.group(2).strip()
        if not content:
            warnings.append(f"空章节: {label}")

    return errors, warnings
