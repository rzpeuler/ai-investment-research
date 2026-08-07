"""Phase 4 Validator 测试（任务书 3.25 Validator 负例节，Commit 16）。

覆盖：禁止词拦截（目标价/评级/仓位/上涨空间）；FACT 无 Evidence；MODEL_INFERENCE
无调用；UNKNOWN 否定；管理层自述强结论；未来信息污染；同行截止时间；情景预测为 FACT；
Phase 3 改写；dry-run 副作用；幂等重复；error vs warning 分级。
"""
from __future__ import annotations

from copy import deepcopy

import pytest

from research_os.equity_research.validator import (
    ValidationOutcome,
    validate_equity_research,
)
from research_os.financials.metrics import compute_period_metrics
from research_os.financials.metrics import normalize_metric_decimal


def _finding(**overrides):
    base = dict(
        finding_id="f-1", claim_type="FACT", statement="营业收入增长",
        evidence_ids=["ev-1"], model_route={"llm_called": False},
        invalidation_conditions=[], finding_type="fact_summary",
        as_of="2026-08-01T00:00:00",
    )
    base.update(overrides)
    return base


def _formula_facts():
    values = {
        "revenue": ("80", "100"), "net_profit_attr": ("15", "20"),
        "deducted_net_profit": ("12", "18"), "cost_of_sales": ("50", "60"),
        "operating_profit": ("20", "25"), "net_profit": ("16", "22"),
        "equity_attr": ("80", "100"), "total_assets": ("180", "200"),
        "ebit": ("24", "30"), "income_tax_rate": ("0.25", "0.25"),
        "interest_bearing_debt": ("45", "50"), "cash_and_equivalents": ("18", "20"),
        "total_liabilities": ("70", "80"), "current_assets": ("90", "100"),
        "current_liabilities": ("45", "50"), "inventory": ("16", "20"),
        "other_illiquid_assets": ("4", "5"), "accounts_receivable": ("10", "20"),
        "operating_cash_flow": ("20", "25"), "capex_paid": ("4", "5"),
        "rd_expense": ("2", "3"), "selling_expense": ("3", "4"),
        "admin_expense": ("4", "5"), "weighted_avg_shares": ("9", "10"),
        "period_end_shares": ("9", "10"),
    }
    facts = []
    balance_codes = {
        "equity_attr", "total_assets", "interest_bearing_debt", "cash_and_equivalents",
        "total_liabilities", "current_assets", "current_liabilities", "inventory",
        "other_illiquid_assets", "accounts_receivable", "period_end_shares",
    }
    cash_codes = {"operating_cash_flow", "capex_paid"}
    for taxonomy, (prior, current) in values.items():
        for year, value in ((2024, prior), (2025, current)):
            statement_type = ("balance_sheet" if taxonomy in balance_codes else
                              "cash_flow" if taxonomy in cash_codes else "income_statement")
            facts.append({
                "fact_id": f"{taxonomy}-{year}", "fact_key": f"{taxonomy}|{year}|FY|consolidated",
                "financial_report_id": f"report-{year}", "company_entity_id": "company:600519.SH",
                "statement_type": statement_type, "taxonomy_code": taxonomy, "label_raw": taxonomy,
                "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
                "instant_or_duration": "instant" if statement_type == "balance_sheet" else "duration",
                "period_basis": "reported_period", "statement_scope": "consolidated",
                "currency": "CNY", "unit_scale": 1, "raw_value": value,
                "normalized_value": value, "normalized_unit": "yuan", "value_status": "reported",
                "sign_convention": "reported", "audit_status": "audited", "segment_id": None,
                "source_document_id": None, "source_block_ids": [], "evidence_ids": [],
                "source_priority": 1, "restatement_version": 1,
                "valid_from": f"{year + 1}-04-01T00:00:00", "valid_to": None,
                "conflict_group_id": None, "warnings": [], "version": 1,
                "created_at": f"{year + 1}-04-01T00:00:00",
            })
    return facts


