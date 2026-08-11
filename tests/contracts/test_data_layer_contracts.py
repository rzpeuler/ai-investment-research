"""P7-D0 Unified Data Layer contract tests.

覆盖：5 个 Schema 注册/可加载、5 个 Pydantic 模型 model_dump 后通过对应 JSON Schema、
未知字段拒绝（additionalProperties=false）、非法枚举拒绝、BriefAttentionSnapshot
禁止持续监控字段（additionalProperties=false 拒绝）、AcquisitionPlan 禁止 source 字段。
"""
from __future__ import annotations

import pytest

from research_os.models import (
    AcquisitionPlan,
    AcquisitionStep,
    AttentionCoverage,
    AttentionTopic,
    BriefAttentionSnapshot,
    DataGap,
    DataReadiness,
    GroupCount,
    PublicMetric,
    RequirementScope,
    ScenarioDataRequirement,
)
from research_os.validators.schema_validator import SCHEMA_NAMES, load_schema, validate_instance

_NEW_SCHEMAS = [
    "scenario_data_requirement",
    "data_readiness",
    "data_gap",
    "acquisition_plan",
    "brief_attention_snapshot",
]

_ISO = "2026-08-11T08:00:00+08:00"


def _requirement() -> ScenarioDataRequirement:
    return ScenarioDataRequirement(
        requirement_id="r1",
        scenario="morning_brief",
        purpose="brief_event_discovery",
        data_type="news_flash",
        scope=RequirementScope(scope_type="global"),
        time_policy="scenario_window",
        required=True,
        minimum_fields=["title", "published_at", "url"],
        minimum_coverage=0.5,
        minimum_source_tier="B",
        freshness_seconds=43200,
        point_in_time_policy="window_bounded",
        acceptable_fallback_modes=["manual_inbox"],
        degradation_policy="degraded",
        notes="x",
    )


def _snapshot() -> BriefAttentionSnapshot:
    return BriefAttentionSnapshot(
        snapshot_id="s1",
        task_id="t1",
        scenario="morning_brief",
        window_start="2026-08-10T20:00:00+08:00",
        window_end="2026-08-11T08:00:00+08:00",
        as_of=_ISO,
        coverage=[
            AttentionCoverage(
                watchlist_group="financial_media", configured_count=5,
                attempted_count=5, succeeded_count=0, failed_count=5,
                status="source_failure", warnings=["无可用获取器"],
            )
        ],
        topics=[
            AttentionTopic(
                rank=1, topic_label="某主题", heat_score=0.9,
                mention_count=10, unique_source_count=3, unique_author_count=5,
                group_counts=[GroupCount(group="community", count=7)],
                representative_item_ids=["ri-1"],
                public_metrics=[PublicMetric(
                    metric_name="views", value=100, unit="count",
                    source_reference="item-1", observed_at=_ISO,
                )],
                warnings=[],
            )
        ],
        warnings=[],
    )


class TestSchemasRegistered:
    def test_all_new_schemas_in_names(self):
        for name in _NEW_SCHEMAS:
            assert name in SCHEMA_NAMES, f"{name} 未注册"

    def test_all_new_schemas_loadable(self):
        for name in _NEW_SCHEMAS:
            s = load_schema(name)
            assert s is not None and s.get("additionalProperties") is False


