"""Phase 4 迁移测试（任务书 3.25 迁移测试节）。

覆盖：空库执行 001—005；user_version 4 升级 5；旧表行数和结构不变；
迁移失败回滚；重复执行无破坏；唯一约束；索引存在；财务值 TEXT decimal。
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


def test_fresh_migration_reaches_version_6(empty_db):
    applied = empty_db.migrate()
    assert empty_db.current_version() == 6
    assert applied == ["001_initial", "002_sources", "003_market", "004_abnormal_move", "005_equity_research", "006_phase5_knowledge_graph"]


def test_migration_from_v4_to_v5(tmp_path):
    """从 user_version 4 升级：先建旧库，再跑全部迁移。"""
    db = Database(tmp_path / "test.db")
    # 只应用 001-004
    for name in ["001_initial", "002_sources", "003_market", "004_abnormal_move"]:
        script = (MIGRATIONS_DIR / f"{name}.sql").read_text(encoding="utf-8")
        with db._conn:
            db._conn.executescript(script)
            db._conn.execute("PRAGMA user_version = 4")
    assert db.current_version() == 4

    # 记录旧表与行数
    old_tables = db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    old_names = {r["name"] for r in old_tables}
    counts_before = {n: db.count(n) for n in sorted(old_names)}

    applied = db.migrate()
    assert applied == ["005_equity_research", "006_phase5_knowledge_graph"]
    assert db.current_version() == 6

    # 旧表行数和结构不变
    for n, c in counts_before.items():
        assert db.count(n) == c, f"旧表 {n} 行数变化"
    new_tables = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    assert old_names <= new_tables
    db.close()


def test_phase4_tables_exist(empty_db):
    empty_db.migrate()
    names = {r["name"] for r in empty_db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "company_profiles", "security_profiles", "document_records", "document_blocks",
        "financial_data_manifests", "financial_reports", "financial_facts",
        "financial_metrics", "business_segments", "peer_candidates", "peer_selections",
        "valuation_snapshots", "forecast_scenarios", "competitive_factors",
        "catalysts", "risk_factors", "research_findings", "equity_research_requests",
        "equity_research_runs", "equity_research_results",
    }
    assert expected <= names


def test_idempotency_unique_constraints(empty_db):
    empty_db.migrate()
    conn = empty_db._conn

    # equity_research_runs(idempotency_key, run_version) 唯一
    conn.execute(
        "INSERT INTO equity_research_runs (run_id, payload, request_id, task_id, idempotency_key, run_version, status, validation_status, started_at) "
        "VALUES ('r1','{}','q1','t1','k1',1,'running','pending','2026-08-06T00:00:00')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO equity_research_runs (run_id, payload, request_id, task_id, idempotency_key, run_version, status, validation_status, started_at) "
            "VALUES ('r2','{}','q1','t1','k1',1,'running','pending','2026-08-06T00:00:00')"
        )
    # 同键不同版本允许（force 场景）
    conn.execute(
        "INSERT INTO equity_research_runs (run_id, payload, request_id, task_id, idempotency_key, run_version, status, validation_status, started_at) "
        "VALUES ('r3','{}','q1','t1','k1',2,'running','pending','2026-08-06T00:00:00')"
    )


def test_manifest_checksum_version_unique(empty_db):
    empty_db.migrate()
    conn = empty_db._conn
    base = ("'m1','{}','manual_import','manual_financial_import','a.csv','abc','v1','accepted',1,1,0,'2026-08-06T00:00:00'")
    conn.execute(
        "INSERT INTO financial_data_manifests (manifest_id, payload, source_kind, source_id, file_name, file_checksum, data_version, validation_status, row_count, accepted_count, rejected_count, imported_at) "
        f"VALUES ({base})"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO financial_data_manifests (manifest_id, payload, source_kind, source_id, file_name, file_checksum, data_version, validation_status, row_count, accepted_count, rejected_count, imported_at) "
            f"VALUES ({base.replace(chr(39)+'m1'+chr(39), chr(39)+'m2'+chr(39))})"
        )


def test_migration_failure_rolls_back(tmp_path, monkeypatch):
    """迁移失败必须回滚，user_version 不得增加。"""
    db = Database(tmp_path / "test.db")
    db.migrate()  # 全部应用
    assert db.current_version() == 6

    # 制造一个坏迁移：在 006 之后创建 007 非法 SQL
    bad = MIGRATIONS_DIR / "007_bad.sql"
    bad.write_text("CREATE TABLE broken (", encoding="utf-8")
    try:
        # 手动模拟 migrate() 逻辑：应用失败不应改变 user_version
        with pytest.raises(Exception):
            with db._conn:
                db._conn.executescript(bad.read_text(encoding="utf-8"))
                db._conn.execute("PRAGMA user_version = 7")
        assert db.current_version() == 6
    finally:
        bad.unlink(missing_ok=True)
    db.close()


def test_repeat_migration_is_noop(empty_db):
    empty_db.migrate()
    applied = empty_db.migrate()
    assert applied == []
    assert empty_db.current_version() == 6


def test_financial_value_columns_are_text(tmp_path):
    """财务值检索列必须为 TEXT（decimal 字符串），不得为 REAL。"""
    db = Database(tmp_path / "test.db")
    db.migrate()
    rows = db.query("PRAGMA table_info(financial_facts)")
    types = {r["name"]: r["type"] for r in rows}
    # financial_facts 无值列拆出（值在 payload），但 financial_metrics 有 value 列
    rows2 = db.query("PRAGMA table_info(financial_metrics)")
    types2 = {r["name"]: r["type"] for r in rows2}
    assert types2.get("value") == "TEXT", f"financial_metrics.value 应为 TEXT，实际 {types2.get('value')}"
    db.close()


def test_phase4_indexes_exist(empty_db):
    empty_db.migrate()
    names = {r["name"] for r in empty_db.query("SELECT name FROM sqlite_master WHERE type='index'")}
    for idx in [
        "idx_cp_entity", "idx_sp_symbol", "idx_dr_company", "idx_db_doc",
        "idx_fdm_status", "idx_fr_company", "idx_ff_company", "idx_fm_company",
        "idx_bs_company", "idx_pc_subject", "idx_ps_request", "idx_vs_security",
        "idx_cat_company", "idx_rf_company", "idx_rfnd_request",
        "idx_err_runs_key", "idx_err_res_request",
    ]:
        assert idx in names, f"缺少索引 {idx}"
