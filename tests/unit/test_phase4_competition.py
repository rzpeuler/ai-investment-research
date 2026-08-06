"""行业与竞争测试（任务书 3.25 竞争节，Commit 10）。

覆盖：管理层自述边界（management_only/weakly_supported）；合格证据类型；
反证 contested；护城河语言禁止；Schema 契约。
"""
from __future__ import annotations

from research_os.equity_research.competition import (
    FactorInput,
    add_counter_evidence,
    build_factor,
    check_moat_language,
    is_management_only,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"


def _input(**overrides) -> FactorInput:
    base = dict(
        company_entity_id=COMPANY, factor_type="brand", direction="advantage",
        statement="高端白酒品牌力强", mechanism="品牌溢价",
        evidence_types=[], evidence_ids=[], counter_evidence_ids=[],
        source_text="管理层表示公司品牌力领先",
    )
    base.update(overrides)
    return FactorInput(**base)


class TestManagementBoundary:
    def test_management_only_weakly_supported(self):
        f = build_factor(_input())
        assert f.management_only is True
        assert f.status == "weakly_supported"
        assert f.confidence <= 0.3
        assert validate_model(f) == []

    def test_evidence_supported(self):
        f = build_factor(_input(
            evidence_types=["market_share"], evidence_ids=["ev-1"],
            source_text="第三方市场数据：市占率 35%",
        ))
        assert f.management_only is False
        assert f.status == "supported"
        assert f.confidence >= 0.7

    def test_evidence_without_ids_weakly_supported(self):
        f = build_factor(_input(
            evidence_types=["market_share"], evidence_ids=[],
            source_text="第三方市场数据：市占率 35%",
        ))
        assert f.status == "weakly_supported"
        assert f.management_only is False

    def test_no_evidence_unknown(self):
        f = build_factor(_input(source_text="无来源描述"))
        assert f.status == "unknown"

    def test_is_management_only_detection(self):
        assert is_management_only("公司表示竞争力强", []) is True
        assert is_management_only("市占率 35%（第三方）", []) is False


class TestCounterEvidence:
    def test_counter_evidence_makes_contested(self):
        f = build_factor(_input(evidence_types=["market_share"], evidence_ids=["ev-1"]))
        assert f.status == "supported"
        f2 = add_counter_evidence(f, ["ev-counter-1"])
        assert f2.status == "contested"
        assert "ev-counter-1" in f2.counter_evidence_ids
        assert f2.version == f.version + 1
        # 原对象未变
        assert f.status == "supported"

    def test_counter_evidence_dedup(self):
        f = build_factor(_input())
        f2 = add_counter_evidence(f, ["ev-c1", "ev-c1"])
        assert f2.counter_evidence_ids == ["ev-c1"]


class TestMoatLanguage:
    def test_forbidden_phrase_detected(self):
        hits = check_moat_language("公司已形成护城河")
        assert len(hits) == 1

    def test_clean_statement(self):
        assert check_moat_language("品牌具有溢价能力") == []
