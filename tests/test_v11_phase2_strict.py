"""Actual LibreOffice/PyMuPDF qualification; never use mocks as visual evidence."""
from __future__ import annotations

from pathlib import Path
import shutil
import pytest

from rizzler.work_skills import render_one
from rizzler.work_quality import inspect_artifact

pytestmark=pytest.mark.skipif(
    not (shutil.which("libreoffice") or shutil.which("soffice")),
    reason="Strict artifact QA requires LibreOffice; production CI installs it")


@pytest.mark.parametrize("kind",["docx","pptx","pdf","xlsx"])
def test_independent_render_or_formula_recalculation(tmp_path,kind):
    title="Sales performance in three regions"
    text=("# Executive summary\nThe sample contains three regional sales results. "
          "North and West have different revenues.\n"
          "## Key evidence\nThree observations were counted from the uploaded dataset. "
          "The mean revenue was 20 in the source data.")
    table=(["region","revenue"],[["North","10"],["South","20"],["West","30"]])
    file=tmp_path/("report."+kind)
    render_one(kind,file,title,text,table,["https://example.org/source"])
    report=inspect_artifact(file,kind,dataset_rows=3,visual_required=True)
    assert report["passed"]
    if kind=="xlsx":
        assert (report["metrics"]["formula_validation"]["recalculation"] ==
                "libreoffice_independently_reconciled")
    else:
        visual=report["metrics"]["visual_validation"]
        assert visual["status"]=="rendered_pages_verified"
        assert len(visual["per_page"])==visual["pages"]
        assert all(p["words"]>=2 and len(p["pixel_sha256"])==64 for p in visual["per_page"])
