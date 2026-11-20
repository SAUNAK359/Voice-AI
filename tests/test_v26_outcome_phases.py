"""V26 source readiness and future-deliverable phase regression tests.

Reproduces the V25 failure mode: an unbuilt deck is not a missing research
result, whereas a missing factual source remains a legitimate blocker.
"""
from __future__ import annotations
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_context_intelligence import validate_context_review
from rizzler.work_outcome_phases import (
    EXECUTION_PENDING,EVIDENCE_READY,phase_projection,
    derive_job_readiness,validate_evidence_request,normalize_context_coverage)
from rizzler.work_feedback import validate_specialist_feedback
from rizzler.v26_flags import foundation_enabled


REQS=[
    {"id":"g1","kind":"analysis","obligation":"Verify the sourced numeric findings",
     "evidence_needed":"Dataset SQL receipt","priority":5},
    {"id":"g2","kind":"deliverable","obligation":"Create a professional editable deck",
     "evidence_needed":"Rendered PPTX","priority":5},
    {"id":"g3","kind":"quality","obligation":"Validate the output pages",
     "evidence_needed":"Actual slide checks","priority":5},
]
APPROVED="https://example.org/source"
FLAGS={
    "RIZZLER_V26_CONTEXT_FABRIC":"1",
    "RIZZLER_V26_OUTCOME_PHASES":"1",
    "RIZZLER_V26_INSIGHT_GRAPH":"1",
}


def package():
    return {"requirements":REQS,"approved_sources":[APPROVED],
            "dataset":None,"outcome_stage":"pre_artifact"}


def coverage(source_status="supported"):
    return [
        {"id":"g1","status":source_status,"evidence_refs":[APPROVED]
         if source_status=="supported" else []},
        {"id":"g2","status":"unknown","evidence_refs":[]},
        {"id":"g3","status":"unknown","evidence_refs":[]},
    ]


def review(source_status="supported",decision="ready",requests=None):
    return {"schema_version":1,"decision":decision,
            "coverage":coverage(source_status),"requests":requests or [],
            "assessment":"Source evidence is sufficient; rendering and visual review come later."}


class OutcomePhaseSafetyTests(unittest.TestCase):
    def test_future_documents_remain_execution_pending_not_source_gaps(self):
        with patch.dict("os.environ",FLAGS,clear=True):
            self.assertTrue(foundation_enabled())
            result=validate_context_review(
                review(),package=package(),permitted=frozenset({"research"}))
            self.assertEqual(result["coverage"][1]["status"],"execution_pending")
            self.assertEqual(result["coverage"][2]["status"],"execution_pending")
            readiness=derive_job_readiness(REQS,result["coverage"])
            self.assertTrue(readiness["evidence_ready"])
            self.assertFalse(readiness["artifacts_ready"])
            self.assertEqual(readiness["states"]["g2"],EXECUTION_PENDING)
            self.assertEqual(readiness["states"]["g1"],EVIDENCE_READY)

    def test_missing_factual_evidence_remains_a_blocker(self):
        with patch.dict("os.environ",FLAGS,clear=True):
            with self.assertRaises(ValueError):
                validate_context_review(
                    review(source_status="unknown"),
                    package=package(),permitted=frozenset({"research"}))

    def test_research_for_a_future_deck_is_not_authorized(self):
        request={"recipient":"research",
                 "question":"Produce the missing binary presentation artifact",
                 "reason":"The deck itself is required by the final deliverable.",
                 "blocking":True,"requirement_id":"g2"}
        with patch.dict("os.environ",FLAGS,clear=True):
            with self.assertRaises(ValueError):
                validate_context_review(
                    review(decision="investigate",requests=[request]),
                    package=package(),permitted=frozenset({"research"}))
            with self.assertRaises(ValueError):
                validate_specialist_feedback(
                    {"specialist":"powerpoint",
                     "readiness":"needs_evidence","requests":[request],
                     "assessment":"Evidence requests must be source scoped and independently verified."},
                    specialist="powerpoint",permitted=frozenset({"research"}),
                    requirements=REQS)

    def test_real_source_gap_may_authorize_a_bounded_investigation(self):
        request={"recipient":"research",
                 "question":"Verify the originating source of the numerical claim",
                 "reason":"The computed dataset needs a source quality assessment.",
                 "blocking":True,"requirement_id":"g1"}
        with patch.dict("os.environ",FLAGS,clear=True):
            good=validate_context_review(
                review(source_status="unknown",decision="investigate",
                       requests=[request]),
                package=package(),permitted=frozenset({"research"}))
            self.assertEqual(good["requests"],[request])
            self.assertEqual(
                validate_evidence_request(request,REQS),request)

    def test_fabric_dependencies_cannot_be_enabled_incoherently(self):
        with patch.dict("os.environ",{
            "RIZZLER_V26_OUTCOME_PHASES":"1"},clear=True):
            with self.assertRaises(ValueError):
                foundation_enabled()
        with patch.dict("os.environ",{},clear=True):
            self.assertFalse(foundation_enabled())


if __name__=="__main__":
    unittest.main()
