"""stock_review 单元测试（Phase 6B B3）。

contract / degraded path / Evidence lineage / 增量复盘（复用 Phase4 产物）。
"""
from __future__ import annotations

import json
from datetime import date

from research_os.models import StockReviewRequest, StockReviewRun
from research_os.review.stock import StockReviewPipeline, report_path_for
from research_os.validators.schema_validator import validate_instance


def _evidence(evidence_id: str, published: str, title: str, entities=None) -> dict:
    return {
        "evidence_id": evidence_id, "source_id": "cninfo", "raw_item_id": "r-" + evidence_id,
        "title": title, "publisher": "巨潮", "published_at": published,
        "retrieved_at": published, "url": f"https://static.cninfo.com.cn/{evidence_id}",
        "excerpt": title, "evidence_type": "official_disclosure",
        "independence_group": "story:y", "source_tier": "S", "access_status": "ok",
        "entities": entities or [],
    }


class _FakeDb:
    def __init__(self, evidences=None, findings=None):
        self._evidences = evidences or []
        self._findings = findings or []

    def query(self, sql, params=()):
        if "research_findings" in sql:
            return [{"payload": json.dumps(f)} for f in self._findings]
        start, end = params
        return [{"payload": json.dumps(ev)} for ev in self._evidences
                if start <= ev["published_at"] <= end]


def _finding(finding_id: str, finding_type: str, statement: str,
             entities=None, invalidation=None) -> dict:
    return {
        "finding_id": finding_id, "request_id": "req-1", "company_entity_id": "company:600519.SH",
        "finding_type": finding_type, "title": statement[:20], "statement": statement,
        "claim_type": "FACT", "predicate": "关联", "object": {"entities": entities or []},
        "as_of": "2026-08-01T20:00:00+08:00", "evidence_ids": [],
        "support_level": "direct", "status": "active", "invalidation_conditions": invalidation or [],
        "materiality": "high", "section_id": "risk", "version": 1,
        "created_at": "2026-08-01T20:00:00+08:00",
    }


def test_contract_request_and_run_schema():
    req = StockReviewRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        task_id="22222222-2222-4222-8222-222222222222",
        entity="600519.SH",
        review_start="2026-08-06", review_end="2026-08-06",
        as_of="2026-08-06T20:00:00+08:00",
        requested_at="2026-08-06T20:00:00+08:00",
    )
    assert validate_instance(req.model_dump(), "stock_review_request") == []
    run = StockReviewRun(
        run_id="33333333-3333-4333-8333-333333333333",
        task_id="22222222-2222-4222-8222-222222222222",
        entity="600519.SH",
        review_start="2026-08-06", review_end="2026-08-06",
        as_of="2026-08-06T20:00:00+08:00",
        new_evidence_count=1,
    )
    assert validate_instance(run.model_dump(), "stock_review_run") == []


def test_report_path_includes_entity_and_date():
    p = report_path_for("company:600519.SH", date(2026, 8, 6), ".")
    assert "company_600519.SH" in p
    assert p.endswith("2026-08-06_stock_review.md")


def test_incremental_review_with_phase4_findings(tmp_path):
    """复用 Phase4 research_findings 做增量对照（不重跑完整研报）。"""
    db = _FakeDb(
        evidences=[
            _evidence("e1", "2026-08-06T10:00:00+08:00",
                      "贵州茅台公告：产能扩建获批", ["company:600519.SH"]),
            _evidence("e2", "2026-08-06T14:00:00+08:00",
                      "贵州茅台披露中报", ["company:600519.SH"]),
        ],
        findings=[
            _finding("f1", "catalyst", "产能扩建获批是重要催化剂",
                     entities=["company:600519.SH"]),
            _finding("f2", "risk_factor", "基酒产能不足构成风险",
                     entities=["company:600519.SH"]),
        ],
    )
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert len(artifacts.what_changed) == 2
    assert artifacts.catalyst_changed, "催化剂变化应被识别"
    md = artifacts.markdown
    assert "scenario: stock_review" in md
    assert "增量复盘" in md
    for section in ("what_changed", "new_evidence", "thesis", "risk changed",
                    "catalyst changed", "valuation assumption changed", "remaining questions"):
        assert section in md
    # Evidence lineage：报告引用真实 Evidence ID
    assert "Evidence ID: `e1`" in md


def test_degraded_without_phase4_findings(tmp_path):
    """无 Phase4 产物 -> 明确降级（不虚构基线）。"""
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "贵州茅台披露中报", ["company:600519.SH"]),
    ], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    assert artifacts.findings == []
    assert any("research_findings" in m for m in artifacts.missing_data)
    assert "不虚构" in artifacts.markdown
    assert "无法评估 thesis/risk/catalyst 变化" in artifacts.markdown


def test_empty_window_is_not_no_change(tmp_path):
    db = _FakeDb(evidences=[], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    assert any("不得" in q for q in artifacts.remaining_questions)
