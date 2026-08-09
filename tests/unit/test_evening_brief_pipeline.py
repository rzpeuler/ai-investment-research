"""evening_brief 共享流水线测试（Phase 6B B1）。

验证：与 morning 相同的处理规则（分类/过滤阈值/评分/校验/渲染）、窗口内去重、
窗口内聚类、无跨报告依赖、无 material_update 层、幂等重跑。
"""
from __future__ import annotations

from datetime import date

from research_os.brief.pipeline import BriefPipeline, PipelineConfig
from research_os.brief.window import evening_policy, morning_policy
from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid

DAY = date(2026, 8, 6)
EVENING = evening_policy()
CHANNELS = {"cninfo": "official_disclosure", "cls": "fast_news",
            "nbs": "government_and_regulator", "manual_inbox": "manual_submission"}
TIERS = {"cninfo": "S", "cls": "B", "nbs": "S", "manual_inbox": "C"}


def evening_pipeline() -> BriefPipeline:
    return BriefPipeline(PipelineConfig(
        source_tiers=TIERS, source_status={}, channel_map=CHANNELS,
    ), window_policy=EVENING)


def _raw(title: str, published: str = "2026-08-06T10:00:00+08:00",
         source_id: str = "cls", entities=None, excerpt: str = "") -> RawItem:
    return RawItem(
        raw_item_id=new_uuid(), source_id=source_id, external_id=new_uuid(),
        url=f"https://example.com/{new_uuid()}", title=title, publisher="财联社",
        author=None, published_at=published, retrieved_at="2026-08-06T20:00:00",
        content_hash=content_sha256(f"{title}|{new_uuid()}"),
        content_excerpt=excerpt or title, content_storage="metadata_and_excerpt",
        language="zh-CN", access_status="ok",
        entities=entities or [], raw_category="news",
    )


def test_same_processing_rules_as_morning():
    """内容相同的候选分别进入 morning 与 evening 窗口，分类/过滤/评分规则一致。

    两个窗口不重叠，故发布时间按各自窗口适配；处理链共用（规则一致）。
    """
    # morning 窗口：前一日 20:00 → 当日 08:00
    m_items = [
        _raw("工信部发布半导体产业支持新政策", entities=["industry:semiconductor"],
             published="2026-08-05T21:00:00+08:00"),
        _raw("某公司公告：因违规被立案调查", source_id="cninfo",
             entities=["company:bad"], published="2026-08-05T22:00:00+08:00"),
        _raw("震惊！内部消息某股要崩了", entities=[], published="2026-08-05T23:00:00+08:00"),
    ]
    # evening 窗口：当日 08:00 → 20:00（内容相同，仅发布时间不同）
    e_items = [
        _raw("工信部发布半导体产业支持新政策", entities=["industry:semiconductor"],
             published="2026-08-06T10:00:00+08:00"),
        _raw("某公司公告：因违规被立案调查", source_id="cninfo",
             entities=["company:bad"], published="2026-08-06T14:00:00+08:00"),
        _raw("震惊！内部消息某股要崩了", entities=[], published="2026-08-06T15:00:00+08:00"),
    ]
    m = BriefPipeline(PipelineConfig(source_tiers=TIERS, source_status={}, channel_map=CHANNELS),
                      window_policy=morning_policy()).run(
        m_items, DAY, as_of="2026-08-06T08:00:00+08:00")
    e = evening_pipeline().run(e_items, DAY, as_of="2026-08-06T20:00:00+08:00")
    m_by_title = {c.title: c for c in m.candidates}
    e_by_title = {c.title: c for c in e.candidates}
    assert set(m_by_title) == set(e_by_title)
    # 分类路径一致
    for title, mc in m_by_title.items():
        assert e_by_title[title].classification_path == mc.classification_path
    # 否决判定一致（震惊帖两条都被否决：status=vetoed 且不进入评分）
    for art in (m, e):
        shock = next((c for c in art.candidates if c.title == "震惊！内部消息某股要崩了"), None)
        assert shock is not None and shock.status == "vetoed"
        assert all(s["candidate_id"] != shock.candidate_id for s in art.scores)
    # 评分规则一致：同标题候选 final_score 相同
    m_scores = {c.title: s["final_score"] for c in m.candidates
                for s in m.scores if s["candidate_id"] == c.candidate_id}
    e_scores = {c.title: s["final_score"] for c in e.candidates
                for s in e.scores if s["candidate_id"] == c.candidate_id}
    for title in m_scores:
        assert e_scores.get(title) == m_scores[title], f"评分规则不一致: {title}"


