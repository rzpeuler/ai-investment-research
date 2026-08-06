"""研报合成与渲染测试（任务书 3.25 报告节，Commit 15）。

覆盖：Findings 构造与 claim_type 边界；Result 状态合法；38 章节模板完整性；
必须章节显示；缺数据写覆盖状态不套话；无目标价/交易建议文案；免责声明固定文案。
"""
from __future__ import annotations

import pytest

from research_os.equity_research.assembler import ResultInput, build_result
from research_os.equity_research.findings import FindingInput, build_finding
from research_os.equity_research.renderer import (
    DISCLAIMER,
    FORBIDDEN_FILLERS,
    MANDATORY_SECTIONS,
    SECTIONS,
    RenderInput,
    check_no_filler,
    render_markdown,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"
SECURITY = "security:600519.SH"


def _result():
    ri = ResultInput(
        run_id="run-1", request_id="req-1", company_entity_id=COMPANY,
        security_entity_id=SECURITY, as_of="2026-08-06T00:00:00",
        research_status="insufficient_data",
        unknowns=["无自动行情来源"],
    )
    return build_result(ri)


class TestFindings:
    def test_build_finding(self):
        f = build_finding(FindingInput(
            request_id="req-1", company_entity_id=COMPANY,
            finding_type="business_analysis", title="业务结构", statement="以白酒为主",
            claim_type="FACT", evidence_ids=["ev-1"], section_id="s8",
        ))
        assert f.status == "supported"
        assert validate_model(f) == []

    def test_illegal_claim_type_rejected(self):
        with pytest.raises(ValueError):
            build_finding(FindingInput(
                request_id="req-1", company_entity_id=COMPANY,
                finding_type="conclusion", title="t", statement="s",
                claim_type="NOT_A_TYPE", section_id="s1",
            ))

    def test_no_evidence_unknown_status(self):
        f = build_finding(FindingInput(
            request_id="req-1", company_entity_id=COMPANY,
            finding_type="conclusion", title="t", statement="s",
            claim_type="HYPOTHESIS", section_id="s1",
        ))
        assert f.status == "unknown"


class TestResult:
    def test_build_result_valid(self):
        r = _result()
        assert r.research_status == "insufficient_data"
        assert validate_model(r) == []

    def test_illegal_status_rejected(self):
        with pytest.raises(ValueError):
            build_result(ResultInput(
                run_id="r", request_id="q", company_entity_id=COMPANY,
                security_entity_id=SECURITY, as_of="2026-08-06T00:00:00",
                research_status="guessed",
            ))

    def test_result_aggregates_ids_only(self):
        """Result 只聚合结构化对象 ID，不含内联新事实。"""
        r = _result()
        assert r.key_finding_ids == []
        assert r.warnings == []


class TestRenderer:
    def test_38_sections(self):
        assert len(SECTIONS) == 38

    def test_mandatory_sections_present(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        for idx in MANDATORY_SECTIONS:
            assert f"## {idx}." in md, f"缺少必须章节 {idx}"

    def test_section_order(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        positions = [md.find(f"## {i}.") for i in range(1, 39)]
        assert all(p >= 0 for p in positions)
        assert positions == sorted(positions)

    def test_missing_data_writes_status_not_filler(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        assert "覆盖状态" in md
        assert check_no_filler(md) == []

    def test_disclaimer_present(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        assert DISCLAIMER in md

    def test_no_target_price_or_rating(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        # 免责声明固定文案允许出现"目标价"（任务书决策 4：引文正常词语不误伤）
        body = md.replace(DISCLAIMER, "")
        for forbidden in ("目标价", "买入评级", "建议买入", "上涨空间", "仓位建议"):
            assert forbidden not in body

    def test_no_forbidden_filler_anywhere(self):
        md = render_markdown(RenderInput(result=_result(), company_name="贵州茅台",
                                         security_symbol="600519.SH", report_date="2026-08-06",
                                         research_status="insufficient_data"))
        for f in FORBIDDEN_FILLERS:
            assert f not in md

    def test_model_route_honest(self):
        md = render_markdown(RenderInput(
            result=_result(), company_name="贵州茅台", security_symbol="600519.SH",
            report_date="2026-08-06", research_status="insufficient_data",
            model_route={"mode": "deterministic_fallback", "llm_called": False,
                         "limitation": "semantic_llm_modules_not_connected"},
        ))
        assert "deterministic_fallback" in md
        assert "llm_called=False" in md
