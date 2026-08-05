"""精确去重（Phase 2 任务 10 节）。

URL 规范化增强（删除追踪参数）+ 内容指纹（source_id/external_id/normalized_url/
title_normalized/content_hash/publisher/published_at）+ DuplicateGroup 结果。

重复记录不可删除到无法审计：保留索引与归并关系（DuplicateGroup 落盘）。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from research_os.models import RawItem, CandidateItem
from research_os.utils.id import content_sha256, new_uuid
from research_os.utils.url import normalize_url

# 常见追踪参数（删除后不影响正文标识）
_TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term",
                    "utm_content", "from", "spm", "share_token", "wechat_redirect",
                    "from_sourcesina", "fid"}


def normalize_url_strict(url: str) -> str:
    """URL 规范化：去 fragment、去追踪参数、去默认端口、小写主机、去尾斜杠。

    保留会改变正文的查询参数（如搜索关键词/分页）。
    """
    base = normalize_url(url)
    try:
        parts = urlsplit(base)
        keep = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
                if k.lower() not in _TRACKING_PARAMS]
        query = urlencode(keep, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except ValueError:
        return base


def title_normalized(title: str) -> str:
    """标题标准化：全角转半角、去空白与标点差异。"""
    text = title.strip().lower()
    full_to_half = str.maketrans(
        "！？：；，。（）【】“”‘’０-９",
        "!?:;,.()[]\"\"''0-9",
    )
    text = text.translate(full_to_half)
    text = re.sub(r"\s+", "", text)
    return text


@dataclass
class DuplicateGroup:
    """去重结果（保留归并关系用于审计）。"""

    duplicate_group_id: str
    canonical_raw_item_id: str
    duplicate_raw_item_ids: List[str] = field(default_factory=list)
    dedup_method: str = "composite"
    confidence: float = 1.0


def build_fingerprint(item: RawItem) -> str:
    """内容指纹：source_id|external_id|normalized_url|title_norm|hash|publisher|published_at。"""
    parts = [
        item.source_id,
        item.external_id or "",
        normalize_url_strict(item.url),
        title_normalized(item.title),
        item.content_hash,
        item.publisher,
        item.published_at,
    ]
    return content_sha256("|".join(parts))


_NUMBER_RE = re.compile(r"(\d+(?:\.\d+)?)(%|亿|万|元|吨|GW|GWh|MW|台|辆|艘|架|亿元|万元)")
# 相反时间/状态词（矛盾信号）
_OPPOSITE_PAIRS = [("今日", "昨日"), ("已", "未"), ("获批", "审批中"),
                   ("批准", "审批中"), ("上调", "下调"), ("完成", "延期"),
                   ("通过", "驳回")]


def _has_key_conflict(excerpt_a: str, excerpt_b: str) -> bool:
    """判定两条同标题内容是否存在关键矛盾（数值/时间/状态不一致）。

    仅表达差异（一方信息量更少）不视为矛盾，允许去重合并；
    双方给出不同数值或相反状态时保留两条供冲突检测（任务 9.6）。
    """
    nums_a = set(_NUMBER_RE.findall(excerpt_a))
    nums_b = set(_NUMBER_RE.findall(excerpt_b))
    if nums_a and nums_b and nums_a != nums_b:
        return True
    for a, b in _OPPOSITE_PAIRS:
        if (a in excerpt_a and b in excerpt_b) or (b in excerpt_a and a in excerpt_b):
            return True
    return False


class ExactDeduplicator:
    """精确去重器。"""

    def __init__(self):
        self._seen: Dict[str, str] = {}   # fingerprint -> canonical raw_item_id
        self._title_excerpts: Dict[str, str] = {}  # 标准化标题 -> 摘录（冲突保留用）
        self.groups: List[DuplicateGroup] = []

    def dedup(self, items: List[RawItem]) -> List[RawItem]:
        """去重并记录归并关系。返回保留下来的规范条目。

        指纹键：external_id / normalized_url / content_hash / 标准化标题。
        标题相同但内容矛盾（时间/数值/状态不一致）时保留两条进入聚类，
        以便冲突检测（任务 9.6：不得消除冲突）。
        """
        result: List[RawItem] = []
        for item in items:
            fp = build_fingerprint(item)
            keys = [k for k in (
                item.external_id and f"eid:{item.source_id}:{item.external_id}",
                f"url:{normalize_url_strict(item.url)}",
                f"hash:{item.content_hash}",
                # 标准化标题跨源匹配：同一公告被多来源转载（任务 10.2）
                f"title:{title_normalized(item.title)}",
            ) if k]

            # 标题键特殊处理：内容存在关键矛盾（数值/时间/状态）不合并，
            # 保留冲突证据供聚类冲突检测（任务 9.6：不得消除冲突）
            title_key = f"title:{title_normalized(item.title)}"
            conflict_keep = (
                title_key in self._seen
                and _has_key_conflict(self._title_excerpts.get(title_key, ""),
                                      item.content_excerpt)
            )

            if any(k in self._seen for k in keys) and not conflict_keep:
                existing = self._seen[keys[0]] if keys[0] in self._seen else \
                    next(self._seen[k] for k in keys if k in self._seen)
                self._merge_into(existing, item)
            else:
                canonical = item.raw_item_id
                self._seen[fp] = canonical
                for k in keys:
                    self._seen.setdefault(k, canonical)
                if title_key not in self._title_excerpts:
                    self._title_excerpts[title_key] = item.content_excerpt
                result.append(item)
        return result

    def _merge_into(self, canonical_id: str, dup: RawItem) -> None:
        for g in self.groups:
            if g.canonical_raw_item_id == canonical_id:
                g.duplicate_raw_item_ids.append(dup.raw_item_id)
                return
        self.groups.append(DuplicateGroup(
            duplicate_group_id=new_uuid(),
            canonical_raw_item_id=canonical_id,
            duplicate_raw_item_ids=[dup.raw_item_id],
            dedup_method="composite",
        ))


def candidates_from_raw(items: List[RawItem],
                        monitoring_channels: Optional[Dict[str, str]] = None) -> List[CandidateItem]:
    """RawItem -> CandidateItem（通道映射由调用方提供 source_id -> channel）。"""
    from research_os.utils.time import now_iso

    channels = monitoring_channels or {}
    out: List[CandidateItem] = []
    for item in items:
        warnings: List[str] = []
        if item.access_status == "failed":
            warnings.append("机器解析明显错误")
        c = CandidateItem(
            candidate_id=new_uuid(),
            raw_item_ids=[item.raw_item_id],
            source_ids=[item.source_id],
            monitoring_channel=channels.get(item.source_id, "unknown"),  # type: ignore[arg-type]
            title=item.title,
            summary=item.content_excerpt,
            published_at=item.published_at,
            retrieved_at=item.retrieved_at or now_iso(),
            entities=item.entities,
            status="collected",
            warnings=warnings,
        )
        out.append(c)
    return out
