"""P8-B2-LIVE-01-REPAIR-01 bounded single-turn diagnostic (NOT acceptance corpus).

Investigation only: boots the pinned Harness, creates ONE session, sends ONE
provider-backed turn (the exact turn-1 prompt of the formal trial), then
observes process survival and captured output. This is NOT a trial session and
is never counted toward the 10-session / 20-turn corpus.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from research_os.agent_runtime.config import AgentRuntimeConfig  # noqa: E402
from research_os.agent_runtime.production_runtime import (  # noqa: E402
    _redacted_tail,
    build_production_harness_adapter,
)


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("CREDENTIAL_ABSENT")
        return 2
    config = AgentRuntimeConfig(mode="harness", max_turns=2, max_active_sessions=1,
                                turn_timeout_seconds=300)
    print("BOOTING_HARNESS")
    adapter, evidence = build_production_harness_adapter(config, require_credential=True)
    owned = adapter.supervisor.process
    print("HARNESS_BOOTED", evidence["version"], evidence["profile"])
    public = None
    try:
        started = time.monotonic()
        try:
            public = adapter.create_session({"diagnostic": "repair-01"})
            print("SESSION_CREATED", round((time.monotonic() - started) * 1000), "ms")
        except Exception as exc:  # noqa: BLE001 — capture any create failure
            code = getattr(exc, "code", type(exc).__name__)
            print(f"SESSION_CREATE_FAILED code={code} elapsed={round(time.monotonic()-started,1)}s "
                  f"message={getattr(exc, 'message', str(exc))[:200]!r}")
        if public is not None:
            prompt = ("For 600519.SH Kweichow Moutai, call get_company_profile once and "
                      "check_data_readiness once. Return a short structured summary.")
            turn_started = time.monotonic()
            try:
                result = adapter.send_message(public, prompt)
                elapsed = round(time.monotonic() - turn_started, 1)
                print("TURN_COMPLETED", elapsed, "s", json.dumps(result.get("status")))
            except Exception as exc:  # noqa: BLE001 — capture the typed failure
                elapsed = round(time.monotonic() - turn_started, 1)
                code = getattr(exc, "code", type(exc).__name__)
                print(f"TURN_FAILED code={code} elapsed={elapsed}s message={getattr(exc, 'message', str(exc))[:200]!r}")
    finally:
        if public is not None:
            try:
                adapter.close_session(public.gateway_session_id)
            except Exception:  # noqa: BLE001
                pass
    time.sleep(1)
    print("PROCESS_POLL_AFTER", owned.poll() if owned is not None else "NO_PROCESS")
    print("SUPERVISOR_READY", adapter.supervisor.ready)
    print("SUPERVISOR_STATE", adapter.supervisor.state.value)
    print("STDOUT_TAIL", _redacted_tail(owned.stdout_tail)[-800:])
    print("STDERR_TAIL", _redacted_tail(owned.stderr_tail)[-1200:])
    adapter.supervisor.stop()
    print("CLEANUP_DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
