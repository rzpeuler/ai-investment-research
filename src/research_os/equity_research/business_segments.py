"""业务分部（Phase 4 任务书 3.14/Commit 8）。

- 分部来源优先级：定期报告分部表 > 产品/地区收入表 > 经营数据公告 > 公司正式说明 > 用户校正；
- 每期保留 raw_name/canonical_name/mapping_method/reclassification_group_id/valid_from/valid_to；
- 不得把跨期不同分类直接相加；产品名标准化规则映射优先，LLM 只生成候选；
- 收入/利润/销量/价格只在原始披露支持时拆分；不得由 收入÷猜测价格 推断销量写成 FACT。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from research_os.models.valuation import BusinessSegment
from research_os.utils.time import now_iso


@dataclass
class SegmentInput:
    """分部输入行（来自报告分部表/产品收入表等）。"""
    company_entity_id: str
    financial_report_id: str
    segment_type: str  # product / geography / customer / channel / other
    raw_name: str
    revenue: Optional[str] = None
    revenue_share: Optional[str] = None
    profit: Optional[str] = None
    profit_margin: Optional[str] = None
    volume: Optional[str] = None
    average_price: Optional[str] = None
    currency: str = "CNY"
    unit_scale: int = 10000
    valid_from: str = "1970-01-01"
    valid_to: Optional[str] = None
    source_block_ids: List[str] = field(default_factory=list)
    source_priority: int = 1  # 1 分部表 / 2 产品地区收入表 / 3 经营数据公告 / 4 公司说明 / 5 用户校正


@dataclass
class SegmentMapping:
    """产品名标准化候选（规则优先，LLM 只生成候选）。"""
    raw_name: str
    canonical_name: str
    mapping_method: str  # rule / llm_assisted / manual
    confidence: float


# 规则映射表：常见产品名 → 标准名（示例级，正式数据按公司登记时扩展）
_RULE_MAP: Dict[str, str] = {
    "茅台酒": "茅台酒",
    "系列酒": "系列酒",
    "茅台酒及系列酒": "茅台酒及系列酒",
    "其他业务": "其他业务",
    "其他": "其他业务",
}


def canonicalize_name(raw_name: str, rule_map: Optional[Dict[str, str]] = None) -> SegmentMapping:
    """产品名标准化：规则映射优先；无规则命中返回 llm_assisted 候选（低置信）。"""
    key = str(raw_name).strip()
    table = rule_map or _RULE_MAP
    if key in table:
        return SegmentMapping(key, table[key], "rule", 1.0)
    # 模糊包含匹配（规则层）
    for k, v in table.items():
        if k and (k in key or key in k):
            return SegmentMapping(key, v, "rule", 0.9)
    # 未命中：保留原名，标记 llm_assisted 候选（不得自动批准）
    return SegmentMapping(key, key, "llm_assisted", 0.3)


def build_segment(si: SegmentInput, rule_map: Optional[Dict[str, str]] = None) -> BusinessSegment:
    """由输入行构造 BusinessSegment（含标准化候选；LLM 候选不自动批准）。"""
    mapping = canonicalize_name(si.raw_name, rule_map)
    ts = now_iso()
    return BusinessSegment(
        segment_id=str(uuid.uuid4()),
        company_entity_id=si.company_entity_id,
        financial_report_id=si.financial_report_id,
        parent_segment_id=None,
        segment_type=si.segment_type,  # type: ignore[arg-type]
        raw_name=si.raw_name,
        canonical_name=mapping.canonical_name,
        mapping_method=mapping.mapping_method,  # type: ignore[arg-type]
        mapping_confidence=mapping.confidence,
        valid_from=si.valid_from,
        valid_to=si.valid_to,
        revenue=si.revenue,
        revenue_share=si.revenue_share,
        profit=si.profit,
        profit_margin=si.profit_margin,
        volume=si.volume,
        average_price=si.average_price,
        currency=si.currency,
        unit_scale=si.unit_scale,
        metric_fact_ids=[],
        source_block_ids=si.source_block_ids,
        evidence_ids=[],
        reclassification_group_id=None,
        status="active",
        version=1,
        created_at=ts,
    )


@dataclass
class ReclassificationRule:
    """跨期重分类规则：把某期间的旧分类映射到新分类组。"""
    group_id: str
    old_raw_name: str
    new_canonical_name: str
    effective_from: str  # 新分类生效日期


def apply_reclassification(
    segments: List[BusinessSegment],
    rules: List[ReclassificationRule],
) -> List[BusinessSegment]:
    """应用跨期重分类：给旧分类打 reclassification_group_id，保留原名与有效期。

    不得把跨期不同分类直接相加——重分类只建立关联，不合并数值。
    """
    result: List[BusinessSegment] = []
    for seg in segments:
        new = seg
        for rule in rules:
            if seg.raw_name == rule.old_raw_name and seg.valid_from < rule.effective_from:
                new = seg.model_copy(deep=True)
                new.reclassification_group_id = rule.group_id
                new.status = "superseded"
                break
        result.append(new)
    return result


def check_cross_period_merge_safety(segments: List[BusinessSegment]) -> List[str]:
    """检查跨期直接相加风险：同一 canonical_name 但 reclassification_group 不同。

    返回警告列表。不得把不同分类直接相加（如旧"白酒"与拆分后"茅台酒+系列酒"）。
    """
    warnings: List[str] = []
    by_name: Dict[str, set] = {}
    for seg in segments:
        by_name.setdefault(seg.canonical_name, set()).add(seg.reclassification_group_id)
    for name, groups in by_name.items():
        if len(groups) > 1:
            warnings.append(
                f"分部 {name!r} 跨期分类组不同（{sorted(g for g in groups if g)}），不得直接相加"
            )
    return warnings
