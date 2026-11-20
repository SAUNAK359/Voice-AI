"""Purpose-aware, fully editable V26 slide composition regression tests.

The test exercises a real PowerPoint document, not a mocked design proposal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))


def slide(kind,title,i):
    return {
        "title":title,
        "message":"A clear, evidence-specific claim is preserved in this format.",
        "kind":kind,
        "bullets":[
            "Evidence remains directly associated with the approved source.",
            "Important analytical limitations remain visible to stakeholders.",
            "The selected layout must retain all original data explanations.",
        ],
        "section_ids":[i],
        "source_urls":["https://docs.example.org/official"],
    }


@unittest.skipUnless(importlib.util.find_spec("pptx") is not None,
                     "Install Work extras for native editable PowerPoint QA")
class NativeProfessionalPresentationTests(unittest.TestCase):
    def test_six_slide_purposes_produce_distinct_native_layouts(self):
        from pptx import Presentation
        from rizzler.work_studio import inspect_storyboard
        from rizzler.work_presentation_layout import (
            render_professional_storyboard)
        kinds=["takeaway","comparison","process","evidence","metrics","decision"]
        slides=[slide(name,f"Source-backed {name.title()} Explanation",i)
                for i,name in enumerate(kinds)]
        original={"schema_version":1,"slides":slides,
                  "sections_covered":list(range(len(kinds)))}
        with TemporaryDirectory() as temp:
            file=Path(temp)/"professional.pptx"
            render_professional_storyboard(
                file,original,title="Executive output",
                sources=("https://docs.example.org/official",))
            deck=Presentation(file)
            self.assertEqual(len(deck.slides),len(kinds))
            shapes=[len(s.shapes) for s in deck.slides]
            self.assertGreater(len(set(shapes)),2)
            reviewed=inspect_storyboard(file,original)
            self.assertTrue(reviewed["passed"])
            self.assertEqual(reviewed["slides"],len(kinds))

    def test_chart_layout_preserves_actual_series_and_source_numeric_values(self):
        from rizzler.work_visual_strategy import (
            validate_visual_plan,inspect_chart_bindings)
        from rizzler.work_presentation_layout import (
            render_professional_storyboard)
        table=(["period","first","second"],[
            ["Q1","125","95"],["Q2","140","105"],
            ["Q3","160","117"],["Q4","175","133"]])
        slides=[slide("metrics","Source first and second quarterly totals",0),
                slide("metrics","Observed balance variation by quarter",1)]
        visual={"schema_version":2,"slides":[
            {"slide_index":0,"visual_type":"bar",
             "category_column":"period",
             "series_columns":["first","second"],
             "difference":None,"claim_binding":"first",
             "reason":"Compare both primary series without hiding the export values."},
            {"slide_index":1,"visual_type":"line",
             "category_column":"period",
             "series_columns":["first"],
             "difference":{"operation":"subtract",
                           "left_column":"second",
                           "right_column":"first",
                           "label":"net balance"},
             "claim_binding":"net balance",
             "reason":"Plot the real quarterly balance computed from the source."},
        ]}
        doc={"schema_version":1,"slides":slides,"visual_plan":visual}
        validate_visual_plan(visual,doc,table)
        with TemporaryDirectory() as temp:
            file=Path(temp)/"verified_chart.pptx"
            render_professional_storyboard(
                file,doc,title="Trade data",
                sources=("https://docs.example.org/official",),
                table=table)
            self.assertTrue(inspect_chart_bindings(
                file,visual,table)["passed"])


if __name__=="__main__":
    unittest.main()
