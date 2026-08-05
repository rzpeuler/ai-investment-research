#!/usr/bin/env python3
"""来源探测脚本（工程指南 22.4、76 节）。

Phase 0：不发起任何网络请求，仅输出来源注册表结构模板与 stub 状态。
Phase 1：真实探测可访问性/账号要求/历史深度/字段完整性/更新延迟/稳定性/
限频/使用条款/是否可结构化，并以 candidate 状态写入 registry/sources.yaml。

用法：
    python scripts/probe_sources.py
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_os.collectors.stub import StubCollector  # noqa: E402


def main() -> int:
    print("=" * 64)
    print("来源探测 (Phase 0 stub，无网络请求)")
    print("=" * 64)
    for sid in ["sse", "szse", "cninfo", "cls", "xueqiu", "nbs", "company_ir"]:
        status = StubCollector(source_id=sid).healthcheck()
        print(f"  [{status.source_id:12s}] access={status.access:12s} ok={status.ok}")
        print(f"      {status.message}")
    print()
    print("TODO Phase 1: 按工程指南 22.4 探测清单逐源验证，"
          "将结果以 candidate 状态写入 registry/sources.yaml，"
          "并填写 registry/source_groups.yaml 与 registry/changelog.md。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
