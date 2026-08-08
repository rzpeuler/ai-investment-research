"""Phase 5 M2 迁移测试（任务书架构评审修正版）。

覆盖：空库执行全部迁移到 v6；v5→v6 升级；
CHECK(version >= 1) 约束；graph_* 表存在；
graph_applications 最小结构含 idempotency_key UNIQUE；
FK ON UPDATE RESTRICT ON DELETE RESTRICT；
旧表不变。
"""
from __future__ import annotations

import sqlite3
import pytest

from research_os.storage import db as storage_db
from research_os.storage.db import Database

MIGRATIONS_DIR = storage_db.MIGRATIONS_DIR


@pytest.fixture()
def empty_db(tmp_path):
    db = Database(tmp_path / "test.db")
    yield db
    db.close()


# ---- 基础迁移 ----

def test_fresh_migration_reaches_version_6(empty_db):
    applied = empty_db.migrate()
    assert empty_db.current_version() == 6
    assert applied == [
        "001_initial", "002_sources", "003_market",
        "004_abnormal_move", "005_equity_research",
        "006_phase5_knowledge_graph",
    ]


def test_migration_from_v5_to_v6(tmp_path):
    """从 user_version 5 升级：004→005 done，再加 006。"""
    db = Database(tmp_path / "test.db")
    for name in ["001_initial", "002_sources", "003_market", "004_abnormal_move", "005_equity_research"]:
        script = (MIGRATIONS_DIR / f"{name}.sql").read_text(encoding="utf-8")
        with db._conn:
            db._conn.executescript(script)
            db._conn.execute(f"PRAGMA user_version = {int(name[:3])}")
    assert db.current_version() == 5

    old_tables = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    old_names = {r["name"] for r in old_tables}

    applied = db.migrate()
    assert applied == ["006_phase5_knowledge_graph"]
    assert db.current_version() == 6

    new_tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    assert old_names <= new_tables
    db.close()


# ---- graph_* 表存在 ----

def test_graph_tables_exist(empty_db):
    empty_db.migrate()
    names = {r["name"] for r in empty_db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    for t in ["graph_nodes", "graph_edges", "graph_reviews", "graph_applications"]:
        assert t in names, f"缺少表: {t}"


# ---- 复合主键 ----

def test_graph_nodes_composite_pk(empty_db):
    empty_db.migrate()
    # 插入同 node_id 不同 version
    empty_db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", 1, "{}", "Industry", "test", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
    )
    empty_db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", 2, "{}", "Industry", "test2", "active", "approved", "governance_seed", "2026-08-07T18:00:00+08:00"),
    )
    rows = empty_db._conn.execute("SELECT COUNT(*) FROM graph_nodes WHERE node_id='n1'").fetchone()
    assert rows[0] == 2

    # 同 (node_id, version) 重复插入应失败
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("n1", 1, "{}", "Industry", "test", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
        )


def test_graph_edges_composite_pk(empty_db):
    empty_db.migrate()
    empty_db._conn.execute(
        "INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, confidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("e1", 1, "{}", "s", "BELONGS_TO", "t", "GOVERNANCE", "approved", "2026-08-07T17:00:00+08:00", 1.0),
    )
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", 1, "{}", "s", "BELONGS_TO", "t", "GOVERNANCE", "approved", "2026-08-07T17:00:00+08:00", 1.0),
        )


# ---- CHECK(version >= 1) ----

def test_graph_nodes_check_version_negative_fails(empty_db):
    empty_db.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("n1", 0, "{}", "Industry", "test", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
        )


def test_graph_nodes_check_version_negative_fails_alt(empty_db):
    empty_db.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("n1", -1, "{}", "Industry", "test", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
        )


def test_graph_nodes_check_version_1_passes(empty_db):
    empty_db.migrate()
    empty_db._conn.execute(
        "INSERT INTO graph_nodes (node_id, version, payload, node_type, name, status, review_status, origin_kind, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("n1", 1, "{}", "Industry", "test", "active", "approved", "governance_seed", "2026-08-07T17:00:00+08:00"),
    )
    rows = empty_db._conn.execute("SELECT COUNT(*) FROM graph_nodes").fetchone()
    assert rows[0] == 1


