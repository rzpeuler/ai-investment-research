"""Linux-only offline regression tests for the real owned process-group tree.

These tests exercise the actual ``BoundedOwnedProcess`` against real OS
process groups (no fake process objects) and cover the "root exited while a
descendant survives" acceptance scenario. They never touch the network or the
DeepSeek provider and are skipped on non-POSIX platforms where the
``/proc``-group semantics and ``start_new_session`` do not apply.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from research_os.agent_runtime.production_runtime import BoundedOwnedProcess

pytestmark = pytest.mark.skipif(
    os.name == "nt" or not Path("/proc").is_dir(),
    reason="POSIX process-group /proc tests",
)


def _stat_pgrp(pid: int) -> int:
    """Parse the process group (post-state field index 2) from /proc/<pid>/stat."""
    text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    pivot = text.rindex(")")
    fields = text[pivot + 2:].split()
    # fields: [state, ppid, pgrp, ...]
    return int(fields[2])


@pytest.fixture
def owned_group():
    """Real root process in its own process group with one surviving child.

    The root spawns a long-sleeping child (which inherits the owned process
    group), prints the child PID, then exits immediately — leaving the owned
    group with a surviving descendant. Exactly the acceptance case "root
    exited but descendant remains".
    """
    root_script = (
        "import subprocess, sys\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
        "print(child.pid, flush=True)\n"
        "sys.exit(0)\n"
    )
    root = subprocess.Popen(
        [sys.executable, "-c", root_script],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        raw = root.stdout.readline().decode().strip()
    finally:
        root.stdout.close()
    descendant_pid = int(raw)
    owned = BoundedOwnedProcess(root, "http://127.0.0.1:0")
    root.wait(timeout=5)
    try:
        yield owned, descendant_pid
    finally:
        try:
            os.kill(descendant_pid, 9)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def test_root_exited_descendant_survives_reports_failed_residue(owned_group):
    owned, descendant_pid = owned_group
    # Root is gone but the descendant is still in the owned process group.
    assert owned.process.poll() is not None
    assert _stat_pgrp(descendant_pid) == owned.owned_pgid
    assert owned._own_group_alive() is True
    status = owned.cleanup_status()
    assert status["root"] == "TERMINATED"
    assert status["tree"] == "FAILED"


def test_terminate_tree_cleans_owned_group_after_root_exit(owned_group):
    owned, descendant_pid = owned_group
    assert owned._own_group_alive() is True
    owned.terminate_tree(grace_seconds=0.2)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and owned._own_group_alive():
        time.sleep(0.05)
    assert owned._own_group_alive() is False
    assert owned.cleanup_status()["tree"] == "VERIFIED"


def test_cleanup_status_tree_flow_matches_process_residue_gate():
    """FAILED -> real leak -> process_residue YES; VERIFIED -> NO; else NOT_VERIFIED."""
    from research_os.agent_runtime.trial import TrialController

    controller = TrialController()
    controller.owned_tree_cleanup = "FAILED"
    assert controller._process_residue() == "YES"
    controller.owned_tree_cleanup = "VERIFIED"
    controller.root_cleanup = "TERMINATED"
    controller.root_alive_after_stop = False
    assert controller._process_residue() == "NO"
    controller.owned_tree_cleanup = "NOT_VERIFIED"
    assert controller._process_residue() == "NOT_VERIFIED"
