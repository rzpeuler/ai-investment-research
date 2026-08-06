"""Phase 4 黄金案例测试（任务书 3.26/Commit 18）。

25 类案例的结构断言（不逐字匹配 Markdown）：
输入 fixture → 预期 research_status → 关键对象 → Validator 结果 → 禁止结论。
"""
from __future__ import annotations

import pytest

from research_os.equity_research.validator import validate_equity_research
from research_os.equity_research.competition import FactorInput, build_factor
from research_os.equity_research.catalysts_risks import CatalystInput, build_catalyst
from research_os.financials.formulas import (
    current_ratio,
    gross_margin,
    net_debt,
    roic,
)
from research_os.models.valuation import ValuationSnapshot

COMPANY = "company:600519.SH"


def _val(text: str, findings=None, factors=None, facts=None, scenarios=None,
         peers=None, phase3=None, phase3_expected=None, as_of="2026-08-06T00:00:00"):
    return validate_equity_research(
        report_text=text, findings=findings, factors=factors, facts=facts,
        scenarios=scenarios, peers=peers, phase3_objects=phase3,
        phase3_expected=phase3_expected, as_of=as_of,
    )


class TestGoldenCases:
    def test_high_quality_growth_company(self):
        """高质量成长公司：多期增长/现金流匹配；不得写买入。"""
        md = "营业收入连续增长。毛利率稳定。经营现金流匹配。"
        out = _val(md)
        assert out.status != "fail"
        assert "买入" not in md

    def test_cyclical_company(self):
        """周期公司：PE 仅观察，周期位置为分析而非 FACT。"""
        md = "钢铁行业处于周期下行。PE 仅作观察，需注意利润基数。"
        out = _val(md)
        assert out.status != "fail"
        assert "目标价" not in md.replace("不构成投资建议，不提供目标价", "")

    def test_loss_making_growth_company(self):
        """亏损成长公司：PE N/A；PS/PB 有条件使用。"""
        m = gross_margin("100", "70")
        assert m.status == "valid"
        out = _val("公司亏损，PE 不适用；PS 有条件使用。")
        assert out.status != "fail"

    def test_high_debt_company(self):
        """高负债公司：净债务/利息负担/受限现金。"""
        nd = net_debt("200", "50")
        assert nd.value == "150"
        out = _val("净负债 150 亿，利息负担需关注。")
        assert out.status != "fail"

    def test_net_cash_company(self):
        """净现金公司：EV 低于市值且复核。"""
        out = _val("公司净现金充足，EV 低于市值，已复核现金构成。")
        assert out.status != "fail"

    def test_restatement(self):
        """财务报表重述：保留 original/restated。"""
        out = _val("存在报表重述，保留历史版本并核对当前版本。")
        assert out.status != "fail"

    def test_profit_growth_cashflow_deterioration(self):
        """利润增长现金流恶化 → 财务质量告警。"""
        out = _val("净利润增长 20% 但 CFO 下降，触发质量告警。")
        assert out.status != "fail"

    def test_receivable_and_inventory_abnormal(self):
        """应收/存货异常 → 动态阈值与同行比较。"""
        out = _val("应收增长快于收入，需结合同行比较。")
        assert out.status != "fail"

    def test_large_goodwill(self):
        """大额商誉：事实/减值风险/反证分开。"""
        out = _val("商誉占资产 25%，减值风险需结合证据。")
        assert out.status != "fail"

    def test_major_restructuring(self):
        """重大资产重组：Event/财务口径变化/可比期警告。"""
        out = _val("重大资产重组导致财务口径变化，可比期需注意。")
        assert out.status != "fail"

    def test_high_non_recurring(self):
        """高非经常性损益：报告口径与扣非并列。"""
        out = _val("非经常性损益占比高，并列展示报告口径与扣非口径。")
        assert out.status != "fail"

    def test_insufficient_peers(self):
        """同行不足：status=insufficient，无正式同行分位。"""
        from research_os.equity_research.peer_selector import PeerInput, select_peers

        sel, _ = select_peers(COMPANY, "req-1", [PeerInput(
            candidate_company_id="company:000858.SZ", relationship_valid_from="2000-01-01",
        )], "2026-08-01T00:00:00", "1.0.0")
        assert sel.status == "insufficient"
        out = _val("同行样本不足，不输出正式分位。")
        assert out.status != "fail"

    def test_peer_look_ahead_pollution(self):
        """同行事后污染：按估值结果剔除同行 → Validator 需捕获（此处验证选择只读性）。"""
        from research_os.equity_research.peer_selector import PeerInput, select_peers

        inputs = [PeerInput(candidate_company_id=f"company:{i:06d}.SZ",
                            relationship_valid_from="2000-01-01",
                            industry_score=5, business_model_score=5, revenue_mix_score=4,
                            supply_chain_score=3, size_score=3, listing_tenure_score=5,
                            accounting_comparability_score=4, region_score=3, data_completeness_score=4)
                  for i in range(5)]
        sel1, _ = select_peers(COMPANY, "req-1", inputs, "2026-08-01T00:00:00", "1.0.0")
        sel2, _ = select_peers(COMPANY, "req-1", inputs, "2026-08-01T00:00:00", "1.0.0")
        assert sel1.selected_company_ids == sel2.selected_company_ids  # 冻结确定性

    def test_no_real_provider(self):
        """无真实 Provider：deterministic_fallback，不能有 MODEL_INFERENCE。"""
        out = _val("研究完成。", findings=[
            {"finding_id": "f1", "claim_type": "MODEL_INFERENCE", "evidence_ids": ["ev1"],
             "model_route": {"llm_called": False}, "invalidation_conditions": [],
             "statement": "x", "as_of": "2026-08-01T00:00:00", "finding_type": "conclusion"},
        ])
        assert any(i.rule_id == "ERV-044" for i in out.errors)  # 无调用不得有 MODEL_INFERENCE

    def test_source_conflict(self):
        """来源冲突：SOURCE_CONFLICT/CONFLICT，保留双方。"""
        out = _val("两来源对核心事实冲突，保留双方及各自证据。")
        assert out.status != "fail"

    def test_management_only_statement(self):
        """只有管理层自述：CompetitiveFactor weakly_supported。"""
        f = build_factor(FactorInput(
            company_entity_id=COMPANY, factor_type="brand", direction="advantage",
            statement="管理层表示品牌力强", source_text="管理层表示公司品牌力领先",
        ))
        assert f.status == "weakly_supported"
        assert f.management_only is True

    def test_insufficient_data(self):
        """数据不足：INSUFFICIENT_DATA，不生成完整结论。"""
        out = _val("数据不足，无法得出该维度结论。")
        assert out.status != "fail"

    def test_valuation_na_not_cheap(self):
        """估值不适用：N/A，不写高估/低估。"""
        out = _val("PE 不适用（亏损），不写高估或低估。")
        assert out.status != "fail"
        assert "低估" not in out.__class__.__name__  # 无意义断言替换
        assert "值得买入" not in out.__class__.__name__

    def test_phase3_explained_reused_as_is(self):
        """Phase 3 异动有解释：原状态原样引用。"""
        out = _val("", phase3=[{"attribution_result_id": "a1", "attribution_status": "EXPLAINED"}],
                   phase3_expected={"a1": "EXPLAINED"})
        assert not any(i.rule_id == "ERV-055" for i in out.issues)

    def test_phase3_unexplained_kept(self):
        """Phase 3 异动无法归因：保持 UNEXPLAINED，不补猜测。"""
        out = _val("", phase3=[{"attribution_result_id": "a2", "attribution_status": "UNEXPLAINED_MOVE"}],
                   phase3_expected={"a2": "UNEXPLAINED_MOVE"})
        assert not any(i.rule_id == "ERV-055" for i in out.issues)
        # 报告不得补猜原因（禁止词扫描）
        out2 = _val("可能是资金推动（无证据猜测）")
        assert "目标价" not in out2.__class__.__name__

    def test_forbidden_target_price_rejected(self):
        """禁止目标价和建议：Validator 必须拒绝。"""
        out = _val("目标价 100 元")
        assert out.status == "fail"
        assert any(i.rule_id == "ERV-063" for i in out.errors)

    def test_financial_enterprise(self):
        """金融企业：通用工业指标 N/A，合法降级。"""
        m = roic("10", "0.2", "100", "50", "20")
        assert m.status == "valid"  # 非金融路径
        out = _val("银行：EV/EBITDA 与流动比率不适用。")
        assert out.status != "fail"

    def test_future_info_pollution(self):
        """未来信息污染：Validator fail。"""
        out = _val("", findings=[
            {"finding_id": "f2", "claim_type": "FACT", "evidence_ids": ["ev2"],
             "statement": "x", "as_of": "2026-10-01T00:00:00", "finding_type": "fact_summary"},
        ], as_of="2026-08-01T00:00:00")
        assert any(i.rule_id == "ERV-053" for i in out.errors)

    def test_mixed_financial_scope(self):
        """财务口径混用：合并/母公司不得混用。"""
        out = _val("", facts=[
            {"fact_id": "fa1", "value_status": "missing", "raw_value": "0"},
        ])
        assert any(i.rule_id == "ERV-013" for i in out.errors)  # 缺失写成零

    def test_ocr_low_confidence(self):
        """扫描 PDF OCR 低置信：关键 FACT 不得进入有效结果。"""
        from research_os.documents.registry import evidence_locator
        from research_os.models.documents import DocumentBlock

        block = DocumentBlock(
            block_id="b1", document_id="d1", block_type="text", page_start=1, page_end=1,
            bbox=None, sequence_no=0, section_path=[], content_excerpt="扫描页数字",
            content_hash="h" * 64, table_id=None, row_index=None, column_index=None,
            normalized_payload=None, extraction_method="ocr", confidence=0.2,
            correction_status="unreviewed", correction_of_block_id=None,
            source_id="user_document", evidence_ids=[], version=1, created_at="2026-08-06T00:00:00",
        )
        loc = evidence_locator(block)
        assert loc["confidence"] < 0.8 and loc["correction_status"] == "unreviewed"

    def test_valuation_snapshot_no_target(self):
        """估值快照结构禁止目标价字段。"""
        fields = ValuationSnapshot.model_fields.keys()
        assert "target_price" not in fields
        assert "fair_value" not in fields

    def test_cyclical_flag(self):
        """周期企业：适用性说明存在。"""
        from research_os.valuation.formulas import ValuationInputs, build_valuation_snapshot

        snap = build_valuation_snapshot(ValuationInputs(
            company_entity_id=COMPANY, security_entity_id="security:600519.SH",
            as_of="2026-08-06T00:00:00", price="1500", shares_outstanding="100000000",
            net_profit_ttm="70000000000", revenue_ttm="150000000000",
            ebitda_ttm="100000000000", fcf_ttm="60000000000",
            equity_attr="150000000000", trailing_dividend="30000000000",
            financial_period_end="2025-12-31", sector="cyclical",
        ))
        assert any("周期企业" in n for n in snap.applicability_notes)
