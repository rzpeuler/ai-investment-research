"""P7-D2 Foundation integration through fake-only injected collaborators."""
from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from research_os.collectors import CollectorAdapter, HealthStatus, ItemRef, RateLimitPolicy, RawPayload
from research_os.data_layer import (
    AcquisitionCoordinationResult,
    AcquisitionCoordinator,
    AcquisitionExecutionService,
    AcquisitionRepository,
    CollectorFetcherBridge,
)
from research_os.data_layer.capabilities import AcquisitionCapability
from research_os.data_layer.checkers import RawItemChecker, ReadinessCheckerRegistry
from research_os.data_layer.execution_policy import ExecutionPolicy
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.projector import ReadinessFieldProjector
from research_os.models import (
    AcquisitionExecutionResult,
    AcquisitionStep,
    DataRoute,
    RawItem,
)
from research_os.orchestrator import Orchestrator
from research_os.orchestrator.scenario_registry import ScenarioRegistry
from research_os.orchestrator.scenario_runner import ScenarioExecutionResult
from research_os.routing.requirements import DataRequirementRegistry
from research_os.routing.router import RoutedDataBatch, Router
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry
from research_os.storage import Database
from research_os.utils.time import parse_iso


ROOT = Path(__file__).resolve().parents[2]
AS_OF = "2026-08-16T08:00:00+08:00"
TASK_FOUNDATION = "11111111-1111-4111-8111-111111111111"
TASK_EMPTY = "22222222-2222-4222-8222-222222222222"
TASK_REPLAY_1 = "33333333-3333-4333-8333-333333333333"
TASK_REPLAY_2 = "44444444-4444-4444-8444-444444444444"
TASK_CLOSED = "55555555-5555-4555-8555-555555555555"
TASK_DRY = "66666666-6666-4666-8666-666666666666"


class _Runner:
    scenario = "morning_brief"
    version = "1.0.0"

    def __init__(self, events):
        self.events = events

    def validate_request(self, request):
        self.events.append("validate")
        return request

    def build_plan(self, request, context):
        return {"steps": ["research"]}

    def execute(self, request, context):
        self.events.append("runner")
        self.context = context
        return ScenarioExecutionResult(
            status="success", exit_code=0, task_id=context["task"].task_id,
            missing_data=["runner-owned-marker"],
        )


class _FakeCollector(CollectorAdapter):
    source_id = "cls"
    version = "fake"

    def __init__(
        self, events, *, empty=False, external_id="fake-1", published_at=None,
        duplicate_refs=False, adapter_source_id="cls", fetch_error=None,
    ):
        self.events = events
        self.empty = empty
        self.external_id = external_id
        self.published_at = published_at or "2026-08-16T07:30:00+08:00"
        self.duplicate_refs = duplicate_refs
        self.source_id = adapter_source_id
        self.fetch_error = fetch_error

    def healthcheck(self):
        return HealthStatus(source_id=self.source_id, ok=True)

    def discover(self, query, time_window):
        self.events.append("discover")
        if self.empty:
            return []
        ref = ItemRef(
            source_id=self.source_id, external_id=self.external_id,
            url=f"https://example.test/{self.external_id}",
            published_at=self.published_at,
        )
        return [ref, ref.model_copy(deep=True)] if self.duplicate_refs else [ref]

    def fetch(self, item_ref):
        self.events.append("fetch")
        if self.fetch_error is not None:
            raise RuntimeError(self.fetch_error)
        return RawPayload(
            source_id=self.source_id, external_id=item_ref.external_id,
            url=item_ref.url, title="fake headline", publisher="fixture",
            published_at=item_ref.published_at, content="fixture",
            retrieved_at="2026-08-16T08:05:00+08:00",
        )

    def normalize(self, payload):
        self.events.append("normalize")
        return [RawItem(
            raw_item_id=str(uuid.uuid4()), source_id=self.source_id,
            external_id=payload.external_id, url=payload.url, title=payload.title,
            publisher=payload.publisher, published_at=payload.published_at,
            retrieved_at=payload.retrieved_at,
            content_hash=hashlib.sha256(payload.content.encode()).hexdigest(),
            content_excerpt=payload.content, content_storage="metadata_and_excerpt",
            language="zh-CN", access_status="ok", entities=[], raw_category="news_flash",
        )]

    def rate_limit_policy(self):
        return RateLimitPolicy()


class _RequirementAuthority:
    """One central requirement with coverage set to a closed fake-test threshold."""

    def __init__(self):
        base = ScenarioDataRequirementRegistry(
            ROOT / "registry" / "scenario_data_requirements.yaml"
        ).get("morning_brief.event.news_flash")
        self.item = base.model_copy(update={"minimum_coverage": 0.0})

    def get(self, requirement_id):
        return self.item if requirement_id == self.item.requirement_id else None

    def for_scenario(self, scenario):
        return [self.item] if scenario == "morning_brief" else []

    def all(self):
        return [self.item]


class _CapabilityAuthority:
    def __init__(self):
        self.item = AcquisitionCapability(
            data_type="news_flash",
            automatic_acquisition_lifecycle="BUSINESS_SUFFICIENT",
        )

    def get(self, data_type):
        if data_type != "news_flash":
            raise KeyError(data_type)
        return self.item

    def has(self, data_type):
        return data_type == "news_flash"


class _FakeRefreshChecker(RawItemChecker):
    """Fake data-family semantics: a newly observed record refreshes the fixture snapshot."""

    data_types = ("news_flash",)

    def _freshness_age(self, eligible, spec, ctx):
        ages = [
            max(0, int((parse_iso(ctx.as_of) - parse_iso(item["published_at"])).total_seconds()))
            for item in eligible if item.get("published_at")
        ]
        return min(ages) if ages else None


