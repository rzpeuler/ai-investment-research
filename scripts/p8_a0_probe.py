"""Deterministic local probe for the P8-A0 runtime boundary."""
import json
import shutil
import subprocess
from pathlib import Path


PINNED_VERSION = "0.1.0-rc.7"


def probe() -> dict[str, object]:
    node = shutil.which("node")
    npx = shutil.which("npx")
    return {
        "package": "@deepseek-ai/dsh",
        "version": PINNED_VERSION,
        "node_available": bool(node),
        "npx_available": bool(npx),
        "installed_without_network": _installed_without_network(npx),
        "status": "ready_for_local_cli_start" if node and npx else "runtime_unavailable",
    }


def _installed_without_network(npx: str | None) -> bool:
    if not npx:
        return False
    result = subprocess.run([npx, "--no-install", "@deepseek-ai/dsh", "--version"],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0


if __name__ == "__main__":
    print(json.dumps(probe(), ensure_ascii=False, indent=2))
