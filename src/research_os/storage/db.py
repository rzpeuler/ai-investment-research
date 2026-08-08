"""SQLite 存储层：初始化、版本化迁移、核心对象存取。

迁移机制：PRAGMA user_version 记录已应用版本，storage/migrations/ 下按序号
排列的 *.sql 逐个在事务中应用。确定性逻辑（数据库写入）必须使用代码（指南 6.3）。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.utils.time import now_iso

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"

# 核心对象 -> 表名 映射
TABLES = {
    "Task": "tasks",
    "Entity": "entities",
    "RawItem": "raw_items",
    "Event": "events",
    "Opinion": "opinions",
    "Claim": "claims",
    "Evidence": "evidence",
    "ModuleResult": "module_results",
    # GraphChange 由 GraphChangeCandidateRepository 专用追加逻辑管理，不经过 generic upsert
    # Phase 1：来源层
    "Source": "sources",
    "SourceProbe": "source_probes",
    "DataRoute": "data_routes",
    "ManualInbox": "manual_inbox",
    # Phase 3：异动分析
    "MarketDailySeriesManifest": "market_daily_series_manifests",
    "AbnormalMoveRequest": "abnormal_move_requests",
    "AbnormalMoveObservation": "abnormal_move_observations",
    "AnomalyMetric": "anomaly_metrics",
    "BenchmarkCandidate": "benchmark_candidates",
    "BenchmarkSelection": "benchmark_selections",
    "CauseCandidate": "cause_candidates",
    "CauseEvidenceLink": "cause_evidence_links",
    "AttributionResult": "attribution_results",
    "AbnormalMoveRun": "abnormal_move_runs",
    # Phase 4：个股研报
    "CompanyProfile": "company_profiles",
    "SecurityProfile": "security_profiles",
    "DocumentRecord": "document_records",
    "DocumentBlock": "document_blocks",
    "FinancialDataManifest": "financial_data_manifests",
    "FinancialReport": "financial_reports",
    "FinancialFact": "financial_facts",
    "FinancialMetric": "financial_metrics",
    "BusinessSegment": "business_segments",
    "PeerCandidate": "peer_candidates",
    "PeerSelection": "peer_selections",
    "ValuationSnapshot": "valuation_snapshots",
    "ForecastScenario": "forecast_scenarios",
    "CompetitiveFactor": "competitive_factors",
    "Catalyst": "catalysts",
    "RiskFactor": "risk_factors",
    "ResearchFinding": "research_findings",
    "EquityResearchRequest": "equity_research_requests",
    "EquityResearchRun": "equity_research_runs",
    "EquityResearchResult": "equity_research_results",
    # Phase 5：产业图谱（graph_* 表使用 GraphRepository 专用追加逻辑，不走 generic upsert）
}

# 各表主键列名（与 001_initial.sql 保持一致）
PK_COLUMNS = {
    "tasks": "task_id",
    "entities": "entity_id",
    "raw_items": "raw_item_id",
    "events": "event_id",
    "opinions": "opinion_id",
    "claims": "claim_id",
    "evidence": "evidence_id",
    # graph_changes 由 GraphChangeCandidateRepository 专用逻辑管理，不走 generic pk 查找
    "sources": "source_id",
    "source_probes": "probe_id",
    "manual_inbox": "inbox_id",
    # Phase 3
    "market_daily_series_manifests": "import_id",
    "abnormal_move_requests": "request_id",
    "abnormal_move_observations": "observation_id",
    "anomaly_metrics": "metric_id",
    "benchmark_candidates": "benchmark_candidate_id",
    "benchmark_selections": "benchmark_selection_id",
    "cause_candidates": "cause_candidate_id",
    "cause_evidence_links": "link_id",
    "attribution_results": "attribution_result_id",
    "abnormal_move_runs": "run_id",
    "llm_call_records": "call_id",
    # Phase 4
    "company_profiles": "company_profile_id",
    "security_profiles": "security_profile_id",
    "document_records": "document_id",
    "document_blocks": "block_id",
    "financial_data_manifests": "manifest_id",
    "financial_reports": "financial_report_id",
    "financial_facts": "fact_id",
    "financial_metrics": "metric_id",
    "business_segments": "segment_id",
    "peer_candidates": "peer_candidate_id",
    "peer_selections": "peer_selection_id",
    "valuation_snapshots": "valuation_snapshot_id",
    "forecast_scenarios": "scenario_id",
    "competitive_factors": "factor_id",
    "catalysts": "catalyst_id",
    "risk_factors": "risk_id",
    "research_findings": "finding_id",
    "equity_research_requests": "request_id",
    "equity_research_runs": "run_id",
    "equity_research_results": "result_id",
    # Phase 5：graph_* 表使用专用 GraphRepository 追加逻辑，不走 generic pk 查找
}


class _Transaction:
    """Database 的事务上下文管理器：commit on success, rollback on exception."""

    def __init__(self, db: "Database"):
        self._db = db

    def __enter__(self):
        return self._db._conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self._db._conn.rollback()
            return False  # re-raise
        self._db._conn.commit()
        return False


class _ImmediateTransaction:
    """BEGIN IMMEDIATE 事务上下文管理器（SQLite write lock，消除 TOCTOU）。

    用于 M6 Apply Engine：事务开始即获取写锁，事务内 rerun preflight/
    validation 后再写入，任一步失败整体 ROLLBACK。
    """

    def __init__(self, db: "Database"):
        self._db = db

    def __enter__(self) -> sqlite3.Connection:
        conn = self._db._conn
        # 结束任何隐式活动事务（python commit() 无活动事务时是 no-op）
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        return conn

    def __exit__(self, exc_type, exc_val, exc_tb):
        conn = self._db._conn
        try:
            if exc_type is not None:
                conn.execute("ROLLBACK")
            else:
                conn.execute("COMMIT")
        except sqlite3.OperationalError:
            # 事务已被外部终止（例如连接错误），无需再次回滚
            pass
        return False


class Database:
    """轻量 SQLite 封装：连接管理 + 迁移 + 对象级 upsert/query。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False：生产路径为本地单用户同步 CLI 契约（单线程）；
        # 放宽仅用于满足 M6 双连接并发测试中"主线程 setup、工作线程 apply"的
        # 跨线程使用模式（SQLite WAL + busy timeout 保证连接级安全）。
        # 生产代码不得在多个线程中同时使用同一 Database 连接执行写操作。
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

    @classmethod
    def open_read_only(cls, path: str | Path) -> "Database":
        """以 SQLite `mode=ro` 打开既有数据库，供严格零写入的 dry-run 使用。"""
        resolved = Path(path).resolve()
        if not resolved.is_file():
            raise FileNotFoundError(resolved)
        instance = cls.__new__(cls)
        instance.path = resolved
        uri = resolved.as_uri() + "?mode=ro"
        instance._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        instance._conn.row_factory = sqlite3.Row
        instance._conn.execute("PRAGMA foreign_keys=ON")
        return instance

    # ---------- 迁移 ----------

    def migrations_available(self) -> List[str]:
        """按文件名排序返回全部迁移脚本名（不含扩展名）。"""
        if not MIGRATIONS_DIR.exists():
            return []
        return sorted(
            p.stem for p in MIGRATIONS_DIR.glob("*.sql")
        )

    def current_version(self) -> int:
        row = self._conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def applied_migrations(self) -> List[str]:
        version = self.current_version()
        return self.migrations_available()[:version]

    def migrate(self) -> List[str]:
        """应用全部未应用迁移。返回本次应用的迁移名列表。"""
        available = self.migrations_available()
        applied = self.current_version()
        applied_now: List[str] = []
        for name in available[applied:]:
            script = (MIGRATIONS_DIR / f"{name}.sql").read_text(encoding="utf-8")
            with self._conn:
                self._conn.executescript(script)
                self._conn.execute(f"PRAGMA user_version = {applied + 1}")
            applied_now.append(name)
            applied += 1
        return applied_now

    def initialize(self) -> List[str]:
        """初始化：确保迁移全部应用。返回应用的迁移名列表。"""
        return self.migrate()

    # ---------- 对象存取 ----------

    @staticmethod
    def _extra_columns(obj: Any, now: str) -> Dict[str, Any]:
        """从模型对象提取索引列。"""
        name = type(obj).__name__
        d = obj.model_dump()
        if name == "Task":
            return {"status": d["status"], "scenario": d["scenario"],
                    "created_at": d["requested_at"], "updated_at": now}
        if name == "Entity":
            return {"entity_type": d["entity_type"], "canonical_name": d["canonical_name"],
                    "valid_from": d["valid_from"], "valid_to": d["valid_to"]}
        if name == "RawItem":
            return {"source_id": d["source_id"], "content_hash": d["content_hash"],
                    "published_at": d["published_at"], "retrieved_at": d["retrieved_at"],
                    "access_status": d["access_status"]}
        if name == "Event":
            return {"event_type": d["event_type"], "event_time": d["event_time"], "status": d["status"]}
        if name == "Opinion":
            return {"speaker_entity_id": d["speaker_entity_id"], "stance": d["stance"],
                    "published_at": d["published_at"]}
        if name == "Claim":
            return {"claim_type": d["claim_type"], "review_status": d["review_status"], "as_of": d["as_of"]}
        if name == "Evidence":
            return {"source_id": d["source_id"], "raw_item_id": d["raw_item_id"],
                    "independence_group": d["independence_group"], "source_tier": d["source_tier"]}
        if name == "ModuleResult":
            return {"status": d["status"], "as_of": d["as_of"]}
        if name == "GraphChange":
            raise ValueError("GraphChange 禁止使用 generic upsert，请使用 GraphChangeCandidateRepository")
        if name == "Source":
            return {"name": d["name"], "status": d["status"],
                    "last_verified_at": d["last_verified_at"]}
        if name == "SourceProbe":
            return {"source_id": d["source_id"], "status": d["status"],
                    "started_at": d["started_at"], "finished_at": d["finished_at"]}
        if name == "ManualInbox":
            return {"source_name": d["source_name"], "status": d["status"],
                    "submitted_at": d["submitted_at"]}
        if name == "MarketDailySeriesManifest":
            return {"source_kind": d["source_kind"], "adjustment_method": d["adjustment_method"],
                    "validation_status": d["validation_status"], "date_start": d["date_start"],
                    "date_end": d["date_end"], "data_version": d["data_version"],
                    "imported_at": d["imported_at"]}
        if name == "AbnormalMoveRequest":
            return {"entity_id": d["entity_id"], "entity_type": d["entity_type"],
                    "analysis_date": d["analysis_date"], "status": d["status"],
                    "created_at": d["as_of"]}
        if name == "AbnormalMoveObservation":
            return {"request_id": d["request_id"], "entity_id": d["entity_id"],
                    "trade_date": d["trade_date"], "status": d["status"]}
        if name == "AnomalyMetric":
            return {"observation_id": d["observation_id"], "metric_type": d["metric_type"],
                    "status": d["status"]}
        if name == "BenchmarkCandidate":
            return {"request_id": d["request_id"], "subject_entity_id": d["subject_entity_id"],
                    "benchmark_entity_id": d["benchmark_entity_id"],
                    "benchmark_type": d["benchmark_type"],
                    "eligible": 1 if d["eligible"] else 0}
        if name == "BenchmarkSelection":
            return {"request_id": d["request_id"], "observation_id": d["observation_id"],
                    "fallback_status": d["fallback_status"]}
        if name == "CauseCandidate":
            return {"request_id": d["request_id"], "observation_id": d["observation_id"],
                    "cause_category": d["cause_category"], "final_score": d["final_score"],
                    "status": d["status"]}
        if name == "CauseEvidenceLink":
            return {"cause_candidate_id": d["cause_candidate_id"],
                    "evidence_id": d["evidence_id"], "relation": d["relation"]}
        if name == "AttributionResult":
            return {"request_id": d["request_id"], "observation_id": d["observation_id"],
                    "attribution_status": d["attribution_status"],
                    "overall_confidence": d["overall_confidence"]}
        if name == "AbnormalMoveRun":
            return {"task_id": d["task_id"], "request_id": d["request_id"],
                    "idempotency_key": d["idempotency_key"], "run_version": d["run_version"],
                    "status": d["status"], "validation_status": d["validation_status"]}
        # ---------- Phase 4：个股研报 ----------
        if name == "CompanyProfile":
            return {"entity_id": d["entity_id"], "valid_from": d["valid_from"],
                    "valid_to": d["valid_to"], "status": d["status"], "version": d["version"]}
        if name == "SecurityProfile":
            return {"security_entity_id": d["security_entity_id"],
                    "company_entity_id": d["company_entity_id"], "symbol": d["symbol"],
                    "exchange": d["exchange"], "status": d["status"], "version": d["version"]}
        if name == "DocumentRecord":
            return {"company_entity_id": d["company_entity_id"],
                    "document_type": d["document_type"], "published_at": d["published_at"],
                    "sha256": d["sha256"], "parse_status": d["parse_status"],
                    "version": d["version"]}
        if name == "DocumentBlock":
            return {"document_id": d["document_id"], "page_start": d["page_start"],
                    "sequence_no": d["sequence_no"], "block_type": d["block_type"],
                    "content_hash": d["content_hash"], "version": d["version"]}
        if name == "FinancialDataManifest":
            return {"source_kind": d["source_kind"], "source_id": d["source_id"],
                    "file_name": d["file_name"], "file_checksum": d["file_checksum"],
                    "data_version": d["data_version"],
                    "validation_status": d["validation_status"],
                    "row_count": d["row_count"], "accepted_count": d["accepted_count"],
                    "rejected_count": d["rejected_count"], "imported_at": d["imported_at"]}
        if name == "FinancialReport":
            return {"company_entity_id": d["company_entity_id"],
                    "document_id": d["document_id"], "manifest_id": d["manifest_id"],
                    "report_type": d["report_type"], "period_end": d["period_end"],
                    "statement_scope": d["statement_scope"], "fiscal_year": d["fiscal_year"],
                    "filing_version": d["filing_version"], "data_status": d["data_status"],
                    "version": d["version"]}
        if name == "FinancialFact":
            return {"fact_key": d["fact_key"], "financial_report_id": d["financial_report_id"],
                    "company_entity_id": d["company_entity_id"],
                    "statement_type": d["statement_type"], "taxonomy_code": d["taxonomy_code"],
                    "period_end": d["period_end"], "value_status": d["value_status"],
                    "source_document_id": d["source_document_id"],
                    "conflict_group_id": d["conflict_group_id"],
                    "restatement_version": d["restatement_version"], "version": d["version"]}
        if name == "FinancialMetric":
            return {"company_entity_id": d["company_entity_id"], "metric_code": d["metric_code"],
                    "period_end": d["period_end"], "status": d["status"],
                    "value": d["value"], "formula_version": d["formula_version"],
                    "version": d["version"]}
        if name == "BusinessSegment":
            return {"company_entity_id": d["company_entity_id"],
                    "financial_report_id": d["financial_report_id"],
                    "segment_type": d["segment_type"], "raw_name": d["raw_name"],
                    "canonical_name": d["canonical_name"], "valid_from": d["valid_from"],
                    "status": d["status"], "version": d["version"]}
        if name == "PeerCandidate":
            return {"subject_company_id": d["subject_company_id"],
                    "candidate_company_id": d["candidate_company_id"],
                    "information_cutoff": d["information_cutoff"],
                    "universe_version": d["universe_version"],
                    "eligible": 1 if d["eligible"] else 0,
                    "total_score": d["total_score"], "version": d["version"]}
        if name == "PeerSelection":
            return {"request_id": d["request_id"], "subject_company_id": d["subject_company_id"],
                    "universe_version": d["universe_version"],
                    "scoring_version": d["scoring_version"], "status": d["status"],
                    "sample_size": d["sample_size"], "version": d["version"]}
        if name == "ValuationSnapshot":
            return {"company_entity_id": d["company_entity_id"],
                    "security_entity_id": d["security_entity_id"], "as_of": d["as_of"],
                    "status": d["status"], "version": d["version"]}
        if name == "ForecastScenario":
            return {"request_id": d["request_id"], "company_entity_id": d["company_entity_id"],
                    "scenario_type": d["scenario_type"],
                    "enabled": 1 if d["enabled"] else 0, "status": d["status"],
                    "version": d["version"]}
        if name == "CompetitiveFactor":
            return {"company_entity_id": d["company_entity_id"],
                    "factor_type": d["factor_type"], "direction": d["direction"],
                    "status": d["status"], "management_only": 1 if d["management_only"] else 0,
                    "version": d["version"]}
        if name == "Catalyst":
            return {"company_entity_id": d["company_entity_id"],
                    "catalyst_type": d["catalyst_type"], "status": d["status"],
                    "time_window_start": d["time_window_start"],
                    "source_phase": d["source_phase"], "version": d["version"]}
        if name == "RiskFactor":
            return {"company_entity_id": d["company_entity_id"], "risk_type": d["risk_type"],
                    "status": d["status"], "source_phase": d["source_phase"],
                    "version": d["version"]}
        if name == "ResearchFinding":
            return {"request_id": d["request_id"], "company_entity_id": d["company_entity_id"],
                    "finding_type": d["finding_type"], "materiality": d["materiality"],
                    "status": d["status"], "version": d["version"]}
        if name == "EquityResearchRequest":
            return {"task_id": d["task_id"], "company_entity_id": d["company_entity_id"],
                    "security_entity_id": d["security_entity_id"],
                    "report_date": d["report_date"], "depth": d["depth"],
                    "status": d["status"], "version": d["version"]}
        if name == "EquityResearchRun":
            return {"request_id": d["request_id"], "task_id": d["task_id"],
                    "idempotency_key": d["idempotency_key"], "run_version": d["run_version"],
                    "status": d["status"], "validation_status": d["validation_status"],
                    "started_at": d["started_at"]}
        if name == "EquityResearchResult":
            return {"run_id": d["run_id"], "request_id": d["request_id"],
                    "company_entity_id": d["company_entity_id"],
                    "research_status": d["research_status"], "version": d["version"]}
        raise ValueError(f"未知对象类型: {name}")

    def upsert(self, obj: Any, task_id: Optional[str] = None) -> None:
        """插入或更新核心对象（幂等：相同主键不产生重复行）。

        调用方必须保证 obj 已通过对应 Schema 校验。
        task_id 仅对 ModuleResult 有意义（归属任务）。
        """
        name = type(obj).__name__
        table = TABLES[name]
        d = obj.model_dump()
        payload = json.dumps(d, ensure_ascii=False)
        now = now_iso()
        extra = self._extra_columns(obj, now)

        with self._conn:
            if name in ("ModuleResult", "DataRoute"):
                if name == "ModuleResult":
                    self._conn.execute(
                        "INSERT INTO module_results (task_id, module, payload, status, as_of, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (task_id or "", d["module"], payload, d["status"], d["as_of"], now),
                    )
                else:
                    self._conn.execute(
                        "INSERT INTO data_routes (data_type, payload, status, selected_source, created_at) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (d["data_type"], payload, d["status"], d.get("selected_source"), now),
                    )
                return

            pk_col = PK_COLUMNS[table]
            pk_value = d[pk_col]
            cols = [c for c in ("payload", *extra.keys())]
            placeholders = ", ".join(f":{c}" for c in cols)
            update_cols = ", ".join(f"{c}=excluded.{c}" for c in cols)
            params = {"payload": payload, **extra}
            sql = (
                f"INSERT INTO {table} ({pk_col}, {', '.join(cols)}) "
                f"VALUES (:{pk_col}, {placeholders}) "
                f"ON CONFLICT({pk_col}) DO UPDATE SET {update_cols}"
            )
            self._conn.execute(sql, {pk_col: pk_value, **params})

    def get(self, table: str, pk_value: str) -> Optional[dict]:
        """按主键读取对象（返回 JSON payload dict）。"""
        pk_col = PK_COLUMNS.get(table)
        if pk_col is None:
            raise ValueError(f"不支持的主键表: {table}")
        row = self._conn.execute(
            f"SELECT payload FROM {table} WHERE {pk_col} = ?", (pk_value,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def query(self, sql: str, params: tuple = ()) -> List[dict]:
        """通用查询，返回 dict 列表。"""
        rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count(self, table: str) -> int:
        row = self._conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        return int(row["n"])

    # ---------- 事务 ----------

    def transaction(self):
        """开始一个确定性事务上下文管理器。

        Usage:
            with db.transaction():
                db._conn.execute(...)
                # commit on normal exit, rollback on exception
        """
        return _Transaction(self)

    def immediate_transaction(self):
        """开始一个 BEGIN IMMEDIATE 事务上下文管理器（SQLite write lock）。

        与 `transaction()` 的区别：立即获取写锁，消除
        "事务外 preflight → 他人写入 → 事务内写入" 的 TOCTOU 窗口。
        用于 M6 Apply Engine 的确定性 apply 写入。

        Usage:
            with db.immediate_transaction() as conn:
                conn.execute(...)
                # COMMIT on normal exit, ROLLBACK on exception

        Note:
            单连接模型下不得与 transaction() 嵌套使用。
        """
        return _ImmediateTransaction(self)

    def close(self) -> None:
        self._conn.close()
