"""Phase 6B 场景集成测试（Orchestrator + isolated registry，F0 §27）。

验证：evening_brief / daily_review / stock_review 通过统一控制面执行，
Task/Plan/Request/Run/Result 血缘、artifact 命名、报告生成与校验、幂等重跑。
不修改中央注册表（runners/__init__.py 与 cli/main.py 保持不变）。
"""
from __future__ import annotations

import json
from pathlib import Path

from research_os.collectors.manual import ManualInboxService
from research_os.models import Evidence, RawItem
from research_os.orchestrator.orchestrator import Orchestrator
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.orchestrator.runners.evening_brief import EveningBriefScenarioRunner
from research_os.orchestrator.runners.daily_review import DailyReviewScenarioRunner
from research_os.orchestrator.runners.stock_review import StockReviewScenarioRunner
from research_os.reports import validate_report
from research_os.storage import Database
from research_os.utils.id import content_sha256, new_uuid


def _make_db(tmp_path) -> Database:
    db_path = tmp_path / "data" / "sqlite" / "research.db"
    db = Database(db_path)
    db.initialize()
    return db


def _registry() -> ScenarioRegistry:
    reg = ScenarioRegistry()
    reg.register(EveningBriefScenarioRunner())
    reg.register(DailyReviewScenarioRunner())
    reg.register(StockReviewScenarioRunner())
    return reg


def _seed_evidence(db: Database) -> None:
    for i, (eid, published, title, entities) in enumerate([
        ("e-0001", "2026-08-06T09:00:00+08:00", "CPI同比上涨0.5%", ["macro:cpi"]),
        ("e-0002", "2026-08-06T14:00:00+08:00", "某光伏龙头签订10GW长单", ["company:solar"]),
    ]):
        raw = RawItem(
            raw_item_id="r-" + eid, source_id="cls", external_id="x" + str(i),
            url=f"https://example.com/{eid}", title=title, publisher="财联社",
            author=None, published_at=published, retrieved_at=published,
            content_hash=content_sha256(title), content_excerpt=title,
            content_storage="metadata_and_excerpt", language="zh-CN",
            access_status="ok", entities=entities, raw_category="news",
        )
        ev = Evidence(
            evidence_id=eid, source_id="cls", raw_item_id=raw.raw_item_id,
            title=title, publisher="财联社", published_at=published,
            retrieved_at=published, url=f"https://example.com/{eid}",
            excerpt=title, evidence_type="news_report",
            independence_group="story:x", source_tier="B", access_status="ok",
        )
        db.upsert(raw)
        db.upsert(ev)


def _seed_finding(db: Database) -> None:
    db.query(
        "INSERT INTO research_findings "
        "(finding_id, payload, request_id, company_entity_id, finding_type, "
        " materiality, status, version) VALUES (?,?,?,?,?,?,?,?)",
        ("f-0001", json.dumps({
            "finding_id": "f-0001", "request_id": "req-1",
            "company_entity_id": "company:solar", "finding_type": "catalyst",
            "title": "光伏长单催化剂", "statement": "10GW 组件长单是重要催化剂",
            "claim_type": "FACT", "predicate": "关联", "object": {"entities": ["company:solar"]},
            "as_of": "2026-08-01T20:00:00+08:00", "evidence_ids": [],
            "support_level": "direct", "status": "active",
            "invalidation_conditions": [], "materiality": "high",
            "section_id": "catalyst", "version": 1,
            "created_at": "2026-08-01T20:00:00+08:00",
        }, ensure_ascii=False), "req-1", "company:solar", "catalyst",
        "high", "active", 1),
    )


def _seed_previous_run(tmp_path, run_id: str) -> None:
    d = tmp_path / "reports" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "claims.json").write_text(json.dumps([{
        "claim_id": "c-0001", "claim_type": "FACT", "title": "CPI同比上涨0.5%",
        "object": {"entities": ["macro:cpi"]}, "evidence_ids": ["e-0001"],
    }], ensure_ascii=False), encoding="utf-8")


# ---------- evening_brief ----------