def test_graph_edges_check_version_negative_fails(empty_db):
    empty_db.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_edges (edge_id, version, payload, source_node_id, relation, target_node_id, assertion_type, review_status, created_at, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("e1", 0, "{}", "s", "BELONGS_TO", "t", "GOVERNANCE", "approved", "2026-08-07T17:00:00+08:00", 1.0),
        )


# ---- idempotency_key UNIQUE ----

def test_graph_applications_idempotency_key_unique(empty_db):
    empty_db.migrate()
    # 先插入一条 graph_change 和 graph_review 以满足 FK
    empty_db._conn.execute(
        "INSERT INTO graph_changes (graph_change_id, payload, change_type, review_status, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("11111111-1111-1111-1111-111111111111", "{}", "add_node", "candidate", "2026-08-07T17:00:00+08:00"),
    )
    empty_db._conn.execute(
        "INSERT INTO graph_reviews (review_id, payload, graph_change_id, decision, reviewer_id, reviewed_at, candidate_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("22222222-2222-2222-2222-222222222222", "{}",
         "11111111-1111-1111-1111-111111111111", "approved", "human:reviewer1",
         "2026-08-07T18:00:00+08:00", "a" * 64),
    )
    empty_db._conn.execute(
        "INSERT INTO graph_applications (application_id, graph_change_id, review_id, idempotency_key, payload, applied_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("33333333-3333-3333-3333-333333333333",
         "11111111-1111-1111-1111-111111111111",
         "22222222-2222-2222-2222-222222222222",
         "ik-001", "{}", "2026-08-07T18:01:00+08:00"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_applications (application_id, graph_change_id, review_id, idempotency_key, payload, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("44444444-4444-4444-4444-444444444444",
             "11111111-1111-1111-1111-111111111111",
             "22222222-2222-2222-2222-222222222222",
             "ik-001", "{}", "2026-08-07T18:02:00+08:00"),
        )


# ---- FK constraints ----

def test_graph_reviews_fk_enforced(empty_db):
    empty_db.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_reviews (review_id, payload, graph_change_id, decision, reviewer_id, reviewed_at, candidate_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("33333333-3333-3333-3333-333333333333", "{}",
             "nonexistent", "approved", "human:r1",
             "2026-08-07T17:00:00+08:00", "a" * 64),
        )


def test_graph_applications_fk_review_enforced(empty_db):
    empty_db.migrate()
    with pytest.raises(sqlite3.IntegrityError):
        empty_db._conn.execute(
            "INSERT INTO graph_applications (application_id, graph_change_id, review_id, idempotency_key, payload, applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            ("33333333-3333-3333-3333-333333333333",
             "11111111-1111-1111-1111-111111111111",
             "nonexistent", "ik-002", "{}", "2026-08-07T17:00:00+08:00"),
        )


# ---- graph_applications 最小结构 ----

def test_graph_applications_minimal_columns(empty_db):
    """M2 修正：graph_applications 仅含 application_id/graph_change_id/review_id/idempotency_key/payload/applied_at。"""
    empty_db.migrate()
    cols = {r["name"] for r in empty_db.query("PRAGMA table_info(graph_applications)")}
    assert "application_id" in cols
    assert "graph_change_id" in cols
    assert "review_id" in cols
    assert "idempotency_key" in cols
    assert "payload" in cols
    assert "applied_at" in cols
    # 不应包含旧结构中的 node_id/node_version/edge_id/edge_version
    assert "node_id" not in cols, "graph_applications 不应包含 node_id 列"
    assert "node_version" not in cols, "graph_applications 不应包含 node_version 列"
    assert "edge_id" not in cols, "graph_applications 不应包含 edge_id 列"
    assert "edge_version" not in cols, "graph_applications 不应包含 edge_version 列"


# ---- 索引存在 ----

def test_graph_applications_indexes(empty_db):
    empty_db.migrate()
    indexes = {r["name"] for r in empty_db.query("SELECT name FROM sqlite_master WHERE type='index'")}
    assert "idx_gapp_change" in indexes
    assert "idx_gapp_review" in indexes
    assert "idx_gapp_applied" in indexes
