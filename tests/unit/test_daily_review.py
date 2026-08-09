"""daily_review 单元测试（Phase 6B B2）。

contract / degraded path / Evidence lineage / 五段结构 / 判断变化近似。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from research_os.models import DailyReviewRequest, DailyReviewRun
from research_os.review.daily import (
    DailyReviewPipeline,
    previous_cutoff_for,
    report_path_for,
)
from research_os.validators.schema_validator import validate_instance


def _evidence(evidence_id: str, published: str, title: str, entities=None) -> dict:
    return {
        "evidence_id": evidence_id, "source_id": "cls", "raw_item_id": "r-" + evidence_id,
        "title": title, "publisher": "财联社", "published_at": published,
        "retrieved_at": published, "url": f"https://example.com/{evidence_id}",
        "excerpt": title, "evidence_type": "news_report",
        "independence_group": "story:x", "source_tier": "B", "access_status": "ok",
        "entities": entities or [],
    }


class _FakeDb:
    """内存 Evidence 查询替身（只读语义）。"""

    def __init__(self, evidences):
        self._evidences = evidences

    def query(self, sql, params=()):
        start, end = params
        return [{"payload": json.dumps(ev)} for ev in self._evidences
                if start <= ev["published_at"] < end]


def _prev_run(project_root: Path, run_id: str, claims) -> Path:
    d = project_root / "reports" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "claims.json").write_text(json.dumps(claims, ensure_ascii=False), encoding="utf-8")
    return d


def test_contract_request_and_run_schema():
    req = DailyReviewRequest(
        request_id="11111111-1111-4111-8111-111111111111",
        task_id="22222222-2222-4222-8222-222222222222",
        review_business_date="2026-08-06",
        as_of="2026-08-06T20:00:00+08:00",
        requested_at="2026-08-06T20:00:00+08:00",
    )
    assert validate_instance(req.model_dump(), "daily_review_request") == []
    run = DailyReviewRun(
        run_id="33333333-3333-4333-8333-333333333333",
        task_id="22222222-2222-4222-8222-222222222222",
        review_business_date="2026-08-06",
        as_of="2026-08-06T20:00:00+08:00",
        previous_cutoff="2026-08-05T20:00:00+08:00",
        observed_fact_count=1, previous_view_count=1, new_evidence_count=1,
        supported_count=1,
    )
    assert validate_instance(run.model_dump(), "daily_review_run") == []


def test_previous_cutoff_default_is_previous_day_2000():
    assert previous_cutoff_for(date(2026, 8, 6)) == "2026-08-05T20:00:00+08:00"


def test_report_path_follows_engineering_guide():
    from pathlib import Path as P

    p = P(report_path_for(date(2026, 8, 6), Path(".")))
    assert p == P("reports/daily_review/2026/2026-08/2026-08-06_review.md")


def test_full_five_sections(tmp_path):
    db = _FakeDb([
        _evidence("e1", "2026-08-06T09:00:00+08:00", "CPI同比上涨0.5%", ["macro:cpi"]),
        _evidence("e2", "2026-08-06T11:00:00+08:00", "某光伏龙头签订长单", ["company:solar"]),
    ])
    claims = [{
        "claim_id": "c1", "claim_type": "FACT", "title": "CPI同比上涨0.5%",
        "object": {"entities": ["macro:cpi"]}, "evidence_ids": ["e1"],
    }]
    _prev_run(tmp_path, "run-morning", claims)
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"])
    assert len(artifacts.observed_facts) == 2
    assert len(artifacts.previous_views) == 1
    assert len(artifacts.new_evidence) == 2  # 均晚于 previous_cutoff(前一日 20:00)
    assert artifacts.interpretations[0]["verdict"] == "supported"
    md = artifacts.markdown
    for section in ("observed_fact", "previous_research_view", "new_evidence",
                    "updated_interpretation", "remaining_unknown"):
        assert f"## " in md and section in md
    assert "scenario: daily_review" in md
    # Evidence lineage：报告引用真实 Evidence ID
    assert "Evidence ID: `e1`" in md


def test_degraded_without_previous_views(tmp_path):
    """无 previous views -> 明确降级，不虚构历史判断。"""
    db = _FakeDb([_evidence("e1", "2026-08-06T09:00:00+08:00", "CPI同比上涨0.5%")])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=[])
    assert artifacts.previous_views == []
    assert any("previous_research_view" in m for m in artifacts.missing_data)
    assert any("不虚构" in m for m in artifacts.missing_data)
    assert "无前序研究产物" in artifacts.markdown
    assert "本段不虚构历史判断" in artifacts.markdown


def test_weakened_signal_detected(tmp_path):
    """相反信号 -> weakened。"""
    db = _FakeDb([
        _evidence("e2", "2026-08-06T10:00:00+08:00", "某公司上调业绩指引", ["company:x"]),
    ])
    claims = [{
        "claim_id": "c2", "claim_type": "FACT", "title": "某公司下调业绩指引",
        "object": {"entities": ["company:x"]}, "evidence_ids": [],
    }]
    _prev_run(tmp_path, "run-morning", claims)
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"])
    assert artifacts.interpretations[0]["verdict"] == "weakened"


def test_empty_day_is_not_no_change(tmp_path):
    """窗口内无 Evidence 不得解释为'没有变化'。"""
    db = _FakeDb([])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00", task_id="t1")
    assert any("不得" in u for u in artifacts.remaining_unknown)
    assert "未检索到 Evidence" in artifacts.markdown
