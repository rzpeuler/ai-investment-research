from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest


ROOT = Path(__file__).resolve().parents[2]
WORKBOOK = ROOT / "reports" / "p8_a4_human_review_template.xlsx"
RUN_ROOT = ROOT / "reports" / "harness_evaluation_runs" / "a3-eval-657677b514b8"


@pytest.mark.skipif(not WORKBOOK.exists(), reason="generated reviewer workbook is workspace-local")
def test_reviewer_workbook_has_two_sheets_and_twenty_case_rows():
    with ZipFile(WORKBOOK) as archive:
        names = set(archive.namelist())
        assert "xl/worksheets/sheet1.xml" in names
        assert "xl/worksheets/sheet2.xml" in names
        assert "xl/tables/table1.xml" in names
        assert "xl/tables/table2.xml" in names
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
        assert sheet_xml.count("<x:row") >= 23


@pytest.mark.skipif(not RUN_ROOT.exists(), reason="R4 retained run is workspace-local")
def test_latest_retained_run_has_complete_raw_evidence_for_twenty_cases():
    case_dirs = sorted(RUN_ROOT.glob("case_*"))
    assert len(case_dirs) == 20
    required = {
        "input.json", "prompt.txt", "harness_output.txt", "events.json",
        "tools.json", "audit.json", "metrics.json",
    }
    for case_dir in case_dirs:
        assert required.issubset({path.name for path in case_dir.iterdir()})
        assert (case_dir / "prompt.txt").read_text(encoding="utf-8").strip()
        assert (case_dir / "harness_output.txt").read_text(encoding="utf-8").strip()
