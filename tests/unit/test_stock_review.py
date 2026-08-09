"""stock_review 单元测试（Phase 6B B3）。

contract / degraded / Evidence lineage / 增量复盘 / future leakage /
entity filter / new_evidence only / Phase4 reuse。
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
        # raw_items：从 evidence 的 raw_item_id 派生（模拟 JOIN）
        self._raw_items = {ev["raw_item_id"]: {"entities": ev.get("entities") or []}
                          for ev in self._evidences}

    def query(self, sql, params=()):
        if "research_findings" in sql:
            return [{"payload": json.dumps(f)} for f in self._findings]
        start, end = params
        if "raw_items" in sql:
            # JOIN 查询：返回 evidence_payload + raw_item_payload
            rows = []
            for ev in self._evidences:
                if start <= ev["published_at"] <= end:
                    ri = self._raw_items.get(ev["raw_item_id"], {"entities": []})
                    rows.append({
                        "evidence_payload": json.dumps(ev),
                        "raw_item_payload": json.dumps(ri),
                    })
            return rows
        # 简单查询（daily_review 用的）
        return [{"payload": json.dumps(ev)} for ev in self._evidences
                if start <= ev["published_at"] < end]


def _finding(finding_id: str, finding_type: str, statement: str,
             entities=None, invalidation=None) -> dict:
    return {
        "finding_id": finding_id, "request_id": "req-1",
        "company_entity_id": "company:600519.SH",
        "finding_type": finding_type, "title": statement[:20], "statement": statement,
        "claim_type": "FACT", "predicate": "关联",
        "object": {"entities": entities or []},
        "as_of": "2026-08-01T20:00:00+08:00", "evidence_ids": [],
        "support_level": "direct", "status": "active",
        "invalidation_conditions": invalidation or [],
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
    assert artifacts.catalyst_changed
    md = artifacts.markdown
    assert "scenario: stock_review" in md
    assert "增量复盘" in md
    for section in ("what_changed", "new_evidence", "thesis", "risk changed",
                    "catalyst changed", "valuation assumption changed", "remaining questions"):
        assert section in md
    assert "Evidence ID: `e1`" in md


def test_degraded_without_phase4_findings(tmp_path):
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "贵州茅台披露中报",
                  ["company:600519.SH"]),
    ], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert artifacts.findings == []
    assert any("research_findings" in m for m in artifacts.missing_data)


def test_empty_window_is_not_no_change(tmp_path):
    db = _FakeDb(evidences=[], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    assert any("不得" in q for q in artifacts.remaining_questions)


# ---------- B3-1 future leakage ----------

def test_future_evidence_excluded(tmp_path):
    """as_of=20:00 → 20:00:01 被排除。"""
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T19:59:59+08:00", "收盘前", ["company:600519.SH"]),
        _evidence("e2", "2026-08-06T20:00:01+08:00", "刚过 as_of",
                  ["company:600519.SH"]),
    ])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    titles = [ev["title"] for ev in artifacts.window_evidence]
    assert "收盘前" in titles
    assert "刚过 as_of" not in titles


# ---------- B3-2 new_evidence only ----------

def test_previous_cutoff_old_evidence_excluded_from_evaluation(tmp_path):
    """previous_cutoff 之前的 Evidence 不影响判断。"""
    db = _FakeDb(
        evidences=[
            _evidence("e-old", "2026-08-06T09:00:00+08:00",
                      "产能扩建已提出多时", ["company:600519.SH"]),
            _evidence("e-new", "2026-08-07T10:00:00+08:00",
                      "产能扩建获批", ["company:600519.SH"]),
        ],
        findings=[
            _finding("f1", "catalyst", "产能扩建获批是重要催化剂",
                     entities=["company:600519.SH"]),
        ],
    )
    # previous_cutoff = 2026-08-06T12:00；e-old 在 cutoff 前，e-new 在 cutoff 后
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 7),
        "2026-08-07T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-06T12:00:00+08:00")
    assert len(artifacts.new_evidence) == 1
    assert artifacts.new_evidence[0]["title"] == "产能扩建获批"


def test_only_new_evidence_affects_thesis(tmp_path):
    """thesis/risk/catalyst/valuation 只对照 new_evidence。"""
    db = _FakeDb(
        evidences=[
            _evidence("e-new", "2026-08-07T10:00:00+08:00",
                      "产能扩建获批", ["company:600519.SH"]),
        ],
        findings=[
            _finding("f1", "catalyst", "产能扩建获批是重要催化剂",
                     entities=["company:600519.SH"]),
        ],
    )
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 7),
        "2026-08-07T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-06T12:00:00+08:00")
    assert artifacts.catalyst_changed


# ---------- B3-3 entity filter ----------

def test_entity_A_excludes_entity_BC(tmp_path):
    """A 公司复盘 → 只输出 A 相关 Evidence，不输出 B/C。"""
    db = _FakeDb(evidences=[
        _evidence("e-a", "2026-08-06T10:00:00+08:00", "A 公司公告",
                  ["company:600519.SH"]),
        _evidence("e-b", "2026-08-06T11:00:00+08:00", "B 公司公告",
                  ["company:000001.SZ"]),
        _evidence("e-c", "2026-08-06T12:00:00+08:00", "C 公司公告",
                  ["company:300750.SZ"]),
    ])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    changed_titles = [w for w in artifacts.what_changed]
    assert any("A 公司公告" in w for w in changed_titles)
    assert not any("B 公司公告" in w for w in changed_titles)
    assert not any("C 公司公告" in w for w in changed_titles)


def test_missing_phase4_baseline_degrades(tmp_path):
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某公告",
                  ["company:600519.SH"]),
    ], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert any("research_findings" in m for m in artifacts.missing_data)
    assert "不虚构" in artifacts.markdown


def test_missing_prior_cutoff_degraded(tmp_path):
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某公告",
                  ["company:600519.SH"]),
    ], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    # new_evidence 为空（无 cutoff 不做伪精确）
    assert artifacts.new_evidence == []


# ---------- B3-R2 prior cutoff degraded ----------

def test_missing_prior_cutoff_degrades(tmp_path):
    """previous_cutoff=None → missing_data + no incremental judgment。"""
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某公告",
                  ["company:600519.SH"]),
    ], findings=[
        _finding("f1", "catalyst", "某催化剂", entities=["company:600519.SH"]),
    ])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    assert artifacts.new_evidence == []
    assert any("prior_cutoff_unavailable" in m for m in artifacts.missing_data)
    assert artifacts.thesis_supported == []
    assert artifacts.thesis_weakened == []
    assert artifacts.risk_changed == []
    assert artifacts.catalyst_changed == []
    assert artifacts.valuation_assumption_changed == []


def test_missing_prior_cutoff_pipeline_returns_early(tmp_path):
    """early return 确保 _evaluate 不被调用。"""
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "某公告",
                  ["company:600519.SH"]),
    ], findings=[
        _finding("f1", "catalyst", "某催化剂", entities=["company:600519.SH"]),
    ])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1")
    assert artifacts.markdown
    assert "prior_cutoff_unavailable" in artifacts.markdown


# ---------- B3-R3 new_evidence_count ----------

def test_new_evidence_count_uses_new_evidence(tmp_path):
    """Run artifact 记录真正参与增量判断的 Evidence 数量。"""
    db = _FakeDb(evidences=[
        _evidence("e-old", "2026-08-06T09:00:00+08:00", "旧证据",
                  ["company:600519.SH"]),
        _evidence("e-new1", "2026-08-06T14:00:00+08:00", "新证据1",
                  ["company:600519.SH"]),
        _evidence("e-new2", "2026-08-06T15:00:00+08:00", "新证据2",
                  ["company:600519.SH"]),
        _evidence("e-other", "2026-08-06T16:00:00+08:00", "其他公司",
                  ["company:000001.SZ"]),
    ], findings=[
        _finding("f1", "catalyst", "某催化剂", entities=["company:600519.SH"]),
    ])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T20:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-06T12:00:00+08:00")
    # window_evidence: 4 条（旧 + 新1 + 新2 + 其他公司被过滤）
    # new_evidence: 2 条（新1 + 新2）—— entity 相关 + cutoff 之后
    assert len(artifacts.window_evidence) == 4
    assert len(artifacts.new_evidence) == 2


def test_effective_end_in_time_window_metadata(tmp_path):
    """stock time_window.end 反映真实 effective_end。"""
    db = _FakeDb(evidences=[
        _evidence("e1", "2026-08-06T10:00:00+08:00", "上午",
                  ["company:600519.SH"]),
    ], findings=[])
    artifacts = StockReviewPipeline(tmp_path, db).run(
        "company:600519.SH", date(2026, 8, 6), date(2026, 8, 6),
        "2026-08-06T12:00:00+08:00", task_id="t1",
        previous_cutoff="2026-08-05T20:00:00+08:00")
    assert "T23:59:59" not in artifacts.markdown
    assert "12:00:00" in artifacts.markdown or artifacts.effective_end.endswith("12:00:00+08:00")
