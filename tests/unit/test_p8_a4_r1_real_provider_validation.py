from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "p8_a4_r1_real_provider_validation.py"


def _module():
    spec = importlib.util.spec_from_file_location("p8_a4_r1_real_provider_validation", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_r1_runner_requires_explicit_opt_in(monkeypatch):
    monkeypatch.delenv("P8_A4_R1_REAL_PROVIDER_VALIDATION", raising=False)
    assert _module().main() == 2


def test_r1_missing_provider_is_data_unavailable(monkeypatch, tmp_path):
    monkeypatch.setenv("P8_A4_R1_REAL_PROVIDER_VALIDATION", "1")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    module = _module()
    module.REPORT_PATH = tmp_path / "report.json"
    module.HUMAN_REVIEW_PATH = tmp_path / "human.json"
    assert module.main() == 1
    report = json.loads(module.REPORT_PATH.read_text(encoding="utf-8"))
    assert report["REAL_RUN"]["status"] == "DATA_UNAVAILABLE"
    assert report["OFFLINE_TEST"]["status"] == "NOT_RUN_BY_THIS_ENTRYPOINT"
    assert report["value"]["automated_score"] is False
    rendered = json.dumps(report, ensure_ascii=False)
    assert "DEEPSEEK_API_KEY" not in rendered
    assert "full_prompt" not in rendered
    assert "raw_response" not in rendered