class TestModelContract:
    """5 个 Pydantic 模型 model_dump 后全部通过对应 JSON Schema。"""

    @pytest.mark.parametrize("model, schema", [
        (_requirement(), "scenario_data_requirement"),
    ])
    def test_requirement_passes_schema(self, model, schema):
        assert validate_instance(model.model_dump(), schema) == []

    def test_readiness_passes_schema(self):
        r = DataReadiness(
            requirement_id="r1", data_type="news_flash",
            checked_at=_ISO, as_of=_ISO, status="MISSING",
            available_fields=[], missing_fields=["title"],
            coverage_ratio=0.0, freshness_age_seconds=None,
            eligible_record_count=0, ineligible_record_count=0,
            source_tiers_present=[], record_refs=[], warnings=[],
        )
        assert validate_instance(r.model_dump(), "data_readiness") == []

    def test_gap_passes_schema(self):
        g = DataGap(
            requirement_id="r1", data_type="news_flash",
            classification="MANUAL_INPUT_REQUIRED",
            reason_codes=["NO_SOURCE"], missing_fields=["title"],
            recommended_action="request_manual_input",
            requires_network=False, requires_user_input=True,
            requires_human_review=False, warnings=[],
        )
        assert validate_instance(g.model_dump(), "data_gap") == []

    def test_plan_passes_schema(self):
        p = AcquisitionPlan(
            task_id="task-1", scenario="morning_brief", as_of=_ISO,
            steps=[AcquisitionStep(
                step_id="s1", requirement_id="r1", data_type="news_flash",
                action="route_existing_sources", dependencies=[], status="pending",
                warnings=[],
            )],
            warnings=[],
        )
        assert validate_instance(p.model_dump(), "acquisition_plan") == []

    def test_snapshot_passes_schema(self):
        assert validate_instance(_snapshot().model_dump(), "brief_attention_snapshot") == []


class TestStrictness:
    def test_unknown_field_rejected(self):
        payload = _requirement().model_dump()
        payload["source_id"] = "cls"
        assert validate_instance(payload, "scenario_data_requirement") != []

    def test_unknown_plan_step_field_rejected(self):
        payload = AcquisitionPlan(
            task_id="t", scenario="morning_brief", as_of=_ISO,
            steps=[AcquisitionStep(
                step_id="s", requirement_id="r", data_type="d",
                action="unavailable", dependencies=[], status="pending", warnings=[],
            )],
            warnings=[],
        ).model_dump()
        payload["steps"][0]["selected_source"] = "cls"
        assert validate_instance(payload, "acquisition_plan") != []

    def test_unknown_snapshot_field_rejected(self):
        payload = _snapshot().model_dump()
        payload["rank_change"] = 3
        assert validate_instance(payload, "brief_attention_snapshot") != []


class TestEnumValidation:
    def test_invalid_readiness_status(self):
        with pytest.raises(ValueError):
            DataReadiness(
                requirement_id="r", data_type="d", checked_at=_ISO, as_of=_ISO,
                status="NOPE", available_fields=[], missing_fields=[],
                coverage_ratio=0.0, freshness_age_seconds=None,
                eligible_record_count=0, ineligible_record_count=0,
                source_tiers_present=[], record_refs=[], warnings=[],
            )

    def test_invalid_gap_classification(self):
        with pytest.raises(ValueError):
            DataGap(
                requirement_id="r", data_type="d", classification="NOPE",
                reason_codes=[], missing_fields=[], recommended_action="x",
                requires_network=False, requires_user_input=False,
                requires_human_review=False, warnings=[],
            )

    def test_invalid_plan_action(self):
        with pytest.raises(ValueError):
            AcquisitionStep(
                step_id="s", requirement_id="r", data_type="d", action="fetch_now",
                dependencies=[], status="pending", warnings=[],
            )

    def test_invalid_snapshot_scenario(self):
        with pytest.raises(ValueError):
            BriefAttentionSnapshot(
                snapshot_id="s", task_id="t", scenario="stock_review",
                window_start=_ISO, window_end=_ISO, as_of=_ISO,
                coverage=[], topics=[], warnings=[],
            )

    def test_invalid_topic_group_counts_free_key(self):
        """group_counts 必须用 {group, count} 数组，不能自由键 dict。"""
        with pytest.raises(ValueError):
            AttentionTopic(
                rank=1, topic_label="t", heat_score=1.0, mention_count=1,
                unique_source_count=1, unique_author_count=1,
                group_counts="not-a-list",  # type: ignore[arg-type]
                representative_item_ids=[], public_metrics=[], warnings=[],
            )


