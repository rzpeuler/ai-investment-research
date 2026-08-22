"""Build a read-only P8-A4 reviewer evidence bundle from R1 artifacts.

This script never runs Harness and never manufactures raw output. The accepted
R1 audit intentionally excludes raw prompts/responses, so unavailable output
is represented by an explicit marker rather than an offline substitute or
summary.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
R1_ARTIFACT = ROOT / "reports" / "p8_a4_r1_real_provider_validation.json"
BUNDLE_ROOT = ROOT / "reports" / "p8_a4_human_review_bundle"
MISSING_OUTPUT = (
    "NOT_PERSISTED_BY_R1_ARTIFACT\n"
    "The R1 audit contract intentionally excludes raw Harness responses. "
    "No offline output, summary, or synthetic response is substituted.\n"
)


def _load_corpus() -> Any:
    import sys

    sys.path.insert(0, str(ROOT / "src"))
    from research_os.agent_runtime.pilot_corpus import PilotCorpus

    return PilotCorpus()


def build_bundle() -> dict[str, Any]:
    source = json.loads(R1_ARTIFACT.read_text(encoding="utf-8"))
    corpus = _load_corpus()
    expected = corpus.exploration_cases()
    audits = {
        record["task_id"]: record
        for record in source.get("audit_records", [])
        if record.get("task_id") in {case.id for case in expected}
    }
    BUNDLE_ROOT.mkdir(parents=True, exist_ok=True)
    case_results = []
    for case in expected:
        audit = audits.get(case.id)
        if audit is None:
            raise ValueError(f"R1 audit record missing for {case.id}")
        case_dir = BUNDLE_ROOT / f"case_{case.id}"
        case_dir.mkdir(parents=True, exist_ok=True)
        metadata = {
            "case_id": case.id,
            "task_type": case.category,
            "runtime_selection": audit.get("runtime_selection"),
            "skills_used": audit.get("skills_used", []),
            "tools_called": audit.get("tools_called", []),
            "source_artifact": str(R1_ARTIFACT.relative_to(ROOT)),
            "prompt_source": "config/harness_pilot_corpus.yaml",
            "harness_output_status": "NOT_AVAILABLE_FROM_R1_ARTIFACT",
            "audit_status": "AVAILABLE",
            "automatic_summary": False,
        }
        (case_dir / "metadata.json").write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (case_dir / "prompt.txt").write_text(case.prompt, encoding="utf-8")
        (case_dir / "harness_output.txt").write_text(MISSING_OUTPUT, encoding="utf-8")
        (case_dir / "audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        case_results.append({
            "case_id": case.id,
            "metadata": True,
            "prompt": True,
            "harness_output": False,
            "audit": True,
            "traceable_to_audit": True,
        })
    complete = sum(
        1 for result in case_results
        if result["metadata"] and result["prompt"] and result["harness_output"] and result["audit"]
    )
    manifest = {
        "bundle_version": "1.0.0",
        "source_artifact": str(R1_ARTIFACT.relative_to(ROOT)),
        "source_run_id": source.get("run_id"),
        "case_count": len(case_results),
        "case_results": case_results,
        "evidence_completeness": {
            "metadata": len(case_results),
            "prompt": len(case_results),
            "harness_output": sum(1 for row in case_results if row["harness_output"]),
            "audit": sum(1 for row in case_results if row["audit"]),
            "complete_cases": complete,
            "status": "PARTIAL_RAW_OUTPUT_NOT_PERSISTED_BY_R1",
        },
        "automatic_summary": False,
        "harness_rerun": False,
    }
    (BUNDLE_ROOT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def main() -> int:
    manifest = build_bundle()
    print(json.dumps({
        "bundle_path": str(BUNDLE_ROOT),
        "case_count": manifest["case_count"],
        "evidence_completeness": manifest["evidence_completeness"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
