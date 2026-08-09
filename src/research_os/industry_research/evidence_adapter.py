"""6A 确定性证据资格适配器（evidence eligibility adapter）。

提供超越 published_at <= as_of 的完整证据资格校验链：
- 来源层级（source_tier）资格
- 内容类型（evidence_type）资格
- 行业标签（industry_tags）相关性
- MODEL_INFERENCE 证据 FACT 不可用
- 图谱证据链批量重载与校验

全部逻辑确定性、零 LLM、只读。证据加载唯一权威入口：
Database.get("evidence", eid)——禁止 raw SQL / 第二套 loader。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from research_os.utils.time import parse_iso

logger = logging.getLogger(__name__)

# ── 常量 ────────────────────────────────────────────────────

# source_tier 合法值（SourceTier: S/A/B/C/D）
_VALID_SOURCE_TIERS = frozenset({"S", "A", "B", "C", "D"})

# 不可用于 FACT 断言的 evidence_type（模型推断产物，非直接事实来源）
_NON_FACT_EVIDENCE_TYPES = frozenset({"MODEL_INFERENCE"})


# ── 公共 API ────────────────────────────────────────────────

def validate_evidence_eligibility(
    evidence: Dict[str, Any],
    as_of: str,
    industry_id: Optional[str] = None,
) -> Tuple[bool, List[str]]:
    """校验单条证据是否具备资格。

    Args:
        evidence: 证据字典（至少含 published_at / source_tier / evidence_type）。
        as_of: 时间断面 ISO-8601（业务有效时间，禁止默认 now()）。
        industry_id: 可选行业标识；提供时若证据含 industry_tags 则校验相关性。

    Returns:
        (is_eligible, reasons) —— reasons 为非空时即不合格原因列表。
    """
    reasons: List[str] = []

    # 1. published_at <= as_of（时间资格，mandatory）
    published_at = evidence.get("published_at")
    if not published_at:
        reasons.append("published_at 缺失")
    else:
        try:
            if parse_iso(published_at) > parse_iso(as_of):
                reasons.append(
                    f"published_at ({published_at}) 晚于 as_of ({as_of})")
        except (ValueError, TypeError) as e:
            reasons.append(f"published_at 非法: {e}")

    # 2. source_tier 不为 unknown 且合法
    source_tier = evidence.get("source_tier")
    if source_tier is None or source_tier == "unknown":
        reasons.append(f"source_tier 为 {source_tier!r}（来源资格不足）")
    elif source_tier not in _VALID_SOURCE_TIERS:
        reasons.append(f"source_tier 非法值: {source_tier!r}")

    # 3. evidence_type 非空（内容资格）
    evidence_type = evidence.get("evidence_type")
    if not evidence_type:
        reasons.append("evidence_type 为空")

    # 4. MODEL_INFERENCE 类型不可用于 FACT 断言
    if evidence_type in _NON_FACT_EVIDENCE_TYPES:
        reasons.append(
            f"evidence_type={evidence_type} 不可用于 FACT 断言（模型推断产物）")

    # 5. 行业标签相关性（仅当同时提供 industry_id 且证据含 industry_tags）
    if industry_id is not None:
        industry_tags: Optional[List[str]] = evidence.get("industry_tags")
        if industry_tags is not None:
            # industry_tags 存在则必须匹配，否则视为无关
            if isinstance(industry_tags, list) and industry_id not in industry_tags:
                reasons.append(
                    f"industry_tags {industry_tags} 不包含 industry_id={industry_id}")

    is_eligible = len(reasons) == 0
    return is_eligible, reasons


def filter_eligible_evidence(
    evidence_list: List[Dict[str, Any]],
    as_of: str,
    industry_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """批量过滤：仅返回具备资格的证据，同时记录过滤原因。

    Args:
        evidence_list: 待校验证据列表。
        as_of: 时间断面 ISO-8601。
        industry_id: 可选行业标识。

    Returns:
        通过全部资格校验的证据列表。
    """
    eligible: List[Dict[str, Any]] = []
    for ev in evidence_list:
        ok, reasons = validate_evidence_eligibility(ev, as_of, industry_id)
        if ok:
            eligible.append(ev)
        else:
            eid = ev.get("evidence_id", "?")
            logger.info(
                "evidence_eligibility_filtered evidence_id=%s reasons=%s",
                eid, reasons)
    return eligible


def validate_evidence_ids_chain(
    evidence_ids: List[str],
    db: Any,
    as_of: str,
) -> Dict[str, Any]:
    """从图谱 evidence_ids 出发，重载权威 Evidence 存储并逐条校验资格。

    使用 Database.get("evidence", eid) 作为唯一权威入口（禁止 raw SQL /
    第二套 loader）。返回结构化结果供上游 fail-closed 决策。

    Args:
        evidence_ids: 图谱节点/边引用的证据 ID 列表。
        db: Database 实例。
        as_of: 时间断面 ISO-8601。

    Returns:
        {
            "valid": [...],    # 存在且资格通过的 evidence_id
            "invalid": [...],  # 存在但资格不通过的 evidence_id
            "missing": [...],  # 不存在的 evidence_id
            "reasons": {eid: [reason_str, ...], ...},
        }
    """
    if not evidence_ids:
        return {"valid": [], "invalid": [], "missing": [], "reasons": {}}

    valid: List[str] = []
    invalid: List[str] = []
    missing: List[str] = []
    reasons: Dict[str, List[str]] = {}

    # 去重但保持 stable order
    seen: set[str] = set()
    for eid in evidence_ids:
        if eid in seen:
            continue
        seen.add(eid)

        # 从权威 Evidence 存储重载（Database.get，禁止 raw SQL）
        try:
            evidence = db.get("evidence", eid)
        except Exception:
            missing.append(eid)
            reasons[eid] = ["Evidence 加载异常"]
            continue

        if evidence is None:
            missing.append(eid)
            reasons[eid] = ["Evidence 不存在"]
            continue

        # 资格校验
        ok, item_reasons = validate_evidence_eligibility(evidence, as_of)
        if ok:
            valid.append(eid)
        else:
            invalid.append(eid)
            reasons[eid] = item_reasons

    return {
        "valid": valid,
        "invalid": invalid,
        "missing": missing,
        "reasons": reasons,
    }
