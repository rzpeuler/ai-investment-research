from __future__ import annotations

import json


def test_runtime_status_reports_provider_health():
    from scripts.run_harness_benchmark import _runtime_status

    class Status:
        ready = True
        state = "READY"
        process_alive = True
        profile_verified = True
        mcp_verified = True
        version_verified = True
        failure_code = None

    class Adapter:
        def get_runtime_status(self):
            return Status()

    result = _runtime_status(Adapter())
    assert result["provider_available"] is True
    assert result["health_check"] == "PASS"
    assert result["process_alive"] is True
    assert result["mcp_verified"] is True


def test_runtime_status_fails_closed_on_health_exception():
    from scripts.run_harness_benchmark import _runtime_status

    class Adapter:
        def get_runtime_status(self):
            raise RuntimeError("health unavailable")

    result = _runtime_status(Adapter())
    assert result["provider_available"] is False
    assert result["health_check"] == "ERROR"


def test_resume_rows_are_loaded_only_when_explicitly_enabled(tmp_path, monkeypatch):
    import scripts.run_harness_benchmark as benchmark

    report = tmp_path / "r5d.json"
    report.write_text(json.dumps({"results": [
        {"case_id": "c1", "runtime": "harness"},
        {"case_id": "c1", "runtime": "legacy"},
        {"case_id": "ignored", "runtime": "fixture"},
    ]}), encoding="utf-8")
    monkeypatch.setattr(benchmark, "REPORT_PATH", report)
    monkeypatch.setenv(benchmark.RESUME_ENV, "1")
    rows = benchmark._load_resume_rows()
    assert set(rows) == {"c1"}
    assert {row["runtime"] for row in rows["c1"]} == {"harness", "legacy"}


def test_resume_rows_are_disabled_by_default(tmp_path, monkeypatch):
    import scripts.run_harness_benchmark as benchmark

    monkeypatch.setattr(benchmark, "REPORT_PATH", tmp_path / "r5d.json")
    monkeypatch.delenv(benchmark.RESUME_ENV, raising=False)
    assert benchmark._load_resume_rows() == {}
