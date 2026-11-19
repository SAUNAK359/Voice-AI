"""Regressions reconstructed from 2026-11-19 real Kaggle evidence ZIP.

Live failure root causes:
- research: list-valued source-count expression inside sum -> TypeError
- Excel: verified studio formulas rejected as unexpected executable cells
- Word: editor prompt lacked the validator's actual minimum word budget
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import unittest
import tempfile
import shutil

from rizzler.work_worker import _usable_source_document
from rizzler.work_ir import compile_ir
from rizzler.work_editor import create_report_plan


class KaggleLiveFailureTests(unittest.TestCase):
    def test_retrieved_source_count_never_aggregates_list_objects(self):
        records = [
            {"source_id": "s1", "blocks": [{"text": "Relevant report body"}],
             "tables": [], "sha256": "a"*64},
            {"source_id": "s2", "blocks": [], "tables": [
                {"rows": [["Year", "value"], ["2025", "42"]]}], "sha256": "b"*64},
            {"source_id": "bad", "error_category": "TimeoutError"},
            {"source_id": "empty", "blocks": [], "tables": []},
        ]
        assert sum(1 for doc in records if _usable_source_document(doc)) == 2
        assert not _usable_source_document({"blocks": "garbled", "tables": []})
        assert not _usable_source_document({"blocks": [], "tables": "bad"})


    def test_excel_preserves_blank_executive_heading_without_accepting_missing_body(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl unavailable in minimal CI")
        from openpyxl import load_workbook
        from rizzler.work_skills import render_one
        from rizzler.work_ir import compile_ir
        from rizzler.work_quality import inspect_artifact
        with tempfile.TemporaryDirectory(prefix="rizzler-ir-") as root:
            original=("# Executive report\\n\\n## Methodology and limitations\\n"
                      "The user-supplied data is the sole basis of these calculations.\\n"
                      "## Independent analysis\\n"
                      "Numbers are derived from the checked source rows.")
            # Include a deliberately empty Executive report body followed by
            # actual analytical sections, the format in a real Gemini output.
            ir=compile_ir("Synthetic INR data analysis",original,[])
            file=Path(root)/"report.xlsx"
            render_one("xlsx",file,ir.title,ir.content,
                       (["region","revenue_inr"],[["East","12"],["West","18"]]),[])
            report=inspect_artifact(file,"xlsx",dataset_rows=2,
                                    artifact_ir=ir)
            self.assertTrue(report["passed"])
            wb=load_workbook(file)
            # Missing substantive prose must still fail closed.
            wb["Summary"]["B4"]=None
            wb.save(file);wb.close()
            with self.assertRaisesRegex(ValueError,"Artifact IR"):
                inspect_artifact(file,"xlsx",dataset_rows=2,
                                 artifact_ir=ir)

    def test_analytical_excel_formulas_are_allowed_only_with_validated_studio_plan(self):
        tmp_path=Path(tempfile.mkdtemp(prefix="rizzler-test-"))
        self.addCleanup(shutil.rmtree,tmp_path)
        try:
            import openpyxl
        except ImportError:
            self.skipTest("openpyxl unavailable in minimal CI")
        from openpyxl import load_workbook
        from rizzler.work_skills import render_one
        from rizzler.work_excel_studio import validate_workbook_plan, apply_workbook_plan
        from rizzler.work_quality import inspect_artifact
        from rizzler.work_formula import verify_workbook
        table=(["region","revenue"], [["East","10"],["West","20"],["East","30"]])
        analysis={"schema_version":1,"analyses":[{
            "title":"Revenue analysis by region", "category":"region",
            "measure":"revenue", "aggregation":"sum",
            "rationale":"Reconcile actual grouped revenue to source observations."
        }]}
        plan=validate_workbook_plan(analysis,table)
        file=tmp_path/"report.xlsx"
        render_one("xlsx",file,"Revenue by region",
                   "# Revenue\nThe supplied data is analyzed using source values.",table,[])
        apply_workbook_plan(file,plan)
        with self.assertRaisesRegex(ValueError,"Unexpected executable"):
            verify_workbook(file)
        validated=inspect_artifact(file,"xlsx",dataset_rows=3,excel_plan=plan)
        assert validated["passed"]
        wb=load_workbook(file)
        wb["Study 1"]["C4"]=999
        wb.save(file); wb.close()
        with self.assertRaises(ValueError):
            inspect_artifact(file,"xlsx",dataset_rows=3,excel_plan=plan)
        wb=load_workbook(file)
        wb["Study 1"]["C4"]=40
        wb["Study 1"]["D4"]="=1+1"
        wb.save(file); wb.close()
        with self.assertRaisesRegex(ValueError,"Unexpected executable"):
            inspect_artifact(file,"xlsx",dataset_rows=3,excel_plan=plan)


    def test_word_editor_repairs_underlength_draft_without_inventing_sources(self):
        try:
            from google import genai
        except ImportError:
            self.skipTest("Google GenAI SDK unavailable in minimal CI")
        ir=compile_ir(
            "Technical evidence analysis",
            "# Research objective\nA technical investigation of supplied observations.\n"
            "## Methodology\nMethods and limitations must be documented honestly.\n"
            "## Implications\nUnsupported claims cannot be represented as verified.",
            [])
        headings=[h for h,_ in ir.sections]
        assert len(headings)>=3
        weak=("The source material has important limitations, so every conclusion "
              "must be connected to evidence and avoid invented measurements. ")*4
        strong=("The available source narrative provides observations and explicit "
                "uncertainty. An analyst should compare alternative explanations, "
                "document methods, separate assumptions from measurements and "
                "identify what remains unresolved before making decisions. ")*12
        calls=[]
        async def generated(client,**kwargs):
            calls.append(kwargs["contents"])
            paragraphs=weak if len(calls)==1 else strong
            return SimpleNamespace(text=json.dumps({
                "schema_version":1,"medium":"docx",
                "sections":[
                    {"heading":f"Technical section {i+1}",
                     "body":paragraphs,
                     "section_ids":[i],
                     "source_urls":[]} for i in range(len(headings))]
            }))
        client=SimpleNamespace(aio=SimpleNamespace(aclose=lambda:asyncio.sleep(0)))
        with patch("rizzler.cognitive_provider.generate_with_recovery",new=generated):
            result=asyncio.run(create_report_plan(
                "Prepare a careful technical report",ir,medium="docx",
                model="test-model",api_key="fake",client=client))
        assert len(calls)==2
        assert "previous draft" in calls[-1].lower()
        assert result["word_count"]>=450
        assert result["original_sections_covered"]==list(range(len(headings)))
