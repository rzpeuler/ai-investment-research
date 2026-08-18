#!/usr/bin/env python
"""P7-D3 Source Acceptance Harness（acceptance-only 真实联网验收工具）。

用途（任务书 §17 方案 A/B、§48、§52）：
- 对治理批准的免费来源（nbs / cninfo）执行真实网络采集闭环验证：
  ScenarioRequirement → DataReadiness before → DataGap → AcquisitionPlan →
  AcquisitionCoordinator → ExecutionService → existing Router →
  CollectorFetcherBridge → 真实 Collector → 真实网络 → normalize →
  RawItem Schema 校验 → 原子幂等持久化 → 独立 readiness recheck。
- 显式标记：ACCEPTANCE ONLY，不是 normal production authorization；
  普通 Scenario CLI（research execute）永远不能到达此路径。

受控 acceptance-only override（方案 B）：
- 只绕过两个"证明对象"门：policy.enabled（内存置 True）与目标 capability
  lifecycle（内存置 BUSINESS_SUFFICIENT）——因为本工具正是要真实联网证明
  BUSINESS_SUFFICIENT 的前置条件；
- 其余全部 gate 原样保留：source allowlist、plan Schema、PIT、
  persistence 幂等、recheck authority、dry-run 语义。

用法示例（真实联网）：
    python scripts/acceptance/run_source_acceptance.py \
        --source nbs --data-type macro_data \
        --window-start 2026-08-01T00:00:00+08:00 --window-end 2026-08-16T00:00:00+08:00 \
        --scenario morning_brief \
        --request '{"task_id":"...","report_date":"2026-08-16","as_of":"2026-08-16T00:00:00+08:00"}'

    python scripts/acceptance/run_source_acceptance.py \
        --source cninfo --data-type company_announcement \
        --entity-ids company:maotai \
        --window-start 2026-08-01T00:00:00+08:00 --window-end 2026-08-16T00:00:00+08:00 \
        --scenario earnings_expectation \
        --request '{"task_id":"...","as_of":"2026-08-16T00:00:00+08:00"}'

输出：JSON 摘要（stdout），含 source_id、task_id、execution_id、plan SHA、
selected_source、URL、external_id、published_at、retrieved_at、raw_item_id、
inserted/reused、readiness before/after。不保存网页全文 / PDF / 凭证。
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

from research_os.data_layer.execution_policy import (  # noqa: E402
    ExecutionPolicy,
    _APPROVED_PRODUCTION_COLLECTORS,
)


def _build(project_root: Path, db, *, data_type: str):
    """构造 acceptance 组件：preflight + coordinator + router（真实 wiring）。"""
    from research_os.collectors.government.nbs import NbsCollector
    from research_os.collectors.official.cninfo import CninfoCollector
    from research_os.data_layer.acquisition_repository import AcquisitionRepository
    from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
    from research_os.data_layer.collector_bridge import CollectorFetcherBridge
    from research_os.data_layer.coordinator import AcquisitionCoordinator
    from research_os.data_layer.execution import AcquisitionExecutionService
    from research_os.data_layer.field_projector import FieldProjector
    from research_os.data_layer.preflight import DataPreflightService
    from research_os.data_layer.source_query_projector import (
        SourceQueryProjector,
        _default_security_resolver,
    )
    from research_os.routing.requirements import DataRequirementRegistry
    from research_os.routing.scenario_requirements import (
        ScenarioDataRequirementRegistry,
    )
    from research_os.routing.router import Router
    from research_os.utils.time import now_iso

    req_registry = ScenarioDataRequirementRegistry(
        _REPO_ROOT / "registry" / "scenario_data_requirements.yaml")
    cap_registry = AcquisitionCapabilityRegistry(
        _REPO_ROOT / "registry" / "data_acquisition_capabilities.yaml",
        scenario_requirements=req_registry,
        repo_root=_REPO_ROOT,
    )
    # 受控 override（仅内存）：目标 capability 置 BUSINESS_SUFFICIENT，
    # 以便完整 D2 collaborator chain 真实执行（这正是要证明的对象）。
    cap_registry._by_data_type[data_type] = cap_registry._by_data_type[
        data_type].model_copy(
        update={"automatic_acquisition_lifecycle": "BUSINESS_SUFFICIENT"})
    preflight = DataPreflightService(req_registry, cap_registry)

    bridge = CollectorFetcherBridge(
        {"nbs": NbsCollector(), "cninfo": CninfoCollector()},
        projector=SourceQueryProjector(
            security_resolver=_default_security_resolver(db)),
        field_projector=FieldProjector(),
    )
    router = Router(
        DataRequirementRegistry(_REPO_ROOT / "registry" / "data_requirements.yaml"),
        bridge.as_fetchers(),
    )
    # 受控 override：acceptance 专用 enabled=True（不落盘、不改变 checked-in 配置）
    policy = ExecutionPolicy(
        enabled=True,
        allowed_actions=("route_existing_sources",),
        production_collector_ids=_APPROVED_PRODUCTION_COLLECTORS,
    )
    execution = AcquisitionExecutionService(
        policy=policy,
        requirement_registry=req_registry,
        capability_registry=cap_registry,
        router=router,
        repository=AcquisitionRepository(db, clock=now_iso),
    )
    coordinator = AcquisitionCoordinator(
        preflight=preflight, execution=execution, live_authorized=True)
    return preflight, coordinator, router


def _evidence(router, *, data_type: str, entity_ids: list[str],
              window: dict) -> dict:
    """真实网络证据采集：Router.resolve_with_items → 记录 item 证据。

    使用 D1 权威窗口（before bundle 的 ctx.window_start/end，与 execution 链一致）。
    仅用于审计证据（不持久化）；正式执行链由 coordinator 完成。
    """
    canonical_query = {
        "entity_ids": list(entity_ids),
        "peer_entity_ids": [],
        "industry_ids": [],
        "watchlist_group": None,
        "request_material_refs": [],
    }
    batch = router.resolve_with_items(
        data_type, query=canonical_query, time_window=window)
    return {
        "window": dict(window),
        "selected_source": batch.route.selected_source,
        "status": batch.route.status,
        "items": [
            {
                "raw_item_id": getattr(it, "raw_item_id", None),
                "external_id": getattr(it, "external_id", None),
                "url": getattr(it, "url", None),
                "title": getattr(it, "title", None),
                "published_at": getattr(it, "published_at", None),
                "retrieved_at": getattr(it, "retrieved_at", None),
                "raw_category": getattr(it, "raw_category", None),
            }
            for it in batch.items
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="P7-D3 Source Acceptance Harness (acceptance only)")
    parser.add_argument("--source", required=True,
                        choices=list(_APPROVED_PRODUCTION_COLLECTORS))
    parser.add_argument("--data-type", required=True,
                        choices=["macro_data", "company_announcement"])
    parser.add_argument("--entity-ids", action="append", default=[])
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--project-root", default=None)
    parser.add_argument("--task-id", default=None)
    args = parser.parse_args(argv)

    project_root = Path(args.project_root) if args.project_root else _REPO_ROOT
    try:
        request = json.loads(args.request)
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "failed", "error": f"request 非法 JSON: {exc}"},
                         ensure_ascii=False))
        return 2
    if not isinstance(request, dict):
        print(json.dumps({"status": "failed", "error": "request 必须是 object"},
                         ensure_ascii=False))
        return 2
    task_id = args.task_id or str(uuid.uuid4())
    request.setdefault("task_id", task_id)
    task_as_of = args.window_end

    db = None
    try:
        from research_os.storage.db import Database
        db = Database(project_root / "data" / "sqlite" / "research.db")
        db.initialize()

        preflight, coordinator, router = _build(
            project_root, db, data_type=args.data_type)

        before = preflight.run(
            scenario=args.scenario, task_id=task_id, task_as_of=task_as_of,
            normalized_request=request, project_root=project_root, db=db,
            runs_root=project_root / "reports" / "runs",
            graph_repo=None, dry_run=False,
        )
        # 权威窗口：D1 resolved context（与 execution 链一致；§46 窗口权威）
        authority_window = None
        for ctx in getattr(before, "contexts", []) or []:
            req = getattr(ctx, "requirement", None)
            if req is not None and getattr(req, "data_type", None) == args.data_type:
                authority_window = {
                    "start": getattr(ctx, "window_start", None),
                    "end": getattr(ctx, "window_end", None),
                }
                break
        if authority_window is None:
            authority_window = {"start": args.window_start, "end": args.window_end}
        evidence = _evidence(router, data_type=args.data_type,
                             entity_ids=args.entity_ids, window=authority_window)

        coordination = coordinator.coordinate(
            before=before, scenario=args.scenario, task_id=task_id,
            task_as_of=task_as_of, normalized_request=request,
            project_root=project_root, db=db,
            runs_root=project_root / "reports" / "runs",
            dry_run=False, graph_repo=None,
        )

        execution = coordination.execution
        summary = {
            "acceptance": True,
            "acceptance_only": True,
            "online": True,
            "network_attempted": True,
            "live_data_authorized": True,
            "source_id": args.source,
            "data_type": args.data_type,
            "scenario": args.scenario,
            "task_id": task_id,
            "task_as_of": task_as_of,
            "execution_id": getattr(execution, "execution_id", None),
            "plan_sha256": getattr(execution, "plan_sha256", None),
            "overall_status": getattr(execution, "status", None),
            "evidence_route": {
                "selected_source": evidence["selected_source"],
                "status": evidence["status"],
            },
            "evidence_items": evidence["items"],
            "steps": [],
            "readiness_before": _readiness_summary(before),
            "readiness_after": _readiness_summary(coordination.readiness_after),
        }
        for step in getattr(execution, "steps", []) or []:
            route = getattr(step, "route", None)
            summary["steps"].append({
                "data_type": getattr(step, "data_type", None),
                "status": getattr(step, "status", None),
                "reason_codes": list(getattr(step, "reason_codes", []) or []),
                "selected_source": getattr(route, "selected_source", None)
                if route is not None else None,
                "inserted_count": getattr(step, "inserted_count", 0),
                "reused_count": getattr(step, "reused_count", 0),
                "rejected_future_item_count": getattr(
                    step, "rejected_future_item_count", 0),
                "inserted_raw_item_ids": list(
                    getattr(step, "inserted_raw_item_ids", []) or []),
                "reused_raw_item_ids": list(
                    getattr(step, "reused_raw_item_ids", []) or []),
            })

        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 —— 验收失败也输出结构化摘要（脱敏）
        print(json.dumps({
            "acceptance": True,
            "acceptance_only": True,
            "online": True,
            "source_id": args.source,
            "data_type": args.data_type,
            "task_id": task_id,
            "status": "failed",
            "error_type": type(exc).__name__,
            # 不保留 arbitrary exception 原文，避免泄漏 URL/header/路径细节
            "message": "acceptance run failed (sanitized)",
        }, ensure_ascii=False, indent=2))
        return 1
    finally:
        if db is not None:
            try:
                db.close()
            except Exception:  # noqa: BLE001
                pass


def _readiness_summary(bundle) -> dict:
    """从 DataPreflightBundle 提取可审计 readiness 摘要（脱敏）。"""
    if bundle is None:
        return {"checked_at": None}
    items = []
    for readiness in getattr(bundle, "readiness", []) or []:
        items.append({
            "requirement_id": getattr(readiness, "requirement_id", None),
            "data_type": getattr(readiness, "data_type", None),
            "readiness": getattr(readiness, "status", None),
            "available_fields": list(getattr(readiness, "available_fields", []) or []),
            "missing_fields": list(getattr(readiness, "missing_fields", []) or []),
            "eligible_record_count": getattr(readiness, "eligible_record_count", None),
            "ineligible_record_count": getattr(readiness, "ineligible_record_count", None),
        })
    return {
        "checked_at": getattr(bundle, "checked_at", None),
        "requirements": items,
    }


if __name__ == "__main__":
    raise SystemExit(main())
