"""Phase 3 契约测试（任务书 5 节、19.2 节）。

每个新增对象验证：正常构造 / 边界值 / 缺必填字段 / 非法枚举 / 额外字段 /
非法时间 / 非法 confidence / Pydantic dump 后 Schema 一致。
同时验证 Schema 总数（30）与注册清单一致。

遵循 schema-model-contract.md：JSON Schema 为完整权威契约（全部字段 required、
additionalProperties:false）；Pydantic 仅构造便利；dump 后必须通过 Schema。
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from research_os.models import (
    AbnormalMoveObservation,
    AbnormalMoveRequest,
    AbnormalMoveRun,
    AnomalyMetric,
    AttributionResult,
    BenchmarkCandidate,
    BenchmarkSelection,
    CauseCandidate,
    CauseEvidenceLink,
    MarketDailySeriesManifest,
    MarketMinuteBar,
)
from research_os.validators.schema_validator import (
    SCHEMA_NAMES,
    validate_all_schemas,
    validate_model,
)

UUID1 = "11111111-1111-1111-1111-111111111111"
UUID2 = "22222222-2222-2222-2222-222222222222"
UUID3 = "33333333-3333-3333-3333-333333333333"
UUID4 = "44444444-4444-4444-4444-444444444444"
TS = "2026-08-05T20:00:00"
D = "2026-08-05"


def _manifest() -> MarketDailySeriesManifest:
    return MarketDailySeriesManifest(
        import_id=UUID1, source_id="manual_import", file_name="d.csv",
        file_checksum="abc", imported_at=TS, imported_by="tester",
        symbols=["600519.SH"], date_start="2026-01-01", date_end="2026-08-01",
        row_count=100, adjustment_method="qfq", adjustment_description="前复权",
        calendar_id="cn-sse", calendar_version="v1", currency="CNY",
        price_unit="yuan", volume_unit="shares", data_version="v1",
    )


def _minute_bar() -> MarketMinuteBar:
    return MarketMinuteBar(
        bar_id=UUID1, symbol="600519.SH", trade_date=D,
        bar_time="2026-08-05T10:30:00", interval="1min", open=10, high=11,
        low=9, close=10.5, volume=1000, amount=10500, source_id="manual_import",
        data_version="v1",
    )


def _request() -> AbnormalMoveRequest:
    return AbnormalMoveRequest(
        request_id=UUID1, task_id=UUID2, entity_id="600519.SH",
        entity_type="company", analysis_date=D, window_start="2026-08-01",
        window_end="2026-08-05", as_of=TS,
    )


def _metric() -> AnomalyMetric:
    return AnomalyMetric(
        metric_id=UUID1, observation_id=UUID2, metric_type="absolute_return",
        value=0.095, unit="pct", direction="positive", severity=4,
        sample_size=60, minimum_sample_size=40,
    )


def _observation() -> AbnormalMoveObservation:
    return AbnormalMoveObservation(
        observation_id=UUID1, request_id=UUID2, entity_id="600519.SH",
        entity_type="company", window_start="2026-08-01", window_end="2026-08-05",
        trade_date=D,
    )


def _benchmark_candidate() -> BenchmarkCandidate:
    return BenchmarkCandidate(
        benchmark_candidate_id=UUID1, request_id=UUID2,
        subject_entity_id="600519.SH", benchmark_entity_id="index:000300.SH",
        benchmark_type="market",
    )


def _benchmark_selection() -> BenchmarkSelection:
    return BenchmarkSelection(
        benchmark_selection_id=UUID1, request_id=UUID2, observation_id=UUID3,
        market_benchmark_id="index:000300.SH", selected_at=TS,
        information_cutoff="2026-08-01T00:00:00",
    )


def _cause_candidate() -> CauseCandidate:
    return CauseCandidate(
        cause_candidate_id=UUID1, request_id=UUID2, observation_id=UUID3,
        title="公告触发", cause_category="direct_trigger",
    )


def _link() -> CauseEvidenceLink:
    return CauseEvidenceLink(
        link_id=UUID1, cause_candidate_id=UUID2, evidence_id="ev-1",
        relation="supports", directness="direct", timing_relation="before",
        independence_group="g1", created_at=TS,
    )


def _attribution() -> AttributionResult:
    return AttributionResult(
        attribution_result_id=UUID1, request_id=UUID2, observation_id=UUID3,
        attribution_status="EXPLAINED", overall_confidence=0.8,
    )


def _run() -> AbnormalMoveRun:
    return AbnormalMoveRun(
        run_id=UUID1, task_id=UUID2, request_id=UUID3, observation_id=UUID4,
        idempotency_key="k1", started_at=TS, finished_at=TS,
    )


# (模型名, 构造工厂, 无默认值的必填字段名——用于缺字段测试)
MODELS = [
    ("MarketDailySeriesManifest", _manifest, "import_id"),
    ("MarketMinuteBar", _minute_bar, "bar_id"),
    ("AbnormalMoveRequest", _request, "entity_id"),
    ("AnomalyMetric", _metric, "metric_id"),
    ("AbnormalMoveObservation", _observation, "observation_id"),
    ("BenchmarkCandidate", _benchmark_candidate, "benchmark_candidate_id"),
    ("BenchmarkSelection", _benchmark_selection, "benchmark_selection_id"),
    ("CauseCandidate", _cause_candidate, "cause_candidate_id"),
    ("CauseEvidenceLink", _link, "link_id"),
    ("AttributionResult", _attribution, "attribution_result_id"),
    ("AbnormalMoveRun", _run, "run_id"),
]

PHASE3_SCHEMAS = {
    "market_daily_series_manifest",
    "market_minute_bar",
    "abnormal_move_request",
    "anomaly_metric",
    "abnormal_move_observation",
    "benchmark_candidate",
    "benchmark_selection",
    "cause_candidate",
    "cause_evidence_link",
    "attribution_result",
    "abnormal_move_run",
}


def _with(obj, **overrides):
    """构造 obj 的副本并覆盖指定字段（避免关键字重复）。"""
    d = obj.model_dump()
    d.update(overrides)
    return obj.__class__(**d)


class TestSchemaRegistry:
    def test_schema_total_count_is_50(self):
        assert len(SCHEMA_NAMES) == 50

    def test_phase3_schemas_registered(self):
        assert PHASE3_SCHEMAS <= set(SCHEMA_NAMES)

    def test_all_schemas_valid(self):
        results = validate_all_schemas()
        bad = {k: v for k, v in results.items() if v}
        assert bad == {}, f"非法 Schema: {bad}"


class TestPhase3ModelContracts:
    @pytest.mark.parametrize("name,factory,required_field", MODELS, ids=[m[0] for m in MODELS])
    def test_valid_construct_and_schema(self, name, factory, required_field):
        obj = factory()
        errors = validate_model(obj)
        assert errors == [], f"{name} dump 后未通过 Schema: {errors}"

    @pytest.mark.parametrize("name,factory,required_field", MODELS, ids=[m[0] for m in MODELS])
    def test_extra_field_rejected(self, name, factory, required_field):
        obj = factory()
        with pytest.raises(ValidationError):
            obj.__class__(**obj.model_dump(), bogus_extra_field=1)

    @pytest.mark.parametrize("name,factory,required_field", MODELS, ids=[m[0] for m in MODELS])
    def test_missing_required_field_rejected(self, name, factory, required_field):
        obj = factory()
        with pytest.raises(ValidationError):
            obj.__class__(
                **{k: v for k, v in obj.model_dump().items() if k != required_field}
            )

    def test_invalid_enum_rejected(self):
        with pytest.raises(ValidationError):
            _with(_request(), entity_type="bad_type")
        with pytest.raises(ValidationError):
            _with(_metric(), metric_type="not_a_metric")
        with pytest.raises(ValidationError):
            _with(_attribution(), attribution_status="MADE_UP")
        with pytest.raises(ValidationError):
            _with(_cause_candidate(), cause_category="no_such_category")

    def test_invalid_time_rejected(self):
        with pytest.raises(ValidationError):
            _with(_request(), as_of="2026-13-99T99:99:99")
        with pytest.raises(ValidationError):
            _with(_request(), analysis_date="2026/08/05")
        with pytest.raises(ValidationError):
            _with(_run(), started_at="not-a-time")

    def test_invalid_confidence_rejected(self):
        with pytest.raises(ValidationError):
            _with(_observation(), confidence=1.5)
        with pytest.raises(ValidationError):
            _with(_attribution(), overall_confidence=-0.1)
        with pytest.raises(ValidationError):
            _with(_benchmark_candidate(), total_score=120)

    def test_severity_bounds_rejected(self):
        with pytest.raises(ValidationError):
            _with(_metric(), severity=6)
        with pytest.raises(ValidationError):
            _with(_metric(), severity=-1)

    def test_timezone_constraint(self):
        with pytest.raises(ValidationError):
            _with(_request(), timezone="UTC")
        with pytest.raises(ValidationError):
            _with(_minute_bar(), timezone="UTC")

    def test_uuid_constraint(self):
        with pytest.raises(ValidationError):
            _with(_request(), request_id="not-a-uuid")
        with pytest.raises(ValidationError):
            _with(_observation(), observation_id="x")

    def test_dump_roundtrip_is_stable(self):
        """dump -> 重新构造 -> dump 幂等。"""
        for name, factory, required_field in MODELS:
            obj = factory()
            d1 = obj.model_dump()
            d2 = obj.__class__(**d1).model_dump()
            assert d1 == d2, f"{name} dump 往返不稳定"


class TestPeerMoveNested:
    def test_peer_move_is_nested_no_top_level_schema(self):
        assert "peer_move" not in SCHEMA_NAMES
        obs = _observation().model_dump()
        assert "peer_moves" in obs

    def test_invalid_peer_move_rejected(self):
        with pytest.raises(ValidationError):
            _with(_observation(), peer_moves=[{"peer_entity_id": "000858.SZ", "severity": 9}])
