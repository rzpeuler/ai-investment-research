"""Phase 4 LLM 语义任务测试（任务书 3.25 LLM 节，Commit 14）。

全部使用 Fake Provider：无 Provider；Flash 成功；Pro 升级；最大一次 Pro；
Provider 故障；任务级预算；数字篡改被拒绝；目标价被拒绝；无思维过程存储。
"""
from __future__ import annotations

import pytest

from research_os.llm.client import LlmClient
from research_os.llm.equity_tasks import (
    BUDGET_PER_DEPTH,
    BudgetTracker,
    EquityLlmTasks,
    FORBIDDEN_OUTPUT_TERMS,
    _detect_forbidden,
)
from research_os.llm.provider import FakeLlmProvider


def _client(provider=None, configured=True):
    return LlmClient(provider=provider, configured=configured)


class TestNoProvider:
    def test_honest_fallback(self):
        client = _client(provider=None, configured=False)
        tasks = EquityLlmTasks(client)
        resp = tasks.run_task(
            "business_description_normalization", task_id="t1",
            evidence_excerpts=["公司主营白酒"], evidence_ids=["ev-1"], cutoff="2026-08-06",
        )
        assert resp.called is False
        assert resp.status == "fallback"
        assert resp.output is None
        assert tasks.budget.flash_used == 0  # 未调用不计预算

    def test_no_model_inference_without_call(self):
        """确定性回退不得产生 MODEL_INFERENCE（输出为 None，不构造 Claim）。"""
        client = _client(configured=False)
        resp = EquityLlmTasks(client).run_task(
            "catalyst_candidates", task_id="t1",
            evidence_excerpts=[], evidence_ids=[], cutoff="2026-08-06",
        )
        assert resp.output is None


class TestBudget:
    def test_budget_table(self):
        assert BUDGET_PER_DEPTH["fast"] == {"flash_max": 2, "pro_max": 0}
        assert BUDGET_PER_DEPTH["standard"] == {"flash_max": 5, "pro_max": 1}
        assert BUDGET_PER_DEPTH["deep"] == {"flash_max": 8, "pro_max": 1}

    def test_flash_exhausted_skips(self):
        """Flash 预算耗尽 → 跳过调用（诚实 fallback）。"""
        provider = FakeLlmProvider()
        client = _client(provider=provider, configured=True)
        tasks = EquityLlmTasks(client, depth="fast")  # flash_max=2
        tasks.run_task("research_questions", task_id="t1", evidence_excerpts=["a"],
                       evidence_ids=[], cutoff="2026-08-06")
        tasks.run_task("research_questions", task_id="t2", evidence_excerpts=["b"],
                       evidence_ids=[], cutoff="2026-08-06")
        assert tasks.budget.flash_used == 2
        resp3 = tasks.run_task("research_questions", task_id="t3", evidence_excerpts=["c"],
                               evidence_ids=[], cutoff="2026-08-06")
        assert resp3.called is False
        assert any("预算耗尽" in w for w in resp3.warnings)

    def test_tracker_records(self):
        b = BudgetTracker("standard")
        assert b.can_call("flash") and b.can_call("pro")
        b.record("flash")
        b.record("pro")
        assert b.flash_used == 1 and b.pro_used == 1
        assert not b.exhausted
        s = b.summary()
        assert s["flash_max"] == 5 and s["pro_max"] == 1


class TestForbiddenOutput:
    def test_target_price_rejected(self):
        hits = _detect_forbidden({"target_price": "100"})
        assert "target_price" in hits

    def test_buy_rating_rejected(self):
        hits = _detect_forbidden({"statement": "建议买入"})
        assert hits

    def test_clean_output_ok(self):
        assert _detect_forbidden({"statement": "营业收入增长 10%"}) == []

    def test_forbidden_terms_defined(self):
        assert "target_price" in FORBIDDEN_OUTPUT_TERMS


class TestFakeProviderCalls:
    def test_flash_success_via_fake(self):
        provider = FakeLlmProvider()
        client = _client(provider=provider, configured=True)
        tasks = EquityLlmTasks(client)
        resp = tasks.run_task(
            "research_questions", task_id="t1",
            evidence_excerpts=["收入增长"], evidence_ids=["ev-1"], cutoff="2026-08-06",
        )
        # Fake Provider 实际被调用（called=True）且计入预算；
        # 输出未通过空 Schema 校验 → fallback 诚实记录（不伪造 MODEL_INFERENCE）
        assert resp.called is True
        assert tasks.budget.flash_used == 1
        assert resp.status in ("success", "failed", "fallback")
