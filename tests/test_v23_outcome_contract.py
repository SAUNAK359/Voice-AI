"""General expert goal contracts and content outcome audit guardrails."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_outcome import (
    validate_goal_contract, fallback_goal, goal_brief,
    validate_outcome_review,
)


class GoalContracts(unittest.TestCase):
    def _contract(self):
        return {"schema_version":1,
                "objective":"Explain trade balances and present source-backed implications.",
                "requirements":[
                    {"id":"g1","kind":"answer",
                     "obligation":"Explain the observed net trade balance across years.",
                     "evidence_needed":"Actual measured imports and exports for every year.",
                     "priority":5},
                    {"id":"g2","kind":"analysis",
                     "obligation":"Compare segment contributions and limitations.",
                     "evidence_needed":"Reconciled source-backed grouped SQL results.",
                     "priority":4}],
                "unknowns":["Reporting currency may be ambiguous."]}

    def test_contract_locks_authorized_formats_and_requires_evidence(self):
        approved=validate_goal_contract(self._contract(),["docx","pptx"])
        self.assertEqual(approved["requested_deliverables"],["docx","pptx"])
        self.assertIn("observed net trade",goal_brief(approved))
        invalid=self._contract()
        invalid["requirements"][1]["id"]="g1"
        with self.assertRaises(ValueError):
            validate_goal_contract(invalid,["pptx"])

    def test_rejects_invalid_priority_and_invented_kind(self):
        for field,value in (("kind","execute_shell"),
                            ("priority",8),
                            ("evidence_needed",""),
                            ("obligation","none")):
            v=self._contract()
            v["requirements"][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):
                validate_goal_contract(v,["docx"])

    def test_review_cannot_omit_or_invent_user_obligations(self):
        contract=validate_goal_contract(self._contract(),["docx"])
        review={"schema_version":1,"assessments":[
            {"id":"g1","satisfied":True,
             "observable_support":"SQL result compares both years.",
             "missing":""},
            {"id":"g2","satisfied":False,
             "observable_support":"Only aggregate statistics were computed.",
             "missing":"Segment-level evidence remains missing."}],
            "overall_gaps":["Segment-level reconciliation is not available."]}
        self.assertFalse(validate_outcome_review(review,contract)["passed"])
        omitted={**review,"assessments":review["assessments"][:1]}
        with self.assertRaises(ValueError):
            validate_outcome_review(omitted,contract)
        fabricated={**review,"assessments":[
            {**review["assessments"][0],"id":"g99"},
            review["assessments"][1]]}
        with self.assertRaises(ValueError):
            validate_outcome_review(fabricated,contract)

    def test_bounded_fallback_never_creates_data_or_tools(self):
        result=fallback_goal("Analyze the supplied dataset thoroughly.",["xlsx"])
        self.assertEqual(len(result["requirements"]),2)
        self.assertEqual(result["requested_deliverables"],["xlsx"])


if __name__=="__main__":
    unittest.main()