def _wired(
    tmp_path, *, empty=False, published_at=None, fallback_primary=False,
    invalid_batch=False, fake_refresh_semantics=False, duplicate_refs=False,
    adapter_source_id="cls", fetch_error=None,
):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    events = []
    requirements = _RequirementAuthority()
    capabilities = _CapabilityAuthority()
    checker_registry = (
        ReadinessCheckerRegistry([_FakeRefreshChecker()])
        if fake_refresh_semantics else ReadinessCheckerRegistry()
    )
    preflight = DataPreflightService(requirements, capabilities, checker_registry)
    original_run = preflight.run

    def run_spy(**kwargs):
        events.append("preflight_before")
        return original_run(**kwargs)

    def recheck_spy(**kwargs):
        events.append("recheck")
        return original_run(**kwargs)

    preflight.run = run_spy
    preflight.recheck = recheck_spy
    collector = _FakeCollector(
        events, empty=empty, published_at=published_at,
        duplicate_refs=duplicate_refs, adapter_source_id=adapter_source_id,
        fetch_error=fetch_error,
    )
    bridge = CollectorFetcherBridge({"cls": collector})
    fetchers = bridge.as_fetchers()
    if empty:
        # An authoritative empty result can only be represented when the source adapter's
        # contract independently proves the response field shape.
        fetchers = {"cls": lambda query, window: (
            [], frozenset({"title", "published_at", "url"}),
        )}
    requirement_path = ROOT / "registry" / "data_requirements.yaml"
    if fallback_primary:
        requirement_path = tmp_path / "fake_requirements.yaml"
        requirement_path.write_text(
            "requirements:\n  news_flash:\n    primary: [unavailable-primary]\n"
            "    secondary: [cls]\n    fallback: []\n"
            "    minimum_acceptable:\n      fields: [title, published_at, url]\n"
            "    failure_policy: degraded\n",
            encoding="utf-8",
        )
    router = Router(DataRequirementRegistry(requirement_path), fetchers)
    if invalid_batch:
        valid_fetch = fetchers["cls"]

        class _InvalidBatchRouter:
            def resolve_with_items(self, data_type, query=None, time_window=None):
                items, fields = valid_fetch(dict(query or {}), dict(time_window or {}))
                route = DataRoute(
                    data_type=data_type, requested_sources=["cls"],
                    attempted_sources=["cls"], selected_source="cls",
                    fallback_used=False, status="success", missing_fields=[], warnings=[],
                )
                return RoutedDataBatch(route=route, items=(*items, object()), fields_present=fields)

        router = _InvalidBatchRouter()
    db = Database(project / "data" / "sqlite" / "research.db")
    db.initialize()
    execution = AcquisitionExecutionService(
        policy=ExecutionPolicy(True, ("route_existing_sources",), ()),
        requirement_registry=requirements,
        capability_registry=capabilities,
        router=router,
        repository=AcquisitionRepository(db, clock=lambda: "2026-08-16T08:06:00+08:00"),
        clock=lambda: "2026-08-16T08:06:00+08:00",
    )
    coordinator = AcquisitionCoordinator(
        preflight=preflight, execution=execution, live_authorized=True,
    )
    runner = _Runner(events)
    registry = ScenarioRegistry()
    registry.register(runner)
    orchestrator = Orchestrator(
        project, db=db, registry=registry, preflight=preflight,
        acquisition_coordinator=coordinator,
    )
    return project, events, runner, db, orchestrator


