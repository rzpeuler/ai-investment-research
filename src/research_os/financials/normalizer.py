"""事实标准化与冲突处理（Phase 4 任务书 3.11/Commit 5）。

- 原始值与标准化值分离；null（缺失）≠ "0"（报告为零）≠ not_applicable ≠ conflict；
- 重述版本：original / restated / superseded 全保留；当前版本选择按优先级；
- 冲突事实：生成 conflict_group_id，保留全部，不选择更符合市场走势的一项。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

from research_os.financials.periods import normalize_to_yuan

# 来源优先级（任务书 3.11）：数字越小越权威
# 1 法定披露原始表格 / 2 审计报告 / 3 公司正式公告或 IR / 4 经验证的标准财务接口 /
# 5 用户导入且可追溯到原始文件 / 6 媒体或第三方摘要
# 第 6 级不能单独生成财务 FACT（在导入层强制 source_priority<=5）


@dataclass
class FactCandidate:
    """标准化前的候选事实。"""
    company_entity_id: str
    taxonomy_code: str
    label_raw: str
    period_end: str
    statement_scope: str
    currency: str
    unit_scale: int
    raw_value: Optional[str]
    source_priority: int
    source_document_id: Optional[str] = None
    restatement_version: int = 1
    instant_or_duration: str = "duration"
    audit_status: str = "unknown"
    warnings: List[str] = field(default_factory=list)


@dataclass
class NormalizedFact:
    """标准化后的事实（含标准化值与单位）。"""
    candidate: FactCandidate
    normalized_value: Optional[str]
    normalized_unit: str
    value_status: str  # reported / derived_from_report / missing / not_applicable / conflict
    warnings: List[str] = field(default_factory=list)


def normalize_fact(c: FactCandidate) -> NormalizedFact:
    """标准化一个候选事实：单位 → CNY yuan（仅 CNY 直接换算）。"""
    value, unit, warnings = normalize_to_yuan(c.raw_value, c.unit_scale, c.currency)
    status = "missing" if c.raw_value is None else "reported"
    return NormalizedFact(
        candidate=c,
        normalized_value=value,
        normalized_unit=unit,
        value_status=status,
        warnings=list(c.warnings) + warnings,
    )


@dataclass
class ConflictGroup:
    conflict_group_id: str
    fact_key: str
    values: List[str]
    sources: List[int]
    evidence_ids: List[str] = field(default_factory=list)


def current_version_priority(
    facts: List[dict],
) -> List[dict]:
    """按任务书优先级选出当前有效版本：法定正式重述 > 更新披露 > 审计优先 > 其余保留。

    facts: FinancialFact dict 列表（同 fact_key）。
    返回 [当前有效版本列表]；无法消除冲突时返回全部并标记 CONFLICT（由调用方处理）。
    """
    if not facts:
        return []
    # 重述状态排序：restated 优先于 superseded 优先于 original
    restate_rank = {"restated": 0, "superseded": 1, "original": 2}
    ranked = sorted(
        facts,
        key=lambda f: (
            restate_rank.get(f.get("restatement_status", "original"), 3),
            int(f.get("source_priority", 6)),  # 数字越小越权威（1 法定披露优先）
            -int(f.get("restatement_version", 1)),
        ),
    )
    return ranked


def detect_conflicts(facts: List[dict]) -> Optional[ConflictGroup]:
    """同 fact_key 存在不同值 → 冲突组；相同值（重述一致）不算冲突。"""
    if not facts:
        return None
    distinct = {}
    for f in facts:
        key = f.get("raw_value")
        distinct.setdefault(key, []).append(f)
    if len(distinct) <= 1:
        return None
    values = sorted(str(k) for k in distinct if k is not None)
    if not values or len(values) <= 1:
        return None
    return ConflictGroup(
        conflict_group_id=f"cg-{facts[0].get('fact_key', 'unknown')}",
        fact_key=facts[0].get("fact_key", ""),
        values=values,
        sources=[int(f.get("source_priority", 6)) for f in facts],
        evidence_ids=[e for f in facts for e in f.get("evidence_ids", [])],
    )