def test_same_filtering_thresholds_and_safety_validation():
    """同一过滤阈值（>=65 正文 / 55-64 附录）与安全校验。"""
    items = [
        _raw("某光伏龙头签订10GW组件长单", entities=["company:solar"],
             published="2026-08-06T11:00:00+08:00"),
        _raw("国家统计局：7月CPI同比上涨0.5%", source_id="nbs",
             published="2026-08-06T09:30:00+08:00"),
    ]
    e = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    selected = {s["candidate_id"] for s in e.scores
                if s["final_score"] >= 65 or s["forced_include"]}
    assert selected, "高价值信息应入选正文（同晨报阈值）"
    for s in e.scores:
        assert 0 <= s["final_score"] <= 100
    # Evidence 机械校验通过（pipeline 内部已执行 validate_brief_evidence）
    assert e.evidences
    assert e.markdown
    # 输出安全：渲染文本不得包含禁止词
    from research_os.reports import FORBIDDEN_WORDS
    for word in FORBIDDEN_WORDS:
        assert word not in e.markdown, f"晚报渲染含禁止词: {word}"


def test_window_internal_dedup():
    """窗口内精确去重：同 URL/指纹重复只保留一条。"""
    dup = _raw("某公司发布半年报", published="2026-08-06T10:00:00+08:00")
    items = [dup]
    # 模拟转载：同标题不同 URL 也会被 title 指纹去重
    items.append(_raw("某公司发布半年报", published="2026-08-06T10:05:00+08:00"))
    e = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    titles = [c.title for c in e.candidates]
    assert titles.count("某公司发布半年报") == 1
    assert e.duplicate_groups, "去重关系应被记录（可审计）"


def test_window_internal_clustering():
    """窗口内聚类：快讯+公告合并为同一事件簇。"""
    items = [
        _raw("贵州茅台发布半年报", source_id="cninfo", entities=["company:600519.SH"],
             published="2026-08-06T10:00:00+08:00"),
        _raw("贵州茅台半年报：营收同比增长15%", entities=["company:600519.SH"],
             published="2026-08-06T10:30:00+08:00"),
    ]
    e = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    assert len(e.clusters) == 1, f"同事件应聚为一簇: {[c.canonical_title for c in e.clusters]}"


def test_no_cross_report_morning_dependency():
    """晚报不依赖晨报产物：同一窗口内独立处理，无 morning 输入。"""
    items = [_raw("某公司公告：因违规被立案调查", source_id="cninfo",
                  entities=["company:bad"], published="2026-08-06T14:00:00+08:00")]
    e = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    assert e.claims, "晚报独立生成 Claim（无跨报告依赖）"
    # pipeline 输出无任何 morning 引用字段
    assert all("morning" not in str(c.model_dump()).lower() for c in e.candidates)
    for cl in e.clusters:
        assert "morning" not in cl.canonical_title.lower()


def test_no_material_update_layer():
    """pipeline 无 material_update / new_since_morning 阶段。"""
    import inspect

    from research_os.brief import pipeline as brief_pipeline

    src = inspect.getsource(brief_pipeline)
    for banned in ("material_update", "new_since_morning", "already_known_in_morning",
                   "cross_report", "cross-report"):
        assert banned not in src, f"共享 pipeline 不得包含 {banned}"


def test_idempotent_rerun_same_input():
    """同一输入重跑：结构化产物确定性一致（同规则、无随机分叉）。

    candidate_id 每次生成新 UUID（身份），但分数/分类/选择结果确定。
    """
    items = [_raw("某光伏龙头签订10GW组件长单", entities=["company:solar"],
                  published="2026-08-06T11:00:00+08:00")]
    a1 = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    a2 = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    assert len(a1.scores) == len(a2.scores)
    s1 = sorted(s["final_score"] for s in a1.scores)
    s2 = sorted(s["final_score"] for s in a2.scores)
    assert s1 == s2
    c1 = sorted((c.title, tuple(c.classification_path)) for c in a1.candidates)
    c2 = sorted((c.title, tuple(c.classification_path)) for c in a2.candidates)
    assert c1 == c2


def test_late_run_window_internal_dedup_still_applies():
    """补跑时窗口内信息仍走同一去重/聚类/筛选链。"""
    items = [
        _raw("某公司发布半年报", source_id="cninfo", published="2026-08-06T09:00:00+08:00"),
        _raw("某公司发布半年报", published="2026-08-06T09:10:00+08:00"),
        _raw("窗口外", published="2026-08-06T20:30:00+08:00"),
    ]
    e = evening_pipeline().run(items, DAY, as_of="2026-08-06T20:00:00+08:00")
    titles = [c.title for c in e.candidates]
    assert titles.count("某公司发布半年报") == 1
    assert "窗口外" not in titles
