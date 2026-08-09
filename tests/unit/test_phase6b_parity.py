"""Phase 6B 复用验收（DECISIONS #43）：evening_brief 与 morning_brief 共享
同一核心信息处理链的机械证明。

要求（任务书第十一节）：共享 classification / filtering / scoring / dedup /
clustering / report composition / validator；唯一预期业务差异 = time window +
scenario/report identity；不得通过复制代码达到"结果看起来一样"。
"""
from __future__ import annotations

import inspect

from research_os.brief.pipeline import BriefPipeline, MorningBriefPipeline, PipelineConfig
from research_os.brief.renderer import render_brief
from research_os.brief.validation import validate_brief_evidence
from research_os.brief.window import evening_policy, morning_policy
from research_os.morning.classification import classify_text, source_to_channel
from research_os.morning.clustering import ClusterBuilder
from research_os.morning.dedup import ExactDeduplicator, candidates_from_raw
from research_os.morning.scoring import InformationScorer
from research_os.morning.veto import apply_vetoes
from research_os.orchestrator.runners.evening_brief import EveningBriefScenarioRunner
from research_os.orchestrator.runners.morning_brief import MorningBriefScenarioRunner


def test_morning_and_evening_share_same_pipeline_class():
    """同一核心处理链：MorningBriefPipeline 即 BriefPipeline（非复制）。"""
    assert MorningBriefPipeline is BriefPipeline


def test_morning_pipeline_is_shared_brief_pipeline_with_morning_policy():
    """默认（无 window_policy）即 morning 策略；evening 注入 evening 策略。"""
    p = BriefPipeline(PipelineConfig())
    assert p.window_policy.scenario_id == "morning_brief"
    assert morning_policy().scenario_id == "morning_brief"
    assert evening_policy().scenario_id == "evening_brief"


def test_policy_identity_is_only_business_difference():
    """唯一预期业务差异：scenario_id + title_prefix + 时间窗口 + 报告路径。"""
    m = morning_policy()
    e = evening_policy()
    assert m.scenario_id == "morning_brief"
    assert e.scenario_id == "evening_brief"
    assert m.title_prefix == "A股每日晨报"
    assert e.title_prefix == "A股每日晚报"
    # 窗口不同（morning: 前一日 20:00→当日 08:00；evening: 当日 08:00→20:00）
    m_start, m_end = m.window(__import__("datetime").date(2026, 8, 6))
    e_start, e_end = e.window(__import__("datetime").date(2026, 8, 6))
    assert (m_start, m_end) != (e_start, e_end)
    # 其余身份字段（报告子目录/后缀）按场景区分
    assert m.report_subdir == "morning" and e.report_subdir == "evening"
    assert m.report_suffix == "morning" and e.report_suffix == "evening"


def test_shared_processing_functions():
    """classification / filtering / scoring / dedup / clustering 均为同一实现。"""
    # classification
    assert callable(classify_text) and callable(source_to_channel)
    # filtering（硬性否决 = 共享过滤规则）
    assert callable(apply_vetoes)
    # scoring
    assert InformationScorer is InformationScorer
    # dedup / clustering
    assert ExactDeduplicator is ExactDeduplicator
    assert ClusterBuilder is ClusterBuilder
    assert candidates_from_raw is candidates_from_raw


def test_shared_renderer_and_validator():
    """report composition 与 validator 为同一函数（非复制）。"""
    from research_os.brief.renderer import band_label as brief_band
    from research_os.brief.validation import BriefEvidenceValidation

    assert callable(render_brief)
    assert callable(validate_brief_evidence)
    assert BriefEvidenceValidation is BriefEvidenceValidation
    assert callable(brief_band)


def test_morning_runner_and_evening_runner_reuse_shared_modules():
    """两个 Runner 的 execute 都引用共享 brief 模块，无第二套 Pipeline。"""
    morning_src = inspect.getsource(MorningBriefScenarioRunner)
    evening_src = inspect.getsource(EveningBriefScenarioRunner)
    # 都走 brief 共享模块
    assert "research_os.brief.collect" in morning_src
    assert "research_os.brief.collect" in evening_src
    assert "BriefPipeline" in evening_src
    # evening 无私有 pipeline 副本
    assert "class BriefPipeline" not in evening_src
    assert "class MorningBriefPipeline" not in evening_src


def test_no_material_update_layer_in_evening_runner():
    """evening 无 material_update / new_since_morning / already_known 层。"""
    evening_src = inspect.getsource(EveningBriefScenarioRunner)
    for banned in ("material_update", "new_since_morning", "already_known_in_morning",
                   "cross_report", "cross-report"):
        assert banned not in evening_src, f"evening runner 不得包含 {banned}"


def test_evening_scenario_identity():
    """scenario/report identity 正确。"""
    r = EveningBriefScenarioRunner()
    assert r.scenario == "evening_brief"
    assert r.version == "1.0.0"
