#!/usr/bin/env python3
"""项目引导脚本（工程指南立即执行清单第 1 条）。

用法（项目根目录下）：
    python scripts/bootstrap.py
创建运行所需目录结构与 SQLite 初始数据库（应用全部迁移）。
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from research_os.storage import Database  # noqa: E402

DIRS = [
    "config", "registry", "schemas", "scripts",
    "reports/morning", "reports/evening", "reports/daily_review",
    "reports/stocks", "reports/industries", "reports/themes",
    "reports/earnings", "reports/runs",
    "data/sqlite", "data/parquet", "data/cache", "data/exports", "data/quarantine",
    "knowledge/ontology", "knowledge/graph", "knowledge/inbox",
    "knowledge/candidates", "knowledge/wiki", "knowledge/history",
]


def main() -> int:
    for rel in DIRS:
        (PROJECT_ROOT / rel).mkdir(parents=True, exist_ok=True)
    db = Database(PROJECT_ROOT / "data" / "sqlite" / "research.db")
    applied = db.initialize()
    version = db.current_version()
    db.close()
    print(f"目录结构就绪: {PROJECT_ROOT}")
    print(f"SQLite 初始化完成: 当前 schema 版本 = {version}, 本次应用迁移 = {applied or '无'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
