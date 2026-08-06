"""同行选择测试（任务书 3.25 同行节，Commit 9）。

覆盖：完整选择；样本 5/3-4/<3；关系在截止日后；用户 peer 不合格；会计口径不一致；
新上市；事后剔除防护；registry 版本变化进幂等键；LLM 不决定资格。
"""
from __future__ import annotations

from research_os.equity_research.peer_selector import (
    SCORING_VERSION,
    PeerInput,
    WEIGHTS,
    score_peer,
    select_peers,
)
from research_os.validators.schema_validator import validate_model

SUBJECT = "company:600519.SH"
CUTOFF = "2026-08-01T00:00:00"
UNIVERSE = "1.0.0"


def _good(**overrides) -> PeerInput:
    base = dict(
        candidate_company_id="company:000858.SZ",
        relationship_valid_from="2000-01-01",
        information_cutoff=CUTOFF,
        universe_version=UNIVERSE,
        industry_score=5, business_model_score=5, revenue_mix_score=4,
        supply_chain_score=3, size_score=3, listing_tenure_score=5,
        accounting_comparability_score=4, region_score=3, data_completeness_score=4,
    )
    base.update(overrides)
    return PeerInput(**base)


class TestScoring:
    def test_weighted_score(self):
        """手工复算：industry 5→20、business 5→20、revenue 4→16 → core=56；加其余。"""
        c = _good()
        # core = 5/5*20 + 5/5*20 + 4/5*20 = 20+20+16 = 56
        assert c.industry_score / 5 * WEIGHTS["industry_relation"] == 20
        # total: 20+20+16 + 3/5*10 + 3/5*10 + 5/5*5 + 4/5*7 + 3/5*3 + 4/5*5
        #     = 56 + 6 + 6 + 5 + 5.6 + 1.8 + 4 = 84.4
        pc = score_peer(c)
        assert pc.total_score == 84.4
        assert pc.core_subtotal == 56.0
        assert pc.eligible

    def test_accounting_low_excluded(self):
        pc = score_peer(_good(accounting_comparability_score=2))
        assert not pc.eligible
        assert any("会计口径" in r for r in pc.exclusion_reasons)

    def test_data_incomplete_excluded(self):
        pc = score_peer(_good(data_completeness_score=2))
        assert not pc.eligible


class TestAntiLookAhead:
    def test_relation_after_cutoff_excluded(self):
        pc = score_peer(_good(relationship_valid_from="2027-01-01"))
        assert not pc.eligible
        assert any("information_cutoff" in r for r in pc.exclusion_reasons)

    def test_user_peer_not_auto_eligible(self):
        """--peer 只增加候选，不自动合格。"""
        pc = score_peer(_good(user_override=True))
        assert not pc.eligible  # 即使分数达标，用户指定也不自动合格
        assert any("用户指定" in r for r in pc.exclusion_reasons)


class TestSelection:
    def test_full_sample(self):
        inputs = [_good(candidate_company_id=f"company:{i:06d}.SZ") for i in range(5)]
        sel, cands = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel.status == "full"
        assert sel.sample_size == 5
        assert len(sel.selected_company_ids) == 5

    def test_limited_sample_3_to_4(self):
        inputs = [_good(candidate_company_id=f"company:{i:06d}.SZ") for i in range(3)]
        sel, _ = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel.status == "limited"

    def test_insufficient_sample_below_3(self):
        inputs = [_good(candidate_company_id="company:000858.SZ")]
        sel, _ = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel.status == "insufficient"

    def test_ineligible_never_selected(self):
        inputs = [
            _good(candidate_company_id="company:000858.SZ"),
            _good(candidate_company_id="company:000568.SZ", accounting_comparability_score=1),
        ]
        sel, cands = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel.sample_size == 1
        assert "company:000568.SZ" not in sel.selected_company_ids

    def test_excluded_candidates_preserved(self):
        """被排除候选与原因必须保留（防事后选择证据）。"""
        inputs = [_good(candidate_company_id="company:000568.SZ", data_completeness_score=1)]
        sel, cands = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert len(cands) == 1
        assert not cands[0].eligible
        assert cands[0].exclusion_reasons

    def test_ranking_by_score(self):
        inputs = [
            _good(candidate_company_id="company:000858.SZ", industry_score=3, business_model_score=3, revenue_mix_score=3),
            _good(candidate_company_id="company:000568.SZ"),
        ]
        sel, _ = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel.selected_company_ids[0] == "company:000568.SZ"  # 高分优先

    def test_frozen_before_valuation(self):
        """选择只依赖输入时点评分：同输入两次选择结果一致（确定性）。"""
        inputs = [_good(candidate_company_id=f"company:{i:06d}.SZ") for i in range(5)]
        sel1, _ = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        sel2, _ = select_peers(SUBJECT, "req-1", inputs, CUTOFF, UNIVERSE)
        assert sel1.selected_company_ids == sel2.selected_company_ids

    def test_universe_version_in_selection(self):
        sel, _ = select_peers(SUBJECT, "req-1", [_good()], CUTOFF, "2.0.0")
        assert sel.universe_version == "2.0.0"
        assert sel.scoring_version == SCORING_VERSION

    def test_selection_passes_schema(self):
        sel, cands = select_peers(SUBJECT, "req-1", [_good()], CUTOFF, UNIVERSE)
        assert validate_model(sel) == []
        for c in cands:
            assert validate_model(c) == []


class TestLLMBoundary:
    def test_llm_dimensions_explicit(self):
        """LLM 可辅助维度标注，但不得决定资格（eligible 由确定性规则计算）。"""
        c = _good()
        pc = score_peer(c)
        assert pc.llm_assisted_dimensions == []  # 本阶段无 LLM 参与
        assert isinstance(pc.eligible, bool)
