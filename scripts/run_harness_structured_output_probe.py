"""Probe Harness provider-level structured output support.

The probe is explicit and bounded. It compares the existing normal Harness
generation path with a provider-level ``send_structured_message`` seam when
available. It never changes production routing, schemas, validators, or
acceptance thresholds. The report is written to
``reports/structured_output_probe.json`` and is intentionally not a tracked
runtime artifact.
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import signal
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import yaml  # noqa: E402

from research_os.agent_runtime.errors import RuntimeNotReady  # noqa: E402
from research_os.llm.client import LlmClient  # noqa: E402
from research_os.llm.models import LlmRequest  # noqa: E402
from research_os.llm.providers.generation_controller import GenerationControlledProvider  # noqa: E402
from research_os.llm.providers.harness import HarnessLlmProvider  # noqa: E402
from research_os.validators.schema_validator import load_schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = ROOT / "config" / "harness_benchmark" / "corpus.yaml"
REPORT_PATH = ROOT / "reports" / "structured_output_probe.json"
PROBE_ENV = "P8_B2_R5_B_STRUCTURED_OUTPUT_PROBE"
SUBSET_IDS = {"fl_invalid_json", "rs_research_finding_generation", "eq_research_questions"}


class _Db:
    def __init__(self, conn):
        self._conn = conn


def _load_cases() -> list[dict[str, Any]]:
    corpus = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    return [case for case in corpus["cases"] if case["id"] in SUBSET_IDS]


def _request(case: dict[str, Any], mode: str) -> LlmRequest:
    prompt = case.get("prompt") or (
        "Generate the requested research finding from the supplied evidence. "
        "Return only the requested structured object."
    )
    return LlmRequest(
        call_id=f"structured-probe-{mode}-{case['id']}",
        task_id=f"structured-probe:{mode}:{case['id']}",
        module=f"structured_output_probe.{case['category']}",
        prompt=prompt,
        prompt_hash=f"structured-probe-{mode}-{case['id']}",
        input_evidence_ids=["probe-e1", "probe-e2"],
        requested_model_class="flash",
        provider="deepseek-harness",
        output_schema_name=case["schema_name"],
        timeout_seconds=60,
    )


def _row(client: LlmClient, provider: GenerationControlledProvider,
         case: dict[str, Any], mode: str) -> dict[str, Any]:
    started = time.monotonic()
    response = client.generate_json(_request(case, mode), load_schema(case["schema_name"]))
    state = provider.states[-1] if provider.states else None
    calls = list(getattr(provider.base_provider, "calls", []))
    invalid_response = any(call.get("status") == "invalid_response" for call in calls[-(state.provider_calls if state else 1):])
    return {
        "case_id": case["id"],
        "mode": mode,
        "provider": response.provider,
        "model": response.model_id,
        "status": response.status,
        "json_parse_success": not invalid_response and response.output is not None,
        "schema_valid": response.schema_valid,
        "latency_seconds": round(time.monotonic() - started, 3),
        "provider_calls": state.provider_calls if state else 0,
        "token_usage": (response.usage_metadata.get("provider_usage") or {}).get("total_tokens"),
        "validation_errors": [str(error)[:160] for error in response.validation_errors[:10]],
        "audit_recorded": response.called,
        "fake_model_inference": 0,
        "validator_bypass": 0,
    }


def _blocked(reason: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "BLOCKED",
        "reason": reason,
        "probe": "P8-B2-R5-B",
        "capability": {
            "normal": {"mode": "normal", "status": "NOT_EXECUTED"},
            "structured": {"mode": "structured", "status": "NOT_EXECUTED"},
        },
        "cases": [case["id"] for case in cases],
        "results": [],
        "comparison": None,
        "audit": {"fake_model_inference": 0, "validator_bypass": 0},
    }


def _comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {}
    for mode in ("normal", "structured"):
        selected = [row for row in rows if row["mode"] == mode]
        available = [row for row in selected if row["status"] != "unsupported"]
        result[mode] = {
            "cases": len(selected),
            "available_cases": len(available),
            "json_parse_success_rate": round(sum(row["json_parse_success"] for row in available) / len(available), 3) if available else None,
            "schema_valid_rate": round(sum(row["schema_valid"] for row in available) / len(available), 3) if available else None,
            "latency_seconds_total": round(sum(row["latency_seconds"] for row in available), 3),
            "provider_calls": sum(row["provider_calls"] for row in available),
            "token_usage": sum(row["token_usage"] or 0 for row in available),
        }
    normal = result["normal"]
    structured = result["structured"]
    result["delta"] = {
        "json_parse_success_rate": (structured["json_parse_success_rate"] - normal["json_parse_success_rate"])
        if structured["json_parse_success_rate"] is not None and normal["json_parse_success_rate"] is not None else None,
        "schema_valid_rate": (structured["schema_valid_rate"] - normal["schema_valid_rate"])
        if structured["schema_valid_rate"] is not None and normal["schema_valid_rate"] is not None else None,
        "latency_seconds": structured["latency_seconds_total"] - normal["latency_seconds_total"],
        "provider_calls": structured["provider_calls"] - normal["provider_calls"],
        "token_usage": structured["token_usage"] - normal["token_usage"],
    }
    return result


def _write_report(report: dict[str, Any]) -> int:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "COMPLETED" else 1


def _run_live_probe() -> int:
    cases = _load_cases()
    if os.environ.get(PROBE_ENV) != "1":
        report = _blocked("PROBE_NOT_ENABLED", cases)
        return _write_report(report)
    if not os.environ.get("DEEPSEEK_API_KEY"):
        report = _blocked("PROVIDER_CREDENTIAL_UNAVAILABLE", cases)
        return _write_report(report)

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE llm_call_records (call_id TEXT, payload TEXT, task_id TEXT, module TEXT, status TEXT, called_at TEXT)")
    rows: list[dict[str, Any]] = []
    providers: dict[str, GenerationControlledProvider] = {}
    try:
        normal_base = HarnessLlmProvider()
        structured_base = HarnessLlmProvider(structured_output=True)
        providers = {
            "normal": GenerationControlledProvider(normal_base, max_repair_passes=2),
            "structured": GenerationControlledProvider(structured_base, max_repair_passes=2),
        }
        clients = {mode: LlmClient(provider=provider, configured=True, db=_Db(conn))
                   for mode, provider in providers.items()}
        capability = {
            "normal": normal_base.capability(),
            "structured": structured_base.capability(),
        }
        for case in cases:
            for mode in ("normal", "structured"):
                rows.append(_row(clients[mode], providers[mode], case, mode))
        status = "COMPLETED"
    except RuntimeNotReady as exc:
        status = "BLOCKED"
        capability = {"normal": {"status": "NOT_AVAILABLE"}, "structured": {"status": "NOT_AVAILABLE"}}
        reason = getattr(exc, "code", type(exc).__name__)
        rows = []
    except Exception as exc:  # noqa: BLE001 - probe boundary records explicit failure
        status = "FAILED"
        capability = {"normal": {"status": "ERROR"}, "structured": {"status": "ERROR"}}
        reason = type(exc).__name__
        rows = []
    finally:
        for provider in providers.values():
            adapter = getattr(provider.base_provider, "adapter", None)
            supervisor = getattr(adapter, "supervisor", None)
            if supervisor is not None:
                supervisor.stop()

    audit_count = conn.execute("SELECT COUNT(*) FROM llm_call_records").fetchone()[0]
    report = {
        "status": status,
        "probe": "P8-B2-R5-B",
        "capability": capability,
        "cases": [case["id"] for case in cases],
        "results": rows,
        "comparison": _comparison(rows) if rows else None,
        "audit": {
            "records": audit_count,
            "expected_minimum": len(rows),
            "complete": audit_count >= len(rows),
            "fake_model_inference": 0,
            "validator_bypass": 0,
        },
    }
    if status != "COMPLETED":
        report["reason"] = reason
    return _write_report(report)


def main() -> int:
    """Run the real worker behind a bounded parent-process timeout."""
    cases = _load_cases()
    if os.environ.get(PROBE_ENV) != "1":
        return _write_report(_blocked("PROBE_NOT_ENABLED", cases))
    if not os.environ.get("DEEPSEEK_API_KEY"):
        return _write_report(_blocked("PROVIDER_CREDENTIAL_UNAVAILABLE", cases))
    if os.environ.get(f"{PROBE_ENV}_WORKER") == "1":
        return _run_live_probe()

    worker_env = os.environ.copy()
    worker_env[f"{PROBE_ENV}_WORKER"] = "1"
    timeout_seconds = int(os.environ.get(f"{PROBE_ENV}_TIMEOUT_SECONDS", "30"))
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve())],
        env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        start_new_session=os.name != "nt",
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)],
                           capture_output=True, check=False)
        else:
            os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
        return _write_report({
            "status": "BLOCKED",
            "reason": "PROBE_TIMEOUT",
            "timeout_seconds": timeout_seconds,
            "probe": "P8-B2-R5-B",
            "capability": {
                "normal": {"mode": "normal", "status": "NOT_AVAILABLE"},
                "structured": {"mode": "structured", "status": "NOT_AVAILABLE"},
            },
            "cases": [case["id"] for case in cases],
            "results": [],
            "comparison": None,
            "audit": {"fake_model_inference": 0, "validator_bypass": 0},
        })
    if stdout:
        print(stdout, end="")
    if stderr:
        print(stderr, end="", file=sys.stderr)
    return process.returncode


if __name__ == "__main__":
    raise SystemExit(main())
