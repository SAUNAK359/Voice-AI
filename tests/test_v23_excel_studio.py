"""Independent analytical workbook studies with real formulas and charts."""
from __future__ import annotations

import sys
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rizzler.work_excel_studio import (
    validate_workbook_plan,apply_workbook_plan,inspect_workbook_plan)


class AdvancedExcelStudioTests(unittest.TestCase):
    def test_category_study_formulas_match_original_source(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("Optional openpyxl work extra unavailable")
        from rizzler.work_skills import render_one
        table=(["region","revenue"],[
            ["East","10"],["West","20"],["East","30"],["West",""],["East","40"]])
        plan={"schema_version":1,"analyses":[
            {"title":"Regional revenue totals","category":"region",
             "measure":"revenue","aggregation":"sum",
             "rationale":"Compare independently measured revenue by region."},
            {"title":"Valid observations by region","category":"region",
             "measure":"revenue","aggregation":"count",
             "rationale":"Inspect completeness of regional revenue records."}
        ]}
        approved=validate_workbook_plan(plan,table)
        with tempfile.TemporaryDirectory() as temp:
            file=Path(temp)/"analysis.xlsx"
            render_one("xlsx",file,"Regional analysis",
                       "# Overview\nIndependently sourced regional values.",
                       table,[])
            apply_workbook_plan(file,approved)
            report=inspect_workbook_plan(file,approved)
            self.assertTrue(report["passed"])
            wb=openpyxl.load_workbook(file,data_only=False)
            self.assertIn("SUMIF",wb["Study 1"]["B4"].value)
            self.assertIn("COUNTIFS",wb["Study 2"]["B4"].value)
            wb["Study 1"]["C4"]=999
            wb.save(file);wb.close()
            with self.assertRaises(ValueError):
                inspect_workbook_plan(file,approved)

    def test_aggregate_only_numeric_table_and_invented_fields(self):
        try:
            import openpyxl
        except ImportError:
            self.skipTest("Optional openpyxl work extra unavailable")
        from rizzler.work_skills import render_one
        table=(["revenue"],[["10"],["20"],["30"]])
        plan={"schema_version":1,"analyses":[{
            "title":"Overall revenue measurement","category":None,
            "measure":"revenue","aggregation":"mean",
            "rationale":"Establish the source-derived average before interpretation."}]}
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"numbers.xlsx"
            render_one("xlsx",path,"All-numeric workbook",
                       "# Summary\nVerified numerical source analysis.",table,[])
            chosen=validate_workbook_plan(plan,table)
            apply_workbook_plan(path,chosen)
            report=inspect_workbook_plan(path,chosen)
            self.assertTrue(report["passed"])
            wb=openpyxl.load_workbook(path)
            self.assertTrue(wb["Study 1"]["B4"].value.startswith("=AVERAGE("))
            wb.close()
        plan["analyses"][0]["measure"]="invented"
        with self.assertRaises(ValueError):
            validate_workbook_plan(plan,table)


if __name__=="__main__":
    unittest.main()
