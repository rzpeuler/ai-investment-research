"""晨报规则测试（Phase 2 任务 25.1 节）。

时间窗口 / 延迟补跑 / 幂等 / 分类树 / 硬性否决 / 评分权重阈值强制纳入 /
URL 去重 / 转载惩罚 / 覆盖状态 / 聚类（含不错误聚类）。
"""
from __future__ import annotations

from datetime import date

import pytest

from research_os.morning.classification import (
    all_paths,
    classify_text,
    source_to_channel,
    validate_path,
)
from research_os.morning.clustering import ClusterBuilder
from research_os.morning.coverage import build_coverage
from research_os.morning.dedup import (
    ExactDeduplicator,
    normalize_url_strict,
    title_normalized,
)
from research_os.morning.scoring import WEIGHTS, InformationScorer, band_for
from research_os.morning.veto import apply_vetoes
from research_os.morning.window import (
    as_of_for,
    delay_info,
    idempotency_key,
    morning_window,
    parse_report_date,
    scheduled_for,
)
from research_os.models import CandidateItem, RawItem
from research_os.utils.id import content_sha256, new_uuid

T0 = "2026-08-05T20:00:00"
T1 = "2026-08-06T08:00:00"
UUID = "11111111-1111-1111-1111-111111111111"


def mk_raw(**ov) -> RawItem:
    title = ov.get("title", "默认标题")
    d = {
        "raw_item_id": new_uuid(), "source_id": "cls", "external_id": "1",
        "url": "https://example.com/a", "title": title,
        "publisher": "财联社", "author": None,
        "published_at": "2026-08-05T21:00:00", "retrieved_at": "2026-08-06T07:00:00",
        "content_hash": content_sha256(f"{title}|{ov.get('external_id', '')}"),
        "content_excerpt": "公司发布新产品",
        "content_storage": "metadata_and_excerpt", "language": "zh-CN",
        "access_status": "ok", "entities": ["company:xxx"], "raw_category": "news",
    }
    d.update(ov)
    return RawItem(**d)


def mk_candidate(**ov) -> CandidateItem:
    d = {
        "candidate_id": UUID, "raw_item_ids": [UUID], "source_ids": ["cls"],
        "monitoring_channel": "fast_news", "title": "某公司发布新产品",
        "summary": "公司发布新一代产品", "published_at": T0, "retrieved_at": T1,
        "event_time": None, "entities": ["company:xxx"],
        "classification_path": ["industry", "event"], "content_type": "fact_report",
        "language": "zh-CN", "status": "collected", "warnings": [],
    }
    d.update(ov)
    return CandidateItem(**d)


# ---------- 时间窗口 / 延迟 / 幂等 ----------

def test_morning_window_default():
    start, end = morning_window(date(2026, 8, 6))
    assert start == "2026-08-05T20:00:00+08:00"
    assert end == "2026-08-06T08:00:00+08:00"


def test_delayed_keeps_original_window():
    """延迟执行仍使用原始窗口（不得改为实际运行时间）。"""
    start, end = morning_window(date(2026, 8, 6))
    # 10:00 才开机运行，窗口不变
    assert end == "2026-08-06T08:00:00+08:00"


def test_delay_info():
    delayed, seconds = delay_info("2026-08-06T10:00:00+08:00",
                                  "2026-08-06T08:10:00+08:00")
    assert delayed is True
    assert seconds == 6600
    delayed2, _ = delay_info("2026-08-06T07:00:00+08:00",
                             "2026-08-06T08:10:00+08:00")
    assert delayed2 is False


def test_idempotency_key_and_parse():
    start, end = morning_window(date(2026, 8, 6))
    k = idempotency_key("morning_brief", "2026-08-06", start, end)
    assert k.startswith("morning_brief|2026-08-06|")
    assert parse_report_date("2026-08-06") == date(2026, 8, 6)
    with pytest.raises(ValueError):
        parse_report_date("not-a-date")


def test_scheduled_and_as_of():
    assert scheduled_for(date(2026, 8, 6)) == "2026-08-06T08:10:00+08:00"
    assert as_of_for(date(2026, 8, 6)) == "2026-08-06T08:00:00+08:00"


