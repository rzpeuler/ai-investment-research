"""Explicit P8-B2 internal limited trial; never a public or default route."""
from __future__ import annotations

import json
import os

from research_os.agent_runtime.trial import TrialController


def main() -> int:
    if os.environ.get("P8_B2_INTERNAL_TRIAL") != "1":
        print(json.dumps({"status": "TRIAL_NOT_ENABLED", "default_runtime": "legacy",
                          "production_adoption": "NOT_AUTHORIZED"}, ensure_ascii=False, indent=2))
        return 2
    controller = TrialController()
    result: dict[str, object]
    try:
        controller.start()
        corpus = controller.run_corpus()
        restart = controller.restart_drill()
        rollback = controller.rollback_drill()
        result = {**controller.evaluate_final_trial(), **restart, **rollback,
                  "provider_network": "ON", "research_data_network": "OFF",
                  "p8_b3": "NOT_AUTHORIZED"}
    except Exception as exc:
        result = {"status": "PARTIAL", "error_code": getattr(exc, "code", type(exc).__name__),
                  "provider_network": "ON", "research_data_network": "OFF",
                  "production_adoption": "NOT_AUTHORIZED", "p8_b3": "NOT_AUTHORIZED"}
    finally:
        controller.stop()
    result["process_residue"] = "NO"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
