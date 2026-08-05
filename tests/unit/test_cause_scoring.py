"""原因候选生成与确定性评分测试（Phase 3 任务书 11 节）。"""
from __future__ import annotations

import pytest

from research_os.abnormal_move.cause_candidate_generator import CauseCandidateGenerator
from research_os.abnormal_move.cause_candidate_scorer import (
    CauseCandidateScorer,
    unexplained_conditions,
)
from research_os.abnormal_move.event_window_retriever import RetrievedItem, RetrievalResult
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    CauseCandidate,
    CauseEvidenceLink,
)
from research_os.utils.id import new_uuid

UUID = "12345678-1234-1234-1234-123456789abc"


def _request() -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID, task_id=UUID, entity_id="600519.SH",
        entity_type="company", analysis_date="2026-08-05",
        window_start="2026-08-01", window_end="2026-08-05",
        as_of="2026-08-05T20:00:00",
    )


def _obs() -> AbnormalMoveObservation:
    return AbnormalMoveObservation(
        observation_id="22222222-2222-2222-2222-222222222222",
        request_id=UUID, entity_id="600519.SH", entity_type="company",
        window_start="2026-08-01", window_end="2026-08-05",
        trade_date="2026-08-05", raw_return=0.095,
        move_start_at="2026-08-05T09:30:00", move_end_at="2026-08-05T15:00:00",
        primary_anomaly_types=["absolute_return", "volume_anomaly"],
    )


def _item(title: str, source_id: str = "cninfo", published_at: str = "2026-08-04T09:00:00",
          entities=None, layer: int = 1, url: str = "https://x") -> RetrievedItem:
    return RetrievedItem(
        item_id=new_uuid(), layer=layer, kind="raw_item", source_id=source_id,
        title=title, published_at=published_at, retrieved_at=published_at,
        url=url, excerpt=f"{title}摘录", entities=entities or ["company:600519.SH"],
    )


class TestGenerator:
    def test_build_generates_candidates_and_links(self):
        retrieval = RetrievalResult(
            items=[_item("公司发布业绩预增公告")], layers_covered={1: 1},
            channels_covered={})
        result = CauseCandidateGenerator(["600519", "贵州茅台"]).build(
            _request(), _obs(), retrieval)
        assert len(result.candidates) == 1
        assert len(result.links) == 1
        c = result.candidates[0]
        assert c.entity_link_score == 5
        assert c.source_reliability_score == 5
        assert c.timing_relation == "BEFORE_MOVE"
        assert c.causal_eligibility is True

    def test_wrong_entity_skipped(self):
        retrieval = RetrievalResult(
            items=[_item("某银行发布公告", entities=["company:000001.SZ"])],
            layers_covered={1: 1}, channels_covered={})
        result = CauseCandidateGenerator(["600519", "贵州茅台"]).build(
            _request(), _obs(), retrieval)
        assert len(result.candidates) == 0
        assert result.skipped

    def test_after_move_categorized(self):
        retrieval = RetrievalResult(
            items=[_item("收盘后机构解读暴涨原因", published_at="2026-08-05T20:00:00")],
            layers_covered={1: 1}, channels_covered={})
        result = CauseCandidateGenerator(["600519", "贵州茅台"]).build(
            _request(), _obs(), retrieval)
        c = result.candidates[0]
        assert c.cause_category == "after_the_fact_explanation"
        assert c.time_match_score <= 1

    def test_xueqiu_rumor(self):
        retrieval = RetrievalResult(
            items=[_item("某用户爆料", source_id="xueqiu", layer=3)],
            layers_covered={3: 1}, channels_covered={})
        result = CauseCandidateGenerator(["600519", "贵州茅台"]).build(
            _request(), _obs(), retrieval)
        c = result.candidates[0]
        assert c.cause_category == "unverified_rumor"
        assert c.source_reliability_score <= 1


