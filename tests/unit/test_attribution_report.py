"""归因合成/叙事/反证/渲染/Validator 测试（Phase 3 任务书 13、15、16 节）。"""
from __future__ import annotations

import pytest

from research_os.abnormal_move.attribution_synthesizer import AttributionSynthesizer
from research_os.abnormal_move.contradiction_checker import ContradictionChecker
from research_os.abnormal_move.cause_candidate_scorer import CauseCandidateScorer, ScoreResult
from research_os.abnormal_move.narrative_analyzer import NarrativeAnalyzer
from research_os.abnormal_move.renderer import AbnormalMoveRenderer, RenderContext
from research_os.abnormal_move.validator import AbnormalMoveValidator, ValidationContext
from research_os.abnormal_move.event_window_retriever import RetrievedItem
from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AbnormalMoveRun,
    AttributionResult,
    BenchmarkSelection,
    CauseCandidate,
    CauseEvidenceLink,
    ModelRoute,
)
from research_os.utils.id import new_uuid

UUID = "12345678-1234-1234-1234-123456789abc"
OBS_ID = "22222222-2222-2222-2222-222222222222"


def _request() -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID, task_id=UUID, entity_id="600519.SH",
        entity_type="company", analysis_date="2026-08-05",
        window_start="2026-08-01", window_end="2026-08-05",
        as_of="2026-08-05T20:00:00")


def _obs(**kw) -> AbnormalMoveObservation:
    base = dict(
        observation_id=OBS_ID, request_id=UUID, entity_id="600519.SH",
        entity_type="company", window_start="2026-08-01",
        window_end="2026-08-05", trade_date="2026-08-05",
        raw_return=0.095, move_start_at="2026-08-05T09:30:00",
        move_end_at="2026-08-05T15:00:00",
        primary_anomaly_types=["absolute_return"],
    )
    base.update(kw)
    return AbnormalMoveObservation(**base)


def _candidate(final: float = 80.0, **kw) -> CauseCandidate:
    base = dict(
        cause_candidate_id=new_uuid(), request_id=UUID, observation_id=OBS_ID,
        title="业绩预增公告", cause_category="direct_trigger",
        time_match_score=5, entity_link_score=5, novelty_score=5,
        peer_linkage_score=4, source_reliability_score=5,
        explanation_coverage_score=4, verifiability_score=5,
        timing_relation="BEFORE_MOVE", causal_eligibility=True,
        published_at="2026-08-04T09:00:00", base_score=final,
        penalties=0, final_score=final,
    )
    base.update(kw)
    return CauseCandidate(**base)


def _selection() -> BenchmarkSelection:
    return BenchmarkSelection(
        benchmark_selection_id=new_uuid(), request_id=UUID, observation_id=OBS_ID,
        market_benchmark_id="index:000300.SH",
        selected_at="2026-08-05T20:00:00",
        information_cutoff="2026-08-01T00:00:00",
        candidate_ids=[new_uuid()], fallback_status="full")


def _run() -> AbnormalMoveRun:
    return AbnormalMoveRun(
        run_id=new_uuid(), task_id=UUID, request_id=UUID, observation_id=OBS_ID,
        idempotency_key="k1", started_at="2026-08-05T20:00:00",
        finished_at="2026-08-05T20:05:00", status="completed",
        rules_versions={"market_data": "manual-2026-08-03-2026-08-05",
                        "anomaly": "anomaly.v1"})


class TestNarrativeAnalyzer:
    def test_classification(self):
        items = [
            RetrievedItem(item_id="1", layer=1, kind="raw_item", source_id="cninfo",
                          title="公告", published_at="2026-08-04T09:00:00"),
            RetrievedItem(item_id="2", layer=3, kind="raw_item", source_id="xueqiu",
                          title="股吧爆料", published_at="2026-08-04T10:00:00"),
            RetrievedItem(item_id="3", layer=3, kind="raw_item", source_id="cls",
                          title="快讯", published_at="2026-08-04T11:00:00"),
        ]
        n = NarrativeAnalyzer().analyze(items)
        assert len(n.facts) == 1
        assert len(n.narratives) == 1
        assert len(n.opinions) == 1
        assert n.heat_indicators.get("community_mentions") == 1
        assert any("机构交易" in w for w in n.warnings)

    def test_anonymous_unverified(self):
        item = RetrievedItem(item_id="1", layer=3, kind="raw_item", source_id="xueqiu",
                             title="匿名爆料", published_at="2026-08-04T10:00:00")
        n = NarrativeAnalyzer().analyze([item])
        assert any(u.get("reason") for u in n.unverified)


