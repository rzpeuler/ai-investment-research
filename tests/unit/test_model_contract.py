"""模型与 Schema 契约测试（docs/contracts/schema-model-contract.md）。

验证：Pydantic 最小构造 → model_dump → JSON Schema 校验通过。
即"模型负责构造便利，Schema 负责完整对象校验"的职责分离。
"""
from __future__ import annotations

import pytest

from research_os.models import (
    Claim, Entity, Event, Evidence, GraphChange, GraphChangeProposal,
    GraphEdge, GraphNode, GraphReview, ModuleResult, Opinion,
    RawItem, Task,
    GraphRelation, GraphAssertionType, GraphReviewer,
    GraphNodeType, GraphProposalAssertionType,
)
from research_os.validators.schema_validator import validate_instance
from tests.fixtures import samples

# 每个对象：最小构造 = 仅提供模型无默认值的必填字段（含 ID 字段，其余走模型默认值）
T0 = "2026-08-05T08:00:00"
_UUID = "11111111-1111-1111-1111-111111111111"
MINIMAL_CONSTRUCTORS = [
    (Task, {"task_id": _UUID, "scenario": "morning_brief", "requested_at": T0, "as_of": T0}, "task"),
    (Entity, {"entity_id": "company:600519.SH", "entity_type": "company",
              "canonical_name": "贵州茅台"}, "entity"),
    (RawItem, {"raw_item_id": _UUID, "source_id": "sse", "url": "https://example.com/a",
               "title": "t", "publisher": "p", "content_hash": "a" * 64,
               "content_excerpt": "x", "published_at": T0, "retrieved_at": T0},
     "raw_item"),
    (Event, {"event_id": _UUID, "event_type": "capacity_expansion", "event_time": T0,
             "announced_at": T0, "summary": "s"}, "event"),
    (Opinion, {"opinion_id": _UUID, "speaker_entity_id": "creator:x", "source_id": "xueqiu",
               "published_at": T0, "thesis": "t"}, "opinion"),
    (Claim, {"claim_id": _UUID, "claim_type": "FACT", "statement": "s",
             "predicate": "has_event", "as_of": T0}, "claim"),
    (Evidence, {"evidence_id": _UUID, "source_id": "cninfo", "raw_item_id": _UUID,
                "title": "t", "publisher": "p", "published_at": T0,
                "retrieved_at": T0, "url": "https://example.com/e",
                "excerpt": "x", "independence_group": "g"}, "evidence"),
    (ModuleResult, {"module": "m", "version": "1.0.0", "as_of": T0},
     "module_result"),
    (GraphChange, {"graph_change_id": _UUID, "change_type": "add_node",
                   "suggested_change": "add new node", "created_at": T0,
                   "node": {
                       "node_id": "company:600519.SH", "node_type": "Company",
                       "name": "贵州茅台", "aliases": [], "description": "",
                       "status": "active", "valid_from": None, "valid_to": None,
                       "evidence_ids": ["ev-001"], "version": 1,
                       "last_reviewed_at": None, "review_status": "candidate",
                       "origin_kind": "graph_change",
                       "originating_graph_change_id": _UUID, "created_at": T0,
                   },
                   "edge": None,
                   "new_evidence_ids": ["ev-001"]}, "graph_change"),
    (GraphNode, {"node_id": "company:600519.SH", "node_type": "Company",
                 "name": "贵州茅台", "created_at": T0,
                 "origin_kind": "graph_change",
                 "originating_graph_change_id": _UUID,
                 "evidence_ids": ["ev-001"]}, "graph_node"),
    (GraphEdge, {"edge_id": "edge-001", "source_node_id": "company:A",
                 "relation": "SUPPLIES", "target_node_id": "company:B",
                 "created_at": T0, "originating_graph_change_id": _UUID,
                 "evidence_ids": ["ev-001"]}, "graph_edge"),
    (GraphChangeProposal, {"proposal_type": "add_node",
                           "source_object_ids": ["obj-001"],
                           "candidate_node": {"existing_node_id": None,
                                              "node_type": "Company",
                                              "name": "新公司",
                                              "aliases": [], "description": "",
                                              "valid_from": None, "valid_to": None},
                           "candidate_edge": None,
                           "new_evidence_ids": ["ev-001"],
                           "suggested_change": "add"}, "graph_change_proposal"),
    (GraphReview, {"review_id": _UUID, "graph_change_id": _UUID,
                   "decision": "approved",
                   "reviewer": {"reviewer_type": "human", "reviewer_id": "user-001",
                                "display_name": "Test"},
                   "reviewed_at": T0, "candidate_hash": "a" * 64}, "graph_review"),
]


@pytest.mark.parametrize("model_cls,kwargs,schema_name", MINIMAL_CONSTRUCTORS)
def test_minimal_construct_dump_passes_schema(model_cls, kwargs, schema_name):
    """最小构造（省略全部带默认值字段）→ model_dump → Schema 校验必须通过。"""
    model = model_cls(**kwargs)
    full = model.model_dump()
    errors = validate_instance(full, schema_name)
    assert errors == [], (
        f"{model_cls.__name__} 最小构造 dump 未通过 {schema_name} Schema: {errors}"
    )


@pytest.mark.parametrize("model_cls,kwargs,schema_name", MINIMAL_CONSTRUCTORS)
def test_dump_contains_all_required_fields(model_cls, kwargs, schema_name):
    """dump 后必须包含 Schema 声明的全部 required 字段（默认值已填充）。"""
    from research_os.validators.schema_validator import load_schema

    schema = load_schema(schema_name)
    full = model_cls(**kwargs).model_dump()
    missing = [f for f in schema["required"] if f not in full]
    assert missing == [], f"{model_cls.__name__} dump 缺少 required 字段: {missing}"


def test_partial_model_fields_not_valid_as_object():
    """裸模型局部字段（未完整 dump）不得直接通过 Schema 校验（从严）。"""
    task = Task(task_id="11111111-1111-1111-1111-111111111111",
                scenario="morning_brief", requested_at="2026-08-05T08:00:00",
                as_of="2026-08-05T08:00:00")
    partial = {"task_id": task.task_id, "status": task.status}
    errors = validate_instance(partial, "task")
    assert errors, "部分字段 dict 应被 Schema 拒绝（缺少 required 字段）"


def test_bare_dict_input_validated_strictly():
    """裸 dict 输入按 Schema 严格规则：缺字段/额外字段均拒绝。"""
    from tests.fixtures.samples import invalid_extra_field, valid_task

    assert validate_instance(valid_task(), "task") == []
    assert validate_instance(invalid_extra_field(valid_task()), "task")
    bad = valid_task()
    del bad["warnings"]
    assert validate_instance(bad, "task")