class TestOneShotAttention:
    def test_snapshot_rejects_continuous_fields(self):
        """additionalProperties=false 保证 rank_change/velocity/trend/history 输入失败。"""
        for field in ("rank_change", "previous_rank", "velocity", "acceleration",
                      "trend", "persistence", "history", "historical_heat"):
            payload = _snapshot().model_dump()
            payload[field] = 1
            assert validate_instance(payload, "brief_attention_snapshot") != [], \
                f"{field} 应被拒绝"
            topic_payload = _snapshot().model_dump()
            topic_payload["topics"][0][field] = 1
            assert validate_instance(topic_payload, "brief_attention_snapshot") != [], \
                f"topics[].{field} 应被拒绝"

    def test_schema_has_no_continuous_properties(self):
        schema = load_schema("brief_attention_snapshot")
        props = set(schema["properties"].keys())
        topic_props = set(schema["properties"]["topics"]["items"]["properties"].keys())
        forbidden = {"rank_change", "previous_rank", "velocity", "acceleration",
                     "trend", "persistence", "history", "historical_heat"}
        assert forbidden.isdisjoint(props)
        assert forbidden.isdisjoint(topic_props)


# ---------- R1: Contract Strictness ----------

class TestR1PublicMetricsStrict:
    """R1-01：public_metrics 必须是严格 array[PublicMetric]，不能是自由 dict。"""

    def test_free_dict_rejected(self):
        """public_metrics = {"views": 100} 必须失败（不再允许自由键 object）。"""
        payload = _snapshot().model_dump()
        payload["topics"][0]["public_metrics"] = {"views": 100}
        assert validate_instance(payload, "brief_attention_snapshot") != []

    def test_nested_unknown_field_fails(self):
        """public_metrics 元素带 trend 必须失败（nested additionalProperties=false）。"""
        payload = _snapshot().model_dump()
        payload["topics"][0]["public_metrics"] = [
            {"metric_name": "views", "value": 100, "trend": "up"}
        ]
        assert validate_instance(payload, "brief_attention_snapshot") != []

    def test_historical_heat_embedded_fails(self):
        """public_metrics 元素带 historical_heat 必须失败。"""
        payload = _snapshot().model_dump()
        payload["topics"][0]["public_metrics"] = [
            {"metric_name": "views", "value": 100, "historical_heat": 90}
        ]
        assert validate_instance(payload, "brief_attention_snapshot") != []

    def test_legal_metric_passes(self):
        """合法 public_metrics 元素通过。"""
        payload = _snapshot().model_dump()
        payload["topics"][0]["public_metrics"] = [
            {"metric_name": "views", "value": 100, "unit": "count",
             "source_reference": "item-1", "observed_at": "2026-08-11T08:00:00+08:00"}
        ]
        assert validate_instance(payload, "brief_attention_snapshot") == []

    def test_schema_public_metrics_is_strict_array(self):
        schema = load_schema("brief_attention_snapshot")
        pm = schema["properties"]["topics"]["items"]["properties"]["public_metrics"]
        assert pm["type"] == "array"
        item = pm["items"]
        assert item["additionalProperties"] is False
        assert set(item["required"]) == {"metric_name", "value", "unit", "source_reference", "observed_at"}

    def test_pydantic_public_metrics_is_list(self):
        snap = _snapshot()
        assert isinstance(snap.topics[0].public_metrics, list)
        assert snap.topics[0].public_metrics[0].metric_name == "views"


class TestR1ScopeRequired:
    """R1-02：scope 完整对象字段全部 required。"""

    def test_scope_missing_reference_fails(self):
        payload = _requirement().model_dump()
        payload["scope"] = {"scope_type": "global", "watchlist_group": None}
        assert validate_instance(payload, "scenario_data_requirement") != []

    def test_scope_missing_watchlist_group_fails(self):
        payload = _requirement().model_dump()
        payload["scope"] = {"scope_type": "global", "reference": None}
        assert validate_instance(payload, "scenario_data_requirement") != []

    def test_pydantic_dump_contains_all_three(self):
        from research_os.models import RequirementScope
        scope = RequirementScope(scope_type="global")
        dumped = scope.model_dump()
        assert set(dumped.keys()) == {"scope_type", "reference", "watchlist_group"}
        assert dumped["scope_type"] == "global"
        assert dumped["reference"] is None
        assert dumped["watchlist_group"] is None
        # 完整 requirement dump 后通过 Schema
        payload = _requirement().model_dump()
        assert validate_instance(payload, "scenario_data_requirement") == []

    def test_schema_scope_required_complete(self):
        schema = load_schema("scenario_data_requirement")
        assert set(schema["properties"]["scope"]["required"]) == {
            "scope_type", "reference", "watchlist_group"
        }
