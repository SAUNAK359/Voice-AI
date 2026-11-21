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
    HandoffContractError,immutable_task_digest,
    validate_upstream_handoff)
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

    def test_upstream_and_downstream_share_the_same_goal_authority(self):
        self.assertEqual(immutable_task_digest(self.payload),
                         self.graph["immutable_goal_digest"])
        for specialist in ("orchestrator",):
            packet=validate_upstream_handoff(
                payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist=specialist)
            self.assertEqual(packet["immutable_goal_digest"],
                             self.graph["immutable_goal_digest"])
            self.assertEqual(packet["owner_scope"],self.owner)
        with self.assertRaises(HandoffContractError):
            validate_upstream_handoff(
                payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="research")
        with self.assertRaises(HandoffContractError):
            validate_upstream_handoff(
                payload=self.payload,owner=self.owner,
                job_id=self.job_id,specialist="unapproved")
        with self.assertRaises(HandoffContractError):
            validate_upstream_handoff(
                payload={**self.payload,"deliverables":[]},
                owner=self.owner,job_id=self.job_id,specialist="orchestrator")

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



    def test_planning_schema_errors_are_owned_by_planner_not_upstream_data(self):
        # Actual archived Kaggle failure: planning/contract_invalid was
        # incorrectly escalated to backdelegated SQL, then rejected by context.
        request=self.request
        backdelegate={"action":"backdelegate",
                      "reason":"A planning contract failed and requires reinspection.",
                      "request":request}
        diagnosis={"stage":"planning","kind":"pptx",
                   "attempt":1,"error_code":"contract_invalid",
                   "error_type":"ValueError"}
        with self.assertRaises(ValueError):
            validate_recovery_decision(
                backdelegate,kind="pptx",permitted=self.permitted,
                requirements=REQS,diagnostic=diagnosis)
        replan={"action":"replan",
                "reason":"Regenerate a valid source-grounded presentation plan.",
                "request":None}
        self.assertEqual(
            validate_recovery_decision(
                replan,kind="pptx",permitted=self.permitted,
                requirements=REQS,diagnostic=diagnosis),replan)
        permitted_gap={**diagnosis,"error_code":"evidence_gap",
                       "error_type":"EvidenceGap"}
        self.assertEqual(
            validate_recovery_decision(
                backdelegate,kind="pptx",permitted=self.permitted,
                requirements=REQS,diagnostic=permitted_gap),backdelegate)
        with self.assertRaises(ValueError):
            validate_recovery_decision(
                backdelegate,kind="pptx",permitted=self.permitted,
                requirements=REQS,diagnostic={**diagnosis,
                    "error_code":"provider_transient"})


class Phase1ActualWorkStoreIntegration(unittest.IsolatedAsyncioTestCase):
    async def test_real_worker_commits_owner_scoped_verified_artifact(self):
        """No provider mocks or fake file receipts: execute actual WorkStore DAG."""
        from tempfile import TemporaryDirectory
        from rizzler.work_store import WorkStore
        from rizzler.work_worker import WorkWorker
        from rizzler.artifacts import verify_artifact

        async def composer(objective,summary):
            return (
                "# Evidence-backed technical report\n"
                "This synthetic document exercises the actual durable Work "
                "orchestration and evidence-handoff implementation.\n"
                "## Source restrictions\n"
                "No external facts are asserted and no third-party statistics "
                "are represented as independently verified.\n"
                "## Validation approach\n"
                "The output must be generated by the real markdown specialist, "
                "checksum-inspected, and committed by final quality review.\n"
                "## Limitations\n"
                "This is a deterministic integration check, not a live paid "
                "Gemini evaluation or professional content-quality assessment.\n"
            )

        async def researcher(objective):
            raise AssertionError("Research is not authorized for this job")

        flags={**FLAGS,"RIZZLER_V23_MODE":"off",
               "RIZZLER_ARTIFACT_QA":"structural",
               "RIZZLER_MEMORY_ENABLED":"0",
               "GEMINI_API_KEY":""}
        with TemporaryDirectory() as root, patch.dict(
                os.environ,flags,clear=True):
            store=WorkStore(root)
            owner="phase1_integration_owner"
            job=store.submit(
                owner,
                "Produce a bounded synthetic Markdown engineering report "
                "showing evidence, execution and validation capabilities.",
                ["md"],"phase1_integration_job_001",[],
                requested_formats=["md"])
            self.assertTrue(await WorkWorker(
                store,composer=composer,researcher=researcher).once())
            state=store.get(owner,job["id"])
            self.assertEqual(state["status"],"completed",
                             f"Job failed: {state.get('error_code')}")
            artifacts=store.artifacts(owner,job["id"])
            self.assertEqual(len(artifacts),1)
            self.assertEqual(artifacts[0]["kind"],"md")
            filepath,metadata=store.artifact(owner,artifacts[0]["id"])
            verified=verify_artifact(filepath,"md")
            self.assertTrue(verified.verified)
            self.assertEqual(verified.sha256,metadata["sha256"])
            events=store.cognitive_events(owner,job["id"],limit=200)
            handoffs=[x for x in events if x["agent"]=="context_handoff"]
            self.assertEqual(
                {x["payload"]["specialist"] for x in handoffs},
                {"orchestrator","pdf_visual","quality"})
            render_handoffs=[x for x in handoffs
                             if x["payload"]["specialist"]!="orchestrator"]
            self.assertEqual(
                len({x["payload"]["revision"] for x in render_handoffs}),1)
            for record in render_handoffs:
                self.assertEqual(len(record["payload"]["handoff_sha256"]),64)
            upstream=next(x["payload"] for x in handoffs
                          if x["payload"]["specialist"]=="orchestrator")
            graph=store.knowledge_checkpoint(owner,job["id"])
            self.assertEqual(upstream["immutable_goal_digest"],
                             graph["immutable_goal_digest"])
            completed=store.agent_steps(owner,job["id"])
            for row in completed:
                self.assertEqual(row["status"],"completed")
            with self.assertRaises(Exception):
                store.artifact("different_owner",artifacts[0]["id"])

if __name__=="__main__":
    unittest.main()
