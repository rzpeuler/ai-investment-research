"""晨报流水线集成测试（Phase 2 任务 25.2/25.3 节）。

CNINFO＋CLS＋NBS 风格 fixture 进入同一流水线；全流程验证。
"""
from __future__ import annotations

from datetime import date

import pytest

from research_os.morning.pipeline import MorningBriefPipeline, PipelineConfig
from research_os.models import RawItem
from research_os.utils.id import content_sha256, new_uuid

REPORT_DATE = date(2026, 8, 6)

CHANNELS = {
    "cninfo": "official_disclosure", "cls": "fast_news", "nbs": "government_and_regulator",
    "manual_inbox": "manual_submission",
}
TIERS = {"cninfo": "S", "cls": "B", "nbs": "S", "manual_inbox": "C"}


def raw(**ov) -> RawItem:
    title = ov.get("title", "默认标题")
    d = {
        "raw_item_id": new_uuid(), "source_id": "cls", "external_id": "1",
        "url": "https://example.com/x", "title": title,
        "publisher": "财联社", "author": None,
        "published_at": "2026-08-05T21:00:00", "retrieved_at": "2026-08-06T07:00:00",
        "content_hash": content_sha256(f"{title}|{ov.get('external_id', '')}"),
        "content_excerpt": "默认摘要",
        "content_storage": "metadata_and_excerpt", "language": "zh-CN",
        "access_status": "ok", "entities": [], "raw_category": "news",
    }
    d.update(ov)
    return RawItem(**d)


@pytest.fixture()
def pipeline():
    return MorningBriefPipeline(PipelineConfig(
        source_tiers=TIERS, source_status={}, channel_map=CHANNELS))


def _rich_items():
    return [
        raw(source_id="cninfo", title="贵州茅台发布2026年半年报公告", external_id="a1",
            url="https://static.cninfo.com.cn/a1", entities=["company:600519.SH"],
            content_excerpt="公司发布半年报，营收同比增长"),
        raw(source_id="cls", title="贵州茅台发布2026年半年报公告", external_id="c1",
            url="https://www.cls.cn/telegraph/c1", entities=["company:600519.SH"],
            content_excerpt="财联社快讯：贵州茅台披露半年报"),
        raw(source_id="nbs", title="国家统计局发布7月CPI数据", external_id="n1",
            url="https://www.stats.gov.cn/n1", entities=[],
            content_excerpt="7月CPI同比上涨"),
        raw(source_id="cls", title="某公司推出新款AI芯片", external_id="c2",
            url="https://www.cls.cn/telegraph/c2", entities=["company:chip"],
            content_excerpt="发布新一代AI芯片"),
    ]


def test_pipeline_full_flow(pipeline):
    """完整流水线：去重 -> 聚类 -> 分类 -> 评分 -> 渲染 -> 校验。"""
    artifacts = pipeline.run(_rich_items(), REPORT_DATE)
    # 去重：cninfo + cls 同标题 -> 一个簇
    assert artifacts.duplicate_groups  # 归并关系保留
    assert len(artifacts.candidates) >= 3
    # 分类
    paths = {tuple(c.classification_path) for c in artifacts.candidates}
    assert ("company", "announcement") in paths
    assert ("macro", "economic_data") in paths
    # 聚类：半年报 cninfo+cls 合并为一簇
    assert len(artifacts.clusters) <= len(artifacts.candidates)
    # 评分与选择
    assert artifacts.scores
    assert all(0 <= s["final_score"] <= 100 for s in artifacts.scores)
    # 渲染
    assert "# A股每日晨报 2026-08-06" in artifacts.markdown
    assert "## 一、重大必读" in artifacts.markdown
    assert "## 六、四个监测方向覆盖" in artifacts.markdown
    assert "## 七、隔夜外围总结" in artifacts.markdown
    # 校验（报告写临时文件后过 validator）
    import tempfile
    from pathlib import Path

    from research_os.reports import validate_report

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "morning.md"
        p.write_text(artifacts.markdown, encoding="utf-8")
        result = validate_report(p)
        assert result.ok, result.errors


def test_pipeline_empty_input(pipeline):
    """所有来源失败/无输入：仍生成结构化产物与降级说明（不得报错）。"""
    artifacts = pipeline.run([], REPORT_DATE)
    assert artifacts.candidates == []
    assert artifacts.markdown
    assert "未纳入正文" in artifacts.markdown
    assert any("manual_only" == c["status"] or c["status"] != "covered"
               for c in artifacts.coverage)
    assert artifacts.missing_data  # 降级说明存在


def test_pipeline_window_filter(pipeline):
    """窗口外旧闻排除（不进候选，记录警告）。"""
    items = _rich_items() + [raw(title="窗口外旧闻", external_id="old",
                                 published_at="2026-08-01T10:00:00")]
    artifacts = pipeline.run(items, REPORT_DATE)
    assert not any(c.title == "窗口外旧闻" for c in artifacts.candidates)
    assert any("窗口外" in w for w in artifacts.warnings)


def test_pipeline_veto_quarantines(pipeline):
    """广告/情绪信息被否决并记录。"""
    items = _rich_items() + [raw(title="震惊！限时扫码领取福利", external_id="ad",
                                 content_excerpt="震惊！", entities=[])]
    artifacts = pipeline.run(items, REPORT_DATE)
    assert any(c.title.startswith("震惊") for c in artifacts.vetoed)


def test_pipeline_claims_and_conflicts(pipeline):
    """Claim 生成 + 冲突检测。"""
    items = _rich_items() + [
        raw(source_id="cls", title="A公司收购B公司 估值100亿", external_id="k1",
            url="https://www.cls.cn/k1", entities=["company:A"], content_excerpt="估值100亿"),
        raw(source_id="cls", title="A公司收购B公司 估值120亿", external_id="k2",
            url="https://www.cls.cn/k2", entities=["company:A"], content_excerpt="估值120亿"),
    ]
    artifacts = pipeline.run(items, REPORT_DATE)
    assert artifacts.claims
    types = {c["claim_type"] for c in artifacts.claims}
    assert types <= {"FACT", "SOURCE_OPINION", "MODEL_INFERENCE", "UNKNOWN", "CONFLICT"}
    # 数值不一致 -> 至少一个簇带冲突
    assert any(cl.conflicts for cl in artifacts.clusters)


def test_pipeline_artifacts_written_to_run_dir(pipeline, tmp_path):
    """流水线产物写入运行目录（二十三节清单）。"""
    from research_os.orchestrator import RunDirectory

    run_dir = RunDirectory(tmp_path, "task-1")
    run_dir.create()
    artifacts = pipeline.run(_rich_items(), REPORT_DATE, run_dir=run_dir)
    for f in ("candidate_items.json", "duplicate_groups.json",
              "event_clusters.json", "scores.json", "claims.json",
              "source_coverage.json"):
        assert (run_dir.root / f).exists(), f"缺少 {f}"
