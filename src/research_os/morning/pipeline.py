"""晨报流水线（Phase 2 任务 4 节完整处理链）。

来源采集 -> RawItem -> 时间窗口过滤 -> 精确去重 -> 语义聚类 -> 分类 ->
硬性否决 -> 评分 -> 事件簇合并 -> Claim 生成 -> 选择 -> Markdown -> 校验。

每个阶段有结构化产物（写入 run 目录），有日志与测试。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from research_os.models import CandidateItem, EventCluster, RawItem
from research_os.morning.claims import build_claim, detect_conflicts
from research_os.morning.classification import classify_text, source_to_channel
from research_os.morning.clustering import ClusterBuilder
from research_os.morning.coverage import build_coverage
from research_os.morning.dedup import ExactDeduplicator, candidates_from_raw
from research_os.morning.scoring import InformationScorer, band_for
from research_os.morning.veto import apply_vetoes
from research_os.morning.window import (
    as_of_for,
    delay_info,
    morning_window,
    report_path_for,
    scheduled_for,
)
from research_os.orchestrator.run_directory import RunDirectory
from research_os.utils.id import new_uuid
from research_os.utils.logging import ErrorLog
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance


@dataclass
class PipelineConfig:
    """流水线配置。"""

    source_tiers: Dict[str, str] = field(default_factory=dict)     # source_id -> S/A/B/C/D
    source_status: Dict[str, str] = field(default_factory=dict)    # source_id -> candidate/...
    channel_map: Dict[str, str] = field(default_factory=dict)      # source_id -> monitoring_channel
    similarity_threshold: float = 0.45
    time_tolerance_hours: float = 72.0


@dataclass
class PipelineArtifacts:
    """流水线各阶段产物（落盘到 run 目录）。"""

    task_id: str
    raw_items: List[RawItem] = field(default_factory=list)
    candidates: List[CandidateItem] = field(default_factory=list)
    vetoed: List[CandidateItem] = field(default_factory=list)
    duplicate_groups: list = field(default_factory=list)
    clusters: List[EventCluster] = field(default_factory=list)
    scores: list = field(default_factory=list)
    claims: list = field(default_factory=list)
    coverage: list = field(default_factory=list)
    selected_cluster_ids: List[str] = field(default_factory=list)
    markdown: str = ""
    report_path: Optional[str] = None
    warnings: List[str] = field(default_factory=list)
    missing_data: List[str] = field(default_factory=list)


class MorningBriefPipeline:
    """晨报流水线（确定性核心；LLM 环节以规则回退实现，接口留扩展）。"""

    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        self.scorer = InformationScorer(self.config.source_tiers,
                                        self.config.source_status)

    def run(
        self,
        raw_items: List[RawItem],
        report_date: date,
        *,
        run_dir: Optional[RunDirectory] = None,
        started_at: Optional[str] = None,
    ) -> PipelineArtifacts:
        """执行流水线。raw_items 为空时仍生成结构化产物（覆盖说明+降级说明）。"""
        window_start, window_end = morning_window(report_date)
        started = started_at or now_iso()
        artifacts = PipelineArtifacts(task_id=new_uuid())

        # 0. 时间窗口过滤（窗口外且无新更新 -> 排除，写入 veto 理由）
        in_window = []
        for item in raw_items:
            try:
                from research_os.utils.time import parse_iso

                if parse_iso(item.published_at) < parse_iso(window_start):
                    artifacts.warnings.append(
                        f"窗口外旧闻排除: {item.raw_item_id[:8]} {item.title[:30]}")
                    continue
            except ValueError:
                artifacts.warnings.append(f"发布时间无法解析: {item.raw_item_id[:8]}")
                continue
            in_window.append(item)
        artifacts.raw_items = in_window

        # 1. 精确去重
        dedup = ExactDeduplicator()
        unique = dedup.dedup(in_window)
        artifacts.duplicate_groups = [g.__dict__ for g in dedup.groups]

        # 2. 标准化为候选
        candidates = candidates_from_raw(
            unique, monitoring_channels=self.config.channel_map)
        artifacts.candidates = candidates

        # 3. 分类
        for c in candidates:
            path, tags = classify_text(c.title, c.summary)
            c.classification_path = path
            c.content_type = _content_type(c)  # type: ignore[assignment]
            c.status = "classified"

        # 4. 硬性否决
        survived = []
        for c in candidates:
            veto = apply_vetoes(c, window_start=window_start,
                                source_status=_first_status(c, self.config.source_status))
            if veto.vetoed:
                c.status = "vetoed"
                artifacts.vetoed.append(c)
            else:
                survived.append(c)

        # 5. 事件相似聚类（确定性第一版：实体+日期预分桶 + 标题相似度；
        #    语义模型未接入，见 clustering.py 说明）
        builder = ClusterBuilder(
            time_tolerance_hours=self.config.time_tolerance_hours,
            similarity_threshold=self.config.similarity_threshold)
        clusters = builder.cluster(survived)
        artifacts.clusters = clusters

        # 6. 评分（簇大小参与转载惩罚）+ 选择
        cluster_members: Dict[str, int] = {}
        for cl in clusters:
            for mid in cl.member_candidate_ids:
                cluster_members[mid] = len(cl.member_candidate_ids)
        for c in survived:
            size = cluster_members.get(c.candidate_id, 1)
            score = self.scorer.score(c, cluster_size=size)
            artifacts.scores.append(score.model_dump())
            c.status = "scored"

        # 7. 选择：正文 >=65（含强制纳入）；55-64 附录；40-54 事件库
        selected = set()
        for score in artifacts.scores:
            if score["final_score"] >= 65 or score["forced_include"]:
                selected.add(score["candidate_id"])
        for cl in clusters:
            if any(m in selected for m in cl.member_candidate_ids):
                artifacts.selected_cluster_ids.append(cl.cluster_id)

        # 8. Claim 生成 + 冲突检测
        for cl in clusters:
            members = [c for c in survived if c.candidate_id in cl.member_candidate_ids]
            conflicts = detect_conflicts(cl, members)
            cl.conflicts = conflicts
            for c in members:
                claim = build_claim(c, conflict_notes=conflicts)
                artifacts.claims.append(claim.model_dump())
                cl.primary_evidence_ids.append(claim.claim_id)

        # 9. 覆盖状态（自动化方向：有正式适配器的通道）
        artifacts.coverage = build_coverage(
            channel_sources=_channel_sources(self.config.channel_map),
            succeeded=_channel_success(self.config.channel_map, candidates),
            failures={},
            limitations={},
            automated_channels={
                "fast_news", "official_disclosure", "government_and_regulator",
                "market_data",
            },
        )

        # 10. 缺失数据说明
        for ch in artifacts.coverage:
            if ch["status"] in ("manual_only", "not_covered", "source_failure"):
                artifacts.missing_data.append(
                    f"{ch['monitoring_channel']}: {ch['status']} "
                    f"({'; '.join(ch['limitations'])})")

        # 11. 渲染（由调用方在 run 目录落盘；此处生成 markdown 文本）
        from research_os.morning.renderer import render_morning_brief

        scheduled = scheduled_for(report_date)
        delayed, delay_seconds = delay_info(started, scheduled)
        artifacts.markdown = render_morning_brief(
            artifacts=artifacts, report_date=report_date,
            window_start=window_start, window_end=window_end,
            as_of=as_of_for(report_date), scheduled_for=scheduled,
            started_at=started, delayed=delayed, delay_seconds=delay_seconds,
        )
        artifacts.report_path = report_path_for(report_date,
                                                str(Path.cwd() / "reports"))

        # 12. run 目录产物落盘（若有）
        if run_dir is not None:
            _write_artifacts(run_dir, artifacts)
        return artifacts


def _content_type(c: CandidateItem) -> str:
    from research_os.morning.claims import content_type_of

    return content_type_of(c)


def _first_status(c: CandidateItem, statuses: Dict[str, str]) -> Optional[str]:
    return statuses.get(c.source_ids[0]) if c.source_ids else None


def _channel_sources(channel_map: Dict[str, str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for sid, ch in channel_map.items():
        out.setdefault(ch, []).append(sid)
    return out


def _channel_success(channel_map: Dict[str, str],
                     candidates: List[CandidateItem]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    for c in candidates:
        ch = c.monitoring_channel
        if ch != "unknown":
            out.setdefault(ch, []).extend(c.source_ids)
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


def _write_artifacts(run_dir: RunDirectory, artifacts: PipelineArtifacts) -> None:
    run_dir.write_json("raw_item_index.json",
                       [i.model_dump() for i in artifacts.raw_items])
    run_dir.write_json("candidate_items.json",
                       [c.model_dump() for c in artifacts.candidates])
    run_dir.write_json("duplicate_groups.json", artifacts.duplicate_groups)
    run_dir.write_json("event_clusters.json",
                       [c.model_dump() for c in artifacts.clusters])
    run_dir.write_json("scores.json", artifacts.scores)
    run_dir.write_json("claims.json", artifacts.claims)
    run_dir.write_json("source_coverage.json", artifacts.coverage)
