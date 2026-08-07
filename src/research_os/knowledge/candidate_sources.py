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
- 从源对象自动推导 evidence_ids + counter_evidence_ids
- Evidence 源对象自身即为证据
- 拒绝 source_ids/raw_item_id 作为 Evidence
- 硬性门禁：0 Evidence → EVIDENCE_REQUIRED
- 每条 derived evidence 必须在 SQLite 中存在 + 通过 Pydantic+Schema 校验

Schema-first 加载路径：
  raw DB payload → JSON Schema validate → Pydantic construct → model_dump → JSON Schema re-validate
  确保 Schema 与 Pydantic 双重覆盖，闭包验证。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

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
from research_os.validators.schema_validator import validate_model, validate_instance

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
    """从 SQLite 读取源对象并构造为 Pydantic 模型实例。

    Schema-first 路径：
    raw DB payload → JSON Schema validate → Pydantic construct → model_dump → JSON Schema re-validate
    """

    def __init__(self, db: Database):
        self._db = db

    def load(self, source_type: str, source_id: str) -> Any:
        """按类型和 ID 加载单个源对象。

        Schema-first 路径：
        1. 从 SQLite 读取 raw payload
        2. JSON Schema 校验 raw dict
        3. Pydantic 构造
        4. model_dump → JSON Schema 再校验

        Returns:
            Pydantic model 实例（如 Event、Claim 等）。
        Raises:
            ValueError: source_type 不在允许名单、对象不存在、Schema 校验失败、Pydantic 构造失败。
        """
        if source_type not in _SOURCE_MAP:
            raise ValueError(
                f"不支持的源类型: {source_type!r}，允许: {sorted(_SOURCE_MAP.keys())}"
            )
        table, model_cls = _SOURCE_MAP[source_type]
        record = self._db.get(table, source_id)
        if record is None:
            raise ValueError(f"{source_type} {source_id} 在表 {table} 中不存在")

        # Schema-first: Step 1 — JSON Schema validate raw dict
        schema_name = _schema_name_for_model(model_cls)
        if schema_name:
            errors = validate_instance(record, schema_name)
            if errors:
                raise ValueError(
                    f"{source_type} {source_id} JSON Schema 校验失败 (raw dict): {'; '.join(errors)}"
                )

        # Step 2 — Pydantic 构造
        try:
            obj = model_cls(**record)
        except Exception as exc:
            raise ValueError(
                f"{source_type} {source_id} Pydantic 构造失败: {exc}"
            ) from exc

        # Step 3 — model_dump → JSON Schema re-validate
        if schema_name:
            dumped = obj.model_dump()
            errors2 = validate_instance(dumped, schema_name)
            if errors2:
                raise ValueError(
                    f"{source_type} {source_id} JSON Schema 校验失败 (model_dump): {'; '.join(errors2)}"
                )

        return obj

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


def _schema_name_for_model(model_cls: type) -> Optional[str]:
    """从 Pydantic 模型类推导 Schema 名称。"""
    # 映射模型名到 schema name
    _MODEL_TO_SCHEMA: Dict[str, str] = {
        "Event": "event",
        "Claim": "claim",
        "ResearchFinding": "research_finding",
        "CompetitiveFactor": "competitive_factor",
        "Catalyst": "catalyst",
        "RiskFactor": "risk_factor",
        "BusinessSegment": "business_segment",
        "CompanyProfile": "company_profile",
        "Evidence": "evidence",
    }
    return _MODEL_TO_SCHEMA.get(model_cls.__name__)


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


def _extract_evidence_ids_from_source(source_obj: Any) -> Tuple[List[str], List[str]]:
    """从源对象中提取 evidence_ids 和 counter_evidence_ids。

    支持字段名：
    - evidence_ids (supporting)
    - counter_evidence_ids (counter)
    - 如果源对象本身就是 Evidence 实例，返回自身 evidence_id 作为 supporting。
    """
    supporting: List[str] = []
    counter: List[str] = []

    # Evidence 源对象：自身即为证据
    if isinstance(source_obj, Evidence):
        supporting.append(source_obj.evidence_id)
        return supporting, counter

    d = source_obj.model_dump() if hasattr(source_obj, "model_dump") else {}

    # 标准 evidence_ids
    ev_ids = d.get("evidence_ids")
    if isinstance(ev_ids, list):
        supporting.extend([eid for eid in ev_ids if isinstance(eid, str)])

    # counter_evidence_ids
    counter_ids = d.get("counter_evidence_ids")
    if isinstance(counter_ids, list):
        counter.extend([eid for eid in counter_ids if isinstance(eid, str)])

    return supporting, counter