def _formula_reports():
    return [{
        "financial_report_id": f"report-{year}", "company_entity_id": "company:600519.SH",
        "document_id": None, "manifest_id": None, "report_type": "annual",
        "period_start": f"{year}-01-01", "period_end": f"{year}-12-31",
        "fiscal_year": year, "fiscal_period": "FY", "duration_months": 12,
        "statement_scope": "consolidated", "accounting_standard": "CAS",
        "currency": "CNY", "unit_scale": 1, "audit_status": "audited",
        "audit_opinion": "unmodified", "restatement_status": "original",
        "supersedes_report_id": None, "filing_version": "v1", "source_ids": [],
        "evidence_ids": [], "data_status": "complete", "version": 1,
        "published_at": f"{year + 1}-04-01T00:00:00", "created_at": f"{year + 1}-04-01T00:00:00",
    } for year in (2024, 2025)]


def _validate_metric(metric, facts=None, reports=None):
    return validate_equity_research(
        metrics=[metric], facts=facts or _formula_facts(), reports=reports or _formula_reports(),
    )


def _valid_metrics():
    return [m.model_dump() for m in compute_period_metrics(
        "company:600519.SH", _formula_facts(), "2025-12-31") if m.status == "valid"]


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

    def test_supported_inference_is_not_misclassified_as_unknown(self):
        out = validate_equity_research(findings=[
            _finding(
                claim_type="MODEL_INFERENCE",
                statement="现有证据没有显示该风险影响已发生",
                model_route={"llm_called": True},
            ),
        ])
        assert not any(i.rule_id == "ERV-048" for i in out.issues)


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


