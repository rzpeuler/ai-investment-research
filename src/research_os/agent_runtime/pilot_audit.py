"""P8-A2 Hybrid Pilot Audit Extension (runtime lineage).

Authority: P8-A1-HYBRID-AGENT-RUNTIME-PILOT-DESIGN (Decision #82). Records
runtime lineage for every pilot task so the system can answer: *"该 Artifact 由
哪个 runtime 产生？"* (which runtime produced this artifact?).

Lineage fields (P8-A1 §6.1):
  runtime_selection        - LEGACY_ONLY | HARNESS_ALLOWED | HYBRID
  runtime_selection_reason - deterministic decision reason
  harness_session_id       - Harness internal session id (bounded, not raw)
  skills_used              - skills loaded/used by the session
  tools_called             - MCP tool call list
  authority_checks         - permission boundary verdicts
  final_artifact_source    - which runtime produced the final artifact
                             (HYBRID -> Phase B = legacy)

Records are written as a bounded JSONL audit trail under
``reports/pilot_audit/`` (never raw prompts/responses/credentials) and, when a
Database is provided, appended to the existing ``llm_call_records`` payload so
the lineage is queryable with the unified audit store.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from research_os.utils.time import now_iso

ROOT = Path(__file__).resolve().parents[3]
PILOT_AUDIT_DIR = ROOT / "reports" / "pilot_audit"

_FORBIDDEN_FIELDS = frozenset({"prompt", "full_prompt", "response", "raw_response",
                               "credential", "reasoning", "raw_payload"})


@dataclass
class RuntimeLineage:
    """Bounded runtime lineage for one pilot task (no raw content)."""

    task_id: str
    runtime_selection: str
    runtime_selection_reason: str
    final_artifact_source: str
    harness_session_id: str = ""
    skills_used: list[str] = field(default_factory=list)
    tools_called: list[str] = field(default_factory=list)
    authority_checks: list[dict[str, Any]] = field(default_factory=list)
    policy_version: str = ""
    status: str = "completed"
    record_id: str = field(default_factory=lambda: f"pilot-{uuid.uuid4().hex[:12]}")
    recorded_at: str = field(default_factory=now_iso)

    def as_dict(self) -> dict[str, Any]:
        return {
            key: value for key, value in asdict(self).items()
            if key not in _FORBIDDEN_FIELDS
        }

    def lineage_sha256(self) -> str:
        blob = json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


class PilotAuditRecorder:
    """Bounded runtime-lineage recorder (JSONL + optional llm_call_records)."""

    def __init__(self, audit_dir: Path = PILOT_AUDIT_DIR, db: Any = None):
        self.audit_dir = Path(audit_dir)
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.db = db
        self._records: list[RuntimeLineage] = []

    # ---------- write ----------

    def record(self, lineage: RuntimeLineage) -> RuntimeLineage:
        if not lineage.task_id:
            raise ValueError("runtime lineage requires task_id")
        self._records.append(lineage)
        self._append_jsonl(lineage)
        if self.db is not None:
            self._append_db(lineage)
        return lineage

    def _append_jsonl(self, lineage: RuntimeLineage) -> None:
        day = lineage.recorded_at[:10]
        path = self.audit_dir / f"pilot-audit-{day}.jsonl"
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(lineage.as_dict(), ensure_ascii=False,
                                    separators=(",", ":")) + "\n")

    def _append_db(self, lineage: RuntimeLineage) -> None:
        payload = json.dumps(lineage.as_dict(), ensure_ascii=False)
        try:
            with self.db._conn:  # noqa: SLF001
                self.db._conn.execute(  # noqa: SLF001
                    "INSERT INTO llm_call_records (call_id, payload, task_id, module, status, called_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (lineage.record_id, payload, lineage.task_id,
                     "agent_runtime.pilot", lineage.status, lineage.recorded_at),
                )
        except Exception:  # noqa: BLE001 — audit persistence failure must not break routing
            pass

    # ---------- read / query ----------

    def records(self) -> list[dict[str, Any]]:
        return [lineage.as_dict() for lineage in self._records]

    def query(self, task_id: str | None = None,
              runtime_selection: str | None = None) -> list[dict[str, Any]]:
        result = []
        for lineage in self._records:
            item = lineage.as_dict()
            if task_id is not None and item["task_id"] != task_id:
                continue
            if runtime_selection is not None and item["runtime_selection"] != runtime_selection:
                continue
            result.append(item)
        return result

    def artifact_source(self, task_id: str) -> str | None:
        """Answer: which runtime produced this task's final artifact?"""
        matches = [item for item in self.query(task_id=task_id) if item.get("final_artifact_source")]
        if not matches:
            return None
        return matches[-1]["final_artifact_source"]


__all__ = ["RuntimeLineage", "PilotAuditRecorder", "PILOT_AUDIT_DIR"]