def _check_evidence_existence(
    db: Database,
    evidence_ids: List[str],
) -> Tuple[List[Evidence], List[str]]:
    """验证 evidence_ids 是否存在且通过 Pydantic+Schema 校验。

    Schema-first: raw DB payload → validate_instance → Pydantic → model_dump → validate_instance。

    Returns:
        (valid_evidence_objects, errors): 每条错误描述缺失/失败的 ID。
    """
    valid: List[Evidence] = []
    errors: List[str] = []
    for eid in evidence_ids:
        record = db.get("evidence", eid)
        if record is None:
            errors.append(f"Evidence {eid} 不存在")
            continue

        # Schema-first: Step 1 — JSON Schema validate raw dict
        schema_errors_1 = validate_instance(record, "evidence")
        if schema_errors_1:
            errors.append(f"Evidence {eid} Schema 校验失败 (raw dict): {'; '.join(schema_errors_1)}")
            continue

        try:
            ev = Evidence(**record)
        except Exception as exc:
            errors.append(f"Evidence {eid} Pydantic 构造失败: {exc}")
            continue

        # Step 2 — model_dump → Schema re-validate
        dumped = ev.model_dump()
        schema_errors_2 = validate_instance(dumped, "evidence")
        if schema_errors_2:
            errors.append(f"Evidence {eid} Schema 校验失败 (model_dump): {'; '.join(schema_errors_2)}")
            continue

        valid.append(ev)
    return valid, errors


def derive_evidence_from_sources(
    db: Database,
    source_objects: Dict[Tuple[str, str], Any],
    explicit_evidence_ids: Optional[List[str]] = None,
) -> Tuple[List[str], List[str], List[str]]:
    """从源对象自动推导 evidence。

    1. 遍历每个源对象，提取 evidence_ids + counter_evidence_ids
    2. 合并 explicit_evidence_ids
    3. Evidence 源对象自身作为证据
    4. 拒绝 source_ids / raw_item_id 格式（预防混淆）
    5. 每条 evidence 在 SQLite 中验证存在 + Pydantic + Schema

    Returns:
        (supporting_ids, counter_ids, errors):
        - supporting_ids: 去重后的支持证据 ID 列表
        - counter_ids: 去重后的反证证据 ID 列表
        - errors: 验证错误列表

    Raises:
        ValueError: 0 Evidence after derivation (EVIDENCE_REQUIRED)
    """
    all_supporting: List[str] = []
    all_counter: List[str] = []

    # 从每个源对象推导
    for (st, sid), obj in source_objects.items():
        sup, cnt = _extract_evidence_ids_from_source(obj)
        all_supporting.extend(sup)
        all_counter.extend(cnt)

    # 合并显式证据 ID
    if explicit_evidence_ids:
        all_supporting.extend(explicit_evidence_ids)

    # 去重（保持首次出现顺序）
    seen: Set[str] = set()
    supporting_ids: List[str] = []
    for eid in all_supporting:
        if eid and eid not in seen:
            seen.add(eid)
            supporting_ids.append(eid)

    seen_c: Set[str] = set()
    counter_ids: List[str] = []
    for eid in all_counter:
        if eid and eid not in seen_c and eid not in seen:
            seen_c.add(eid)
            counter_ids.append(eid)

    # 拒绝 source_ids / raw_item_id 格式
    all_for_validation = list(dict.fromkeys(supporting_ids + counter_ids))
    errors: List[str] = []
    for eid in all_for_validation:
        if eid.startswith("source:") or eid.startswith("raw_item:"):
            errors.append(f"拒绝 source_id/raw_item_id 作为 Evidence: {eid}")

    if errors:
        return [], [], errors

    # 验证所有 evidence 存在并通过 Schema（Schema-first）
    valid_evs, ev_errors = _check_evidence_existence(db, all_for_validation)
    if ev_errors:
        return [], [], ev_errors

    # 硬性门禁：0 Evidence
    if len(valid_evs) == 0:
        return [], [], ["EVIDENCE_REQUIRED: 0 条有效证据（须至少 1 条真实 Evidence）"]

    # 过滤掉不存在的 ID
    valid_ids = {ev.evidence_id for ev in valid_evs}
    final_supporting = [eid for eid in supporting_ids if eid in valid_ids]
    final_counter = [eid for eid in counter_ids if eid in valid_ids]

    if len(final_supporting) + len(final_counter) == 0:
        return [], [], ["EVIDENCE_REQUIRED: 推导出 0 条有效证据（所有候选 ID 验证失败）"]

    return final_supporting, final_counter, []


def load_evidence_context(
    db: Database,
    evidence_ids: List[str],
    counter_evidence_ids: Optional[List[str]] = None,
) -> Tuple[List[EvidenceContext], List[str]]:
    """加载证据上下文并验证存在性。

    Schema-first: raw DB payload → validate_instance → Pydantic → validate_instance。

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

        # Schema-first: raw dict → Schema validate
        schema_errs = validate_instance(record, "evidence")
        if schema_errs:
            errors.append(f"Evidence {eid} Schema 校验失败: {'; '.join(schema_errs)}")
            continue

        try:
            ev = Evidence(**record)
        except Exception as exc:
            errors.append(f"Evidence {eid} Pydantic 构造失败: {exc}")
            continue

        # model_dump → Schema re-validate
        dumped = ev.model_dump()
        schema_errs2 = validate_instance(dumped, "evidence")
        if schema_errs2:
            errors.append(f"Evidence {eid} Schema 校验失败 (model_dump): {'; '.join(schema_errs2)}")
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