class TestDeterministicMetricRecompute:
    def test_roe_normal_recompute(self):
        roe = next(m for m in _valid_metrics() if m["metric_code"] == "roe")
        out = _validate_metric(roe)
        assert not any(i.rule_id == "ERV-019" for i in out.errors)

    def test_roe_value_tamper_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        roe["value"] = "999"
        out = _validate_metric(roe)
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_gross_margin_plus_1e_minus_9_fails(self):
        metric = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "gross_margin"))
        from decimal import Decimal
        metric["value"] = str(Decimal(metric["value"]) + Decimal("1E-9"))
        out = _validate_metric(metric)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    @pytest.mark.parametrize("delta", ["0.000000001", "-0.000000001", "0.00000001"])
    def test_roe_sub_precision_tamper_fails(self, delta):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        from decimal import Decimal
        roe["value"] = str(Decimal(roe["value"]) + Decimal(delta))
        out = _validate_metric(roe)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_decimal_canonical_equivalences(self):
        assert normalize_metric_decimal("1.2300", 8, None) == "1.23"
        assert normalize_metric_decimal("1.23E+0", 8, None) == "1.23"
        assert normalize_metric_decimal("-0.000", 8, None) == "0"

    def test_scientific_notation_is_validator_equivalent(self):
        from research_os.equity_research.metric_display import (
            FINANCIAL_METRIC_DISPLAY,
            render_metric_line,
        )

        metric = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "gross_margin"))
        metric["value"] = "4E-1"
        report = "## 11. 利润与利润率\n" + render_metric_line(
            metric, FINANCIAL_METRIC_DISPLAY["gross_margin"], metric["metric_id"],
        )
        out = validate_equity_research(
            metrics=[metric], facts=_formula_facts(), reports=_formula_reports(),
            report_text=report,
        )
        assert out.status == "pass"

    def test_trailing_zeros_are_validator_equivalent(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        roe["value"] += "000"
        assert not any(i.rule_id == "ERV-019" for i in _validate_metric(roe).errors)

    def test_negative_zero_is_validator_equivalent_to_zero(self):
        facts = deepcopy(_formula_facts())
        cogs = next(f for f in facts if f["fact_id"] == "cost_of_sales-2025")
        cogs["raw_value"] = cogs["normalized_value"] = "100"
        metric = next(m.model_dump() for m in compute_period_metrics(
            "company:600519.SH", facts, "2025-12-31") if m.metric_code == "gross_margin")
        metric["value"] = "-0"
        assert not any(i.rule_id == "ERV-019" for i in _validate_metric(metric, facts=facts).errors)

    @pytest.mark.parametrize("field,value", [
        ("company_entity_id", "company:000001.SZ"),
        ("statement_scope", "parent"),
        ("financial_report_id", "report-2024"),
        ("currency", "USD"),
        ("unit_scale", 10000),
        ("statement_type", "cash_flow"),
        ("period_start", "2025-02-01"),
    ])
    def test_binding_identity_tamper_fails(self, field, value):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        roe["input_bindings"][0][field] = value
        out = _validate_metric(roe)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_fact_and_binding_statement_type_tamper_fails(self):
        """攻击者同步改写事实和 binding 时，公式参数契约仍须独立拒绝。"""
        from research_os.equity_research.metric_display import (
            FINANCIAL_METRIC_DISPLAY,
            render_metric_line,
        )

        metric = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "gross_margin"))
        facts = deepcopy(_formula_facts())
        revenue = next(f for f in facts if f["fact_id"] == "revenue-2025")
        revenue["statement_type"] = "cash_flow"
        binding = next(b for b in metric["input_bindings"] if b["parameter"] == "revenue")
        binding["statement_type"] = "cash_flow"
        report = "## 11. 利润与利润率\n" + render_metric_line(
            metric, FINANCIAL_METRIC_DISPLAY["gross_margin"], metric["metric_id"],
        )
        out = validate_equity_research(
            metrics=[metric], facts=facts, reports=_formula_reports(), report_text=report,
        )
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" and "statement_type" in i.message for i in out.errors)

    def test_fact_company_substitution_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        facts = deepcopy(_formula_facts())
        fact_id = roe["input_bindings"][0]["fact_id"]
        fact = next(f for f in facts if f["fact_id"] == fact_id)
        fact["company_entity_id"] = "company:000001.SZ"
        roe["input_bindings"][0]["company_entity_id"] = "company:000001.SZ"
        out = _validate_metric(roe, facts=facts)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_report_identity_substitution_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        reports = deepcopy(_formula_reports())
        reports[-1]["statement_scope"] = "parent"
        out = _validate_metric(roe, reports=reports)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_bound_report_missing_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        out = _validate_metric(roe, reports=[r for r in _formula_reports()
                                             if r["financial_report_id"] != "report-2025"])
        assert any(i.rule_id == "ERV-019" and "报告不存在" in i.message for i in out.errors)

    def test_start_end_scope_mismatch_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        facts = deepcopy(_formula_facts())
        start_fact = next(f for f in facts if f["fact_id"] == "equity_attr-2024")
        start_fact["statement_scope"] = "parent"
        start_binding = next(b for b in roe["input_bindings"] if b["parameter"] == "equity_start")
        start_binding["statement_scope"] = "parent"
        reports = deepcopy(_formula_reports())
        reports[0]["statement_scope"] = "parent"
        out = _validate_metric(roe, facts=facts, reports=reports)
        assert any(i.rule_id == "ERV-019" and "statement_scope" in i.message for i in out.errors)

    def test_consolidated_revenue_replaced_by_parent_fails_even_when_value_synced(self):
        metric = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "gross_margin"))
        facts = deepcopy(_formula_facts())
        parent = deepcopy(next(f for f in facts if f["fact_id"] == "revenue-2025"))
        parent.update(fact_id="parent-revenue-2025", financial_report_id="report-parent-2025",
                      statement_scope="parent", raw_value="50", normalized_value="50")
        facts.append(parent)
        reports = deepcopy(_formula_reports())
        parent_report = deepcopy(reports[-1])
        parent_report.update(financial_report_id="report-parent-2025", statement_scope="parent")
        reports.append(parent_report)
        binding = next(b for b in metric["input_bindings"] if b["parameter"] == "revenue")
        for field in ("fact_id", "company_entity_id", "financial_report_id", "taxonomy_code",
                      "statement_scope", "statement_type", "period_start", "period_end",
                      "currency", "unit_scale"):
            binding[field] = parent[field]
        metric["input_fact_ids"] = [b["fact_id"] for b in metric["input_bindings"]]
        metric["value"] = "-0.2"
        out = _validate_metric(metric, facts=facts, reports=reports)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    def test_legal_restatement_priority_passes_and_old_version_swap_fails(self):
        facts = deepcopy(_formula_facts())
        original = next(f for f in facts if f["fact_id"] == "net_profit_attr-2025")
        restated = deepcopy(original)
        restated.update(fact_id="net_profit_attr-2025-r2", financial_report_id="report-2025-r2",
                        raw_value="30", normalized_value="30", restatement_version=2)
        facts.append(restated)
        reports = deepcopy(_formula_reports())
        restated_report = deepcopy(reports[-1])
        restated_report.update(financial_report_id="report-2025-r2", restatement_status="restated",
                               supersedes_report_id="report-2025", filing_version="v2")
        reports.append(restated_report)
        roe = next(m.model_dump() for m in compute_period_metrics(
            "company:600519.SH", facts, "2025-12-31", reports=reports) if m.metric_code == "roe")
        valid = _validate_metric(roe, facts=facts, reports=reports)
        assert not any(i.rule_id == "ERV-019" for i in valid.errors)

        old = deepcopy(roe)
        binding = next(b for b in old["input_bindings"] if b["parameter"] == "net_profit_attr")
        for field in ("fact_id", "company_entity_id", "financial_report_id", "taxonomy_code",
                      "statement_scope", "statement_type", "period_start", "period_end",
                      "currency", "unit_scale"):
            binding[field] = original[field]
        old["input_fact_ids"] = [b["fact_id"] for b in old["input_bindings"]]
        old["value"] = "0.2222222222222222222222222222"
        out = _validate_metric(old, facts=facts, reports=reports)
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-019" and "优先事实版本" in i.message for i in out.errors)

    def test_roe_start_end_swap_fails(self):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        start = next(b for b in roe["input_bindings"] if b["parameter"] == "equity_start")
        end = next(b for b in roe["input_bindings"] if b["parameter"] == "equity_end")
        start["fact_id"], end["fact_id"] = end["fact_id"], start["fact_id"]
        start["period_end"], end["period_end"] = end["period_end"], start["period_end"]
        out = _validate_metric(roe)
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    @pytest.mark.parametrize("mutation", ["delete", "missing_fact", "taxonomy", "formula_version"])
    def test_roe_binding_and_formula_tamper_fails(self, mutation):
        roe = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "roe"))
        if mutation == "delete":
            roe["input_bindings"] = [b for b in roe["input_bindings"] if b["parameter"] != "equity_start"]
            roe["input_fact_ids"] = [b["fact_id"] for b in roe["input_bindings"]]
        elif mutation == "missing_fact":
            roe["input_bindings"][0]["fact_id"] = "does-not-exist"
            roe["input_fact_ids"] = [b["fact_id"] for b in roe["input_bindings"]]
        elif mutation == "taxonomy":
            roe["input_bindings"][0]["taxonomy_code"] = "revenue"
        else:
            roe["formula_version"] = "999.0.0"
        out = _validate_metric(roe)
        assert any(i.rule_id == "ERV-019" for i in out.errors)

    @pytest.mark.parametrize("metric", _valid_metrics(), ids=lambda m: m["metric_code"])
    def test_every_valid_supported_metric_value_tamper_fails(self, metric):
        tampered = deepcopy(metric)
        from decimal import Decimal
        tampered["value"] = str(Decimal(tampered["value"]) + Decimal("0.000000001"))
        out = _validate_metric(tampered)
        assert any(i.rule_id == "ERV-019" for i in out.errors), metric["metric_code"]

    @pytest.mark.parametrize("code", [
        "roa", "gross_margin", "debt_to_assets", "receivable_turnover",
        "inventory_turnover", "roic", "eps", "bvps", "cfo_per_share",
    ])
    def test_required_formula_families_are_valid_and_recomputable(self, code):
        metric = next(m for m in _valid_metrics() if m["metric_code"] == code)
        out = _validate_metric(metric)
        assert not any(i.rule_id == "ERV-019" for i in out.errors)

    def test_input_fact_id_order_does_not_affect_recompute(self):
        metric = deepcopy(next(m for m in _valid_metrics() if m["metric_code"] == "gross_margin"))
        metric["input_fact_ids"].reverse()
        out = _validate_metric(metric)
        assert not any(i.rule_id == "ERV-019" for i in out.errors)


