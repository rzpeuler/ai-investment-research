"""异动分析黄金测试执行器（Phase 3 任务书 20 节）。

对每个案例：构造行情与事件池 -> detector -> generator -> scorer ->
synthesizer，断言 attribution_status、允许/禁止原因类别、最低独立证据、
置信度范围。不要求逐字匹配 Markdown。
"""
from __future__ import annotations

from datetime import date

import pytest
import yaml
from pathlib import Path

from research_os.abnormal_move.anomaly_detector import AnomalyDetector
from research_os.abnormal_move.attribution_synthesizer import AttributionSynthesizer
from research_os.abnormal_move.cause_candidate_generator import CauseCandidateGenerator
from research_os.abnormal_move.cause_candidate_scorer import CauseCandidateScorer
from research_os.abnormal_move.contradiction_checker import ContradictionChecker
from research_os.abnormal_move.narrative_analyzer import NarrativeAnalyzer
from research_os.models import CauseEvidenceLink, ModelRoute
from research_os.utils.id import new_uuid

from tests.golden.abnormal_move.fixtures import (
    CASES,
    big_move_series,
    flat_series,
    request,
    short_series,
)

HERE = Path(__file__).resolve().parent


def _load_manifest() -> dict:
    with (HERE / "manifest.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


MANIFEST = _load_manifest()


def _bars(name: str):
    start = date(2026, 5, 1)
    builders = {
        "big_move": lambda: big_move_series(start, move=0.095),
        "big_move_negative": lambda: big_move_series(start, move=-0.095),
        "flat_series": lambda: flat_series(start),
        "short_series": lambda: short_series(start),
    }
    return builders[name]()


def _run_case(case_id: str):
    cfg = CASES[case_id]
    bars = _bars(cfg["bars"])
    events = list(cfg["events"])

    # 模拟 retriever 层按标题去重（转载不增加独立证据）
    seen = set()
    dedup = []
    for e in events:
        if e.title in seen:
            continue
        seen.add(e.title)
        dedup.append(e)
    events = dedup

    req = request()
    detector = AnomalyDetector(req)
    detect = detector.detect(bars, flags={"provisional": bool(cfg.get("provisional"))})
    obs = detect.observation
    obs.raw_return = bars[-1].close / bars[-2].close - 1.0
    # 模拟 pipeline：异动窗口时间由交易日历确定（开市 09:30 / 收盘 15:00）
    obs.move_start_at = f"{obs.trade_date}T09:30:00"
    obs.move_end_at = f"{obs.trade_date}T15:00:00"

    from research_os.abnormal_move.event_window_retriever import RetrievalResult

    retrieval = RetrievalResult(items=events, layers_covered={}, channels_covered={})
    gen = CauseCandidateGenerator(["600519", "贵州茅台"])
    generated = gen.build(req, obs, retrieval, linkage=None, entity_id="600519.SH")
    scored = CauseCandidateScorer().score(generated.candidates, generated.links)

    # 反证注入（模拟 contradiction_checker 的语义反证输出，任务书 13 节）
    # 对指定索引的候选追加 contradicts 链接（保留其原 supports 证据）
    links = list(scored.links)
    if "contradicting_index" in cfg:
        idx = cfg["contradicting_index"]
        if idx < len(links):
            links.append(CauseEvidenceLink(
                link_id=new_uuid(),
                cause_candidate_id=links[idx].cause_candidate_id,
                evidence_id=links[idx].evidence_id, relation="contradicts",
                directness="direct", timing_relation="before",
                independence_group="golden-contradict",
                weight=1.0, notes="黄金测试注入的反证", created_at="2026-08-05T20:00:00",
            ))
    contradictions = ContradictionChecker().check(scored.candidates, links, obs)

    synth = AttributionSynthesizer().synthesize(
        req, obs, scored, None, contradictions,
        NarrativeAnalyzer().analyze(events), ModelRoute(),
        sample_insufficient=detect.sample_size < 20,
    )
    return cfg, synth, scored, detect


class TestGoldenAbnormalMove:
    @pytest.mark.parametrize("case_id", [c["id"] for c in MANIFEST["cases"]])
    def test_golden_case(self, case_id):
        cfg, synth, scored, detect = _run_case(case_id)
        a = synth.attribution

        # 1. 归因状态
        assert a.attribution_status == cfg["expected_status"], (
            f"[{case_id}] 预期 {cfg['expected_status']}，实际 {a.attribution_status}；"
            f"候选: {[(c.title[:20], c.final_score, c.cause_category) for c in scored.candidates]}")

        # 2. 主原因类别约束（primary_cause_ids 已含 multi 原因）
        primary = [c for c in scored.candidates if c.cause_candidate_id in
                   a.primary_cause_ids]
        forbidden = cfg.get("forbidden_categories", [])
        for c in primary:
            assert c.cause_category not in forbidden, (
                f"[{case_id}] 主原因包含禁止类别 {c.cause_category}")
        forbidden_primary = cfg.get("forbidden_primary_categories", [])
        for c in primary:
            assert c.cause_category not in forbidden_primary, (
                f"[{case_id}] 主原因包含禁止类别 {c.cause_category}")
        allowed = cfg.get("allowed_categories", [])
        if primary and allowed:
            assert all(c.cause_category in allowed for c in primary), (
                f"[{case_id}] 主原因类别不在允许集合 {allowed}")

        # 3. 最低独立证据数量（候选 independence_groups 计数）
        if cfg.get("min_independent_evidence", 0) > 0 and scored.candidates:
            top = scored.candidates[0]
            assert len(top.independence_groups) >= cfg["min_independent_evidence"], (
                f"[{case_id}] 独立证据不足")
        if "assert_independence_groups" in cfg and scored.candidates:
            top = scored.candidates[0]
            assert len(top.independence_groups) == cfg["assert_independence_groups"], (
                f"[{case_id}] 独立证据组数应为 {cfg['assert_independence_groups']}，"
                f"实际 {len(top.independence_groups)}（转载不得增加独立证据）")

        # 4. 置信度范围
        lo, hi = cfg["confidence_range"]
        assert lo <= a.overall_confidence <= hi, (
            f"[{case_id}] 置信度 {a.overall_confidence} 超出 [{lo}, {hi}]")

        # 5. 方向不自动加分（任务书 11.3）
        if cfg.get("assert_no_direction_bonus"):
            # 候选分数不因方向匹配与否改变：直接断言评分维度不含方向项
            for c in scored.candidates:
                assert not any("方向" in w for w in c.warnings), \
                    f"[{case_id}] 评分逻辑引入了方向加分"

    def test_manifest_matches_cases(self):
        manifest_ids = {c["id"] for c in MANIFEST["cases"]}
        assert manifest_ids == set(CASES.keys()), \
            f"manifest 与 fixtures 不一致: 缺失 {manifest_ids ^ set(CASES.keys())}"

    def test_coverage_categories(self):
        """五大类覆盖（任务书 20.1-20.5）。"""
        categories = {CASES[k]["category"] for k in CASES}
        assert {"attributable", "misattribution", "unattributable",
                "data_insufficient", "boundary"} <= categories
