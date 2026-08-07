"""测试样本工厂：为 9 个核心对象提供有效/无效实例。

有效样本必须通过对应 JSON Schema；无效样本用于失败路径测试。
"""
from __future__ import annotations

import copy
from typing import Any, Dict

from research_os.utils.id import content_sha256, new_uuid

T0 = "2026-08-05T08:00:00"
T1 = "2026-08-05T09:30:00"


def valid_task(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "task_id": new_uuid(),
        "scenario": "morning_brief",
        "status": "planned",
        "requested_at": T0,
        "as_of": T0,
        "finished_at": None,
        "timezone": "Asia/Shanghai",
        "entities": ["company:600519.SH"],
        "time_window": {"start": T0, "end": T1},
        "depth": "standard",
        "max_runtime_seconds": 1200,
        "source_policy": "public_first",
        "output_formats": ["markdown"],
        "model_policy": "flash_default",
        "warnings": [],
    }
    data.update(overrides)
    return data


def valid_entity(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "entity_id": "company:600519.SH",
        "entity_type": "company",
        "canonical_name": "贵州茅台",
        "aliases": ["600519", "茅台"],
        "market": "A-share",
        "industry_ids": ["industry:baijiu"],
        "concept_ids": ["concept:baijiu"],
        "valid_from": None,
        "valid_to": None,
        "source_ids": ["sse"],
    }
    data.update(overrides)
    return data


def valid_raw_item(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "raw_item_id": new_uuid(),
        "source_id": "sse",
        "external_id": "ann-2026-001",
        "url": "https://example.com/announcement/1",
        "title": "贵州茅台关于召开股东大会的公告",
        "publisher": "上海证券交易所",
        "author": None,
        "published_at": T0,
        "retrieved_at": T1,
        "content_hash": content_sha256("最小必要证据摘录"),
        "content_excerpt": "公司拟于2026年8月召开年度股东大会。",
        "content_storage": "metadata_and_excerpt",
        "language": "zh-CN",
        "access_status": "ok",
        "entities": ["company:600519.SH"],
        "raw_category": "announcement",
    }
    data.update(overrides)
    return data


def valid_event(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "event_id": new_uuid(),
        "event_type": "capacity_expansion",
        "subject_entities": ["company:600519.SH"],
        "object_entities": [],
        "event_time": T0,
        "announced_at": T0,
        "effective_at": None,
        "status": "announced",
        "summary": "公司公告新增产能项目。",
        "quantitative_fields": {"capacity": 10000},
        "industry_coordinates": ["industry_segment:baijiu"],
        "novelty": 0.6,
        "impact_direction": "positive",
        "impact_horizon": "medium",
        "evidence_ids": [],
        "confidence": 0.8,
        "conflicts": [],
    }
    data.update(overrides)
    return data


def valid_opinion(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "opinion_id": new_uuid(),
        "speaker_entity_id": "creator:some_analyst",
        "source_id": "xueqiu",
        "published_at": T0,
        "target_entities": ["company:600519.SH"],
        "stance": "bullish",
        "thesis": "高端白酒需求稳健。",
        "arguments": ["批价稳定"],
        "predictions": [],
        "conditions": ["宏观经济不恶化"],
        "time_horizon": "medium",
        "evidence_ids": [],
        "influence_score": 60.0,
    }
    data.update(overrides)
    return data


def valid_claim(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "claim_id": new_uuid(),
        "claim_type": "FACT",
        "statement": "公司于2026年8月5日披露股东大会通知。",
        "subject_entities": ["company:600519.SH"],
        "predicate": "has_event",
        "object": {"event_type": "shareholders_meeting"},
        "as_of": T0,
        "evidence_ids": [],
        "support_level": "direct",
        "confidence": 0.9,
        "valid_until": None,
        "review_status": "unreviewed",
    }
    data.update(overrides)
    return data


def valid_evidence(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "evidence_id": new_uuid(),
        "source_id": "cninfo",
        "raw_item_id": new_uuid(),
        "title": "股东大会通知公告",
        "publisher": "巨潮资讯",
        "published_at": T0,
        "retrieved_at": T1,
        "url": "https://example.com/cninfo/1",
        "excerpt": "公司拟于2026年8月召开年度股东大会。",
        "evidence_type": "official_disclosure",
        "independence_group": "original-event-001",
        "source_tier": "S",
        "access_status": "ok",
    }
    data.update(overrides)
    return data


def valid_module_result(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "module": "abnormal_move_attribution",
        "version": "1.0.0",
        "status": "success",
        "as_of": T1,
        "inputs": {"entity": "company:600519.SH"},
        "facts": ["股价当日上涨5%"],
        "source_opinions": [],
        "analyses": ["无显著事件匹配"],
        "hypotheses": [],
        "open_questions": ["是否受板块联动影响"],
        "evidence_ids": [],
        "confidence": 0.5,
        "warnings": [],
        "missing_data": ["分钟级成交"],
        "metrics": {"matched_events": 0},
        "artifacts": [],
    }
    data.update(overrides)
    return data


def valid_graph_change(**overrides: Any) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "graph_change_id": new_uuid(),
        "change_type": "add_node",
        "node": {
            "node_id": "company:xxx",
            "node_type": "Company",
            "name": "测试公司",
            "aliases": [],
            "description": "",
            "status": "active",
            "valid_from": None,
            "valid_to": None,
            "evidence_ids": ["ev-001"],
            "version": 1,
            "last_reviewed_at": None,
            "review_status": "candidate",
            "origin_kind": "graph_change",
            "originating_graph_change_id": new_uuid(),
            "created_at": T0,
        },
        "edge": None,
        "current_knowledge": "公司产品线不明确。",
        "new_evidence_ids": ["ev-001"],
        "suggested_change": "新增节点。",
        "impact_scope": ["半导体"],
        "conflicts": [],
        "verification_points": ["核实产品公告"],
        "review_status": "candidate",
        "created_at": T0,
        "reviewed_at": None,
    }
    data.update(overrides)
    return data


def invalid_extra_field(data: Dict[str, Any]) -> Dict[str, Any]:
    """给样本附加额外字段 -> 应触发 additionalProperties 失败。"""
    out = copy.deepcopy(data)
    out["unexpected_field"] = True
    return out