class TestPeerAndValuation:
    def test_peer_cutoff_after_asof_fails(self):
        out = validate_equity_research(
            peers=[{"peer_candidate_id": "p-1", "information_cutoff": "2026-09-01T00:00:00"}],
            as_of="2026-08-01T00:00:00",
        )
        assert any(i.rule_id == "ERV-028" for i in out.errors)


class TestMarkdownMetricGrammar:
    def test_ordinary_numbers_headings_and_disclaimer_do_not_false_positive(self):
        report = """## 11. 盈利能力
- 报告期为 2025-12-31，样本年份 2024 年。
- 数据不足，暂不形成正式指标。
## 38. 免责声明
- 本报告仅供研究参考，不构成投资建议。
"""
        out = validate_equity_research(report_text=report)
        assert not any(i.rule_id in {"ERV-059", "ERV-060", "ERV-061"} for i in out.errors)

    def test_unmarked_formal_alias_fails(self):
        out = validate_equity_research(report_text="## 11. 盈利能力\n- 综合毛利率：99.99%\n")
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-060" for i in out.errors)


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

    def test_processing_created_at_after_historical_as_of_is_allowed(self):
        out = validate_equity_research(
            blocks=[{
                "block_id": "block-review", "page_start": 1,
                "content_hash": "a" * 64,
                "created_at": "2026-08-07T10:00:00+08:00",
            }],
            as_of="2026-08-07T00:00:00+08:00",
        )
        assert not any(i.rule_id == "ERV-053" for i in out.errors)

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


