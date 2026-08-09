"""daily_review 单元测试（Phase 6B B2）。

contract / degraded path / Evidence lineage / 五段结构 / 判断变化近似 /
future leakage / prior cutoff derivation / as_of 安全 / fact/view 分离。
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from research_os.models import DailyReviewRequest, DailyReviewRun
from research_os.review.daily import (
    DailyReviewPipeline,
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
    def __init__(self, evidences):
        self._evidences = evidences

    def query(self, sql, params=()):
        start, end = params
        return [{"payload": json.dumps(ev)} for ev in self._evidences
                if start <= ev["published_at"] < end]


def _prev_run(project_root: Path, run_id: str, claims,
              task_json: dict | None = None,
              validation_status: str | None = "pass") -> Path:
    d = project_root / "reports" / "runs" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "claims.json").write_text(json.dumps(claims, ensure_ascii=False), encoding="utf-8")
    if task_json is not None:
        (d / "task.json").write_text(json.dumps(task_json, ensure_ascii=False), encoding="utf-8")
    if validation_status is not None:
        (d / "validation.json").write_text(
            json.dumps({"status": validation_status}, ensure_ascii=False),
            encoding="utf-8")
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
        task_id="t1", previous_run_ids=["run-morning"],
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert len(artifacts.observed_facts) == 2
    assert len(artifacts.previous_views) == 1
    assert len(artifacts.new_evidence) == 2
    assert artifacts.interpretations[0]["verdict"] == "supported"
    md = artifacts.markdown
    for section in ("observed_fact", "previous_research_view", "new_evidence",
                    "updated_interpretation", "remaining_unknown"):
        assert "## " in md and section in md
    assert "scenario: daily_review" in md
    assert "Evidence ID: `e1`" in md


def test_degraded_without_previous_views(tmp_path):
    db = _FakeDb([_evidence("e1", "2026-08-06T09:00:00+08:00", "CPI同比上涨0.5%")])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=[],
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert artifacts.previous_views == []
    assert any("previous_research_view" in m for m in artifacts.missing_data)
    assert any("不虚构" in m for m in artifacts.missing_data)


def test_weakened_signal_detected(tmp_path):
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
        task_id="t1", previous_run_ids=["run-morning"],
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert artifacts.interpretations[0]["verdict"] == "weakened"


def test_empty_day_is_not_no_change(tmp_path):
    db = _FakeDb([])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert any("不得" in u for u in artifacts.remaining_unknown)
    assert "未检索到 Evidence" in artifacts.markdown


# ---------- B2-1 future leakage ----------

def test_future_evidence_after_as_of_excluded(tmp_path):
    """19:59:59 included; 20:00:01 excluded; 23:00 excluded。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T19:59:59+08:00", "收盘前", ["macro:cpi"]),
        _evidence("e2", "2026-08-06T20:00:01+08:00", "刚过 as_of", ["macro:cpi"]),
        _evidence("e3", "2026-08-06T23:00:00+08:00", "深夜", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_cutoff="2026-08-05T20:00:00+08:00")
    titles = [ev["title"] for ev in artifacts.observed_facts]
    assert "收盘前" in titles
    assert "刚过 as_of" not in titles
    assert "深夜" not in titles


def test_historical_as_of_replay(tmp_path):
    """以更早的 as_of 重跑不应看到未来 Evidence。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "上午", ["macro:cpi"]),
        _evidence("e2", "2026-08-06T15:00:00+08:00", "下午", ["macro:cpi"]),
        _evidence("e3", "2026-08-06T18:00:00+08:00", "晚间", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T12:00:00+08:00",
        task_id="t1", previous_cutoff="2026-08-05T20:00:00+08:00")
    titles = [ev["title"] for ev in artifacts.observed_facts]
    assert "上午" in titles
    assert "下午" not in titles
    assert "晚间" not in titles


# ---------- B2-2 previous_cutoff ----------

def test_explicit_previous_cutoff_used(tmp_path):
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "新证据", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_cutoff="2026-08-06T09:00:00+08:00")
    assert artifacts.previous_cutoff == "2026-08-06T09:00:00+08:00"
    assert len(artifacts.new_evidence) == 1  # 晚于 09:00


def test_derived_prior_cutoff_from_run_metadata(tmp_path):
    """从 previous_run_ids 的 task.json 推导真实 cutoff。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "新证据", ["macro:cpi"]),
    ])
    _prev_run(tmp_path, "run-morning-1", [], task_json={
        "task_id": "task-morning",
        "scenario": "morning_brief",
        "as_of": "2026-08-06T08:00:00+08:00",
        "window_end": "2026-08-06T08:00:00+08:00",
    })
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning-1"])
    assert artifacts.previous_cutoff == "2026-08-06T08:00:00"
    assert len(artifacts.new_evidence) == 1  # 晚于 08:00


