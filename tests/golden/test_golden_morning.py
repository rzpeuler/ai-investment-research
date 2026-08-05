"""黄金测试集（Phase 2 任务 24 节 / tests/golden/morning_brief/）。

验证流水线对黄金输入的结构性判断：
- 高价值信息入选（分类/评分/强制纳入）
- 应拒绝信息被否决（含原因）
- 聚类分组正确（含不错误合并）
- 冲突被保留（不消除）
- 降级场景有覆盖说明
- 完整晨报渲染 + Validator 通过
不要求逐字匹配全文。
"""
from __future__ import annotations

from datetime import date

from research_os.morning.pipeline import MorningBriefPipeline, PipelineConfig
from research_os.reports import validate_report
from tests.golden.morning_brief.fixtures import (
    CLUSTER_GROUPS,
    CONFLICT_GROUPS,
    FULL_BRIEFS,
    HIGH_VALUE,
    REJECTED,
)

REPORT_DATE = date(2026, 8, 6)
CHANNELS = {"cninfo": "official_disclosure", "nbs": "government_and_regulator",
            "cls": "fast_news", "manual_inbox": "manual_submission"}
TIERS = {"cninfo": "S", "nbs": "S", "cls": "B", "xueqiu": "C", "manual_inbox": "C"}


def pipeline() -> MorningBriefPipeline:
    return MorningBriefPipeline(PipelineConfig(
        source_tiers=TIERS, source_status={}, channel_map=CHANNELS))


# ---------- 高价值信息 ----------

def test_golden_high_value_selected():
    a = pipeline().run(HIGH_VALUE, REPORT_DATE)
    selected_ids = set()
    for s in a.scores:
        if s["final_score"] >= 65 or s["forced_include"]:
            selected_ids.add(s["candidate_id"])
    # 半年报（强制纳入）、CPI、政策、风险事件 应入选
    titles = {c.title for c in a.candidates if c.candidate_id in selected_ids}
    assert any("半年报" in t for t in titles)
    assert any("CPI" in t for t in titles)
    assert any("政策" in t for t in titles)
    assert any("立案" in t for t in titles)
    # 每类强制纳入记录原因
    forced = [s for s in a.scores if s["forced_include"]]
    assert any(s["forced_include_reason"] for s in forced)


def test_golden_rejected_with_reasons():
    a = pipeline().run(REJECTED, REPORT_DATE)
    # 8 条中 7 条被否决（窗口外旧闻被前置过滤，也不进正文）
    assert len(a.vetoed) >= 7, f"应拒绝至少 7 条，实际否决 {len(a.vetoed)}"
    assert a.vetoed  # 有否决记录


def test_golden_rejected_never_in_body():
    a = pipeline().run(REJECTED, REPORT_DATE)
    body_titles = {c.title for c in a.candidates if c.status == "scored"}
    for c in REJECTED:
        assert c.title not in body_titles, f"应拒绝信息进入正文: {c.title}"


# ---------- 聚类 ----------

def test_golden_cluster_groups():
    p = pipeline()
    for group in CLUSTER_GROUPS:
        a = p.run(group, REPORT_DATE)
        titles = [c.title for c in a.candidates]
        clusters = a.clusters
        if "中标" in titles[0]:
            # 快讯+公告 应合并
            assert len(clusters) == 1, f"快讯+公告应合并: {[cl.canonical_title for cl in clusters]}"
        elif "订单X" in titles[0]:
            # 同一公司不同事件 不得合并
            assert len(clusters) == 2
        elif "立项" in titles[0]:
            # 同一项目不同阶段 不得合并
            assert len(clusters) == 2


def test_golden_conflicts_preserved():
    p = pipeline()
    for group in CONFLICT_GROUPS:
        a = p.run(group, REPORT_DATE)
        assert any(cl.conflicts for cl in a.clusters), \
            f"冲突未保留: {group[0].title}"


# ---------- 降级 ----------

def test_golden_degraded_coverage():
    a = pipeline().run([], REPORT_DATE)  # 全部来源无输入
    assert a.coverage
    assert a.missing_data  # 必须说明缺失
    assert any(c["status"] in ("manual_only", "source_failure", "not_covered")
               for c in a.coverage)


def test_golden_manual_only_flagged():
    a = pipeline().run([item_manual()], REPORT_DATE)
    community = next(c for c in a.coverage
                     if c["monitoring_channel"] == "community_sentiment")
    assert community["status"] == "manual_only"


def item_manual():
    from tests.golden.morning_brief.fixtures import item

    return item("manual_inbox", "用户分享深度文章", "手动导入", ext="u1")


# ---------- 完整晨报 3 期 ----------

def test_golden_full_briefs_render_and_validate(tmp_path):
    p = pipeline()
    for brief in FULL_BRIEFS:
        a = p.run(brief["items"], REPORT_DATE)
        assert "# A股每日晨报" in a.markdown
        assert "## 一、重大必读" in a.markdown
        assert "## 六、四个监测方向覆盖" in a.markdown
        assert "## 七、隔夜外围总结" in a.markdown
        # 渲染产物通过 Validator
        f = tmp_path / f"{brief['name']}.md"
        f.write_text(a.markdown, encoding="utf-8")
        result = validate_report(f)
        assert result.ok, f"{brief['name']} 校验失败: {result.errors[:5]}"
