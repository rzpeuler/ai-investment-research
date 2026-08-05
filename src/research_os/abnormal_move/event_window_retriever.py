"""分层事件检索（Phase 3 任务书 9 节）。

四层检索：
- L1 高权威事实：公司公告（cninfo/sse/szse/company_ir）、监管（csrc）、
  政府统计（nbs）
- L2 结构化事件池：晨报入选/未入选 CandidateItem、EventCluster、历史 Event、
  历史 Claim、manual_inbox 已接受条目
- L3 四个并列监测方向：fast_news / deep_financial_media /
  community_sentiment / institutional_activity（与宏观/产业/市场/公司分类正交）
- L4 扩大检索（证据不足时）：窗口扩展、实体别名、较低等级来源

检索预算：fast=1-2 层+有限 L3；standard=1-3 层+证据不足才 L4；deep=四层。
来源失败不等于无事件（空结果 + 字段齐全 = success，不得解释为业务无变化）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from research_os.storage import Database
from research_os.utils.time import parse_iso

# 分层来源映射（source_id -> 层）
LAYER1_SOURCES = {"cninfo", "sse", "szse", "csrc", "nbs", "company_ir"}
LAYER3_CHANNELS = {
    "fast_news": {"cls"},
    "deep_financial_media": set(),
    "community_sentiment": {"xueqiu"},
    "institutional_activity": set(),
}

DEPTH_BUDGET = {
    "fast": 3,       # L1-L2 + 有限 L3
    "standard": 4,   # L1-L3 + 证据不足才 L4
    "deep": 4,       # 四层完整
}


@dataclass
class RetrievedItem:
    item_id: str
    layer: int
    kind: str                      # raw_item / event / claim / candidate / cluster / manual
    source_id: str
    title: str
    published_at: Optional[str]
    retrieved_at: Optional[str]
    url: str = ""
    excerpt: str = ""
    entities: List[str] = field(default_factory=list)
    monitoring_channel: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalResult:
    items: List[RetrievedItem]
    layers_covered: Dict[int, int]   # layer -> 命中数
    channels_covered: Dict[str, str]  # monitoring_channel -> covered/partial/manual_only/not_covered/source_failure
    warnings: List[str] = field(default_factory=list)
    expanded_window: bool = False


class EventWindowRetriever:
    """分层事件检索器。"""

    def __init__(self, db: Database, reports_root: Optional[Path] = None):
        self.db = db
        self.reports_root = reports_root

    # ---------- 各层检索 ----------

    def _query_raw_items(self, window_start: str, window_end: str,
                         source_ids: Optional[List[str]] = None,
                         entity_ids: Optional[List[str]] = None) -> List[RetrievedItem]:
        sql = ("SELECT payload FROM raw_items WHERE "
               "COALESCE(published_at, retrieved_at) BETWEEN ? AND ?")
        params: List[Any] = [window_start, window_end]
        if source_ids:
            sql += " AND source_id IN ({})".format(",".join("?" * len(source_ids)))
            params.extend(source_ids)
        rows = self.db.query(sql, tuple(params))
        items = []
        for r in rows:
            try:
                d = json.loads(r["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            if entity_ids and not (set(d.get("entities", [])) & set(entity_ids)):
                continue
            items.append(RetrievedItem(
                item_id=d.get("raw_item_id", ""), layer=1, kind="raw_item",
                source_id=d.get("source_id", ""),
                title=d.get("title", ""),
                published_at=d.get("published_at"),
                retrieved_at=d.get("retrieved_at"),
                url=d.get("url", ""), excerpt=d.get("content_excerpt", "")[:300],
                entities=d.get("entities", []),
            ))
        return items

    def _query_events(self, window_start: str, window_end: str,
                      entity_ids: Optional[List[str]] = None) -> List[RetrievedItem]:
        sql = "SELECT payload FROM events WHERE COALESCE(event_time, '') BETWEEN ? AND ?"
        rows = self.db.query(sql, (window_start, window_end))
        items = []
        for r in rows:
            try:
                d = json.loads(r["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            items.append(RetrievedItem(
                item_id=d.get("event_id", ""), layer=2, kind="event",
                source_id=d.get("source_ids", [""])[0] if d.get("source_ids") else "event_store",
                title=d.get("event_type", ""), published_at=d.get("event_time"),
                retrieved_at=d.get("created_at"), excerpt="",
                entities=d.get("entities", []),
            ))
        return items

    def _query_claims(self, entity_ids: Optional[List[str]] = None) -> List[RetrievedItem]:
        rows = self.db.query("SELECT payload FROM claims ORDER BY rowid DESC LIMIT 200")
        items = []
        for r in rows:
            try:
                d = json.loads(r["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            items.append(RetrievedItem(
                item_id=d.get("claim_id", ""), layer=2, kind="claim",
                source_id=d.get("source_ids", [""])[0] if d.get("source_ids") else "claim_store",
                title=d.get("statement", "")[:200], published_at=d.get("as_of"),
                retrieved_at=None, excerpt=d.get("statement", "")[:300],
                entities=d.get("entities", []),
            ))
        return items

    def _query_manual_inbox(self, status: str = "accepted") -> List[RetrievedItem]:
        rows = self.db.query(
            "SELECT payload FROM manual_inbox WHERE status = ? ORDER BY rowid DESC LIMIT 200",
            (status,),
        )
        items = []
        for r in rows:
            try:
                d = json.loads(r["payload"])
            except (TypeError, json.JSONDecodeError):
                continue
            items.append(RetrievedItem(
                item_id=d.get("inbox_id", ""), layer=2, kind="manual",
                source_id="manual_inbox", title=d.get("title", ""),
                published_at=d.get("published_at") or d.get("submitted_at"),
                retrieved_at=d.get("submitted_at"),
                url=d.get("source_url", ""), excerpt=d.get("content_excerpt", "")[:300],
                entities=d.get("intended_entities", []),
            ))
        return items

    def _query_morning_artifacts(self, window_start: str, window_end: str,
                                 entity_ids: Optional[List[str]] = None) -> List[RetrievedItem]:
        """L2：从晨报运行产物读取 CandidateItem / EventCluster（不能只检索晨报正文）。"""
        items = []
        if self.reports_root is None:
            return items
        runs_dir = self.reports_root / "runs"
        if not runs_dir.exists():
            return items
        for run_dir in sorted(runs_dir.iterdir()):
            for fname, kind in (("candidate_items.json", "candidate"),
                                ("event_clusters.json", "cluster")):
                path = run_dir / fname
                if not path.exists():
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                seq = data if isinstance(data, list) else data.get("items", [])
                for d in seq:
                    if not isinstance(d, dict):
                        continue
                    pub = d.get("published_at") or d.get("created_at")
                    if pub and not (window_start <= pub <= window_end):
                        continue
                    ents = d.get("entities", [])
                    if entity_ids and not (set(ents) & set(entity_ids)):
                        continue
                    items.append(RetrievedItem(
                        item_id=d.get("candidate_item_id") or d.get("cluster_id") or "",
                        layer=2, kind=kind, source_id=d.get("source_id", "morning_artifacts"),
                        title=d.get("canonical_title") or d.get("title", ""),
                        published_at=pub, retrieved_at=None,
                        excerpt=d.get("summary", "")[:300],
                        entities=ents,
                        raw=d,
                    ))
        return items

    # ---------- 主入口 ----------

    def retrieve(
        self,
        entity_id: str,
        window_start: str,
        window_end: str,
        depth: str = "standard",
        entity_ids: Optional[List[str]] = None,
        expand_window: bool = False,
        expand_window_days: int = 5,
    ) -> RetrievalResult:
        """按深度预算执行分层检索。"""
        if depth not in DEPTH_BUDGET:
            raise ValueError(f"depth 非法: {depth}（fast/standard/deep）")
        target_ids = entity_ids or [entity_id]
        max_layer = DEPTH_BUDGET[depth]
        warnings: List[str] = []
        items: List[RetrievedItem] = []

        # L1 高权威事实
        if max_layer >= 1:
            l1 = self._query_raw_items(window_start, window_end,
                                       source_ids=sorted(LAYER1_SOURCES),
                                       entity_ids=target_ids)
            items.extend(l1)

        # L2 结构化事件池
        if max_layer >= 2:
            items.extend(self._query_events(window_start, window_end, target_ids))
            items.extend(self._query_claims(target_ids))
            items.extend(self._query_manual_inbox())
            items.extend(self._query_morning_artifacts(window_start, window_end, target_ids))

        # L3 四方向（并列；社区/机构覆盖如实标注）
        if max_layer >= 3:
            l3_raw = self._query_raw_items(window_start, window_end,
                                           source_ids=["cls", "xueqiu"],
                                           entity_ids=target_ids)
            items.extend(l3_raw)

        # L4 扩大检索（仅 deep，或 standard 且证据不足）
        expanded = False
        if max_layer >= 4 and (depth == "deep" or len(items) < 5):
            if expand_window:
                from datetime import timedelta
                from research_os.utils.time import parse_iso

                try:
                    ws = parse_iso(window_start) - timedelta(days=expand_window_days)
                    we = parse_iso(window_end) + timedelta(days=expand_window_days)
                    items.extend(self._query_raw_items(
                        ws.isoformat(timespec="seconds"), we.isoformat(timespec="seconds"),
                        entity_ids=target_ids))
                    expanded = True
                except ValueError:
                    pass
            # 较低等级来源（其余 raw_items）
            items.extend(self._query_raw_items(
                window_start, window_end, entity_ids=target_ids))
            warnings.append("已扩大检索（窗口扩展/较低等级来源），直接触发证据标准不降低")

        # 去重（按 title 归并；同标题多篇转载只保留一条，独立证据计数在 evidence 层）
        seen = set()
        dedup = []
        for it in items:
            key = it.title or it.item_id
            if key in seen:
                continue
            seen.add(key)
            dedup.append(it)
        items = dedup

        layers_covered = {1: 0, 2: 0, 3: 0, 4: 0}
        for it in items:
            layers_covered[it.layer] = layers_covered.get(it.layer, 0) + 1

        channels = {
            "fast_news": "covered" if any(it.source_id == "cls" for it in items) else "not_covered",
            "deep_financial_media": "manual_only",
            "community_sentiment": "covered" if any(it.source_id == "xueqiu" for it in items) else "not_covered",
            "institutional_activity": "manual_only",
        }
        if not items:
            warnings.append("窗口内无命中（不等于没有事件：来源失败或窗口内确实无有效信息，需区分）")

        return RetrievalResult(
            items=items, layers_covered=layers_covered,
            channels_covered=channels, warnings=warnings,
            expanded_window=expanded,
        )
