"""V26 editorial contracts prevent irrelevant reports from being forced into slides.

No provider calls: all citations, selected sections, protected metadata and
source coverage are evaluated against the authoritative original ArtifactIR.
"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import AsyncMock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_ir import compile_ir
from rizzler.work_studio import validate_storyboard
from rizzler.work_editorial_director import (
    validate_editorial_plan,validate_editorial_critique,
    EditorialQualificationError)
from rizzler.work_artifact_strategy import create_editorial_storyboard


def sample_ir():
    return compile_ir(
        "Audience-first financial analysis",
        "# Executive finding\nSource-backed observed imports exceed exports in each period.\n"
        "## Internal execution logs\nSQL returned four records and a ZIP was created.\n"
        "## Limitations\nFour fictional rows cannot establish a causal region effect.",
        ["https://example.org/approved"])


def plan():
    return {"schema_version":2,
            "audience":"Executive decision makers",
            "purpose":"Communicate the observed finding and its limitations.",
            "thesis":"Trade differences require careful, qualified interpretation.",
            "selected_section_ids":[0,2],
            "excluded_section_ids":[1],
            "rationale":"The internal SQL and packaging activity is not an audience-facing finding.",
            "source_urls":["https://example.org/approved"],
            "limitations":["The regional comparison is confounded by the time periods."]}


def slide(index):
    return {"title":"Supported executive finding",
            "message":"Observed values need a carefully qualified interpretation.",
            "kind":"takeaway",
            "bullets":["Source data explains the observed conclusion within the sample.",
                       "No real-world causal inference follows from the sample."],
            "section_ids":[index],
            "source_urls":["https://example.org/approved"]}


class EditorialContractTests(unittest.TestCase):
    def test_plan_can_explicitly_exclude_irrelevant_technical_sections(self):
        ir=sample_ir()
        self.assertEqual(validate_editorial_plan(
            plan(),sections=ir.sections,
            required_sources=ir.sources)["selected_section_ids"],[0,2])

    def test_plan_must_account_for_every_omission(self):
        ir=sample_ir()
        bad={**plan(),"excluded_section_ids":[]}
        with self.assertRaises(EditorialQualificationError):
            validate_editorial_plan(bad,sections=ir.sections,
                                    required_sources=ir.sources)

    def test_model_cannot_mint_approved_source(self):
        ir=sample_ir()
        bad={**plan(),"source_urls":["https://fabrication.invalid"]}
        with self.assertRaises(EditorialQualificationError):
            validate_editorial_plan(bad,sections=ir.sections,
                                    required_sources=ir.sources)

    def test_selected_insight_coverage_is_protected_from_model_only_authority(self):
        ir=sample_ir()
        doc={"schema_version":1,"slides":[slide(0),slide(2)],
             "editorial_plan":plan()}
        with self.assertRaises(ValueError):
            validate_storyboard(doc,ir.sections,ir.sources,
                                min_slides=1,allow_editorial=False)
        valid=validate_storyboard(doc,ir.sections,ir.sources,
                                  min_slides=1,allow_editorial=True)
        self.assertEqual(valid["sections_covered"],[0,2])
        # One excluded SQL/ZIP section need not become a slide.
        self.assertNotIn(1,valid["sections_covered"])
        forged={"schema_version":1,"slides":[slide(0),slide(1),slide(2)],
                "editorial_plan":plan()}
        with self.assertRaises(ValueError):
            validate_storyboard(forged,ir.sections,ir.sources,
                                allow_editorial=True)

    def test_editorial_critic_rejects_material_omission(self):
        ir=sample_ir()
        with self.assertRaises(EditorialQualificationError):
            validate_editorial_critique(
                {"decision":"accept","critical_gaps":[{
                    "section_id":2,"category":"missing_caveat",
                    "reason":"The report contains an omitted confounding warning."}],
                 "assessment":"The deck is incomplete without the documented caveat."},
                plan=plan(),section_count=len(ir.sections))


class EditorialExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_strategy_reuses_approved_renderer_and_remaps_global_ids(self):
        ir=sample_ir()
        async def fake_deck(objective,scoped,**kwargs):
            self.assertEqual(len(scoped.sections),2)
            return validate_storyboard(
                {"schema_version":1,"slides":[slide(0),slide(1)]},
                scoped.sections,scoped.sources,min_slides=1)
        with TemporaryDirectory() as temp,patch(
                "rizzler.work_editorial_director.create_editorial_plan",
                new=AsyncMock(return_value=plan())),patch(
                "rizzler.work_studio.create_storyboard",new=fake_deck),patch(
                "rizzler.v23_flags.enabled",return_value=False):
            result=await create_editorial_storyboard(
                "Explain trade data for executives",ir,
                model="mock",api_key="not_used",
                checkpoint=Path(temp),client=object())
        self.assertEqual(result["sections_covered"],[0,2])
        self.assertEqual(
            [s["section_ids"] for s in result["slides"]],[[0],[2]])


if __name__=="__main__":
    unittest.main()