class TestContradictionChecker:
    def test_timing_contradiction(self):
        c = _candidate(timing_relation="BEFORE_MOVE",
                       published_at="2026-08-05T20:00:00")
        result = ContradictionChecker().check([c], [], _obs())
        assert any(x.kind == "timing" for x in result.contradictions)

    def test_entity_error(self):
        c = _candidate(entity_link_score=0)
        result = ContradictionChecker().check([c], [], _obs())
        assert any(x.kind == "entity" for x in result.contradictions)

    def test_high_authority_conflict(self):
        c = _candidate(source_reliability_score=5)
        links = [
            CauseEvidenceLink(link_id=new_uuid(), cause_candidate_id=c.cause_candidate_id,
                              evidence_id="e1", relation="supports", directness="direct",
                              timing_relation="before", independence_group="g1",
                              created_at="2026-08-05T20:00:00"),
            CauseEvidenceLink(link_id=new_uuid(), cause_candidate_id=c.cause_candidate_id,
                              evidence_id="e2", relation="contradicts", directness="direct",
                              timing_relation="before", independence_group="g2",
                              created_at="2026-08-05T20:00:00"),
        ]
        result = ContradictionChecker().check([c], links, _obs())
        assert result.high_authority_conflict is True


class TestAttributionSynthesizer:
    def test_explained(self):
        c = _candidate(final=85.0)
        score = ScoreResult(candidates=[c], links=[], primary_ids=[c.cause_candidate_id])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        assert synth.attribution.attribution_status == "EXPLAINED"
        assert synth.attribution.primary_cause_ids == [c.cause_candidate_id]

    def test_unexplained(self):
        c = _candidate(final=30.0, cause_category="after_the_fact_explanation",
                       causal_eligibility=False)
        score = ScoreResult(candidates=[c], links=[], excluded_ids=[c.cause_candidate_id])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        assert synth.attribution.attribution_status == "UNEXPLAINED_MOVE"

    def test_sample_insufficient_not_unexplained(self):
        """行情不足 -> INSUFFICIENT_EVIDENCE，不是 UNEXPLAINED_MOVE。"""
        score = ScoreResult(candidates=[], links=[])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(status="no_abnormal_move"), score, None,
            ContradictionChecker().check([], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute(),
            sample_insufficient=True)
        assert synth.attribution.attribution_status == "INSUFFICIENT_EVIDENCE"

    def test_source_conflict(self):
        c = _candidate(source_reliability_score=5)
        links = [CauseEvidenceLink(link_id=new_uuid(), cause_candidate_id=c.cause_candidate_id,
                                   evidence_id="e1", relation="supports", directness="direct",
                                   timing_relation="before", independence_group="g1",
                                   created_at="2026-08-05T20:00:00"),
                 CauseEvidenceLink(link_id=new_uuid(), cause_candidate_id=c.cause_candidate_id,
                                   evidence_id="e2", relation="contradicts", directness="direct",
                                   timing_relation="before", independence_group="g2",
                                   created_at="2026-08-05T20:00:00")]
        score = ScoreResult(candidates=[c], links=links)
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], links, _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        assert synth.attribution.attribution_status == "SOURCE_CONFLICT"

    def test_schema_valid(self):
        from research_os.validators.schema_validator import validate_model

        c = _candidate(final=85.0)
        score = ScoreResult(candidates=[c], links=[],
                            primary_ids=[c.cause_candidate_id])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        assert validate_model(synth.attribution) == []


class TestRenderer:
    def test_render_18_sections(self):
        c = _candidate(final=85.0)
        score = ScoreResult(candidates=[c], links=[],
                            primary_ids=[c.cause_candidate_id])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        ctx = RenderContext(
            run=_run(), attribution=synth.attribution, observation=_obs(),
            selection=_selection(), candidates=[c],
            metrics=[], peer_info={"effective_peers": 12, "advancing_ratio": 0.8,
                                   "peer_median_return": 0.01,
                                   "subject_cross_sectional_percentile": 95.0,
                                   "idiosyncratic": False},
            narrative=NarrativeAnalyzer().analyze([]),
            contradictions=[], entity_name="贵州茅台")
        text = AbnormalMoveRenderer().render(ctx)
        for i in range(1, 19):
            assert f"## {_SECTION_NAMES[i]}" in text, f"缺少章节 {i}"
        assert "scenario: abnormal_move_analysis" in text
        assert "attribution_status: EXPLAINED" in text
        assert "不构成目标价" in text

    def test_render_no_forbidden_words(self):
        c = _candidate(final=85.0)
        score = ScoreResult(candidates=[c], links=[],
                            primary_ids=[c.cause_candidate_id])
        synth = AttributionSynthesizer().synthesize(
            _request(), _obs(), score, _selection(),
            ContradictionChecker().check([c], [], _obs()),
            NarrativeAnalyzer().analyze([]), ModelRoute())
        ctx = RenderContext(
            run=_run(), attribution=synth.attribution, observation=_obs(),
            selection=_selection(), candidates=[c], entity_name="贵州茅台")
        text = AbnormalMoveRenderer().render(ctx)
        # 免责声明固定文案存在（任务书要求），且无实质建议类表述
        assert "不构成目标价" in text
        for word in ("买入评级", "卖出评级", "建议仓位", "明日交易", "可以买", "可以跟"):
            assert word not in text


