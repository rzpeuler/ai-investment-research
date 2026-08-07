"""M3 Candidate Sources：将已持久化的结构化对象读入候选管线（确定性代码，零 LLM）。

支持的源类型与表/Pydantic 模型映射：
  Event → events / Event
  Claim → claims / Claim
  ResearchFinding → research_findings / ResearchFinding
  CompetitiveFactor → competitive_factors / CompetitiveFactor
  Catalyst → catalysts / Catalyst
  RiskFactor → risk_factors / RiskFactor
  BusinessSegment → business_segments / BusinessSegment
  CompanyProfile → company_profiles / CompanyProfile
  Evidence → evidence / Evidence

Evidence context loader：
- 读取 evidence_ids + counter_evidence_ids 并验证存在性
- 最小证据信息供 LLM：evidence_id, title, publisher, published_at,
  source_tier, evidence_type, excerpt, url, role
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from research_os.models.core import (
    Claim,
    Event,
    Evidence,
)
from research_os.models.equity_research import (
    Catalyst,
    CompetitiveFactor,
    ResearchFinding,
    RiskFactor,
)
from research_os.models.companies import CompanyProfile
from research_os.models.valuation import BusinessSegment
from research_os.storage.db import Database

# ---- 源类型 → 表名 & Pydantic 模型 ----

_SOURCE_MAP: Dict[str, Tuple[str, type]] = {
    "Event": ("events", Event),
    "Claim": ("claims", Claim),
    "ResearchFinding": ("research_findings", ResearchFinding),
    "CompetitiveFactor": ("competitive_factors", CompetitiveFactor),
    "Catalyst": ("catalysts", Catalyst),
    "RiskFactor": ("risk_factors", RiskFactor),
    "BusinessSegment": ("business_segments", BusinessSegment),
    "CompanyProfile": ("company_profiles", CompanyProfile),
    "Evidence": ("evidence", Evidence),
}

_ALLOWED_SOURCE_TYPES = set(_SOURCE_MAP.keys())


def is_allowed_source_type(source_type: str) -> bool:
    """source_type 是否在 M3 允许名单内。"""
    return source_type in _ALLOWED_SOURCE_TYPES


class SourceAdapter:
    """从 SQLite 读取源对象并构造为 Pydantic 模型实例。"""

    def __init__(self, db: Database):
        self._db = db

    def load(self, source_type: str, source_id: str) -> Any:
        """按类型和 ID 加载单个源对象。

        Returns:
            Pydantic model 实例（如 Event、Claim 等）。
        Raises:
            ValueError: source_type 不在允许名单、对象不存在、Pydantic 构造失败。
        """
        if source_type not in _SOURCE_MAP:
            raise ValueError(
                f"不支持的源类型: {source_type!r}，允许: {sorted(_SOURCE_MAP.keys())}"
            )
        table, model_cls = _SOURCE_MAP[source_type]
        record = self._db.get(table, source_id)
        if record is None:
            raise ValueError(f"{source_type} {source_id} 在表 {table} 中不存在")
        try:
            return model_cls(**record)
        except Exception as exc:
            raise ValueError(
                f"{source_type} {source_id} Pydantic 构造失败: {exc}"
            ) from exc

    def load_batch(
        self, sources: List[Tuple[str, str]]
    ) -> Dict[Tuple[str, str], Any]:
        """批量加载源对象。返回 {(type, id): model}。"""
        result: Dict[Tuple[str, str], Any] = {}
        errors: List[str] = []
        for source_type, source_id in sources:
            try:
                result[(source_type, source_id)] = self.load(source_type, source_id)
            except ValueError as exc:
                errors.append(str(exc))
        if errors:
            raise ValueError("批量加载源对象失败:\n" + "\n".join(errors))
        return result


# ---- Evidence 上下文 ----

class EvidenceContext:
    """最小证据上下文（供 LLM 参考，不含全文）。"""

    def __init__(
        self,
        evidence_id: str,
        title: str,
        publisher: str,
        published_at: str,
        source_tier: str,
        evidence_type: str,
        excerpt: str,
        url: str,
        role: str,  # "supporting" or "counter"
    ):
        self.evidence_id = evidence_id
        self.title = title
        self.publisher = publisher
        self.published_at = published_at
        self.source_tier = source_tier
        self.evidence_type = evidence_type
        self.excerpt = excerpt
        self.url = url
        self.role = role

    def to_minimal_dict(self) -> Dict[str, str]:
        """返回供 LLM 使用的最小字段。"""
        return {
            "evidence_id": self.evidence_id,
            "title": self.title,
            "publisher": self.publisher,
            "published_at": self.published_at,
            "source_tier": self.source_tier,
            "evidence_type": self.evidence_type,
            "excerpt": self.excerpt,
            "url": self.url,
            "role": self.role,
        }


def load_evidence_context(
    db: Database,
    evidence_ids: List[str],
    counter_evidence_ids: Optional[List[str]] = None,
) -> Tuple[List[EvidenceContext], List[str]]:
    """加载证据上下文并验证存在性。

    Args:
        db: Database 实例。
        evidence_ids: 支持证据 ID 列表。
        counter_evidence_ids: 反证证据 ID 列表（可选）。

    Returns:
        (contexts, errors): contexts 为 EvidenceContext 列表，
        errors 为缺失/失败的证据 ID 描述。
    """
    counter_evidence_ids = counter_evidence_ids or []
    all_ids = list(dict.fromkeys(evidence_ids + counter_evidence_ids))  # preserve order, unique
    contexts: List[EvidenceContext] = []
    errors: List[str] = []

    for eid in all_ids:
        record = db.get("evidence", eid)
        if record is None:
            errors.append(f"Evidence {eid} 不存在")
            continue
        try:
            ev = Evidence(**record)
        except Exception as exc:
            errors.append(f"Evidence {eid} Pydantic 构造失败: {exc}")
            continue
        role = "counter" if eid in counter_evidence_ids else "supporting"
        contexts.append(EvidenceContext(
            evidence_id=ev.evidence_id,
            title=ev.title,
            publisher=ev.publisher,
            published_at=ev.published_at,
            source_tier=ev.source_tier,
            evidence_type=ev.evidence_type,
            excerpt=ev.excerpt,
            url=ev.url,
            role=role,
        ))
    return contexts, errors
