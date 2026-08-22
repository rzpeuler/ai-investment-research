"""P8-A4-R2 bounded regression evidence collector.

The command records a real full-suite outcome, including a truthful timeout
classification. It never turns a timeout into PASS and never scores human
value. Generated evidence stays under the ignored reports/ directory.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "p8_a4_r2_regression_evidence.json"
TIMEOUT_SECONDS = 600
NODE_RE = re.compile(r"^(tests\S+::\S+\s+(?:PASSED|FAILED|SKIPPED))", re.IGNORECASE)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run() -> dict[str, Any]:
    command = [sys.executable, "-m", "pytest", "-vv", "--durations=50", "--durations-min=1.0"]
    started = time.monotonic()
    started_at = _now()
    proc = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    timed_out = False
    try:
        output, _ = proc.communicate(timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        proc.kill()
        output, _ = proc.communicate()
        partial = exc.output
        if partial:
            output = (partial if isinstance(partial, str) else partial.decode("utf-8", "replace")) + output
    lines = output.splitlines()
    tail = lines[-80:]
    completed_nodes = [match.group(1) for line in lines if (match := NODE_RE.match(line))]
    elapsed = round(time.monotonic() - started, 3)
    status = "TIMEOUT" if timed_out else ("PASS" if proc.returncode == 0 else "FAIL")
    return {
        "command": command,
        "status": status,
        "exit_code": proc.returncode,
        "started_at": started_at,
        "ended_at": _now(),
        "elapsed_seconds": elapsed,
        "timeout_seconds": TIMEOUT_SECONDS,
        "completed_node_count_observed": len(completed_nodes),
        "last_completed_nodes": completed_nodes[-10:],
        "output_tail": tail,
        "slow_test_summary": (
            "AVAILABLE_IF_COMPLETED_FROM_PYTEST_DURATIONS"
            if status == "PASS" else "NOT_AVAILABLE_FULL_RUN_DID_NOT_COMPLETE"
        ),
    }


def main() -> int:
    report = {
        "task": "P8-A4-R2-HUMAN-VALUE-AND-REGRESSION-CLOSURE",
        "status": "RECORDED",
        "default_runtime": "legacy",
        "production_adoption": "NOT_AUTHORIZED",
        "full_pytest": _run(),
        "schema_validation": "RUN_SEPARATELY",
        "compileall": "RUN_SEPARATELY",
        "diff_check": "RUN_SEPARATELY",
        "human_value": {"status": "PENDING_REVIEW", "automated_score": False},
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": report["status"], "full_pytest": report["full_pytest"]}, ensure_ascii=False, indent=2))
    return 0 if report["full_pytest"]["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
