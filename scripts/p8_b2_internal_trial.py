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
        # evaluate_final_trial returns the authoritative, frozen evidence
        # snapshot. The CLI may only add non-authoritative metadata; it must
        # not override acceptance fields (R2-02).
        snapshot = controller.evaluate_final_trial()
        result = {
            **snapshot,
            "provider_network": "ON",
            "research_data_network": "OFF",
            "p8_b3": "NOT_AUTHORIZED",
            "restart_drill_detail": restart,
            "rollback_drill_detail": rollback,
            "corpus_report": {k: v for k, v in corpus.items() if k not in snapshot},
        }
    except Exception as exc:
        # Boot/start/run failure still renders the full fail-closed evidence
        # snapshot (rework 6): complete fields + evidence basis + error code.
        reason = getattr(exc, "code", None) or type(exc).__name__
        result = {**controller.finalize_fail_closed(reason),
                  "provider_network": "ON", "research_data_network": "OFF",
                  "production_adoption": "NOT_AUTHORIZED", "p8_b3": "NOT_AUTHORIZED"}
    finally:
        controller.stop()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "PASS CANDIDATE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
