"""Phase 1 architectural handoff integration: actual graph, goal and request scopes.

Do not substitute synthetic success for a completed Work job. These tests
prove protocol invariants with real compiled IR and validated PCCF graphs;
paid provider and multi-artifact acceptance remain separate release gates.
"""
from __future__ import annotations

import copy
import os
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))

from rizzler.work_ir import compile_ir
from rizzler.work_context_fabric import (
    migrate_v1,validate_fabric,ContextAccessDenied,ContextIntegrityError,
    context_fetch,affected_dependents)
from rizzler.work_phase1_protocol import (
    validate_task_handoff, assert_current_handoff,
    validate_source_request,source_obligations,
    HandoffContractError)
from rizzler.work_execution_recovery import (
    validate_recovery_decision,raise_verified_backdelegation)
from rizzler.work_feedback import EvidenceGap,validate_specialist_feedback

FLAGS={
    "RIZZLER_V26_CONTEXT_FABRIC":"1",
    "RIZZLER_V26_OUTCOME_PHASES":"1",
    "RIZZLER_V26_INSIGHT_GRAPH":"1",
}
REQS=[
    {"id":"g1","kind":"analysis",
     "obligation":"Determine observed differences using the verified uploaded table.",
     "evidence_needed":"A source-bound SQL investigation","priority":5},
    {"id":"g2","kind":"quality",
     "obligation":"Check all generated report figures against verified source totals.",
     "evidence_needed":"Final independently inspected file bytes","priority":5},
    {"id":"g3","kind":"deliverable",
     "obligation":"Produce a professional editable PowerPoint report.",
     "evidence_needed":"Fully inspected native PowerPoint bytes","priority":5},
]


