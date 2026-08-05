"""事件相似聚类（Phase 2 任务 11 节）——确定性第一版。

当前实现：实体+日期预分桶 + 标题相似度候选 + 确定性规则（LLM 语义判断
尚未接入，不得以"语义聚类"名义掩盖未接语义模型的事实）。
语义模型接入后作为第二层判断叠加，禁止让 LLM 在全量候选中自由聚类。

不得错误聚类：同一公司不同订单/同一政策不同细则/同一行业不同价格品种/
不同时间相似事故/同一产品不同版本/同一项目立项与投产。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple

from research_os.models import CandidateItem, EventCluster
from research_os.utils.id import new_uuid
from research_os.utils.time import now_iso
from research_os.validators.schema_validator import validate_instance


def _title_similarity(a: str, b: str) -> float:
    """标题字符级相似度（0-1）。"""
    return SequenceMatcher(None, a, b).ratio()


class ClusterBuilder:
    """事件簇构建器：确定性预分桶 + 相似度候选。"""

    def __init__(self, time_tolerance_hours: float = 72.0,
                 similarity_threshold: float = 0.45):
        self.time_tolerance_hours = time_tolerance_hours
        self.similarity_threshold = similarity_threshold

    def _bucket(self, c: CandidateItem) -> Tuple[str, str]:
        """预分桶键：(主实体, 日期)。

        不使用分类子类：快讯与官方公告（分类路径可能不同）仍需合并；
        同一公司不同事件/同一项目不同阶段靠标题相似度区分。
        """
        entity = c.entities[0] if c.entities else c.source_ids[0] if c.source_ids else "?"
        day = (c.published_at or "")[:10]
        return entity, day

    def _same_event(self, a: CandidateItem, b: CandidateItem) -> bool:
        """同一事件判定：预分桶相同 + 标题相似度达到阈值。"""
        if self._bucket(a) != self._bucket(b):
            return False
        return _title_similarity(a.title, b.title) >= self.similarity_threshold

    def cluster(self, candidates: List[CandidateItem]) -> List[EventCluster]:
        """候选 -> 事件簇。单个候选也形成单成员簇（不丢信息）。"""
        clusters: List[EventCluster] = []
        assigned: Dict[str, str] = {}   # candidate_id -> cluster_id

        for c in sorted(candidates, key=lambda x: x.published_at or ""):
            matched = None
            for cluster in clusters:
                rep = next((m for m in candidates if m.candidate_id in
                            cluster.member_candidate_ids), None)
                if rep is not None and self._same_event(c, rep):
                    matched = cluster
                    break
            if matched is None:
                cluster = EventCluster(
                    cluster_id=new_uuid(),
                    canonical_title=c.title,
                    event_type=c.classification_path[1] if len(c.classification_path) > 1
                    else c.classification_path[0] if c.classification_path else "unknown",
                    event_time=c.event_time,
                    first_published_at=c.published_at,
                    last_updated_at=c.published_at,
                    subject_entities=list(c.entities),
                    member_candidate_ids=[c.candidate_id],
                    source_ids=list(c.source_ids),
                    official_confirmation="官方" in f"{c.title} {c.summary}" or
                                          c.monitoring_channel in
                                          ("official_disclosure", "government_and_regulator"),
                    status="active",
                )
                clusters.append(cluster)
                assigned[c.candidate_id] = cluster.cluster_id
            else:
                matched.member_candidate_ids.append(c.candidate_id)
                matched.source_ids = list(dict.fromkeys(matched.source_ids + c.source_ids))
                matched.last_updated_at = max(matched.last_updated_at, c.published_at)
                if c.published_at < matched.first_published_at:
                    matched.first_published_at = c.published_at
                # 官方确认升级
                if c.monitoring_channel in ("official_disclosure", "government_and_regulator"):
                    matched.official_confirmation = True
                assigned[c.candidate_id] = matched.cluster_id

        for cl in clusters:
            errs = validate_instance(cl.model_dump(), "event_cluster")
            if errs:
                raise ValueError(f"EventCluster 未通过 Schema 校验: {errs}")
        return clusters


def cluster_summary(cluster: EventCluster) -> Dict[str, int]:
    """簇摘要（审计用）。"""
    return {"members": len(cluster.member_candidate_ids),
            "sources": len(cluster.source_ids),
            "official": cluster.official_confirmation}