def test_unknown_prior_cutoff_degraded(tmp_path):
    """既无显式 cutoff 也无 run metadata → None（不可用），不伪造新增。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某证据", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=[])
    assert artifacts.previous_cutoff is None
    assert any("prior_cutoff_unavailable" in m for m in artifacts.missing_data)
    # new_evidence 为空（无 cutoff 不做伪精确分类）
    assert artifacts.new_evidence == []
    # observed_facts 仍可生成
    assert len(artifacts.observed_facts) == 1


def test_no_fabricated_new_evidence(tmp_path):
    """prior_cutoff 不可用时，不得标记任何'新增' Evidence。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某证据", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1")
    assert artifacts.new_evidence == []
    assert any("prior_cutoff_unavailable" in m for m in artifacts.missing_data)


def test_fact_view_interpretation_separation(tmp_path):
    """observed_fact != previous_research_view != updated_interpretation。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "CPI同比上涨0.5%", ["macro:cpi"]),
    ])
    claims = [{
        "claim_id": "c99", "claim_type": "FACT", "title": "CPI可能上涨0.5%",
        "object": {"entities": ["macro:cpi"]}, "evidence_ids": [],
    }]
    _prev_run(tmp_path, "run-morning", claims)
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"],
        previous_cutoff="2026-08-05T20:00:00+08:00")
    # observed_fact 是 Evidence 列表（事实）
    assert len(artifacts.observed_facts) == 1
    assert artifacts.observed_facts[0]["title"] == "CPI同比上涨0.5%"
    # previous_research_view 是 claims（非事实）
    assert len(artifacts.previous_views) == 1
    # updated_interpretation 是 verdict（非事实）
    assert artifacts.interpretations[0]["verdict"] in ("supported", "weakened", "unchanged", "unknown")


# ---------- B2-R2 finished_at exclusion ----------

def test_finished_at_not_used_as_prior_cutoff(tmp_path):
    """prior artifact 有 window_end=08:00 和 finished_at=08:15 → cutoff=08:00 而非 08:15。"""
    db = _FakeDb([
        _evidence("e-0805", "2026-08-06T08:05:00+08:00", "08:05 证据", ["macro:cpi"]),
    ])
    _prev_run(tmp_path, "run-morning", [], task_json={
        "task_id": "task-morning",
        "scenario": "morning_brief",
        "as_of": "2026-08-06T08:00:00+08:00",
        "window_end": "2026-08-06T08:00:00+08:00",
        "finished_at": "2026-08-06T08:15:00+08:00",
    })
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"])
    assert artifacts.previous_cutoff == "2026-08-06T08:00:00"
    # 08:05 在 cutoff 之后 → new_evidence
    assert len(artifacts.new_evidence) == 1
    assert artifacts.new_evidence[0]["title"] == "08:05 证据"


def test_window_end_preferred_over_finished_at(tmp_path):
    """window_end 优先于 finished_at。"""
    db = _FakeDb([])
    _prev_run(tmp_path, "run-morning", [], task_json={
        "task_id": "task-morning",
        "scenario": "morning_brief",
        "window_end": "2026-08-06T08:00:00+08:00",
        "finished_at": "2026-08-06T09:00:00+08:00",
    })
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"])
    assert artifacts.previous_cutoff == "2026-08-06T08:00:00"


def test_as_of_preferred_over_completion_timestamps(tmp_path):
    """as_of=08:00, finished_at=09:00 → cutoff=08:00 而非 09:00。"""
    db = _FakeDb([])
    _prev_run(tmp_path, "run-morning", [], task_json={
        "task_id": "task-morning",
        "scenario": "morning_brief",
        "as_of": "2026-08-06T08:00:00+08:00",
        "finished_at": "2026-08-06T09:00:00+08:00",
    })
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T20:00:00+08:00",
        task_id="t1", previous_run_ids=["run-morning"])
    assert artifacts.previous_cutoff == "2026-08-06T08:00:00"


def test_effective_end_in_time_window_metadata(tmp_path):
    """time_window.end 反映真实 effective_end，而非硬编码 23:59:59。"""
    db = _FakeDb([
        _evidence("e1", "2026-08-06T10:00:00+08:00", "上午", ["macro:cpi"]),
    ])
    artifacts = DailyReviewPipeline(tmp_path, db).run(
        date(2026, 8, 6), "2026-08-06T12:00:00+08:00",
        task_id="t1", previous_cutoff="2026-08-05T20:00:00+08:00")
    assert artifacts.effective_end.endswith("12:00:00+08:00") or "12:00:00" in artifacts.effective_end
    assert "T23:59:59" not in artifacts.markdown