class Phase1CrossAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.owner="tenant_phase1"
        self.job_id="job_phase1"
        self.payload={
            "objective":"Analyze the synthetic quarterly import/export data.",
            "deliverables":["pptx","xlsx","zip"],"uploads":[]}
        self.ir=compile_ir(
            "Trade study",
            "# Findings\nObserved quarterly deficits need source verification.\n"
            "## Scope\nAll figures are synthetic, not observed country data.",
            [])
        self.graph=migrate_v1(
            self.ir,owner=self.owner,job_id=self.job_id,
            objective=self.payload["objective"],
            deliverables=self.payload["deliverables"],
            requirements=REQS)
        self.permitted=frozenset({"sql_analytics"})
        self.request={
            "recipient":"sql_analytics",
            "question":"Verify dataset units and exact quarterly trade balances.",
            "reason":"Source-defined units must be correct before publishing a chart.",
            "blocking":True,
            "requirement_id":"g1"}

    def test_same_proof_and_immutable_scope_reaches_every_output_specialist(self):
        validate_fabric(self.graph)
        revisions=set()
        for specialist in ("powerpoint","excel","pdf_visual","quality"):
            receipt=validate_task_handoff(
                self.graph,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist=specialist)
            revisions.add(receipt["context_revision"])
            self.assertEqual(receipt["authorized_formats"],
                             self.payload["deliverables"])
            self.assertEqual(receipt["requirement_ids"],
                             ["requirement:g1","requirement:g2","requirement:g3"])
            self.assertEqual(receipt["source_ids"],[])
            self.assertEqual(receipt["critical_metric_ids"],[])
            self.assertEqual(len(receipt["handoff_sha256"]),64)
            assert_current_handoff(
                receipt,self.graph,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist=specialist)
        self.assertEqual(revisions,{self.graph["context_revision"]})

    def test_owner_job_specialist_and_immutable_scope_cannot_be_forged(self):
        receipt=validate_task_handoff(
            self.graph,payload=self.payload,owner=self.owner,
            job_id=self.job_id,specialist="powerpoint")
        with self.assertRaises(ContextAccessDenied):
            validate_task_handoff(
                self.graph,payload=self.payload,owner="other_tenant",
                job_id=self.job_id,specialist="powerpoint")
        with self.assertRaises(ContextAccessDenied):
            validate_task_handoff(
                self.graph,payload=self.payload,owner=self.owner,
                job_id="different_job",specialist="powerpoint")
        with self.assertRaises(ContextAccessDenied):
            validate_task_handoff(
                self.graph,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="arbitrary_tool")
        changed={**self.payload,"deliverables":["pptx","pdf"]}
        with self.assertRaises(HandoffContractError):
            validate_task_handoff(
                self.graph,payload=changed,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")
        changed={**self.payload,"objective":"Different task"}
        with self.assertRaises(HandoffContractError):
            validate_task_handoff(
                self.graph,payload=changed,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")
        forged=copy.deepcopy(receipt)
        forged["authorized_formats"].append("pdf")
        with self.assertRaises(HandoffContractError):
            assert_current_handoff(
                forged,self.graph,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")
        with self.assertRaises(HandoffContractError):
            assert_current_handoff(
                None,self.graph,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")

    def test_source_revision_revokes_stale_handoff_and_tampering(self):
        old=validate_task_handoff(
            self.graph,payload=self.payload,owner=self.owner,
            job_id=self.job_id,specialist="powerpoint")
        newer=compile_ir("Trade study",
            "# Findings\nRevised quantitative source conclusion.\n"
            "## Scope\nNumbers remain synthetic.",
            [])
        revised=migrate_v1(
            newer,owner=self.owner,job_id=self.job_id,
            objective=self.payload["objective"],
            deliverables=self.payload["deliverables"],requirements=REQS)
        self.assertNotEqual(
            self.graph["context_revision"],revised["context_revision"])
        with self.assertRaises(HandoffContractError):
            assert_current_handoff(
                old,revised,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")
        modified=copy.deepcopy(self.graph)
        modified["nodes"][0]["data"]["malicious"]="injected"
        with self.assertRaises(ContextIntegrityError):
            validate_task_handoff(
                modified,payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="powerpoint")

    def test_one_request_schema_across_recovery_feedback_and_context(self):
        self.assertEqual([x["id"] for x in source_obligations(REQS)],["g1"])
        with patch.dict(os.environ,FLAGS,clear=False):
            verified=validate_source_request(
                self.request,requirements=REQS,permitted=self.permitted)
            self.assertIs(verified,self.request)
            approved_feedback=validate_specialist_feedback(
                {"specialist":"powerpoint","readiness":"needs_evidence",
                 "requests":[self.request],
                 "assessment":"The source units require verified SQL analysis."},
                specialist="powerpoint",requirements=REQS,
                permitted=self.permitted)
            self.assertEqual(approved_feedback["requests"],[self.request])
            decision={"action":"backdelegate",
                      "reason":"Obtain validated original source units before rendering.",
                      "request":self.request}
            self.assertEqual(validate_recovery_decision(
                decision,kind="pptx",requirements=REQS,
                permitted=self.permitted),decision)
            with self.assertRaises(EvidenceGap) as captured:
                raise_verified_backdelegation(
                    decision,specialist="powerpoint",
                    permitted=self.permitted,requirements=REQS)
            self.assertEqual(captured.exception.requests,[self.request])

    def test_invalid_source_ids_and_tool_permissions_never_pass(self):
        bad=[
            {**self.request,"requirement_id":"g2"},
            {**self.request,"requirement_id":"g3"},
            {**self.request,"requirement_id":"fabricated"},
            {k:v for k,v in self.request.items() if k!="requirement_id"},
            {**self.request,"recipient":"web_shell"},
        ]
        for request in bad:
            with self.subTest(request=request):
                with self.assertRaises((HandoffContractError,ValueError)):
                    validate_source_request(
                        request,requirements=REQS,permitted=self.permitted)
        with self.assertRaises(HandoffContractError):
            validate_source_request(
                self.request,requirements=REQS,permitted=frozenset())


if __name__=="__main__":
    unittest.main()
