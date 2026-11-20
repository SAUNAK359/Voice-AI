"""V25 material quality reviews cannot bypass provenance or produce silent passes."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_semantic_quality import (
    validate_candidate_review,CandidateQualityIssue)
from rizzler.work_diagnostics import failure_code


class CriticalQualityContracts(unittest.TestCase):
    def test_accepted_candidate_has_no_hidden_material_defects(self):
        record={"status":"accept","issues":[],
                "assessment":"The draft covers all supported task requirements."}
        self.assertEqual(validate_candidate_review(
            record,kind="pptx",permitted_sources=("https://official.test",)),
            record)
        with self.assertRaises(ValueError):
            validate_candidate_review(
                dict(record,issues=[{"category":"misleading_visual",
                         "section_ids":[0],"finding":"The comparison omits the axis units.",
                         "source_urls":[]}]),
                kind="pptx",permitted_sources=("https://official.test",))

    def test_critical_issue_can_trigger_replanning_without_source_invention(self):
        record={"status":"revise","issues":[
            {"category":"missing_user_requirement","section_ids":[0],
             "finding":"The presentation does not address the requested limitations.",
             "source_urls":["https://official.test"]}],
            "assessment":"The missing limitations must be included before delivery."}
        self.assertEqual(validate_candidate_review(
            record,kind="pptx",permitted_sources=("https://official.test",)),
            record)
        with self.assertRaises(ValueError):
            validate_candidate_review(
                record,kind="pptx",permitted_sources=("https://other.test",))
        issue=CandidateQualityIssue(("missing_user_requirement",))
        self.assertEqual(failure_code(issue),
                         "candidate_quality_revision_required")
        self.assertEqual(issue.reason,"missing_user_requirement")

    def test_reviewer_cannot_request_revision_without_specific_defect(self):
        with self.assertRaises(ValueError):
            validate_candidate_review(
                {"status":"revise","issues":[],
                 "assessment":"There is an unexplained but concerning issue."},
                kind="pdf",permitted_sources=())

    def test_unknown_fields_or_issue_categories_not_accepted(self):
        issues=[{"category":"unapproved_creative_claim","section_ids":[0],
                 "finding":"A malicious result attempted to change the task.",
                 "source_urls":[]}]
        with self.assertRaises(ValueError):
            validate_candidate_review(
                {"status":"revise","issues":issues,
                 "assessment":"The draft should be reconsidered at this stage."},
                kind="docx",permitted_sources=())


if __name__=="__main__":
    unittest.main()
