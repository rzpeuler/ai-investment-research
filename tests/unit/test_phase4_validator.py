"""Phase 4 Validator 测试（任务书 3.25 Validator 负例节，Commit 16）。

覆盖：禁止词拦截（目标价/评级/仓位/上涨空间）；FACT 无 Evidence；MODEL_INFERENCE
无调用；UNKNOWN 否定；管理层自述强结论；未来信息污染；同行截止时间；情景预测为 FACT；
Phase 3 改写；dry-run 副作用；幂等重复；error vs warning 分级。
"""
from __future__ import annotations

from research_os.equity_research.validator import (
    ValidationOutcome,
    validate_equity_research,
)


def _finding(**overrides):
    base = dict(
        finding_id="f-1", claim_type="FACT", statement="营业收入增长",
        evidence_ids=["ev-1"], model_route={"llm_called": False},
        invalidation_conditions=[], finding_type="fact_summary",
        as_of="2026-08-01T00:00:00",
    )
    base.update(overrides)
    return base


class TestForbiddenOutput:
    def test_target_price_fails(self):
        out = validate_equity_research(report_text="我们预测目标价 100 元")
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-063" for i in out.errors)

    def test_buy_rating_fails(self):
        out = validate_equity_research(report_text="建议买入该股票")
        assert out.status == "fail"

    def test_upside_fails(self):
        out = validate_equity_research(report_text="上行空间 50%")
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-063" for i in out.errors)

    def test_clean_report_passes(self):
        out = validate_equity_research(report_text="营业收入同比增长 10%。")
        assert out.status == "pass"

    def test_disclaimer_not_false_positive(self):
        """免责声明固定文案（含"目标价"字样）不误伤。"""
        disclaimer = "本报告由 AI＋A 股投研系统自动生成，仅供研究参考，不构成投资建议。不提供目标价、买卖评级、仓位建议或任何交易建议。"
        out = validate_equity_research(report_text=disclaimer)
        assert out.status in ("pass", "pass_with_warnings")


class TestClaimRules:
    def test_fact_without_evidence_fails(self):
        out = validate_equity_research(findings=[_finding(evidence_ids=[])])
        assert any(i.rule_id == "ERV-041" for i in out.errors)

    def test_model_inference_without_call_fails(self):
        out = validate_equity_research(findings=[
            _finding(claim_type="MODEL_INFERENCE", model_route={"llm_called": False}),
        ])
        assert any(i.rule_id == "ERV-044" for i in out.errors)

    def test_model_inference_with_call_passes(self):
        out = validate_equity_research(findings=[
            _finding(claim_type="MODEL_INFERENCE", model_route={"llm_called": True}),
        ])
        assert not any(i.rule_id == "ERV-044" for i in out.issues)

    def test_hypothesis_without_failure_condition_fails(self):
        """ERV-046 硬约束：HYPOTHESIS 缺失效条件 → error（任务书要求，独立验收指出 warning 不足）。"""
        out = validate_equity_research(findings=[_finding(claim_type="HYPOTHESIS", invalidation_conditions=[])])
        assert any(i.rule_id == "ERV-046" for i in out.errors)
        assert out.status == "fail"

    def test_unknown_written_as_negative_fails(self):
        out = validate_equity_research(findings=[
            _finding(claim_type="UNKNOWN", statement="没有发生任何事件"),
        ])
        assert any(i.rule_id == "ERV-048" for i in out.errors)


class TestFinancialRules:
    def test_missing_written_as_zero_fails(self):
        out = validate_equity_research(facts=[
            {"fact_id": "fa-1", "value_status": "missing", "raw_value": "0"},
        ])
        assert any(i.rule_id == "ERV-013" for i in out.errors)

    def test_derived_written_as_reported_fails(self):
        out = validate_equity_research(facts=[
            {"fact_id": "fa-2", "value_status": "reported", "period_basis": "single_quarter"},
        ])
        assert any(i.rule_id == "ERV-016" for i in out.errors)


