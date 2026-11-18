"""V23 semantic document editor contract, rendering and tamper tests."""
from __future__ import annotations
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_ir import compile_ir
from rizzler.work_editor import (
    validate_report_plan, report_text, inspect_report_document)


class EditorialStudioTests(unittest.TestCase):
    def base(self):
        ir=compile_ir("International trade methods",
            "# Executive context\nThe evidence must retain historical periods and unit definitions.\n"
            "## Measurement framework\nAn accurate comparison requires consistent reporting units and documented assumptions.\n"
            "## Policy implications\nPolicy advice must account for possible alternative explanations.",
            ["https://example.org/data"])
        # Deliberately synthetic text; tests content accounting, not domain truth.
        paragraphs=[
            "This section explains how the analytical team would validate "
            "primary historical observations. It records the assumptions "
            "needed to compare measurement periods and units, and describes "
            "which alternative explanations might undermine a conclusion. "
            "The review distinguishes documented evidence from provisional "
            "interpretation, discusses the limits of the available data, and "
            "proposes independently checkable steps before policy decisions. "
        ]*4
        blueprint={"schema_version":1,"medium":"docx","sections":[
            {"heading":"Methods and scope", "body":" ".join(paragraphs),
             "section_ids":[0],"source_urls":["https://example.org/data"]},
            {"heading":"Evidence and measurement", "body":" ".join(paragraphs),
             "section_ids":[1],"source_urls":["https://example.org/data"]},
            {"heading":"Bounded recommendations", "body":" ".join(paragraphs),
             "section_ids":[2],"source_urls":[]},
        ]}
        return ir,blueprint

    def test_edited_report_is_source_scoped_and_substantive(self):
        ir,plan=self.base()
        valid=validate_report_plan(plan,medium="docx",
            original_sections=ir.sections,allowed_sources=ir.sources)
        self.assertGreater(valid["word_count"],450)
        self.assertEqual(validate_report_plan(valid,medium="docx",
            original_sections=ir.sections,allowed_sources=ir.sources),valid)
        invalid={"schema_version":1,"medium":"docx",
                 "sections":[dict(item) for item in plan["sections"]]}
        invalid["sections"][0]["source_urls"]=["https://invented.example"]
        with self.assertRaises(ValueError):
            validate_report_plan(invalid,medium="docx",
                                 original_sections=ir.sections,
                                 allowed_sources=ir.sources)

    def test_editable_word_and_pdf_reconcile_to_blueprint(self):
        try:
            from docx import Document
            import fitz
            import reportlab
        except ImportError:
            self.skipTest("Work artifact renderer extras unavailable")
        from rizzler.work_skills import render_one
        ir,base=self.base()
        with tempfile.TemporaryDirectory() as tmp:
            for kind in ("docx","pdf"):
                plan={**base,"medium":kind}
                checked=validate_report_plan(
                    plan,medium=kind,original_sections=ir.sections,
                    allowed_sources=ir.sources)
                path=Path(tmp)/("report."+kind)
                render_one(kind,path,ir.title,report_text(checked),None,list(ir.sources))
                quality=inspect_report_document(path,checked,source_urls=ir.sources)
                self.assertTrue(quality["passed"])
                self.assertEqual(quality["sections"],3)

if __name__=="__main__":
    unittest.main()
