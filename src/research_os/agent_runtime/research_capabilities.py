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