class TestPeerAndValuation:
    def test_peer_cutoff_after_asof_fails(self):
        out = validate_equity_research(
            peers=[{"peer_candidate_id": "p-1", "information_cutoff": "2026-09-01T00:00:00"}],
            as_of="2026-08-01T00:00:00",
        )
        assert any(i.rule_id == "ERV-028" for i in out.errors)


class TestManagementBoundary:
    def test_management_only_supported_fails(self):
        out = validate_equity_research(factors=[
            {"factor_id": "cf-1", "management_only": True, "status": "supported"},
        ])
        assert any(i.rule_id == "ERV-049" for i in out.errors)

    def test_management_only_weakly_supported_ok(self):
        out = validate_equity_research(factors=[
            {"factor_id": "cf-2", "management_only": True, "status": "weakly_supported"},
        ])
        assert not any(i.rule_id == "ERV-049" for i in out.issues)


class TestTimeAndReuse:
    def test_future_info_fails(self):
        out = validate_equity_research(
            findings=[_finding(as_of="2026-10-01T00:00:00")],
            as_of="2026-08-01T00:00:00",
        )
        assert any(i.rule_id == "ERV-053" for i in out.errors)

    def test_phase3_rewrite_fails(self):
        out = validate_equity_research(
            phase3_objects=[{"attribution_result_id": "attr-1", "attribution_status": "EXPLAINED"}],
            phase3_expected={"attr-1": "UNEXPLAINED_MOVE"},
        )
        assert any(i.rule_id == "ERV-055" for i in out.errors)

    def test_phase3_preserved_passes(self):
        out = validate_equity_research(
            phase3_objects=[{"attribution_result_id": "attr-1", "attribution_status": "UNEXPLAINED_MOVE"}],
            phase3_expected={"attr-1": "UNEXPLAINED_MOVE"},
        )
        assert not any(i.rule_id == "ERV-055" for i in out.issues)


class TestForecastAndDryRun:
    def test_scenario_fact_fails(self):
        out = validate_equity_research(scenarios=[
            {"scenario_id": "sc-1", "assumptions": [{"claim_type": "FACT"}]},
        ])
        assert any(i.rule_id == "ERV-062" for i in out.errors)

    def test_dry_run_with_artifacts_fails(self):
        out = validate_equity_research(dry_run=True, artifact_paths=["reports/x.md"])
        assert any(i.rule_id == "ERV-069" for i in out.errors)

    def test_dry_run_clean_passes(self):
        out = validate_equity_research(dry_run=True, artifact_paths=[])
        assert not any(i.rule_id == "ERV-069" for i in out.issues)


class TestSeverity:
    def test_error_blocks_pass(self):
        out = validate_equity_research(report_text="目标价 100 元")
        assert out.status == "fail"

    def test_warning_allows_pass_with_warnings(self):
        """warning（非 error）允许 pass_with_warnings：外币事实无汇率证据。"""
        out = validate_equity_research(facts=[
            {"fact_id": "fa-w", "fact_key": "k", "taxonomy_code": "revenue",
             "company_entity_id": "company:1", "period_end": "2025-12-31",
             "statement_scope": "consolidated", "currency": "USD",
             "unit_scale": 1, "raw_value": "100", "normalized_value": "100",
             "period_start": "2025-01-01", "instant_or_duration": "duration",
             "period_basis": "reported_period", "value_status": "reported",
             "sign_convention": "reported", "audit_status": "unknown",
             "source_priority": 5, "restatement_version": 1,
             "evidence_ids": [], "source_block_ids": [], "warnings": [],
             "valid_from": "2026-08-06T00:00:00", "valid_to": None,
             "version": 1, "created_at": "2026-08-06T00:00:00", "label_raw": "收入",
             "normalized_unit": "USD", "statement_type": "income_statement",
             "financial_report_id": "r1", "segment_id": None,
             "source_document_id": None, "conflict_group_id": None},
        ])
        assert any(i.rule_id == "ERV-010" for i in out.warnings)
        assert out.status == "pass_with_warnings"

    def test_outcome_helpers(self):
        out = ValidationOutcome("fail", issues=[])
        assert out.errors == [] and out.warnings == []
