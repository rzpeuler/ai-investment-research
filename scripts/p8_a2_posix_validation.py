"""P8-A2 POSIX runtime validation (Ubuntu CI: process_residue=NO).

Closes the P8-A0 leftover: the accepted R2 cleanup evidence model cannot
mechanically enumerate an owned process tree on Windows, so ``process_residue``
is NOT_VERIFIED there (fail-closed). On POSIX (Ubuntu) the owned process-group
mechanism CAN prove ``process_residue=NO``. This script boots the pinned
Harness, runs one bounded provider-backed turn, and mechanically verifies the
owned process-tree cleanup.

This is a validation script, not an acceptance engine: it never admits
sessions/turns into a formal corpus, and the turn is marked
POSIX_VALIDATION_ONLY / FORMAL_ACCEPTANCE_TURN=NO.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSIX_VALIDATION_ENV = "P8_A2_POSIX_VALIDATION"
FORMAL_ACCEPTANCE_TURN = "NO"


def main() -> int:
    if os.environ.get(POSIX_VALIDATION_ENV) != "1":
        print(json.dumps({"status": "POSIX_VALIDATION_NOT_ENABLED",
                          "env": POSIX_VALIDATION_ENV}, ensure_ascii=False, indent=2))
        return 2
    if os.name == "nt":
        print(json.dumps({"status": "SKIPPED", "reason": "POSIX validation requires a POSIX host",
                          "os": os.name}, ensure_ascii=False, indent=2))
        return 0
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print(json.dumps({"status": "PROVIDER_AUTH_MISSING"}, ensure_ascii=False, indent=2))
        return 2

    sys.path.insert(0, str(ROOT / "src"))
    pythonpath = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + pythonpath if pythonpath else "")

    from research_os.agent_runtime.config import AgentRuntimeConfig
    from research_os.agent_runtime.production_runtime import build_hybrid_spike_harness_adapter

    report: dict = {
        "task": "P8-A2-POSIX-RUNTIME-VALIDATION",
        "formal_acceptance_turn": FORMAL_ACCEPTANCE_TURN,
        "status": "FAILED",
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
    }
    adapter = None
    try:
        config = AgentRuntimeConfig(mode="harness", max_turns=2, turn_timeout_seconds=300)
        adapter, evidence = build_hybrid_spike_harness_adapter(config, require_credential=True)
        report["harness"] = {
            "version": evidence.get("version"),
            "profile": evidence.get("profile"),
            "tools": list(evidence.get("tools", ())),
            "runtime_state": str(adapter.supervisor.state),
            "process_alive": bool(adapter.supervisor.process
                                  and adapter.supervisor.process.poll() is None),
        }
        session = adapter.create_session({"validation": "posix"})
        result = adapter.send_message(
            session, "Return a JSON object: {\"ok\": true}. Do not call any tools.")
        report["turn"] = {"status": result.get("status"),
                          "usage_reported": bool((result.get("operational_metadata") or {}).get("usage"))}
        adapter.close_session(session.gateway_session_id)
        report["status"] = "COMPLETED"
    except Exception as exc:  # noqa: BLE001 — bounded validation failure
        report["risks"] = [{"kind": "validation_exception",
                            "message": f"{type(exc).__name__}: {str(exc)[:200]}"}]
    finally:
        if adapter is not None:
            owned = adapter.supervisor.process
            try:
                adapter.supervisor.stop()
            except Exception:  # noqa: BLE001
                pass
            if owned is not None:
                status = getattr(owned, "cleanup_status", None)
                if callable(status):
                    cleanup = status()
                    report["process_cleanup"] = cleanup
                    tree = cleanup.get("tree")
                    report["process_residue"] = (
                        "NO" if tree == "VERIFIED" else ("YES" if tree == "FAILED" else "NOT_VERIFIED")
                    )
    out_path = ROOT / "reports" / "p8_a2_posix_validation.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # The gate: process_residue must be mechanically NO on POSIX.
    return 0 if report.get("process_residue") == "NO" else 2


if __name__ == "__main__":
    raise SystemExit(main())