class TestScorer:
    def _candidate(self, **overrides) -> CauseCandidate:
        base = dict(
            cause_candidate_id=new_uuid(), request_id=UUID,
            observation_id="22222222-2222-2222-2222-222222222222",
            title="业绩预增", cause_category="direct_trigger",
            time_match_score=5, entity_link_score=5, novelty_score=5,
            peer_linkage_score=5, source_reliability_score=5,
            explanation_coverage_score=4, verifiability_score=5,
            timing_relation="BEFORE_MOVE", causal_eligibility=True,
            published_at="2026-08-04T09:00:00",
        )
        base.update(overrides)
        return CauseCandidate(**base)

    def _direct_link(self, cid: str) -> CauseEvidenceLink:
        return CauseEvidenceLink(
            link_id=new_uuid(), cause_candidate_id=cid,
            evidence_id="ev-1", relation="supports", directness="direct",
            timing_relation="before", independence_group="g1",
            weight=1.0, notes="", created_at="2026-08-05T20:00:00",
        )

    def test_manual_score_calculation(self):
        # base = (5*25 + 5*20 + 5*15 + 5*15 + 5*10 + 4*10 + 5*5)/5
        #      = (125+100+75+75+50+40+25)/5 = 490/5 = 98
        c = self._candidate()
        link = self._direct_link(c.cause_candidate_id)
        result = CauseCandidateScorer().score([c], [link])
        assert c.base_score == 98.0
        assert c.final_score == 98.0
        assert result.primary_ids == [c.cause_candidate_id]

    def test_old_news_penalty(self):
        # novelty=1 -> base 86，惩罚 -20 -> final 66
        c = self._candidate(novelty_score=1)
        link = self._direct_link(c.cause_candidate_id)
        result = CauseCandidateScorer().score([c], [link])
        assert c.penalties == 20.0
        assert c.final_score == 66.0

    def test_after_fact_penalty_and_eligibility_removed(self):
        c = self._candidate(cause_category="after_the_fact_explanation",
                            time_match_score=1, causal_eligibility=True)
        result = CauseCandidateScorer().score([c])
        assert c.penalties >= 25.0
        assert c.causal_eligibility is False

    def test_anonymous_penalty(self):
        c = self._candidate(source_reliability_score=1, independence_groups=["g1"])
        result = CauseCandidateScorer().score([c])
        assert c.penalties >= 30.0

    def test_missing_time_penalty(self):
        c = self._candidate(published_at=None)
        result = CauseCandidateScorer().score([c])
        assert c.penalties >= 10.0

    def test_clamp_lower_bound(self):
        c = self._candidate(time_match_score=0, entity_link_score=0, novelty_score=0,
                            peer_linkage_score=0, source_reliability_score=0,
                            explanation_coverage_score=0, verifiability_score=0)
        result = CauseCandidateScorer().score([c])
        assert c.final_score == 0.0

    def test_multi_cause_detection(self):
        c1 = self._candidate(title="公告A", final_score=0, base_score=0)
        c2 = self._candidate(title="公告B", final_score=0, base_score=0)
        scorer = CauseCandidateScorer()
        # 两个都在 72 分附近，差值 <8
        c1.time_match_score, c2.time_match_score = 4, 4
        c1.novelty_score, c2.novelty_score = 4, 4
        result = scorer.score([c1, c2])
        assert len(result.multi_ids) == 2, f"multi_ids={result.multi_ids}"

    def test_primary_requires_gap(self):
        c1 = self._candidate(title="A")
        c2 = self._candidate(title="B", time_match_score=4, novelty_score=4)
        link = self._direct_link(c1.cause_candidate_id)
        result = CauseCandidateScorer().score([c1, c2], [link])
        # A 98 分，B 90 分，差=8 >= 8 且 A 满足直接证据门槛 -> primary
        assert result.primary_ids == [c1.cause_candidate_id]

    def test_excluded_below_45(self):
        c = self._candidate(time_match_score=1, entity_link_score=1, novelty_score=1,
                            peer_linkage_score=1, source_reliability_score=1,
                            explanation_coverage_score=1, verifiability_score=1)
        result = CauseCandidateScorer().score([c])
        assert c.final_score < 45
        assert result.excluded_ids == [c.cause_candidate_id]

    def test_unexplained_conditions(self):
        # 全部事后解释 -> UNEXPLAINED 条件
        c = self._candidate(cause_category="after_the_fact_explanation",
                            time_match_score=1, causal_eligibility=False)
        reasons = unexplained_conditions([c])
        assert any("事后解释" in r for r in reasons)


class TestGeneratorScorerIntegration:
    def test_full_pipeline_primary(self):
        retrieval = RetrievalResult(
            items=[_item("贵州茅台发布业绩预增公告", published_at="2026-08-04T09:00:00")],
            layers_covered={1: 1}, channels_covered={})
        gen = CauseCandidateGenerator(["600519", "贵州茅台"])
        g = gen.build(_request(), _obs(), retrieval)
        assert len(g.candidates) == 1
        result = CauseCandidateScorer().score(g.candidates, g.links)
        c = result.candidates[0]
        assert c.final_score >= 75
        assert result.primary_ids == [c.cause_candidate_id]

    def test_schema_consistency(self):
        from research_os.validators.schema_validator import validate_model

        retrieval = RetrievalResult(
            items=[_item("贵州茅台公告")], layers_covered={1: 1}, channels_covered={})
        gen = CauseCandidateGenerator(["600519", "贵州茅台"])
        g = gen.build(_request(), _obs(), retrieval)
        for c in g.candidates:
            assert validate_model(c) == []
        for l in g.links:
            assert validate_model(l) == []