def test_fake_collector_missing_persist_ready_and_exact_order(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    coordination = runner.context["data_acquisition"]
    assert coordination.readiness_before.readiness[0].status == "MISSING"
    assert coordination.execution.steps[0].inserted_count == 1
    assert coordination.readiness_after.readiness[0].status == "READY"
    assert coordination.execution.readiness_after_requirement_ids == [
        item.requirement_id for item in coordination.readiness_after.readiness
    ]
    assert events == [
        "validate", "preflight_before", "discover", "fetch", "normalize", "recheck", "runner",
    ]
    assert db.count("raw_items") == 1
    run_dir = Path(result.run_dir)
    assert (run_dir / "acquisition_execution.json").is_file()
    assert (run_dir / "data_readiness_after.jsonl").is_file()
    execution_payload = json.loads((run_dir / "acquisition_execution.json").read_text("utf-8"))
    assert execution_payload["status"] == "completed"
    assert result.missing_data == ["runner-owned-marker"]
    orchestrator.close()


def test_empty_result_stays_missing_and_is_audited(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path, empty=True)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_EMPTY, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    coordination = runner.context["data_acquisition"]
    assert coordination.execution.steps[0].status == "partial_success"
    assert coordination.execution.steps[0].reason_codes == ["EMPTY_RESULT"]
    assert coordination.readiness_after.readiness[0].status == "MISSING"
    assert db.count("raw_items") == 0
    assert db.count("data_routes") == 1
    assert result.exit_code == 0
    orchestrator.close()


def test_replay_keeps_raw_item_count_and_reports_reuse(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    first = orchestrator.execute("morning_brief", {
        "task_id": TASK_REPLAY_1, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    replay = orchestrator.acquisition_coordinator.coordinate(
        before=runner.context["data_acquisition"].readiness_before,
        scenario="morning_brief", task_id=TASK_REPLAY_1, task_as_of=AS_OF,
        normalized_request={"report_date": "2026-08-16", "as_of": AS_OF},
        project_root=project, db=db, runs_root=project / "reports" / "runs",
        dry_run=False,
    )
    assert first.exit_code == 0
    assert db.count("raw_items") == 1
    assert replay.execution.steps[0].inserted_count == 0
    assert replay.execution.steps[0].reused_count == 1
    assert db.count("data_routes") == 2
    orchestrator.close()


def test_duplicate_itemrefs_and_normalized_items_are_accounted_once(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path, duplicate_refs=True)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    step = runner.context["acquisition_execution"].steps[0]
    assert events.count("fetch") == events.count("normalize") == 2
    assert step.status == "completed"
    assert step.inserted_count == 1
    assert step.reused_count == 0
    assert db.count("raw_items") == db.count("data_routes") == 1
    assert result.exit_code == 0
    orchestrator.close()


def test_adapter_source_identity_mismatch_fails_without_persistence(tmp_path):
    project, events, runner, db, orchestrator = _wired(
        tmp_path, adapter_source_id="forged-source",
    )
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    step = runner.context["acquisition_execution"].steps[0]
    assert step.status == "failed"
    assert step.reason_codes == ["ROUTE_UNAVAILABLE"]
    assert db.count("raw_items") == db.count("data_routes") == 0
    assert result.exit_code == 0
    orchestrator.close()


@pytest.mark.parametrize("secret_error", [
    "Authorization: Bearer top-secret-token",
    "Authorization Bearer delimiter-free-secret",
    "Cookie=session=top-secret-cookie",
    "Cookie sessionid delimiter-free-cookie",
    "token top-secret",
    "headers={'X-Auth-Token': 'top-secret-token'}",
    "<html><body>full private upstream payload</body></html>",
])
def test_collector_credentials_never_escape_execution_audit(tmp_path, secret_error):
    project, events, runner, db, orchestrator = _wired(
        tmp_path, fetch_error=secret_error,
    )
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    step = runner.context["acquisition_execution"].steps[0]
    dumped = json.dumps(step.model_dump(), ensure_ascii=False)
    assert secret_error not in dumped
    assert "top-secret" not in dumped
    assert "delimiter-free" not in dumped
    assert "private upstream payload" not in dumped
    assert step.reason_codes == ["ROUTE_UNAVAILABLE"]
    assert db.count("raw_items") == db.count("data_routes") == 0
    assert result.exit_code == 0
    orchestrator.close()


def test_default_production_path_is_closed_and_preserves_runner_result(tmp_path, monkeypatch):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    events = []
    runner = _Runner(events)
    registry = ScenarioRegistry()
    registry.register(runner)

    def boom(*args, **kwargs):
        raise AssertionError("disabled production path performed acquisition I/O")

    monkeypatch.setattr("research_os.routing.router.Router.resolve_with_items", boom)
    monkeypatch.setattr("research_os.data_layer.acquisition_repository.AcquisitionRepository.persist_batch", boom)
    orchestrator = Orchestrator(project, registry=registry)
    original_recheck = orchestrator.preflight.recheck

    def concurrent_read_recheck(**kwargs):
        bundle = original_recheck(**kwargs)
        bundle.checked_at = "2099-01-01T00:00:00+08:00"
        bundle.readiness = [
            item.model_copy(update={"checked_at": bundle.checked_at})
            for item in bundle.readiness
        ]
        return bundle

    orchestrator.preflight.recheck = concurrent_read_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_CLOSED, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.status == "success"
    assert result.exit_code == 0
    assert result.missing_data == ["runner-owned-marker"]
    payload = json.loads(
        (Path(result.run_dir) / "acquisition_execution.json").read_text("utf-8")
    )
    assert payload["status"] == "not_executable"
    assert {reason for step in payload["steps"] for reason in step["reason_codes"]} == {
        "EXECUTION_DISABLED"
    }
    coordination = runner.context["data_acquisition"]
    assert coordination.persistence_committed is False
    assert coordination.readiness_after is not None
    assert coordination.readiness_after.checked_at == "2099-01-01T00:00:00+08:00"
    assert coordination.readiness_before.checked_at != coordination.readiness_after.checked_at
    assert runner.context["data_preflight"] is coordination.readiness_before
    orchestrator.close()


def test_dry_run_has_no_file_db_or_collector_side_effect(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    before_routes = db.count("data_routes")
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_DRY, "report_date": "2026-08-16", "as_of": AS_OF,
        "dry_run": True,
    })
    assert result.exit_code == 0
    assert "discover" not in events
    assert db.count("raw_items") == 0
    assert db.count("data_routes") == before_routes
    assert not (project / "reports" / "runs").exists()
    orchestrator.close()


def test_stale_record_is_refreshed_to_ready(tmp_path):
    project, events, runner, db, orchestrator = _wired(
        tmp_path, published_at="2026-08-16T07:59:00+08:00",
        fake_refresh_semantics=True,
    )
    old = RawItem(
        raw_item_id=str(uuid.uuid4()), source_id="cls", external_id="old",
        url="https://example.test/old", title="old", publisher="fixture",
        published_at="2026-08-15T20:30:00+08:00",
        retrieved_at="2026-08-15T20:31:00+08:00", content_hash="a" * 64,
        content_excerpt="old", content_storage="metadata_and_excerpt", language="zh-CN",
        access_status="ok", entities=[], raw_category="news_flash",
    )
    AcquisitionRepository(db, clock=lambda: "2026-08-15T20:31:00+08:00").persist_batch(
        task_id=TASK_FOUNDATION, step_id="seed",
        as_of="2026-08-16T19:45:00+08:00",
        route=DataRoute(
            data_type="news_flash", requested_sources=["cls"], attempted_sources=["cls"],
            selected_source="cls", fallback_used=False, status="success",
            missing_fields=[], warnings=[],
        ),
        items=(old,),
    )
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16",
        "as_of": "2026-08-16T19:45:00+08:00",
    })
    coordination = runner.context["data_acquisition"]
    assert coordination.readiness_before.readiness[0].status == "STALE"
    assert coordination.readiness_after.readiness[0].status == "READY"
    assert result.exit_code == 0
    orchestrator.close()


def test_primary_failure_secondary_success_preserves_route_audit(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path, fallback_primary=True)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    route = runner.context["acquisition_execution"].steps[0].route
    assert route.attempted_sources == ["unavailable-primary", "cls"]
    assert route.selected_source == "cls"
    assert route.warnings == ["[REDACTED]"]
    assert result.exit_code == 0
    orchestrator.close()


def test_invalid_item_rolls_back_whole_step_and_runner_still_executes(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path, invalid_batch=True)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    step = runner.context["acquisition_execution"].steps[0]
    assert step.status == "failed"
    assert step.reason_codes == ["RAW_ITEM_SCHEMA_INVALID"]
    assert db.count("raw_items") == db.count("data_routes") == 0
    assert result.exit_code == 0
    assert result.missing_data == ["runner-owned-marker"]
    orchestrator.close()


def test_committed_write_recheck_failure_is_partial_and_does_not_invent_readiness(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)

    def recheck_boom(**kwargs):
        raise RuntimeError("Authorization: Bearer must-not-leak")

    orchestrator.preflight.recheck = recheck_boom
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.readiness_after_requirement_ids == []
    assert execution.errors[-1].code == "RECHECK_FAILED"
    assert "must-not-leak" not in json.dumps(execution.model_dump())
    assert db.count("raw_items") == 1
    assert result.exit_code == 0
    assert not (Path(result.run_dir) / "data_readiness_after.jsonl").exists()
    orchestrator.close()


def test_all_future_route_commit_plus_recheck_failure_is_partial(tmp_path):
    project, events, runner, db, orchestrator = _wired(
        tmp_path, published_at="2026-08-16T08:01:00+08:00",
    )

    def recheck_boom(**kwargs):
        raise RuntimeError("secret=must-not-leak")

    orchestrator.preflight.recheck = recheck_boom
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.steps[0].status == "failed"
    assert execution.steps[0].reason_codes == ["FUTURE_ITEM_REJECTED"]
    assert execution.readiness_after_requirement_ids == []
    assert runner.context["data_acquisition"].persistence_committed is True
    assert db.count("raw_items") == 0
    assert db.count("data_routes") == 1
    assert result.exit_code == 0
    orchestrator.close()


def test_coordinator_control_failure_marks_started_task_and_db_failed(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)

    def coordinate_boom(**kwargs):
        raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: injected failure")

    orchestrator.acquisition_coordinator.coordinate = coordinate_boom
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert result.validation_status == "fail"
    assert result.run_dir
    assert json.loads((Path(result.run_dir) / "task.json").read_text("utf-8"))["status"] == "failed"
    assert db.get("tasks", TASK_FOUNDATION)["status"] == "failed"
    orchestrator.close()


def test_artifact_failure_marks_started_task_and_db_failed(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)

    def artifact_boom(*args, **kwargs):
        raise ValueError("CONTROL_PLANE_CONFIGURATION_ERROR: second artifact failed")

    orchestrator.acquisition_coordinator.persist_artifacts = artifact_boom
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert json.loads((Path(result.run_dir) / "task.json").read_text("utf-8"))["status"] == "failed"
    assert db.get("tasks", TASK_FOUNDATION)["status"] == "failed"
    orchestrator.close()


def test_injected_preflight_protocol_fails_early_without_custom_coordinator(tmp_path):
    class _LegacyPreflight:
        pass

    class _CustomCoordinator:
        pass

    project = tmp_path / "project"
    with pytest.raises(ValueError, match="CONTROL_PLANE_CONFIGURATION_ERROR"):
        Orchestrator(project, preflight=_LegacyPreflight())
    # Explicit coordinator injection owns compatibility and therefore remains supported.
    orchestrator = Orchestrator(
        project, preflight=_LegacyPreflight(), acquisition_coordinator=_CustomCoordinator(),
    )
    assert isinstance(orchestrator.acquisition_coordinator, _CustomCoordinator)
    orchestrator.close()


def test_artifact_pair_prevalidation_prevents_malformed_half_publish(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    coordination = runner.context["data_acquisition"]
    malformed_after = deepcopy(coordination.readiness_after)
    malformed_after.readiness[0] = malformed_after.readiness[0].model_construct(
        **{**malformed_after.readiness[0].model_dump(), "status": "BROKEN"}
    )
    malformed = AcquisitionCoordinationResult(
        coordination.readiness_before, coordination.execution, malformed_after, True,
    )
    target = tmp_path / "malformed-pair"
    target.mkdir()
    with pytest.raises(ValueError):
        orchestrator.acquisition_coordinator.persist_artifacts(target, malformed)
    assert not (target / "acquisition_execution.json").exists()
    assert not (target / "data_readiness_after.jsonl").exists()
    orchestrator.close()


def test_artifact_pair_rolls_back_when_second_publish_fails(tmp_path, monkeypatch):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    coordination = runner.context["data_acquisition"]
    target = tmp_path / "publish-pair"
    target.mkdir()
    import research_os.data_layer.coordinator as coordinator_module

    real_replace = coordinator_module.os.replace
    calls = {"count": 0}

    def fail_second(source, destination):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("injected second publish failure")
        return real_replace(source, destination)

    monkeypatch.setattr(coordinator_module.os, "replace", fail_second)
    with pytest.raises(ValueError, match="CONTROL_PLANE_CONFIGURATION_ERROR") as exc:
        orchestrator.acquisition_coordinator.persist_artifacts(target, coordination)
    assert "injected" not in str(exc.value)
    assert str(target) not in str(exc.value)
    assert not (target / "acquisition_execution.json").exists()
    assert not (target / "data_readiness_after.jsonl").exists()
    assert not list(target.glob("*.tmp"))
    orchestrator.close()


def test_realistic_second_publish_oserror_is_structured_and_marks_task_failed(
    tmp_path, monkeypatch,
):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    import research_os.data_layer.coordinator as coordinator_module

    real_replace = coordinator_module.os.replace
    failed = {"value": False}

    def fail_d2_readiness_publish_once(source, destination):
        if (
            not failed["value"]
            and str(source).endswith("data_readiness_after.jsonl.p7d2.tmp")
        ):
            failed["value"] = True
            raise OSError(f"injected filesystem detail: {destination}")
        return real_replace(source, destination)

    monkeypatch.setattr(coordinator_module.os, "replace", fail_d2_readiness_publish_once)
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert result.validation_status == "fail"
    assert result.run_dir
    assert result.message == (
        "CONTROL_PLANE_CONFIGURATION_ERROR: acquisition artifact publish failed"
    )
    assert "injected" not in result.message
    run_dir = Path(result.run_dir)
    assert not (run_dir / "acquisition_execution.json").exists()
    assert not (run_dir / "data_readiness_after.jsonl").exists()
    assert not list(run_dir.glob("*.tmp"))
    assert json.loads((run_dir / "task.json").read_text("utf-8"))["status"] == "failed"
    assert db.get("tasks", TASK_FOUNDATION)["status"] == "failed"
    orchestrator.close()


def test_unchecked_execution_collaborator_payload_is_rejected_before_recheck(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)

    class _MalformedExecution:
        def execute(self, **kwargs):
            return {
                "execution_id": "20509024-d8a9-5a6d-82f1-bb2266fd66b7",
                "task_id": TASK_FOUNDATION, "scenario": "morning_brief", "as_of": AS_OF,
                "plan_sha256": "a" * 64, "started_at": AS_OF, "finished_at": AS_OF,
                "status": "invented", "steps": [],
                "readiness_before_requirement_ids": [],
                "readiness_after_requirement_ids": [], "warnings": [], "errors": [],
            }

    orchestrator.acquisition_coordinator._execution = _MalformedExecution()
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert "invalid acquisition execution result" in result.message
    assert "recheck" not in events
    assert db.get("tasks", TASK_FOUNDATION)["status"] == "failed"
    orchestrator.close()


def _schema_valid_execution_substitution(payload, substitution):
    if substitution == "task_id":
        payload["task_id"] = TASK_EMPTY
    elif substitution == "scenario":
        payload["scenario"] = "daily_review"
    elif substitution == "as_of":
        payload["as_of"] = "2026-08-16T09:00:00+08:00"
    elif substitution == "plan_sha256":
        payload["plan_sha256"] = "b" * 64
    elif substitution == "execution_id":
        payload["execution_id"] = str(uuid.uuid5(uuid.NAMESPACE_DNS, "substitution"))
    elif substitution == "step_field":
        payload["steps"][0]["data_type"] = "document"
    elif substitution == "readiness_before_ids":
        payload["readiness_before_requirement_ids"] = ["other.requirement"]
    elif substitution == "readiness_after_ids":
        payload["readiness_after_requirement_ids"] = ["other.requirement"]
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(substitution)
    return AcquisitionExecutionResult.model_validate(payload)


@pytest.mark.parametrize(
    "substitution",
    [
        "task_id", "scenario", "as_of", "plan_sha256", "execution_id",
        "step_field", "readiness_before_ids", "readiness_after_ids",
    ],
)
def test_schema_valid_execution_substitution_is_rejected_before_recheck_and_artifact(
    tmp_path, substitution,
):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    delegate = orchestrator.acquisition_coordinator._execution

    class _SubstitutingExecution:
        def execute(self, **kwargs):
            valid = delegate.execute(**kwargs)
            return _schema_valid_execution_substitution(
                valid.model_dump(), substitution,
            )

    orchestrator.acquisition_coordinator._execution = _SubstitutingExecution()
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert result.message == (
        "CONTROL_PLANE_CONFIGURATION_ERROR: execution audit authority mismatch"
    )
    assert "recheck" not in events
    run_dir = Path(result.run_dir)
    assert not (run_dir / "acquisition_execution.json").exists()
    assert not (run_dir / "data_readiness_after.jsonl").exists()
    orchestrator.close()


def test_execution_audit_accepts_offset_equivalent_as_of_semantics(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    delegate = orchestrator.acquisition_coordinator._execution

    class _EquivalentAsOfExecution:
        def execute(self, **kwargs):
            payload = delegate.execute(**kwargs).model_dump()
            payload["as_of"] = "2026-08-16T00:00:00Z"
            return AcquisitionExecutionResult.model_validate(payload)

    orchestrator.acquisition_coordinator._execution = _EquivalentAsOfExecution()
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    assert "recheck" in events
    assert (Path(result.run_dir) / "acquisition_execution.json").exists()
    orchestrator.close()


def test_execution_audit_step_order_is_bound_to_immutable_plan_before_recheck(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    first = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert first.exit_code == 0
    before = runner.context["data_acquisition"].readiness_before
    before.acquisition_plan = before.acquisition_plan.model_copy(update={
        "steps": [
            *before.acquisition_plan.steps,
            AcquisitionStep(
                step_id="manual-step", requirement_id="manual.requirement",
                data_type="document", action="request_manual_input",
            ),
        ],
    })
    delegate = orchestrator.acquisition_coordinator._execution

    class _ReorderedExecution:
        def execute(self, **kwargs):
            payload = delegate.execute(**kwargs).model_dump()
            payload["steps"] = list(reversed(payload["steps"]))
            return AcquisitionExecutionResult.model_validate(payload)

    orchestrator.acquisition_coordinator._execution = _ReorderedExecution()
    events.clear()
    with pytest.raises(ValueError, match="execution audit authority mismatch"):
        orchestrator.acquisition_coordinator.coordinate(
            before=before, scenario="morning_brief", task_id=TASK_FOUNDATION,
            task_as_of=AS_OF,
            normalized_request={"report_date": "2026-08-16", "as_of": AS_OF},
            project_root=project, db=db, runs_root=project / "reports" / "runs",
            dry_run=False,
        )
    assert "recheck" not in events
    orchestrator.close()


def test_execution_collaborator_cannot_rewrite_immutable_plan_authority(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    delegate = orchestrator.acquisition_coordinator._execution

    class _InputMutatingExecution:
        def execute(self, **kwargs):
            kwargs["plan"].steps[0].data_type = "document"
            return delegate.execute(**kwargs)

    orchestrator.acquisition_coordinator._execution = _InputMutatingExecution()
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert result.message == (
        "CONTROL_PLANE_CONFIGURATION_ERROR: execution audit authority mismatch"
    )
    assert "recheck" not in events
    assert not (Path(result.run_dir) / "acquisition_execution.json").exists()
    orchestrator.close()


def _mutate_after_readiness(bundle, attack):
    if attack == "forged_id":
        bundle.readiness[0] = bundle.readiness[0].model_copy(update={
            "requirement_id": "forged.requirement",
        })
    elif attack == "reordered_ids":
        bundle.readiness = list(reversed(bundle.readiness))
    elif attack == "data_type":
        bundle.readiness[0] = bundle.readiness[0].model_copy(update={
            "data_type": "document",
        })
    elif attack == "as_of":
        bundle.readiness[0] = bundle.readiness[0].model_copy(update={
            "as_of": "2026-08-16T09:00:00+08:00",
        })
    elif attack == "readiness_checked_at":
        bundle.readiness[0] = bundle.readiness[0].model_copy(update={
            "checked_at": "2000-01-01T00:00:00+08:00",
        })
    elif attack == "readiness_schema":
        bundle.readiness[0] = bundle.readiness[0].model_copy(update={
            "status": "FORGED",
        })
    elif attack == "context_id":
        bundle.contexts[0].requirement = bundle.contexts[0].requirement.model_copy(
            update={"requirement_id": "forged.context.requirement"},
        )
    elif attack == "requirement_minimum_fields":
        bundle.requirements[0] = bundle.requirements[0].model_copy(update={
            "minimum_fields": ["forged_field"],
        })
    elif attack == "requirement_alias_mutation":
        bundle.requirements[0].minimum_fields.append("forged_alias_field")
    elif attack == "requirement_freshness":
        bundle.requirements[0] = bundle.requirements[0].model_copy(update={
            "freshness_seconds": bundle.requirements[0].freshness_seconds + 1,
        })
    elif attack == "requirement_tier":
        forged_tier = "S" if bundle.requirements[0].minimum_source_tier != "S" else "D"
        bundle.requirements[0] = bundle.requirements[0].model_copy(update={
            "minimum_source_tier": forged_tier,
        })
    elif attack == "context_scope":
        context = bundle.contexts[0]
        context.requirement = context.requirement.model_copy(update={
            "scope": context.requirement.scope.model_copy(update={"scope_type": "subject"}),
        })
    elif attack == "context_window":
        bundle.contexts[0].window_start = "2000-01-01T00:00:00+08:00"
    elif attack == "context_entities":
        bundle.contexts[0].entity_ids = ["company:forged"]
    elif attack == "context_material":
        bundle.contexts[0].request_material_refs = ["forged-material"]
    elif attack == "context_binding":
        bundle.contexts[0].binding = replace(
            bundle.contexts[0].binding, authority_location="forged-authority",
        )
    elif attack == "context_binding_alias_mutation":
        bundle.contexts[0].binding.minimum_field_sources["forged"] = "direct"
    elif attack == "context_projector":
        bundle.contexts[0].projector = object()
    elif attack == "gap_classification":
        bundle.gaps[0] = bundle.gaps[0].model_copy(update={"classification": "UNAVAILABLE"})
    elif attack == "gap_reasons":
        bundle.gaps[0] = bundle.gaps[0].model_copy(update={"reason_codes": ["FORGED"]})
    elif attack == "gap_recommended":
        bundle.gaps[0] = bundle.gaps[0].model_copy(update={
            "recommended_action": "forged_action", "requires_network": True,
            "requires_user_input": True, "requires_human_review": True,
        })
    elif attack == "gap_warnings":
        bundle.gaps[0] = bundle.gaps[0].model_copy(update={"warnings": ["forged warning"]})
    elif attack.startswith("plan_"):
        if attack == "plan_root_warnings":
            bundle.acquisition_plan = bundle.acquisition_plan.model_copy(update={
                "warnings": ["forged plan warning"],
            })
            return bundle
        step = bundle.acquisition_plan.steps[0]
        field_updates = {
            "plan_step_id": {"step_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "forged-step"))},
            "plan_action": {"action": "request_manual_input"},
            "plan_dependencies": {"dependencies": ["forged-dependency"]},
            "plan_status": {"status": "completed"},
            "plan_warnings": {"warnings": ["forged warning"]},
        }
        bundle.acquisition_plan.steps[0] = step.model_copy(update=field_updates[attack])
    else:  # pragma: no cover - test helper misuse
        raise AssertionError(attack)
    return bundle


@pytest.mark.parametrize("attack", [
    "forged_id", "data_type", "as_of", "readiness_checked_at",
    "readiness_schema", "context_id",
])
def test_committed_forged_recheck_is_sanitized_partial_without_forged_artifact(
    tmp_path, attack,
):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    authoritative_recheck = orchestrator.preflight.recheck

    def forged_recheck(**kwargs):
        return _mutate_after_readiness(authoritative_recheck(**kwargs), attack)

    orchestrator.preflight.recheck = forged_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.readiness_after_requirement_ids == []
    assert [error.code for error in execution.errors] == ["RECHECK_FAILED"]
    assert runner.context["data_acquisition"].readiness_after is None
    run_dir = Path(result.run_dir)
    persisted = json.loads((run_dir / "acquisition_execution.json").read_text("utf-8"))
    assert persisted["readiness_after_requirement_ids"] == []
    assert "forged.requirement" not in json.dumps(persisted)
    assert not (run_dir / "data_readiness_after.jsonl").exists()
    orchestrator.close()


@pytest.mark.parametrize(
    "attack", ["forged_id", "reordered_ids", "data_type", "as_of"],
)
def test_uncommitted_forged_recheck_gates_runner_and_never_persists_after(
    tmp_path, attack,
):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    events = []
    runner = _Runner(events)
    registry = ScenarioRegistry()
    registry.register(runner)
    orchestrator = Orchestrator(project, registry=registry)
    authoritative_recheck = orchestrator.preflight.recheck

    def forged_recheck(**kwargs):
        return _mutate_after_readiness(authoritative_recheck(**kwargs), attack)

    orchestrator.preflight.recheck = forged_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_CLOSED, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 2
    assert result.message == (
        "CONTROL_PLANE_CONFIGURATION_ERROR: readiness recheck failed"
    )
    assert "runner" not in events
    run_dir = Path(result.run_dir)
    assert not (run_dir / "acquisition_execution.json").exists()
    assert not (run_dir / "data_readiness_after.jsonl").exists()
    orchestrator.close()


def test_recheck_accepts_offset_equivalent_readiness_as_of(tmp_path):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    authoritative_recheck = orchestrator.preflight.recheck

    def equivalent_recheck(**kwargs):
        bundle = authoritative_recheck(**kwargs)
        bundle.readiness = [
            item.model_copy(update={"as_of": "2026-08-16T00:00:00Z"})
            for item in bundle.readiness
        ]
        return bundle

    orchestrator.preflight.recheck = equivalent_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    assert runner.context["data_acquisition"].readiness_after is not None
    assert runner.context["acquisition_execution"].status == "completed"
    assert (Path(result.run_dir) / "data_readiness_after.jsonl").exists()
    orchestrator.close()


@pytest.mark.parametrize("attack", [
    "requirement_minimum_fields", "requirement_alias_mutation",
    "requirement_freshness", "requirement_tier",
    "context_scope", "context_window", "context_entities", "context_material",
    "context_binding", "context_binding_alias_mutation", "context_projector",
    "gap_classification", "gap_reasons",
    "gap_recommended", "gap_warnings",
])
def test_same_preflight_authority_rejects_cross_layer_recheck_substitution(
    tmp_path, attack,
):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    authoritative_recheck = orchestrator.preflight.recheck

    def forged_recheck(**kwargs):
        return _mutate_after_readiness(authoritative_recheck(**kwargs), attack)

    orchestrator.preflight.recheck = forged_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_FOUNDATION, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.readiness_after_requirement_ids == []
    assert [error.code for error in execution.errors] == ["RECHECK_FAILED"]
    assert runner.context["data_acquisition"].readiness_after is None
    assert not (Path(result.run_dir) / "data_readiness_after.jsonl").exists()
    orchestrator.close()


@pytest.mark.parametrize("attack", [
    "plan_step_id", "plan_action", "plan_dependencies", "plan_status", "plan_warnings",
    "plan_root_warnings",
])
def test_same_preflight_authority_rejects_full_plan_substitution(tmp_path, attack):
    project, events, runner, db, orchestrator = _wired(tmp_path, empty=True)
    authoritative_recheck = orchestrator.preflight.recheck

    def forged_recheck(**kwargs):
        return _mutate_after_readiness(authoritative_recheck(**kwargs), attack)

    orchestrator.preflight.recheck = forged_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_EMPTY, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.readiness_after_requirement_ids == []
    assert [error.code for error in execution.errors] == ["RECHECK_FAILED"]
    assert runner.context["data_acquisition"].readiness_after is None
    assert not (Path(result.run_dir) / "data_readiness_after.jsonl").exists()
    orchestrator.close()


@pytest.mark.parametrize("attack", ["documents", "entities", "peers"])
def test_coordinator_freezes_nested_normalized_request_before_recheck_collaborator(
    tmp_path, attack,
):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    orchestrator = Orchestrator(project)
    if attack == "entities":
        scenario = "daily_review"
        request = {
            "as_of": AS_OF, "review_business_date": "2026-08-16",
            "entities": ["company:original"],
            "documents": [{"path": "original", "nested": {"refs": ["doc-a"]}}],
        }
    else:
        scenario = "stock_research_report"
        request = {
            "as_of": AS_OF, "date": "2026-08-16", "entity": "company:subject",
            "peers": ["company:peer-original"],
            "documents": [{"path": "original", "nested": {"refs": ["doc-a"]}}],
        }
    original_request = deepcopy(request)
    before = orchestrator.preflight.run(
        scenario=scenario, task_id=TASK_CLOSED, task_as_of=AS_OF,
        normalized_request=deepcopy(request), project_root=project,
        runs_root=project / "reports" / "runs", dry_run=True,
    )
    authoritative_recheck = orchestrator.preflight.recheck

    def mutating_recheck(**kwargs):
        visible = kwargs["normalized_request"]
        if attack == "documents":
            visible["documents"][0]["nested"]["refs"].append("forged-doc")
        elif attack == "entities":
            visible["entities"].append("company:forged")
        else:
            visible["peers"].append("company:forged-peer")
        return authoritative_recheck(**kwargs)

    orchestrator.preflight.recheck = mutating_recheck
    with pytest.raises(ValueError, match="readiness recheck failed"):
        orchestrator.acquisition_coordinator.coordinate(
            before=before, scenario=scenario, task_id=TASK_CLOSED,
            task_as_of=AS_OF, normalized_request=request, project_root=project,
            db=None, runs_root=project / "reports" / "runs", dry_run=False,
        )
    assert request == original_request
    orchestrator.close()


def _hostile_normalized_request(case):
    class _HostileList(list):
        def __deepcopy__(self, memo):
            return self

    class _HostileDict(dict):
        def __deepcopy__(self, memo):
            return self

    class _CustomScalar:
        pass

    class _IntSubclass(int):
        pass

    class _StrSubclass(str):
        pass

    if case == "list_subclass":
        return {"entities": _HostileList(["company:original"])}
    if case == "dict_subclass":
        return {"nested": _HostileDict({"value": "original"})}
    if case == "root_dict_subclass":
        return _HostileDict({"entities": ["company:original"]})
    if case == "nan":
        return {"value": float("nan")}
    if case == "infinity":
        return {"value": float("inf")}
    if case == "custom_scalar":
        return {"value": _CustomScalar()}
    if case == "scalar_subclass":
        return {"value": _IntSubclass(1)}
    if case == "key_subclass":
        return {_StrSubclass("entities"): ["company:original"]}
    if case == "tuple":
        return {"entities": ("company:original",)}
    if case == "cycle":
        value = {"entities": ["company:original"]}
        value["cycle"] = value
        return value
    raise AssertionError(case)  # pragma: no cover


@pytest.mark.parametrize("case", [
    "list_subclass", "dict_subclass", "root_dict_subclass", "nan", "infinity",
    "custom_scalar", "scalar_subclass", "key_subclass", "tuple", "cycle",
])
def test_coordinator_strict_json_snapshot_rejects_hostile_values_before_recheck(
    tmp_path, case,
):
    project, events, runner, db, orchestrator = _wired(tmp_path)
    before = orchestrator.preflight.run(
        scenario="morning_brief", task_id=TASK_FOUNDATION, task_as_of=AS_OF,
        normalized_request={"report_date": "2026-08-16", "as_of": AS_OF},
        project_root=project, db=db, runs_root=project / "reports" / "runs",
        dry_run=False,
    )

    def forbidden_recheck(**kwargs):
        raise AssertionError("recheck must not run")

    orchestrator.preflight.recheck = forbidden_recheck
    with pytest.raises(
        ValueError,
        match="CONTROL_PLANE_CONFIGURATION_ERROR: normalized request canonicalization failed",
    ) as raised:
        orchestrator.acquisition_coordinator.coordinate(
            before=before, scenario="morning_brief", task_id=TASK_FOUNDATION,
            task_as_of=AS_OF, normalized_request=_hostile_normalized_request(case),
            project_root=project, db=db, runs_root=project / "reports" / "runs",
            dry_run=False,
        )
    assert "recheck must not run" not in str(raised.value)
    orchestrator.close()


def test_coordinator_preserves_ordinary_nested_json_request_semantics(tmp_path):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    orchestrator = Orchestrator(project)
    request = {
        "as_of": AS_OF, "date": "2026-08-16", "entity": "company:subject",
        "peers": ["company:peer"],
        "documents": [{"path": "original", "nested": {"refs": ["doc-a"]}}],
        "flags": {"enabled": True, "count": 2, "ratio": 0.5, "optional": None},
    }
    original = deepcopy(request)
    before = orchestrator.preflight.run(
        scenario="stock_research_report", task_id=TASK_CLOSED, task_as_of=AS_OF,
        normalized_request=deepcopy(request), project_root=project,
        runs_root=project / "reports" / "runs", dry_run=True,
    )
    coordination = orchestrator.acquisition_coordinator.coordinate(
        before=before, scenario="stock_research_report", task_id=TASK_CLOSED,
        task_as_of=AS_OF, normalized_request=request, project_root=project,
        db=None, runs_root=project / "reports" / "runs", dry_run=False,
    )
    assert coordination.readiness_after is not None
    assert request == original
    orchestrator.close()


@pytest.mark.parametrize("attack", ["ready", "counts", "fields", "warnings"])
def test_independent_readiness_recompute_rejects_consistent_forged_candidate(
    tmp_path, attack,
):
    project, events, runner, db, orchestrator = _wired(tmp_path, empty=True)
    preflight = orchestrator.preflight
    candidate_recheck = preflight.recheck

    def forged_recheck(**kwargs):
        bundle = candidate_recheck(**kwargs)
        readiness = bundle.readiness[0]
        updates = {
            "ready": {
                "status": "READY", "available_fields": ["title", "published_at", "url"],
                "missing_fields": [], "coverage_ratio": 1.0,
                "eligible_record_count": 1, "record_refs": ["forged-record"],
            },
            "counts": {"eligible_record_count": 7, "ineligible_record_count": 3},
            "fields": {
                "available_fields": ["forged_field"],
                "missing_fields": ["forged_missing"],
            },
            "warnings": {"warnings": ["forged readiness warning"]},
        }[attack]
        bundle.readiness[0] = readiness.model_copy(update=updates)
        bundle.gaps = [
            preflight._gaps.classify(requirement, forged_readiness)
            for requirement, forged_readiness
            in zip(bundle.requirements, bundle.readiness)
        ]
        bundle.acquisition_plan = preflight._planner.plan(
            task_id=TASK_EMPTY, scenario="morning_brief", as_of=AS_OF,
            gaps=bundle.gaps,
            requirement_order=[item.requirement_id for item in bundle.requirements],
        )
        return bundle

    preflight.recheck = forged_recheck
    result = orchestrator.execute("morning_brief", {
        "task_id": TASK_EMPTY, "report_date": "2026-08-16", "as_of": AS_OF,
    })
    assert result.exit_code == 0
    execution = runner.context["acquisition_execution"]
    assert execution.status == "partial_success"
    assert execution.readiness_after_requirement_ids == []
    assert [error.code for error in execution.errors] == ["RECHECK_FAILED"]
    assert runner.context["data_acquisition"].readiness_after is None
    assert runner.context["data_preflight"].readiness[0].status == "MISSING"
    assert db.count("raw_items") == 0
    run_dir = Path(result.run_dir)
    assert not (run_dir / "data_readiness_after.jsonl").exists()
    persisted = json.loads((run_dir / "acquisition_execution.json").read_text("utf-8"))
    assert persisted["readiness_after_requirement_ids"] == []
    assert "forged" not in json.dumps(persisted)
    orchestrator.close()


def test_projectors_are_per_context_stateless_and_exact_type_authoritative(tmp_path):
    project = tmp_path / "project"
    (project / "reports").mkdir(parents=True)
    orchestrator = Orchestrator(project)
    request = {"as_of": AS_OF, "report_date": "2026-08-16"}
    bundle = orchestrator.preflight.run(
        scenario="morning_brief", task_id=TASK_CLOSED, task_as_of=AS_OF,
        normalized_request=deepcopy(request), project_root=project,
        runs_root=project / "reports" / "runs", dry_run=True,
    )
    projectors = [context.projector for context in bundle.contexts]
    assert len({id(projector) for projector in projectors}) == len(projectors)
    assert all(type(projector) is ReadinessFieldProjector for projector in projectors)
    assert all(not hasattr(projector, "__dict__") for projector in projectors)
    with pytest.raises(AttributeError):
        projectors[0].has_field = lambda *args: True

    class _ForgedProjector(ReadinessFieldProjector):
        __slots__ = ()

        def has_field(self, *args):
            return True

    bundle.contexts[0].projector = _ForgedProjector()
    with pytest.raises(ValueError, match="recheck authority mismatch"):
        orchestrator.preflight.assert_recheck_bundle_authority(
            bundle, scenario="morning_brief", task_id=TASK_CLOSED,
            task_as_of=AS_OF, normalized_request=deepcopy(request),
        )

    future = orchestrator.preflight.recheck(
        scenario="morning_brief", task_id=TASK_CLOSED, task_as_of=AS_OF,
        normalized_request=deepcopy(request), project_root=project,
        runs_root=project / "reports" / "runs", dry_run=True,
    )
    assert all(type(context.projector) is ReadinessFieldProjector for context in future.contexts)
    assert not ({id(item) for item in projectors} & {id(c.projector) for c in future.contexts})
    orchestrator.close()
