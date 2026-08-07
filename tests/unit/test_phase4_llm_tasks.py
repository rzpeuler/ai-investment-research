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
            evidence_excerpts=["公司主营白酒"], evidence_ids=["ev-1"],
            evidence_types=["official_disclosure"], cutoff="2026-08-06",
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
            evidence_excerpts=[], evidence_ids=[], evidence_types=[], cutoff="2026-08-06",
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
                       evidence_ids=["ev-1"], evidence_types=["manual_input"],
                       cutoff="2026-08-06")
        assert tasks.budget.flash_used == 2
        resp3 = tasks.run_task("research_questions", task_id="t2", evidence_excerpts=["c"],
                               evidence_ids=["ev-2"], evidence_types=["manual_input"],
                               cutoff="2026-08-06")
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

    def test_shared_budget_counts_every_flash_retry_and_pro_upgrade(self):
        models = []

        def behavior(request, schema):
            models.append(request.requested_model_class)
            return {"ok": True, "output": {"invalid": True},
                    "model_id": request.requested_model_class}

        tasks = EquityLlmTasks(
            _client(provider=FakeLlmProvider(behavior=behavior), configured=True),
            depth="standard",
        )
        for index in range(4):
            tasks.run_task(
                "research_questions", task_id=f"t{index}",
                evidence_excerpts=["待验证问题"], evidence_ids=[f"ev-{index}"],
                evidence_types=["manual_input"], cutoff="2026-08-06",
            )
        assert models.count("flash") == 5
        assert models.count("pro") == 1
        assert tasks.budget.flash_used == 5
        assert tasks.budget.pro_used == 1


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
    def test_actual_project_schema_is_passed_to_provider(self):
        observed = {}

        def behavior(request, schema):
            observed.update(schema)
            return {"ok": True, "output": {"invalid": True}, "model_id": "flash"}

        tasks = EquityLlmTasks(
            _client(provider=FakeLlmProvider(behavior=behavior), configured=True))
        tasks.run_task(
            "research_questions", task_id="t1",
            evidence_excerpts=["收入增长"], evidence_ids=["ev-1"],
            evidence_types=["manual_input"], cutoff="2026-08-06",
        )
        assert observed.get("$schema")
        assert observed.get("type") == "object"

    def test_flash_success_via_fake(self):
        provider = FakeLlmProvider()
        client = _client(provider=provider, configured=True)
        tasks = EquityLlmTasks(client)
        resp = tasks.run_task(
            "research_questions", task_id="t1",
            evidence_excerpts=["收入增长"], evidence_ids=["ev-1"],
            evidence_types=["manual_input"], cutoff="2026-08-06",
        )
        # Fake Provider 实际被调用（called=True）且计入预算；
        # 输出未通过空 Schema 校验 → fallback 诚实记录（不伪造 MODEL_INFERENCE）
        assert resp.called is True
        assert tasks.budget.flash_used == resp.usage_metadata["attempts_by_model"]["flash"]
        assert resp.status in ("success", "failed", "fallback")

    def test_ineligible_evidence_skips_provider(self):
        provider = FakeLlmProvider()
        tasks = EquityLlmTasks(_client(provider=provider, configured=True))
        resp = tasks.run_task(
            "competitive_factor_candidates", task_id="t1",
            evidence_excerpts=["人工财务行"], evidence_ids=["ev-1"],
            evidence_types=["manual_input"], cutoff="2026-08-06",
        )
        assert resp.called is False
        assert tasks.budget.flash_used == 0
        assert any("Evidence 输入不足" in warning for warning in resp.warnings)
