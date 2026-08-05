"""运行目录管理（工程指南 50 节）。

每次任务保存：
reports/runs/{task_id}/
├── task.json
├── plan.json
├── retrieval_log.jsonl
├── module_results/
├── evidence_index.json
├── validation.json
├── final.md
└── errors.log

使任务可复盘，降低幻觉和不可追踪修改。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional


class RunDirectory:
    """管理单个任务的运行目录。"""

    def __init__(self, runs_root: str | Path, task_id: str):
        self.task_id = task_id
        self.root = Path(runs_root) / task_id
        self.module_results_dir = self.root / "module_results"

    # ---------- 路径 ----------

    @property
    def task_json(self) -> Path:
        return self.root / "task.json"

    @property
    def plan_json(self) -> Path:
        return self.root / "plan.json"

    @property
    def retrieval_log(self) -> Path:
        return self.root / "retrieval_log.jsonl"

    @property
    def evidence_index(self) -> Path:
        return self.root / "evidence_index.json"

    @property
    def validation_json(self) -> Path:
        return self.root / "validation.json"

    @property
    def final_md(self) -> Path:
        return self.root / "final.md"

    @property
    def errors_log(self) -> Path:
        return self.root / "errors.log"

    # ---------- 生命周期 ----------

    def exists(self) -> bool:
        return self.root.exists()

    def create(self) -> None:
        """创建运行目录骨架。已存在时幂等（不覆盖已有文件）。"""
        self.module_results_dir.mkdir(parents=True, exist_ok=True)
        # 初始化空文件（若不存在）
        for f in (self.retrieval_log, self.evidence_index, self.errors_log):
            if not f.exists():
                f.write_text("" if f.suffix == ".log" else "[]", encoding="utf-8")
        if not self.validation_json.exists():
            self.write_json("validation.json", {"status": "pending", "checks": []})
        if not self.final_md.exists():
            self.final_md.write_text("# 待生成报告\n", encoding="utf-8")

    # ---------- 写入（全部原子：先写临时文件再替换，避免半写状态） ----------

    def write_json(self, filename: str, data: Any) -> Path:
        path = self.root / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
        return path

    def write_task(self, task_dict: Dict[str, Any]) -> Path:
        return self.write_json("task.json", task_dict)

    def write_plan(self, plan_dict: Dict[str, Any]) -> Path:
        return self.write_json("plan.json", plan_dict)

    def append_retrieval_log(self, entry: Dict[str, Any]) -> None:
        with self.retrieval_log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def write_evidence_index(self, evidence_list: List[Dict[str, Any]]) -> Path:
        return self.write_json("evidence_index.json", evidence_list)

    def write_validation(self, validation: Dict[str, Any]) -> Path:
        return self.write_json("validation.json", validation)

    def write_module_result(self, module: str, result_dict: Dict[str, Any]) -> Path:
        path = self.module_results_dir / f"{module}.json"
        path.write_text(json.dumps(result_dict, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def write_final(self, markdown: str) -> Path:
        self.final_md.write_text(markdown, encoding="utf-8")
        return self.final_md

    # ---------- 读取 ----------

    def read_task(self) -> Optional[Dict[str, Any]]:
        if not self.task_json.exists():
            return None
        return json.loads(self.task_json.read_text(encoding="utf-8"))

    def list_module_results(self) -> List[Path]:
        if not self.module_results_dir.exists():
            return []
        return sorted(self.module_results_dir.glob("*.json"))
