"""Phase 2 晨报对象契约测试（CandidateItem/EventCluster/InformationScore/MorningBriefRun）。

每个对象：正常、边界、非法输入、Schema 与 model dump 一致性。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_os.models import (
    CandidateItem,
    EventCluster,
    InformationScore,
    MorningBriefRun,
)
from research_os.validators.schema_validator import validate_model

T0 = "2026-08-05T20:00:00"
T1 = "2026-08-06T08:00:00"
UUID = "11111111-1111-1111-1111-111111111111"


def valid_candidate(**ov) -> dict:
    d = {
        "candidate_id": UUID, "raw_item_ids": [UUID], "source_ids": ["cls"],
        "monitoring_channel": "fast_news", "title": "某公司发布新产品",
        "summary": "公司发布新一代产品", "published_at": T0, "retrieved_at": T1,
        "event_time": None, "entities": ["company:xxx"],
        "classification_path": ["industry", "event"], "content_type": "fact_report",
        "language": "zh-CN", "status": "collected", "warnings": [],
    }
    d.update(ov)
    return d


def valid_cluster(**ov) -> dict:
    d = {
        "cluster_id": UUID, "canonical_title": "某公司新产品发布", "event_type": "product_launch",
        "event_time": T0, "first_published_at": T0, "last_updated_at": T1,
        "subject_entities": ["company:xxx"], "member_candidate_ids": [UUID],
        "source_ids": ["cls"], "independence_groups": ["g1"],
        "official_confirmation": False, "primary_evidence_ids": [],
        "conflicts": [], "status": "active",
    }
    d.update(ov)
    return d


def valid_score(**ov) -> dict:
    d = {
        "candidate_id": UUID, "novelty": 4, "impact_strength": 3, "authority": 3,
        "certainty": 4, "impact_scope": 3, "expectation_gap": 2,
        "verifiability": 3, "market_relevance": 4,
        "base_score": 65.0, "penalties": [], "bonuses": [],
        "final_score": 65.0, "hard_veto": False, "veto_reasons": [],
        "score_reasons": [], "forced_include": False, "forced_include_reason": None,
    }
    d.update(ov)
    return d


def valid_run(**ov) -> dict:
    d = {
        "report_id": UUID, "task_id": UUID, "as_of": T1,
        "window_start": T0, "window_end": T1,
        "actual_started_at": T0, "actual_finished_at": T1,
        "scheduled_for": "2026-08-06T08:10:00", "delayed": False, "delay_seconds": 0,
        "coverage": [], "selected_cluster_ids": [], "missing_data": [],
        "warnings": [], "status": "success",
    }
    d.update(ov)
    return d


MODELS = [
    (CandidateItem, valid_candidate, "candidate_item"),
    (EventCluster, valid_cluster, "event_cluster"),
    (InformationScore, valid_score, "information_score"),
    (MorningBriefRun, valid_run, "morning_brief_run"),
]


@pytest.mark.parametrize("cls,factory,schema", MODELS)
def test_valid_and_schema_consistent(cls, factory, schema):
    model = cls(**factory())
    assert validate_model(model) == []


@pytest.mark.parametrize("cls,factory,schema", MODELS)
def test_missing_required_fails(cls, factory, schema):
    data = factory()
    key = {"CandidateItem": "candidate_id", "EventCluster": "cluster_id",
           "InformationScore": "candidate_id", "MorningBriefRun": "report_id"}[cls.__name__]
    del data[key]
    with pytest.raises(ValidationError):
        cls(**data)


@pytest.mark.parametrize("cls,factory,schema", MODELS)
def test_extra_field_fails(cls, factory, schema):
    data = factory()
    data["unexpected"] = True
    with pytest.raises(ValidationError):
        cls(**data)


def test_invalid_enum_fails():
    with pytest.raises(ValidationError):
        CandidateItem(**valid_candidate(monitoring_channel="alien_channel"))
    with pytest.raises(ValidationError):
        CandidateItem(**valid_candidate(content_type="gossip"))
    with pytest.raises(ValidationError):
        CandidateItem(**valid_candidate(status="frozen"))
    with pytest.raises(ValidationError):
        EventCluster(**valid_cluster(status="frozen"))
    with pytest.raises(ValidationError):
        MorningBriefRun(**valid_run(status="maybe"))


def test_score_dimension_bounds():
    """各维度 0-5 边界；越界拒绝。"""
    InformationScore(**valid_score(novelty=0, market_relevance=5))
    with pytest.raises(ValidationError):
        InformationScore(**valid_score(novelty=6))
    with pytest.raises(ValidationError):
        InformationScore(**valid_score(final_score=101))


def test_classification_path_validation():
    """分类路径必须属于分类树（主分类 + 子分类）。"""
    CandidateItem(**valid_candidate(classification_path=["macro", "policy"]))
    with pytest.raises(ValidationError):
        CandidateItem(**valid_candidate(classification_path=["aliens", "x"]))
    with pytest.raises(ValidationError):
        CandidateItem(**valid_candidate(classification_path=["macro", "not_a_sub"]))


def test_run_window_ordering():
    """窗口顺序由调用方保证（此处验证时间字段格式）。"""
    with pytest.raises(ValidationError):
        MorningBriefRun(**valid_run(window_start="not-a-date"))


def test_nullable_fields_ok():
    CandidateItem(**valid_candidate(event_time=None))
    EventCluster(**valid_cluster(event_time=None))
