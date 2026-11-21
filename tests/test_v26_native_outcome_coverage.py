"""Phase 2 native Office outcome coverage adversarial tests.

All fixtures are synthetic. The reviewer operates on original file-extracted
text, never self-certified blueprint or planning summaries.
"""
from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_outcome_coverage import (
    obligations,validate_coverage,reconcile_coverage,
    OutcomeCoverageError)
from rizzler.work_consistency import extracted_artifact_text

GOAL={
    "objective":"Analyze a fictional four-row trade dataset for an executive audience.",
    "requirements":[
        {"id":"g1","kind":"analysis","priority":5,
         "obligation":"Analyze verified quarterly import versus export balance",
         "evidence_needed":"Observed synthetic quarterly source totals"},
        {"id":"g2","kind":"comparison","priority":5,
         "obligation":"Explain how fictional quarterly net position changes",
         "evidence_needed":"Observed quarterly import and export comparisons"},
        {"id":"g3","kind":"quality","priority":5,
         "obligation":"Keep reported figures and scope correct",
         "evidence_needed":"Inspected native artifact receipt"},
        {"id":"g4","kind":"deliverable","priority":5,
         "obligation":"Publish editable presentation",
         "evidence_needed":"Editable native output"},
    ]
}
TEXT=("Quarterly comparison shows a synthetic net position of -150 units. "
      "In the four observed quarters the differences are negative. "
      "These rows are synthetic, not official trade statistics.")
A=TEXT[:73]
B="In the four observed quarters the differences are negative."


def review(kind="pptx",first="covered",second="covered",first_excerpt=A,
           second_excerpt=B):
    return {"schema_version":1,"artifact_kind":kind,
            "coverage":[
                {"requirement_id":"g1","status":first,
                 "observed_excerpt":first_excerpt,
                 "assessment":"The artifact explicitly reports the synthetic net total."},
                {"requirement_id":"g2","status":second,
                 "observed_excerpt":second_excerpt,
                 "assessment":"The observed quarterly net direction is stated clearly."}],
            "assessment":"The native source text is independently reviewed for goal coverage."}


class NativeOutcomeQualityTests(unittest.TestCase):
    def setUp(self):
        self.targets=obligations(GOAL)

    def test_source_requirements_not_output_future_files(self):
        self.assertEqual([x["id"] for x in self.targets],["g1","g2"])

    def test_valid_real_excerpt_and_complete_coverage(self):
        data=validate_coverage(review(),kind="pptx",
                               expected=self.targets,actual_text=TEXT)
        self.assertTrue(data["passed"])
        self.assertEqual(data["covered_requirement_ids"],["g1","g2"])
        combined=reconcile_coverage({"pptx":data},GOAL)
        self.assertTrue(combined["passed"])

    def test_reject_hallucinated_excerpt_and_unknown_ids(self):
        forged=review(first_excerpt="Invented source evidence -150 units")
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(forged,kind="pptx",
                              expected=self.targets,actual_text=TEXT)
        fake=review()
        fake["coverage"][0]["requirement_id"]="g4"
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(fake,kind="pptx",
                              expected=self.targets,actual_text=TEXT)

    def test_missing_requirement_is_not_accepted(self):
        data=review(first="missing",first_excerpt="")
        single=validate_coverage(data,kind="pptx",
                                 expected=self.targets,actual_text=TEXT)
        self.assertEqual(single["uncovered_requirement_ids"],["g1"])
        result=reconcile_coverage({"pptx":single},GOAL)
        self.assertFalse(result["passed"])
        self.assertEqual(result["uncovered_critical_requirements"],["g1"])

    def test_coverage_can_be_divided_across_powerpoint_and_word(self):
        presentation=validate_coverage(
            review(second="missing",second_excerpt=""),
            kind="pptx",expected=self.targets,actual_text=TEXT)
        document=validate_coverage(
            review(kind="docx",first="missing",first_excerpt=""),
            kind="docx",expected=self.targets,actual_text=TEXT)
        joint=reconcile_coverage({"pptx":presentation,"docx":document},GOAL)
        self.assertTrue(joint["passed"])
        self.assertEqual(joint["uncovered_critical_requirements"],[])

    def test_no_duplicate_or_missing_obligation(self):
        incomplete=review()
        incomplete["coverage"].pop()
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(incomplete,kind="pptx",
                              expected=self.targets,actual_text=TEXT)
        duplicate=review()
        duplicate["coverage"][1]["requirement_id"]="g1"
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(duplicate,kind="pptx",
                              expected=self.targets,actual_text=TEXT)

    def test_missing_never_carries_fabricated_evidence(self):
        false_missing=review(first="missing",first_excerpt=A)
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(false_missing,kind="pptx",
                              expected=self.targets,actual_text=TEXT)

    def test_reject_unsupported_or_self_certifying_review(self):
        corrupt=review()
        corrupt["coverage"][0]["status"]="verified_by_model"
        with self.assertRaises(OutcomeCoverageError):
            validate_coverage(corrupt,kind="pptx",
                              expected=self.targets,actual_text=TEXT)
        with self.assertRaises(OutcomeCoverageError):
            reconcile_coverage({},GOAL)

    def test_actual_native_word_file_text_supports_excerpts(self):
        try:
            from docx import Document
        except ImportError:
            self.skipTest("Requires python-docx Work optional dependency")
        with TemporaryDirectory() as temp:
            path=Path(temp)/"report.docx"
            doc=Document()
            doc.add_heading("Fictional data study",0)
            doc.add_paragraph(TEXT)
            doc.save(path)
            actual=extracted_artifact_text(path,"docx")
            result=validate_coverage(review(kind="docx"),
                       kind="docx",expected=self.targets,
                       actual_text=actual)
            self.assertTrue(result["passed"])


if __name__=="__main__":
    unittest.main()
