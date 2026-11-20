"""V24 PR56 regression coverage for exact, non-destructive PowerPoint repair."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from rizzler.work_ir import compile_ir
from rizzler.work_repair import (
    StoryboardQualificationError, storyboard_diagnostics,
    apply_storyboard_patch, repair_failure_reason)
from rizzler.work_studio import validate_storyboard
from rizzler.work_diagnostics import failure_code


class ContextPreservingStoryboardRecovery(unittest.TestCase):
    def setUp(self):
        self.ir=compile_ir(
            "Source-backed tool capabilities",
            "# Context\nA documented feature overview needs the exact source and publication date.\n"
            "## Evidence\nPrimary documentation establishes available model capability boundaries.\n"
            "## Decision\nDecisions must retain source limitations and uncertainty notes.\n"
            "## Follow-up\nAdditional audit controls require verifying source publication dates before drawing conclusions. "
            "Every numerical statement must be supported by a source with verified provenance and precise definitions.",
            ["https://example.org/source"])
        self.assertEqual(len(self.ir.sections),4)
        def slide(title, message, sid):
            return {
                "title": title, "message":message, "kind":"evidence",
                "bullets":[
                    "Each claim must retain its original source information.",
                    "Missing factual details cannot be invented by the model."],
                "section_ids":[sid],
                "source_urls":["https://example.org/source"]}
        self.deck={"schema_version":1,"slides":[
            slide("Source capabilities","The original research must remain source-grounded",0),
            slide("Verified source review","Existing evidence has specific reliability boundaries",1),
            slide("Stakeholder decisions","Unverified assumptions must be disclosed before action",2)],
            "sections_covered":[0,1,2]}

    def extra(self):
        return {
            "title":"Additional source audit",
            "message":"Publication dates and provenance constrain factual conclusions",
            "kind":"evidence",
            "bullets":[
                "Additional audit controls require verifying source publication dates before drawing conclusions.",
                "Every numerical statement must be supported by a source with verified provenance and precise definitions."],
            "section_ids":[3],
            "source_urls":["https://example.org/source"]}

    def test_missing_section_is_added_without_rewriting_existing_slides(self):
        before=deepcopy(self.deck)
        issues=storyboard_diagnostics(
            before,sections=self.ir.sections,sources=self.ir.sources)
        self.assertEqual([x["field"] for x in issues],["missing_sections"])
        result=apply_storyboard_patch(
            before,{"changes":[],"additional_slides":[self.extra()]},
            diagnostics=issues,sections=self.ir.sections,sources=self.ir.sources)
        self.assertEqual(before["slides"],result["slides"][:3])
        self.assertEqual(result["sections_covered"],[0,1,2,3])
        self.assertEqual(validate_storyboard(
            result,self.ir.sections,self.ir.sources)["sections_covered"],[0,1,2,3])

    def test_bullet_repair_cannot_erase_a_numeric_fact_or_neighbor_content(self):
        old=deepcopy(self.deck)
        old["slides"][1]["bullets"][0]="2025"
        issues=storyboard_diagnostics(
            old,sections=self.ir.sections,sources=self.ir.sources)
        self.assertIn("bullet",{i["field"] for i in issues})
        proposal={"changes":[{"index":1,"field":"bullet","item_index":0,
                  "replacement":"Documentation published in 2025 remains under review."}],
                  "additional_slides":[self.extra()]}
        result=apply_storyboard_patch(
            old,proposal,diagnostics=issues,
            sections=self.ir.sections,sources=self.ir.sources)
        self.assertEqual(result["slides"][0],old["slides"][0])
        self.assertEqual(result["slides"][2],old["slides"][2])
        self.assertEqual(result["slides"][1]["bullets"][1],
                         old["slides"][1]["bullets"][1])
        self.assertEqual(old["slides"][1]["bullets"][0],"2025")
        self.assertEqual(validate_storyboard(
            result,self.ir.sections,self.ir.sources)["sections_covered"],
            [0,1,2,3])
        proposal["changes"][0]["replacement"]="Documentation published in 2026 is confirmed."
        with self.assertRaisesRegex(ValueError,"numerical"):
            apply_storyboard_patch(
                old,proposal,diagnostics=issues,
                sections=self.ir.sections,sources=self.ir.sources)

    def test_added_slide_cannot_invent_source_evidence(self):
        issues=storyboard_diagnostics(
            self.deck,sections=self.ir.sections,sources=self.ir.sources)
        invented=self.extra()
        invented["bullets"][0]="This independently confirmed fact was never in the approved report."
        with self.assertRaisesRegex(ValueError,"source-IR excerpts"):
            apply_storyboard_patch(
                self.deck,{"changes":[],"additional_slides":[invented]},
                diagnostics=issues,sections=self.ir.sections,sources=self.ir.sources)
        invented=self.extra()
        invented["source_urls"]=["https://unapproved.invalid"]
        with self.assertRaisesRegex(ValueError,"unapproved"):
            apply_storyboard_patch(
                self.deck,{"changes":[],"additional_slides":[invented]},
                diagnostics=issues,sections=self.ir.sections,sources=self.ir.sources)

    def test_coverage_checksum_repaired_without_model_call(self):
        old=deepcopy(self.deck)
        old["slides"].append(self.extra())
        original=deepcopy(old["slides"])
        issues=storyboard_diagnostics(
            old,sections=self.ir.sections,sources=self.ir.sources)
        self.assertEqual([i["field"] for i in issues],["coverage_checksum"])
        patched=apply_storyboard_patch(
            old,{"changes":[]},diagnostics=issues,
            sections=self.ir.sections,sources=self.ir.sources)
        self.assertEqual(original,patched["slides"])
        self.assertEqual(patched["sections_covered"],[0,1,2,3])

    def test_unknown_citation_fails_closed_with_actionable_diagnostic(self):
        old=deepcopy(self.deck)
        old["slides"][0]["source_urls"]=["https://fabricated.invalid"]
        self.assertEqual(
            repair_failure_reason(old,sections=self.ir.sections,
                                  sources=self.ir.sources),"invalid_citations")
        self.assertEqual(failure_code(
            StoryboardQualificationError("invalid_citations")),
            "powerpoint_invalid_citations")


if __name__=="__main__":
    unittest.main()
