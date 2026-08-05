#!/usr/bin/env python3
"""数据库迁移工具。

用法：
    python scripts/migrate.py          # 应用全部未应用迁移
    python scripts/migrate.py --status # 查看当前版本
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_os.storage import Database  # noqa: E402


def main() -> int:
    db = Database(PROJECT_ROOT / "data" / "sqlite" / "research.db")
    if "--status" in sys.argv:
        print(f"当前 schema 版本: {db.current_version()}")
        print(f"已应用迁移: {db.applied_migrations() or '无'}")
        print(f"可用迁移: {db.migrations_available() or '无'}")
        db.close()
        return 0
    applied = db.initialize()
    print(f"本次应用迁移: {applied or '无（已是最新）'}")
    print(f"当前 schema 版本: {db.current_version()}")
    db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