class TestEvidenceLineageAndCompletion:
    EID = "11111111-1111-4111-8111-111111111111"
    RID = "22222222-2222-4222-8222-222222222222"

    @classmethod
    def raw_item(cls, **overrides):
        item = {
            "raw_item_id": cls.RID, "source_id": "manual_financial_import",
            "external_id": "fact-1", "url": "manual://financial/m1/fact-1",
            "title": "财务导入：营业收入", "publisher": "financial.csv", "author": None,
            "published_at": "2026-04-30T00:00:00", "retrieved_at": "2026-08-01T00:00:00",
            "content_hash": "a" * 64,
            "content_excerpt": (
                "manifest=m1；checksum=abc；locator=row:2；source_kind=manual_import；"
                "parser_version=v1；imported_at=2026-08-01T00:00:00；is_statutory_original=false"
            ),
            "content_storage": "metadata_and_excerpt", "language": "zh-CN",
            "access_status": "ok", "entities": ["company:600519.SH"],
            "raw_category": "financial_fact_import",
        }
        item.update(overrides)
        return item

    @classmethod
    def evidence(cls, **overrides):
        evidence = {
            "evidence_id": cls.EID, "source_id": "manual_financial_import",
            "raw_item_id": cls.RID, "title": "营业收入", "publisher": "financial.csv",
            "published_at": "2026-04-30T00:00:00", "retrieved_at": "2026-08-01T00:00:00",
            "url": "manual://financial/m1/fact-1", "excerpt": "营业收入=100",
            "evidence_type": "manual_input", "independence_group": "fact:1",
            "source_tier": "C", "access_status": "ok",
        }
        evidence.update(overrides)
        return evidence

    def test_manual_financial_evidence_requires_original_locator(self):
        raw = self.raw_item(content_excerpt="只有人工数值")
        out = validate_equity_research(evidences=[self.evidence()], raw_items=[raw])
        assert any(issue.rule_id == "ERV-079" for issue in out.errors)

    def test_derived_event_cannot_forge_official_source(self):
        forged = self.evidence(source_id="morning_brief_events", evidence_type="official_disclosure")
        raw = self.raw_item(source_id="morning_brief_events")
        out = validate_equity_research(evidences=[forged], raw_items=[raw])
        assert any(issue.rule_id == "ERV-072" for issue in out.errors)

    def test_event_must_retain_original_evidence_id(self):
        missing = "33333333-3333-4333-8333-333333333333"
        out = validate_equity_research(
            evidences=[self.evidence()], raw_items=[self.raw_item()],
            events=[{"event_id": "event-1", "event_type": "earnings", "evidence_ids": [missing]}],
        )
        assert any(issue.rule_id == "ERV-072" and issue.object_id == missing for issue in out.errors)

    def test_high_materiality_fact_cannot_rely_on_tier_c_directly(self):
        finding = _finding(evidence_ids=[self.EID], materiality="high", support_level="direct")
        out = validate_equity_research(
            findings=[finding], evidences=[self.evidence()], raw_items=[self.raw_item()],
            as_of="2026-08-01T00:00:00",
        )
        assert any(issue.rule_id == "ERV-043" and issue.severity == "error" for issue in out.errors)

    def test_competitive_factor_required_type_must_match_actual_evidence(self):
        factor = {
            "factor_id": "factor-1", "company_entity_id": "company:600519.SH",
            "factor_type": "brand", "direction": "advantage", "statement": "品牌因素",
            "business_segment_ids": [], "mechanism": "渠道覆盖",
            "required_evidence_types": ["official_disclosure"],
            "evidence_ids": [self.EID], "counter_evidence_ids": [],
            "management_only": False, "confidence": 0.5, "status": "weakly_supported",
            "valid_from": "2026-08-01", "valid_to": None, "version": 1,
            "created_at": "2026-08-01T00:00:00",
        }
        out = validate_equity_research(
            factors=[factor], evidences=[self.evidence()], raw_items=[self.raw_item()],
        )
        assert any(issue.rule_id == "ERV-078" and "类型不一致" in issue.message
                   for issue in out.errors)

    def test_success_rejected_when_core_modules_missing(self):
        out = validate_equity_research(result={
            "research_status": "success", "coverage": {"missing_core_modules": ["competition"]},
        })
        assert any(issue.rule_id == "ERV-076" for issue in out.errors)

    def test_llm_called_requires_provider_and_model(self):
        out = validate_equity_research(
            run={"model_route_summary": {"llm_called": True}},
            semantic_records=[{"task_name": "research_questions", "llm_called": True,
                               "validation_status": "fallback", "provider": "", "model": None}],
        )
        assert any(issue.rule_id == "ERV-077" for issue in out.errors)

    def test_fake_provider_cannot_satisfy_full_success(self):
        names = {
            "business_description_normalization", "management_statement_summary",
            "competitive_factor_candidates", "catalyst_candidates", "risk_candidates",
            "counter_evidence_organizing", "research_questions",
        }
        records = [{
            "task_name": name, "llm_called": True, "validation_status": "pass",
            "provider": "semantic-fake", "model": "fake-flash", "input_evidence_ids": [],
        } for name in names]
        out = validate_equity_research(
            result={"research_status": "success"}, semantic_records=records)
        assert any(issue.rule_id == "ERV-089" for issue in out.errors)

    def test_success_requires_all_seven_semantic_tasks(self):
        out = validate_equity_research(
            result={"research_status": "success"},
            semantic_records=[{
                "task_name": "research_questions", "llm_called": True,
                "validation_status": "pass", "provider": "deepseek",
                "model": "deepseek-v4-flash", "input_evidence_ids": [],
            }],
        )
        assert any(issue.rule_id == "ERV-088" for issue in out.errors)

    def test_semantic_input_entity_pollution_is_rejected(self):
        raw = self.raw_item(entities=["company:000001.SZ"])
        evidence = self.evidence(raw_item_id=raw["raw_item_id"])
        out = validate_equity_research(
            result={"research_status": "degraded", "company_entity_id": "company:600519.SH"},
            evidences=[evidence], raw_items=[raw], as_of="2026-08-01T00:00:00",
            semantic_records=[{
                "task_name": "research_questions", "llm_called": True,
                "validation_status": "pass", "provider": "deepseek",
                "model": "deepseek-v4-flash", "input_evidence_ids": [evidence["evidence_id"]],
            }],
        )
        assert any(issue.rule_id == "ERV-090" for issue in out.errors)

    def test_management_and_counter_business_rules_are_enforced(self):
        management = _finding(
            finding_id="management", claim_type="SOURCE_OPINION",
            model_route={"task_name": "management_statement_summary", "llm_called": True},
            object={"speaker": "董事长"},
        )
        counter = _finding(
            finding_id="counter", statement="原主张",
            model_route={"task_name": "counter_evidence_organizing", "llm_called": True},
            object={"challenged_claim": "原主张"}, counter_evidence_ids=[],
        )
        out = validate_equity_research(
            findings=[management, counter], semantic_records=[],
            result={"research_status": "degraded"},
        )
        assert any(issue.rule_id == "ERV-091" for issue in out.errors)
        assert any(issue.rule_id == "ERV-093" for issue in out.errors)

    def test_phase4_model_risk_requires_evidence_and_cannot_be_fact(self):
        out = validate_equity_research(
            result={"research_status": "degraded", "company_entity_id": "company:600519.SH"},
            risks=[{
                "risk_id": "risk-1", "source_phase": "phase4", "claim_type": "FACT",
                "company_entity_id": "company:600519.SH", "evidence_ids": [],
            }], semantic_records=[],
        )
        assert any(issue.rule_id == "ERV-092" for issue in out.errors)
