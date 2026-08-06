"""业务分部测试（任务书 3.25 分部节，Commit 8）。

覆盖：原名/标准名/重分类保留；LLM 候选不自动批准；跨期不同分类不得直接相加；
收入/利润/销量拆分只在披露支持时；Schema 契约。
"""
from __future__ import annotations

import pytest

from research_os.equity_research.business_segments import (
    ReclassificationRule,
    apply_reclassification,
    build_segment,
    canonicalize_name,
    check_cross_period_merge_safety,
    SegmentInput,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"
REPORT = "report-2025"


def _input(**overrides) -> SegmentInput:
    base = dict(
        company_entity_id=COMPANY, financial_report_id=REPORT,
        segment_type="product", raw_name="茅台酒", revenue="800000000",
        unit_scale=10000,
    )
    base.update(overrides)
    return SegmentInput(**base)


class TestCanonicalization:
    def test_rule_mapping(self):
        m = canonicalize_name("茅台酒")
        assert m.canonical_name == "茅台酒"
        assert m.mapping_method == "rule"
        assert m.confidence == 1.0

    def test_fuzzy_rule_mapping(self):
        m = canonicalize_name("其他")
        assert m.canonical_name == "其他业务"
        assert m.mapping_method == "rule"

    def test_unmapped_becomes_llm_assisted_candidate_not_approved(self):
        m = canonicalize_name("飞天茅台")
        assert m.mapping_method == "llm_assisted"
        assert m.confidence < 0.5  # 低置信，不得自动批准
        assert m.canonical_name == "飞天茅台"  # 保留原名


class TestBuildSegment:
    def test_build_with_rule(self):
        seg = build_segment(_input())
        assert seg.raw_name == "茅台酒"
        assert seg.canonical_name == "茅台酒"
        assert seg.mapping_method == "rule"
        assert seg.valid_from == "1970-01-01"
        assert seg.status == "active"
        assert validate_model(seg) == []

    def test_build_keeps_raw_name_for_llm_candidate(self):
        seg = build_segment(_input(raw_name="飞天茅台"))
        assert seg.raw_name == "飞天茅台"
        assert seg.mapping_method == "llm_assisted"
        assert seg.mapping_confidence < 0.5

    def test_build_preserves_volume_price(self):
        seg = build_segment(_input(volume="100000", average_price="8000"))
        assert seg.volume == "100000"
        assert seg.average_price == "8000"

    def test_revenue_share_preserved(self):
        seg = build_segment(_input(revenue_share="0.8"))
        assert seg.revenue_share == "0.8"


class TestReclassification:
    def test_old_classification_superseded_with_group(self):
        segs = [build_segment(_input(raw_name="白酒业务", valid_from="2024-01-01"))]
        rules = [ReclassificationRule(group_id="rg-1", old_raw_name="白酒业务",
                                      new_canonical_name="茅台酒", effective_from="2025-01-01")]
        out = apply_reclassification(segs, rules)
        assert out[0].reclassification_group_id == "rg-1"
        assert out[0].status == "superseded"
        assert out[0].raw_name == "白酒业务"  # 原名保留

    def test_new_classification_not_touched(self):
        segs = [build_segment(_input(raw_name="白酒业务", valid_from="2025-06-01"))]
        rules = [ReclassificationRule(group_id="rg-1", old_raw_name="白酒业务",
                                      new_canonical_name="茅台酒", effective_from="2025-01-01")]
        out = apply_reclassification(segs, rules)
        assert out[0].reclassification_group_id is None
        assert out[0].status == "active"


class TestCrossPeriodMergeSafety:
    def test_different_groups_warned(self):
        a = build_segment(_input(raw_name="白酒业务", valid_from="2024-01-01"))
        b = build_segment(_input(raw_name="茅台酒", valid_from="2025-01-01"))
        a.reclassification_group_id = "rg-1"
        a.status = "superseded"
        b.reclassification_group_id = None
        b.canonical_name = "茅台酒"
        a.canonical_name = "茅台酒"
        warnings = check_cross_period_merge_safety([a, b])
        assert any("不得直接相加" in w for w in warnings)

    def test_same_group_no_warning(self):
        a = build_segment(_input())
        b = build_segment(_input(raw_name="系列酒"))
        assert check_cross_period_merge_safety([a, b]) == []