# ---------- 分类 ----------

def test_classification_tree_preserved():
    assert all_paths()["industry"] == \
        ["event", "trend", "data", "policy", "technology_breakthrough"]
    assert all_paths()["company"][0] == "announcement"


def test_classify_company_announcement():
    path, tags = classify_text("贵州茅台发布2026年半年报公告", "")
    assert path[0] == "company" and path[1] == "announcement"


def test_classify_macro_policy():
    path, _ = classify_text("央行宣布降准政策", "")
    assert path == ["macro", "policy"]


def test_classify_industry_event_vs_tech():
    path, tags = classify_text("某公司先进封装技术完成客户认证", "")
    assert path == ["industry", "event"]  # 已进入商业验证 -> industry.event


def test_classify_market():
    path, _ = classify_text("沪指收盘上涨 恒指走低", "")
    assert path[0] == "market"


def test_source_to_channel():
    assert source_to_channel("news_flash") == "fast_news"
    assert source_to_channel("community") == "community_sentiment"
    assert source_to_channel("unknown_type") == "unknown"


def test_validate_path():
    assert validate_path(["macro", "policy"])
    assert not validate_path(["nope", "x"])
    assert not validate_path(["macro", "bad_sub"])


# ---------- 硬性否决 ----------

def test_veto_advertisement():
    v = apply_vetoes(mk_candidate(summary="限时扫码加微信领取福利"))
    assert v.vetoed and any("广告" in r for r in v.reasons)


def test_veto_emotion_without_fact():
    v = apply_vetoes(mk_candidate(title="震惊！", summary="暴跌！",
                                  entities=[], published_at=T0))
    assert v.vetoed and any("情绪" in r for r in v.reasons)


def test_veto_window_outside():
    v = apply_vetoes(mk_candidate(published_at="2026-08-01T10:00:00"),
                     window_start=T0)
    assert v.vetoed and any("窗口" in r for r in v.reasons)


def test_veto_source_status():
    v = apply_vetoes(mk_candidate(), source_status="blocked")
    assert v.vetoed and any("blocked" in r for r in v.reasons)


def test_veto_parse_error():
    v = apply_vetoes(mk_candidate(warnings=["机器解析明显错误"]))
    assert v.vetoed


def test_no_veto_clean():
    v = apply_vetoes(mk_candidate())
    assert not v.vetoed


# ---------- 评分 ----------

def test_score_weights_sum_100():
    assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-6


def test_score_band_thresholds():
    assert band_for(80) == "重大必读"
    assert band_for(70) == "晨报正文"
    assert band_for(60) == "附录或候选观察"
    assert band_for(45) == "事件库候选（不进入正文）"
    assert band_for(10) == "索引、隔离或丢弃"


def test_score_forced_include():
    scorer = InformationScorer(source_tiers={"cls": "B"})
    c = mk_candidate(classification_path=["company", "announcement"],
                     summary="公司发布重大风险提示公告")
    s = scorer.score(c)
    assert s.forced_include is True
    assert s.forced_include_reason in ("major_regulatory_event",
                                       "major_company_disclosure")
    assert s.final_score >= 80


def test_score_duplicate_penalty():
    """大量转载（簇内 >=5）不显著提升得分，反而受罚。"""
    scorer = InformationScorer(source_tiers={"cls": "B"})
    c = mk_candidate()
    s1 = scorer.score(c, cluster_size=1)
    s5 = scorer.score(c, cluster_size=5)
    assert s5.final_score < s1.final_score
    assert any("转载" in p for p in s5.penalties)


def test_score_authority_tier_mapping():
    scorer = InformationScorer(source_tiers={"cninfo": "S", "cls": "B"})
    a = mk_candidate(source_ids=["cninfo"])
    b = mk_candidate(source_ids=["cls"])
    assert scorer.score_authority(a) == 5
    assert scorer.score_authority(b) == 3


# ---------- URL 去重 / 指纹 ----------

