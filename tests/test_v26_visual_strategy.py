"""V26 source-semantic PowerPoint chart plan, native rendering and audit.

This test uses the actual python-pptx editable chart writer and re-opens the
file to compare plotted series with independently computed CSV row values.
"""
from __future__ import annotations

from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_studio import render_storyboard,validate_storyboard
from rizzler.work_visual_strategy import (
    validate_visual_plan,chart_values,inspect_chart_bindings,
    VisualStrategyError)


TABLE=(
    ["quarter","imports","exports","region"],
    [["Q1","125","95","North"],
     ["Q2","140","105","North"],
     ["Q3","160","117","South"],
     ["Q4","175","133","South"]]
)
SECTIONS=(
    ("Trade totals","Quarterly values support source-bound comparison."),
    ("Balance change","Each quarter has a negative and changing trade balance.")
)


def slide(title,index):
    return {"title":title,
            "message":"These source metrics must match the real plotted series.",
            "kind":"metrics",
            "bullets":["All plotted chart values come from the approved data.",
                       "Measurement units are unspecified in the synthetic source."],
            "section_ids":[index],"source_urls":[]}


def planned():
    return {"schema_version":2,"slides":[
        {"slide_index":0,"visual_type":"bar",
         "category_column":"quarter",
         "series_columns":["imports","exports"],"difference":None,
         "claim_binding":"imports",
         "reason":"Show both contributing series to compare trade magnitude."},
        {"slide_index":1,"visual_type":"line",
         "category_column":"quarter","series_columns":["exports"],
         "difference":{"operation":"subtract",
                       "left_column":"exports",
                       "right_column":"imports","label":"trade balance"},
         "claim_binding":"trade balance",
         "reason":"Plot the actual negative trade balances instead of imports alone."}
    ]}


class EditableChartQualificationTests(unittest.TestCase):
    def test_two_semantically_distinct_charts_render_source_accurate_values(self):
        ir={"schema_version":1,"slides":[
            slide("Imports and exports by quarter",0),
            slide("Deficit changes across quarters",1)]}
        visuals=planned()
        self.assertEqual(validate_visual_plan(visuals,ir,TABLE),visuals)
        approved=validate_storyboard(
            {**ir,"visual_plan":visuals},SECTIONS,(),
            min_slides=1,allow_visual=True)
        self.assertIn("visual_plan",approved)
        with TemporaryDirectory() as root:
            file=Path(root)/"source_charts.pptx"
            render_storyboard(file,approved,title="Trade tests",
                              sources=(),table=TABLE)
            result=inspect_chart_bindings(file,visuals,TABLE)
            self.assertTrue(result["passed"])
            self.assertEqual(result["chart_count"],2)
        cat,series=chart_values(visuals["slides"][1],TABLE)
        self.assertEqual(series["trade balance"],[-30.,-35.,-43.,-42.])

    def test_duplicate_chart_encoding_is_rejected(self):
        b=planned()
        b["slides"][1]={**b["slides"][0],"slide_index":1}
        doc={"schema_version":1,"slides":[
            slide("Example one",0),slide("Example two",1)]}
        with self.assertRaises(VisualStrategyError):
            validate_visual_plan(b,doc,TABLE)

    def test_slide_claim_must_match_a_plotted_metric(self):
        b=planned()
        b["slides"][1]["claim_binding"]="imports"
        doc={"schema_version":1,"slides":[
            slide("Example one",0),slide("Example two",1)]}
        with self.assertRaises(VisualStrategyError):
            validate_visual_plan(b,doc,TABLE)

    def test_model_visual_metadata_cannot_bypass_legacy_schema(self):
        b={"schema_version":1,"slides":[
            slide("Example one",0),slide("Example two",1)],
            "visual_plan":planned()}
        with self.assertRaises(ValueError):
            validate_storyboard(b,SECTIONS,(),min_slides=1)
        self.assertEqual(len(validate_storyboard(
            b,SECTIONS,(),allow_visual=True,min_slides=1)["slides"]),2)


if __name__=="__main__":
    unittest.main()
