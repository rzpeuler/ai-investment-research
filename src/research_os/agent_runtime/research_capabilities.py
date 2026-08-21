"""Read-only Research OS capabilities for the P8-A0-R2 MCP process."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from research_os.data_layer.capabilities import AcquisitionCapabilityRegistry
from research_os.data_layer.preflight import DataPreflightService
from research_os.data_layer.readiness import DataReadinessService
from research_os.routing.scenario_requirements import ScenarioDataRequirementRegistry
from research_os.storage import Database
from research_os.utils.time import now_iso


ROOT = Path(__file__).resolve().parents[3]
MAX_RESULT_BYTES = 64 * 1024

def _authority_db_path() -> Path:
    return ROOT / "data" / "sqlite" / "research.db"


def _payload_rows(db: Any, table: str) -> list[dict[str, Any]]:
    rows = []
    for row in db.query(f"SELECT payload FROM {table} WHERE status IN ('active', 'listed', 'suspended')"):
        try:
            rows.append(json.loads(row["payload"]))
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"TOOL_RESULT_INVALID: {table} payload") from exc
    return rows


def _matches(payload: dict[str, Any], target: str) -> bool:
    needle = "".join(str(target).split()).casefold()
    if len(needle) == 6 and needle.isdigit():
        symbol = str(payload.get("symbol") or "").casefold()
        if symbol.startswith(needle + "."):
            return True
    candidates = [payload.get("symbol"), payload.get("name"), payload.get("current_name"),
                  payload.get("company_name"), payload.get("canonical_name"),
                  payload.get("entity_id"), payload.get("company_entity_id")]
    return any("".join(str(value).split()).casefold() == needle for value in candidates if value)


def get_company_profile(target: str, **_: Any) -> dict[str, Any]:
    """Return exact-match identity from existing SQLite authority only."""
    if not isinstance(target, str) or not target.strip():
        return {"status": "insufficient_evidence", "reason": "target_required"}
    db_path = _authority_db_path()
    if not db_path.is_file():
        return {"status": "data_degraded", "reason": "authoritative_db_missing"}
    db = Database.open_read_only(db_path)
    try:
        securities = [p for p in _payload_rows(db, "security_profiles") if _matches(p, target)]
        companies = [p for p in _payload_rows(db, "company_profiles") if _matches(p, target)]
        if len(securities) != 1 and len(companies) != 1:
            return {"status": "insufficient_evidence", "reason": "target_not_uniquely_resolved"}
        security = securities[0] if len(securities) == 1 else None
        company = companies[0] if len(companies) == 1 else None
        return {
            "status": "partial_success" if company is None else "success",
            "entity_id": (company or security).get("company_entity_id") or (company or security).get("entity_id"),
            "display_name": (company or security).get("canonical_name") or (security or company).get("company_name") or (security or company).get("name"),
            "security_reference": {
                "symbol": security.get("symbol"),
                "security_entity_id": security.get("security_entity_id"),
            } if security else None,
            "company_profile": company,
            "as_of": now_iso(),
            "limitations": ["company_profile_missing"] if company is None else [],
        }
    finally:
        db.close()


def check_data_readiness(target: str, as_of: str | None = None, **_: Any) -> dict[str, Any]:
    """Run the existing zero-network/zero-write DataPreflight authority."""
    if not isinstance(target, str) or not target.strip():
        return {"status": "insufficient_evidence", "reason": "target_required"}
    effective_as_of = as_of or now_iso()
    identity = get_company_profile(target)
    entity = identity.get("entity_id") or target
    requirements = ScenarioDataRequirementRegistry(ROOT / "registry" / "scenario_data_requirements.yaml")
    capabilities = AcquisitionCapabilityRegistry(
        ROOT / "registry" / "data_acquisition_capabilities.yaml", requirements, ROOT)
    service = DataPreflightService(requirements, capabilities)
    bundle = service.run(
        scenario="stock_research_report",
        task_id="p8-a0-r2-readiness",
        task_as_of=effective_as_of,
        normalized_request={"entity": entity, "as_of": effective_as_of, "report_date": effective_as_of[:10]},
        project_root=ROOT,
        dry_run=True,
    )
    readiness = [item.model_dump(mode="json") for item in bundle.readiness]
    gaps = [item.model_dump(mode="json") for item in bundle.gaps]
    status = "success" if readiness and all(item["status"] == "READY" for item in readiness) else "partial_success"
    return {"status": status, "entity_id": identity.get("entity_id"), "as_of": effective_as_of, "requirement_count": len(readiness),
            "missing_count": sum(item["status"] != "READY" for item in readiness),
            "readiness": readiness, "gaps": gaps,
            "limitations": ["research_data_acquisition_disabled", "no_external_source_network"]}


TOOLS = {
    "get_company_profile": {
        "description": "Read an exact-match company/security identity from Research OS authority.",
        "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}}, "required": ["target"], "additionalProperties": False},
        "handler": get_company_profile,
    },
    "check_data_readiness": {
        "description": "Read current Research OS data readiness for stock research without acquisition or network access.",
        "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}, "as_of": {"type": "string"}}, "required": ["target"], "additionalProperties": False},
        "handler": check_data_readiness,
    },
}


def bounded(value: dict[str, Any]) -> dict[str, Any]:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_RESULT_BYTES:
        return {"status": "tool_result_invalid", "reason": "bounded_result_limit_exceeded", "truncated": True}
    return value


# ---------------------------------------------------------------------------
# P8-A0 Hybrid spike: two additional read/bounded Tools (opt-in spike surface).
# ---------------------------------------------------------------------------


def query_industry_graph(root_node_id: str, as_of: str, max_depth: int = 1,
                         direction: str = "both", **_: Any) -> dict[str, Any]:
    """Read-only industry graph traversal from Research OS authority (spike).

    Uses the existing read-only GraphQueryService; never mutates the graph.
    Empty/absent graph data is reported honestly (``insufficient_evidence`` /
    ``data_degraded``); no fabricated nodes or edges are returned.
    """
    if not isinstance(root_node_id, str) or not root_node_id.strip():
        return {"status": "insufficient_evidence", "reason": "root_node_id_required"}
    if not isinstance(as_of, str) or not as_of.strip():
        return {"status": "insufficient_evidence", "reason": "as_of_required"}
    if not isinstance(max_depth, int) or not 1 <= max_depth <= 3:
        return {"status": "insufficient_evidence", "reason": "max_depth_out_of_bounds"}
    if direction not in {"in", "out", "both"}:
        return {"status": "insufficient_evidence", "reason": "direction_out_of_bounds"}
    db_path = _authority_db_path()
    if not db_path.is_file():
        return {"status": "data_degraded", "reason": "authoritative_db_missing"}
    db = Database.open_read_only(db_path)
    try:
        from research_os.knowledge.query import GraphQueryService, QueryError

        service = GraphQueryService(db)
        result = service.query_graph(root_node_id, as_of, max_depth=max_depth, direction=direction)
        payload = result.to_dict()
        status = ("success" if payload.get("nodes") else
                  "insufficient_evidence")
        return {
            "status": status,
            "root_node_id": root_node_id,
            "as_of": as_of,
            "max_depth": max_depth,
            "direction": direction,
            "node_count": len(payload.get("nodes", [])),
            "edge_count": len(payload.get("edges", [])),
            "nodes": payload.get("nodes", []),
            "edges": payload.get("edges", []),
            "limitations": ["graph_read_only_spike", "no_graph_mutation"] + payload.get("limitations", []),
        }
    except QueryError as exc:
        return {"status": "insufficient_evidence", "reason": str(exc),
                "root_node_id": root_node_id, "as_of": as_of}
    finally:
        db.close()


def run_research_scenario(scenario: str, target: str, as_of: str | None = None, **_: Any) -> dict[str, Any]:
    """Trigger an existing Research OS scenario workflow (spike, bounded).

    Validates the scenario against the existing ScenarioRegistry and returns
    the formal workflow's task/plan/readiness projection. It is a *trigger*
    surface: it does not reimplement the workflow, does not write the graph or
    database, and does not bypass the Research Workflow authority. If the
    scenario is not registered the tool reports ``insufficient_evidence``.
    """
    if not isinstance(scenario, str) or not scenario.strip():
        return {"status": "insufficient_evidence", "reason": "scenario_required"}
    if not isinstance(target, str) or not target.strip():
        return {"status": "insufficient_evidence", "reason": "target_required"}
    from research_os.orchestrator.orchestrator import Orchestrator
    from research_os.orchestrator.runners import DEFAULT_SCENARIOS

    if scenario not in DEFAULT_SCENARIOS:
        return {"status": "insufficient_evidence", "reason": "scenario_not_registered",
                "scenario": scenario}
    effective_as_of = as_of or now_iso()
    orch = Orchestrator(ROOT, db=None)
    try:
        task = orch.create_task(scenario=scenario, entities=[target], as_of=effective_as_of)
        plan = orch.create_plan(task, {"entity": target, "as_of": effective_as_of})
        return {
            "status": "success",
            "scenario": scenario,
            "target": target,
            "as_of": effective_as_of,
            "task_id": task.task_id,
            "plan_steps": [step.get("step") for step in plan.steps],
            "data_requirement_ids": plan.data_requirement_ids,
            "runtime_budget": plan.runtime_budget,
            "limitations": ["spike_trigger_only", "workflow_authority_research_os",
                            "no_graph_write", "no_database_write"],
        }
    except ValueError as exc:
        return {"status": "insufficient_evidence", "reason": str(exc), "scenario": scenario}