def test_evening_brief_full_flow(tmp_path):
    db = _make_db(tmp_path)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        ManualInboxService(db).add(
            source_name="财联社", source_url="https://example.com/n1",
            title="某公司公告：因违规被立案调查",
            content_excerpt="重大风险事件", intended_entities=["company:bad"],
            published_at="2026-08-06T10:00:00+08:00",
        )
        result = orch.execute("evening_brief", {
            "report_date": "2026-08-06", "as_of": "2026-08-06T20:00:00+08:00",
        })
        assert result.status in ("success", "partial_success"), result.message
        assert result.exit_code == 0
        assert result.task_id
        report = Path(result.report_path)
        assert report.exists()
        assert "evening" in str(report)
        assert validate_report(report).ok, validate_report(report).errors

        # Front Matter：晚报身份 + 窗口 [08:00, 20:00)
        fm = report.read_text(encoding="utf-8").split("---")[1]
        assert "scenario: evening_brief" in fm
        assert "A股每日晚报" in fm
        assert "2026-08-06T08:00:00+08:00" in fm and "2026-08-06T20:00:00+08:00" in fm

        # Artifact 血缘：Request/Run/Result 全部同 task_id
        run_dir = Path(result.run_dir)
        req = json.loads((run_dir / "evening_brief_request.json").read_text(encoding="utf-8"))
        run = json.loads((run_dir / "evening_brief_run.json").read_text(encoding="utf-8"))
        ser = json.loads((run_dir / "scenario_execution_result.json").read_text(encoding="utf-8"))
        assert req["task_id"] == run["task_id"] == ser["task_id"] == result.task_id
        # run 记录窗口正确
        assert run["window_start"] == "2026-08-06T08:00:00+08:00"
        assert run["window_end"] == "2026-08-06T20:00:00+08:00"

        # 幂等重跑 -> idempotent_skipped
        again = orch.execute("evening_brief", {
            "report_date": "2026-08-06", "as_of": "2026-08-06T20:00:00+08:00",
        })
        assert again.status == "idempotent_skipped"
    finally:
        orch.close()


def test_evening_brief_dry_run_no_side_effects(tmp_path):
    db = _make_db(tmp_path)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("evening_brief", {
            "report_date": "2026-08-06", "dry_run": True,
        })
        assert result.status == "planned"
        assert result.run_dir is None
    finally:
        orch.close()


# ---------- daily_review ----------

def test_daily_review_full_flow(tmp_path):
    db = _make_db(tmp_path)
    _seed_evidence(db)
    _seed_previous_run(tmp_path, "run-morning-1")
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("daily_review", {
            "review_business_date": "2026-08-06",
            "as_of": "2026-08-06T20:00:00+08:00",
            "previous_run_ids": ["run-morning-1"],
        })
        assert result.status in ("success", "partial_success"), result.message
        assert result.exit_code == 0
        report = Path(result.report_path)
        assert report.exists()
        assert validate_report(report).ok
        md = report.read_text(encoding="utf-8")
        for section in ("observed_fact", "previous_research_view", "new_evidence",
                        "updated_interpretation", "remaining_unknown"):
            assert section in md
        assert "2026-08-06" in md

        run_dir = Path(result.run_dir)
        req = json.loads((run_dir / "daily_review_request.json").read_text(encoding="utf-8"))
        run = json.loads((run_dir / "daily_review_run.json").read_text(encoding="utf-8"))
        assert req["task_id"] == run["task_id"] == result.task_id
        assert run["observed_fact_count"] >= 1
        assert run["previous_view_count"] == 1
    finally:
        orch.close()


def test_daily_review_degraded_without_previous(tmp_path):
    db = _make_db(tmp_path)
    _seed_evidence(db)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("daily_review", {
            "review_business_date": "2026-08-06",
            "as_of": "2026-08-06T20:00:00+08:00",
        })
        assert result.status == "partial_success"
        assert any("previous_research_view" in m for m in result.missing_data)
        assert result.exit_code == 0
    finally:
        orch.close()


# ---------- stock_review ----------

def test_stock_review_full_flow(tmp_path):
    db = _make_db(tmp_path)
    _seed_evidence(db)
    _seed_finding(db)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("stock_review", {
            "entity": "company:solar",
            "review_start": "2026-08-06", "review_end": "2026-08-06",
            "as_of": "2026-08-06T20:00:00+08:00",
            "previous_cutoff": "2026-08-05T20:00:00+08:00",
        })
        assert result.status in ("success", "partial_success"), result.message
        assert result.exit_code == 0
        report = Path(result.report_path)
        assert report.exists()
        assert validate_report(report).ok
        md = report.read_text(encoding="utf-8")
        assert "scenario: stock_review" in md
        assert "catalyst" in md

        run_dir = Path(result.run_dir)
        req = json.loads((run_dir / "stock_review_request.json").read_text(encoding="utf-8"))
        run = json.loads((run_dir / "stock_review_run.json").read_text(encoding="utf-8"))
        assert req["task_id"] == run["task_id"] == result.task_id
        assert run["entity"] == "company:solar"
        assert run["new_evidence_count"] >= 1
    finally:
        orch.close()


def test_unregistered_scenario_fails_cleanly(tmp_path):
    """未注册场景 -> 结构化失败（不静默）。"""
    db = _make_db(tmp_path)
    orch = Orchestrator(tmp_path, db=db, registry=_registry())
    try:
        result = orch.execute("theme_discovery", {})
        assert result.status == "failed"
        assert result.exit_code in (2, 5)
    finally:
        orch.close()