_SECTION_NAMES = {
    1: "一、执行说明", 2: "二、对象和分析窗口", 3: "三、数据覆盖和降级",
    4: "四、异动事实", 5: "五、市场、行业和概念相对表现", 6: "六、结论摘要",
    7: "七、主要原因", 8: "八、次要原因", 9: "九、背景因素",
    10: "十、候选原因证据表", 11: "十一、板块和同类公司联动",
    12: "十二、媒体与市场叙事", 13: "十三、反证", 14: "十四、排除项",
    15: "十五、无法确认事项", 16: "十六、后续验证问题",
    17: "十七、来源与证据", 18: "十八、模型路由和限制",
}


class TestValidator:
    def _vctx(self, **kw) -> ValidationContext:
        base = dict(
            request=_request(), observation=_obs(),
            attribution=AttributionResult(
                attribution_result_id=new_uuid(), request_id=UUID,
                observation_id=OBS_ID, attribution_status="EXPLAINED",
                overall_confidence=0.8, model_route=ModelRoute()),
            run=_run(), candidates=[], links=[],
        )
        base.update(kw)
        return ValidationContext(**base)

    def test_clean_passes(self):
        v = AbnormalMoveValidator().validate(self._vctx())
        assert v.ok is True

    def test_recompute_mismatch_detected(self):
        from research_os.models import MarketDailyOhlcv

        bars = []
        from datetime import date, timedelta
        d = date(2026, 7, 1)
        price = 10.0
        for i in range(30):
            while d.weekday() >= 5:
                d += timedelta(days=1)
            bars.append(MarketDailyOhlcv(
                bar_id=new_uuid(), symbol="600519.SH", trade_date=d.isoformat(),
                open=price, high=price * 1.01, low=price * 0.99,
                close=price, volume=1000))
            price *= 1.001
            d += timedelta(days=1)
        # 观测 raw_return 与行情不符
        ctx = self._vctx(bars=bars,
                         observation=_obs(raw_return=0.5, move_start_at=None, move_end_at=None))
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[5]") for e in v.errors)

    def test_forbidden_words_detected(self):
        ctx = self._vctx(report_text="建议买入，目标价 2000 元")
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[32]") for e in v.errors)

    def test_unexplained_misuse_detected(self):
        ctx = self._vctx(
            observation=_obs(status="no_abnormal_move"),
            attribution=AttributionResult(
                attribution_result_id=new_uuid(), request_id=UUID,
                observation_id=OBS_ID, attribution_status="UNEXPLAINED_MOVE",
                overall_confidence=0.5, model_route=ModelRoute()))
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[26]") for e in v.errors)

    def test_after_fact_primary_detected(self):
        c = _candidate(cause_category="after_the_fact_explanation", final=80.0)
        ctx = self._vctx(
            candidates=[c],
            attribution=AttributionResult(
                attribution_result_id=new_uuid(), request_id=UUID,
                observation_id=OBS_ID, attribution_status="EXPLAINED",
                overall_confidence=0.8, primary_cause_ids=[c.cause_candidate_id],
                model_route=ModelRoute()))
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[14]") for e in v.errors)

    def test_snapshot_in_daily_detected(self):
        ctx = self._vctx(
            snapshot_ids=["snap-1"],
            observation=_obs(market_data_ids=["snap-1"]))
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[3]") for e in v.errors)

    def test_anonymous_primary_detected(self):
        c = _candidate(source_reliability_score=1, final=80.0)
        ctx = self._vctx(
            candidates=[c],
            attribution=AttributionResult(
                attribution_result_id=new_uuid(), request_id=UUID,
                observation_id=OBS_ID, attribution_status="EXPLAINED",
                overall_confidence=0.8, primary_cause_ids=[c.cause_candidate_id],
                model_route=ModelRoute()))
        v = AbnormalMoveValidator().validate(ctx)
        assert any(e.startswith("[18]") for e in v.errors)
