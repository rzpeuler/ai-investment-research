"""运行目录机制测试（工程指南 50 节）。"""
from __future__ import annotations

from research_os.orchestrator import RunDirectory


def test_create_builds_skeleton(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    assert rd.module_results_dir.is_dir()
    assert rd.retrieval_log.exists()
    assert rd.evidence_index.exists()
    assert rd.validation_json.exists()
    assert rd.final_md.exists()
    assert rd.errors_log.exists()


def test_create_is_idempotent(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    rd.create()  # 不报错、不覆盖


def test_write_and_read_task(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    rd.write_task({"task_id": "t1", "status": "planned"})
    assert rd.read_task()["task_id"] == "t1"
    assert rd.read_task()["status"] == "planned"


def test_append_retrieval_log(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    rd.append_retrieval_log({"event": "a"})
    rd.append_retrieval_log({"event": "b"})
    lines = rd.retrieval_log.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2


def test_write_module_result(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    p = rd.write_module_result("financial_analysis", {"module": "financial_analysis"})
    assert p.name == "financial_analysis.json"
    assert p in rd.list_module_results()


def test_write_validation_and_evidence(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    rd.write_validation({"status": "ok"})
    rd.write_evidence_index([{"evidence_id": "e1"}])
    assert '"status": "ok"' in rd.validation_json.read_text(encoding="utf-8")
    assert '"evidence_id": "e1"' in rd.evidence_index.read_text(encoding="utf-8")


def test_write_final_md(tmp_path):
    rd = RunDirectory(tmp_path, "task-1")
    rd.create()
    rd.write_final("# 报告\n")
    assert rd.final_md.read_text(encoding="utf-8").startswith("# 报告")
