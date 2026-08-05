"""SQLite 存储层测试：初始化、迁移、幂等写入。"""
from __future__ import annotations

import pytest

from research_os.models import Task, Evidence
from research_os.storage import Database
from tests.fixtures import samples


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


def test_initialize_applies_all_migrations(db):
    applied = db.initialize()
    assert applied == db.migrations_available()
    assert db.current_version() == len(db.migrations_available()) >= 1


def test_migrate_is_idempotent(db):
    first = db.initialize()
    second = db.initialize()
    assert first  # 首次应用
    assert second == []  # 重复调用不重复应用
    assert db.current_version() == len(db.migrations_available())


def test_core_tables_exist(db):
    db.initialize()
    for table in ["tasks", "entities", "raw_items", "events", "opinions",
                  "claims", "evidence", "module_results", "graph_changes",
                  "sources"]:
        rows = db.query(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        assert rows, f"缺少表 {table}"


def test_upsert_task_and_read_back(db):
    db.initialize()
    task = Task(**samples.valid_task())
    db.upsert(task)
    stored = db.get("tasks", task.task_id)
    assert stored is not None
    assert stored["task_id"] == task.task_id
    assert stored["scenario"] == task.scenario
    assert db.count("tasks") == 1


def test_upsert_same_pk_is_idempotent(db):
    """相同主键重复写入不产生重复行（幂等）。"""
    db.initialize()
    task = Task(**samples.valid_task())
    db.upsert(task)
    db.upsert(task)
    assert db.count("tasks") == 1


def test_upsert_updates_payload(db):
    """相同主键再写入更新 payload 而非新增。"""
    db.initialize()
    task = Task(**samples.valid_task())
    db.upsert(task)
    task.status = "completed"
    db.upsert(task)
    stored = db.get("tasks", task.task_id)
    assert stored["status"] == "completed"
    assert db.count("tasks") == 1


def test_upsert_evidence_with_index_columns(db):
    db.initialize()
    ev = Evidence(**samples.valid_evidence())
    db.upsert(ev)
    rows = db.query(
        "SELECT source_id, source_tier FROM evidence WHERE evidence_id=?",
        (ev.evidence_id,),
    )
    assert rows[0]["source_id"] == ev.source_id
    assert rows[0]["source_tier"] == ev.source_tier


def test_query_unknown_table_raises(db):
    db.initialize()
    with pytest.raises(ValueError):
        db.get("no_such_table", "x")


def test_database_file_created(tmp_path):
    db = Database(tmp_path / "nested" / "sub" / "test.db")
    db.initialize()
    assert (tmp_path / "nested" / "sub" / "test.db").exists()
    db.close()
