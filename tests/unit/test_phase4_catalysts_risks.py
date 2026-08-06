"""催化剂/风险测试（任务书 3.25 催化剂风险节，Commit 13）。

覆盖：已发生/已宣布未完成/公司指引/外部观点区分；必填字段完整性；
市场广泛知晓缺证据 unknown；Phase 3 归因只读关联不改写；反证 mitigates 风险；
Schema 契约。
"""
from __future__ import annotations

from research_os.equity_research.catalysts_risks import (
    CatalystInput,
    RiskInput,
    build_catalyst,
    build_risk,
    check_widely_known,
)
from research_os.validators.schema_validator import validate_model

COMPANY = "company:600519.SH"


def _catalyst(**overrides) -> CatalystInput:
    base = dict(
        company_entity_id=COMPANY, catalyst_type="earnings",
        description="年报披露", claim_type="FACT",
        announcement_status="announced", source_phase="phase4",
        impact_mechanism="盈利预期", widely_known="unknown",
    )
    base.update(overrides)
    return CatalystInput(**base)


def _risk(**overrides) -> RiskInput:
    base = dict(
        company_entity_id=COMPANY, risk_type="regulatory",
        description="消费税政策变化", claim_type="HYPOTHESIS",
        source_phase="phase4", impact_mechanism="税率影响利润",
        widely_known="unknown",
    )
    base.update(overrides)
    return RiskInput(**base)


class TestCatalyst:
    def test_announced_active(self):
        c = build_catalyst(_catalyst())
        assert c.status == "active"
        assert c.announcement_status == "announced"
        assert validate_model(c) == []

    def test_completed_realized(self):
        c = build_catalyst(_catalyst(announcement_status="completed"))
        assert c.status == "realized"

    def test_cancelled(self):
        c = build_catalyst(_catalyst(announcement_status="cancelled"))
        assert c.status == "cancelled"

    def test_required_fields_present(self):
        c = build_catalyst(_catalyst(
            time_window_start="2026-08-01", time_window_end="2026-08-31",
            prerequisites=["审批通过"], invalidation_conditions=["项目取消"],
            evidence_ids=["ev-1"], confidence=0.8,
        ))
        assert c.time_window_start == "2026-08-01"
        assert c.prerequisites == ["审批通过"]
        assert c.invalidation_conditions == ["项目取消"]
        assert c.evidence_ids == ["ev-1"]

    def test_phase3_link_preserved(self):
        """Phase 3 归因 ID 只读关联。"""
        c = build_catalyst(_catalyst(phase3_attribution_result_id="attr-1"))
        assert c.phase3_attribution_result_id == "attr-1"
        # description 未被改写（UNEXPLAINED 不得补猜）
        assert c.description == "年报披露"

    def test_claim_type_kinds(self):
        for ct in ("FACT", "SOURCE_OPINION", "MODEL_INFERENCE", "HYPOTHESIS", "UNKNOWN", "CONFLICT"):
            c = build_catalyst(_catalyst(claim_type=ct))
            assert c.claim_type == ct


class TestRisk:
    def test_active_risk(self):
        r = build_risk(_risk())
        assert r.status == "active"
        assert validate_model(r) == []

    def test_counter_evidence_mitigates(self):
        r = build_risk(_risk(counter_evidence_ids=["ev-c1"]))
        assert r.status == "mitigated"

    def test_triggers_and_mitigants(self):
        r = build_risk(_risk(triggers=["税率上调"], mitigants=["产品提价"]))
        assert r.triggers == ["税率上调"]
        assert r.mitigants == ["产品提价"]

    def test_phase3_link_preserved(self):
        r = build_risk(_risk(phase3_attribution_result_id="attr-2"))
        assert r.phase3_attribution_result_id == "attr-2"


class TestWidelyKnown:
    def test_unknown_without_evidence(self):
        assert check_widely_known([], explicitly_known=False) == "unknown"

    def test_yes_with_evidence(self):
        assert check_widely_known(["ev-1"], explicitly_known=False) == "yes"

    def test_yes_explicit(self):
        assert check_widely_known([], explicitly_known=True) == "yes"

    def test_not_model_guessed(self):
        """缺证据时不得由模型自信判断 → unknown。"""
        assert check_widely_known([], explicitly_known=False) == "unknown"
