"""错误记录与运行日志（指南 50 节：每次任务保存 errors.log）。

所有失败必须显式记录并返回明确状态，禁止静默失败（工程指南约束）。
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_lock = threading.Lock()


class ErrorLog:
    """线程安全的 errors.log 写入器。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def record(
        self,
        level: str,
        component: str,
        message: str,
        details: Optional[dict] = None,
    ) -> None:
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "level": level,
            "component": component,
            "message": message,
            "details": details or {},
        }
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def error(self, component: str, message: str, details: Optional[dict] = None) -> None:
        self.record("ERROR", component, message, details)

    def warning(self, component: str, message: str, details: Optional[dict] = None) -> None:
        self.record("WARNING", component, message, details)

    def info(self, component: str, message: str, details: Optional[dict] = None) -> None:
        self.record("INFO", component, message, details)

    def read(self) -> list[dict]:
        """读取全部记录（用于审计与测试）。"""
        if not self.path.exists():
            return []
        entries: list[dict] = []
        with self.path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        return entries
