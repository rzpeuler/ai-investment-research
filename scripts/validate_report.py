#!/usr/bin/env python3
"""报告机械校验器（工程指南 59 节）。

用法：
    python scripts/validate_report.py <report.md>
校验不通过返回退出码 1（格式类问题输出可自动修复提示；逻辑与证据问题
返回模块重跑，最多 2 次；仍失败输出 partial——Phase 2+ 实现自动修复）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_os.reports import validate_report  # noqa: E402


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/validate_report.py <report.md>")
        return 2
    result = validate_report(sys.argv[1])
    if result.ok:
        print(f"[OK] 校验通过: {sys.argv[1]}")
        return 0
    for err in result.errors:
        print(f"[FAIL] {err}")
    print("Phase 0 基础校验：Front Matter + 禁止项。"
          "绝对日期/引用覆盖率/来源观点标签等扩展项见工程指南 59 节（Phase 2+）。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
