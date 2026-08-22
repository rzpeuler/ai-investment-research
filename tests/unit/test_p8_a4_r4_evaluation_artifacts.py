from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass


def _module():
    spec = importlib.util.spec_from_file_location(
        "p8_a3_pilot_evaluation_artifacts",
        "scripts/p8_a3_pilot_evaluation.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@dataclass
class _Case:
    id: str = "case_one"
    category: str = "exploration"
    task_type: str = "industry_exploration"
    output_contract: str = "exploration"
    risk_level: str = "low"
    authority_requirement: str = "research_read"
    expected: str = "HARNESS_ALLOWED"


class _Decision:
    def as_dict(self):
        return {"selection": "HARNESS_ALLOWED", "reason": "test", "policy_version": "1.0.0"}


def test_case_artifact_retains_raw_response_events_tools_and_audit(tmp_path):
    module = _module()
    result = module._write_case_evidence(
        artifact_root=tmp_path,
        case=_Case(),
        decision=_Decision(),
        audit_record={"task_id": "case_one", "status": "completed"},
        events=[{"event_type": "tool_call", "tool_name": "get_company_profile"}],
        turn_records=[{
            "turn": 1,
            "prompt": "exact prompt",
            "response": {"status": "completed", "response": "exact harness output"},
        }],
        metrics={"status": "completed"},
    )
    case_dir = tmp_path / "case_case_one"
    assert result["raw_output_exists"] is True
    for name in ("input.json", "prompt.txt", "harness_output.txt",
                 "events.json", "tools.json", "audit.json", "metrics.json"):
        assert (case_dir / name).exists()
    assert (case_dir / "harness_output.txt").read_text(encoding="utf-8") == "exact harness output"
    assert "exact prompt" in (case_dir / "prompt.txt").read_text(encoding="utf-8")


def test_case_artifact_writer_rejects_overwrite(tmp_path):
    module = _module()
    kwargs = {
        "artifact_root": tmp_path, "case": _Case(), "decision": _Decision(),
        "audit_record": {}, "events": [], "turn_records": [],
        "metrics": {},
    }
    module._write_case_evidence(**kwargs)
    try:
        module._write_case_evidence(**kwargs)
    except FileExistsError:
        pass
    else:
        raise AssertionError("artifact writer must fail closed on overwrite")