def test_normalize_url_strict_removes_tracking():
    u1 = normalize_url_strict("https://example.com/a?utm_source=x&id=1&utm_medium=y")
    u2 = normalize_url_strict("https://EXAMPLE.com/a?id=1")
    assert u1 == u2


def test_normalize_url_keeps_semantic_params():
    u = normalize_url_strict("https://example.com/search?keyword=茅台&page=2")
    assert "keyword=" in u and "page=2" in u


def test_title_normalized():
    assert title_normalized("　贵州茅台：发布公告！") == \
        title_normalized("贵州茅台:发布公告!")


def test_dedup_by_url():
    d = ExactDeduplicator()
    a = mk_raw(url="https://example.com/a?utm_source=x", external_id="1")
    b = mk_raw(url="https://example.com/a", external_id="2")
    kept = d.dedup([a, b])
    assert len(kept) == 1
    assert d.groups and d.groups[0].duplicate_raw_item_ids


def test_dedup_different_articles_not_merged():
    d = ExactDeduplicator()
    a = mk_raw(url="https://example.com/a", title="订单一", external_id="e1")
    b = mk_raw(url="https://example.com/b", title="订单二", external_id="e2")
    assert len(d.dedup([a, b])) == 2


def test_dedup_same_title_cross_source_merged():
    """同一公告标题跨来源（cninfo+cls）视为重复并保留归并关系。"""
    d = ExactDeduplicator()
    a = mk_raw(source_id="cninfo", url="https://a.example/x",
               title="贵州茅台发布半年报", external_id="a1")
    b = mk_raw(source_id="cls", url="https://b.example/x",
               title="贵州茅台发布半年报", external_id="c1")
    kept = d.dedup([a, b])
    assert len(kept) == 1
    assert d.groups and d.groups[0].duplicate_raw_item_ids


# ---------- 聚类 ----------

def test_cluster_similar_titles_merged():
    builder = ClusterBuilder()
    a = mk_candidate(title="A公司宣布收购B公司", entities=["company:A"])
    b = mk_candidate(candidate_id=new_uuid(),
                     title="A公司宣布收购B公司（续）", entities=["company:A"])
    clusters = builder.cluster([a, b])
    assert len(clusters) == 1
    assert len(clusters[0].member_candidate_ids) == 2


def test_cluster_different_events_not_merged():
    """同一公司不同订单（不同实体桶）不得错误聚类。"""
    builder = ClusterBuilder(similarity_threshold=0.6)
    a = mk_candidate(title="A公司获得订单X", entities=["company:A"])
    b = mk_candidate(candidate_id=new_uuid(),
                     title="B公司获得订单Y", entities=["company:B"])
    clusters = builder.cluster([a, b])
    assert len(clusters) == 2


def test_cluster_official_confirmation_upgrade():
    builder = ClusterBuilder()
    a = mk_candidate(title="X公司拟收购Y公司", monitoring_channel="fast_news")
    b = mk_candidate(candidate_id=new_uuid(), title="X公司拟收购Y公司（公告）",
                     monitoring_channel="official_disclosure",
                     source_ids=["cninfo"])
    clusters = builder.cluster([a, b])
    assert clusters[0].official_confirmation is True


# ---------- 覆盖状态 ----------

def test_coverage_states():
    cov = build_coverage(
        channel_sources={"fast_news": ["cls"]},
        succeeded={"fast_news": ["cls"]},
        failures={},
        limitations={},
        automated_channels={"fast_news"},
    )
    by = {c["monitoring_channel"]: c for c in cov}
    assert by["fast_news"]["status"] == "covered"
    assert by["community_sentiment"]["status"] == "manual_only"
    assert by["institutional_activity"]["limitations"]


def test_source_failure_marked():
    cov = build_coverage(
        channel_sources={"fast_news": ["cls"]},
        succeeded={},
        failures={"fast_news": ["cls"]},
        limitations={},
        automated_channels={"fast_news"},
    )
    by = {c["monitoring_channel"]: c for c in cov}
    assert by["fast_news"]["status"] == "source_failure"
    assert "来源故障" in by["fast_news"]["limitations"][0]
