#!/usr/bin/env python3
"""场景运行入口（等价 research run）。

用法：
    python scripts/run_scenario.py --scenario morning_brief --entity 600519.SH
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_os.orchestrator import Orchestrator  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    scenario = "morning_brief"
    entities: list[str] = []
    depth = "standard"
    i = 0
    while i < len(args):
        if args[i] == "--scenario" and i + 1 < len(args):
            scenario = args[i + 1]
            i += 2
        elif args[i] == "--entity" and i + 1 < len(args):
            entities.append(args[i + 1])
            i += 2
        elif args[i] == "--depth" and i + 1 < len(args):
            depth = args[i + 1]
            i += 2
        else:
            print(f"未知参数: {args[i]}")
            return 2

    outcome = Orchestrator(PROJECT_ROOT).run(
        scenario=scenario, entities=entities, depth=depth,
    )
    if outcome.status == "failed":
        print(f"失败: {outcome.message}", file=sys.stderr)
        return 1
    print(f"{outcome.status}: {outcome.message}")
    print(f"运行目录: {outcome.run_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
