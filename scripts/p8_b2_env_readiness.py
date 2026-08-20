"""P8-B2-ENV-01 environment readiness probe; never a public or default route.

Runs the provider-backed internal trial environment readiness probe. This is
NOT the formal P8-B2 acceptance corpus (P8-B2-LIVE-01): it performs at most one
tiny bounded provider call marked ENVIRONMENT_READINESS_PROBE_ONLY and never
increments any trial/session/turn counter.
"""
from __future__ import annotations

import json
import os

from research_os.agent_runtime.environment_readiness import TrialEnvironmentReadinessProbe

READINESS_ENV = "P8_B2_ENV_READINESS"


def main() -> int:
    if os.environ.get(READINESS_ENV) != "1":
        print(json.dumps({"status": "ENV_READINESS_NOT_ENABLED", "default_runtime": "legacy",
                          "production_adoption": "NOT_AUTHORIZED",
                          "formal_acceptance_turn": "NO"}, ensure_ascii=False, indent=2))
        return 2
    probe = TrialEnvironmentReadinessProbe()
    result = probe.probe()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return {"READY": 0, "BLOCKED": 1, "FAIL": 2}[result["result"]]


if __name__ == "__main__":
    raise SystemExit(main())
